#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2020 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

# coldstakepool$ python setup.py test

import os
import sys
import time
import json
import shutil
import signal
import logging
import unittest
import subprocess
import urllib.request
import multiprocessing
from unittest.mock import patch

from coldstakepool.util import callrpc, dumpj, COIN
from coldstakepool.contrib.rpcauth import generate_salt, password_to_hmac

import bin.coldstakepool_prepare as prepareSystem
import bin.coldstakepool_run as runSystem


PARTICL_BINDIR = os.path.expanduser(os.getenv('TEST_BINDIR', prepareSystem.PARTICL_BINDIR))
PARTICLD = prepareSystem.PARTICLD
TEST_DIR = os.path.expanduser(os.getenv('TEST_DIR', '~/csptest'))
NUM_NODES = 3
BASE_PORT = 14792
BASE_RPC_PORT = 19792


def prepareDataDir(datadir, node_id, conf_file):
    node_dir = os.path.join(datadir, str(node_id))
    if not os.path.exists(node_dir):
        os.makedirs(node_dir)
    cfg_file_path = os.path.join(node_dir, conf_file)
    if os.path.exists(cfg_file_path):
        return
    with open(cfg_file_path, 'w+') as fp:
        fp.write('regtest=1\n')
        fp.write('[regtest]\n')
        fp.write('port=' + str(BASE_PORT + node_id) + '\n')
        fp.write('rpcport=' + str(BASE_RPC_PORT + node_id) + '\n')

        salt = generate_salt(16)
        fp.write('rpcauth={}:{}${}\n'.format('test' + str(node_id), salt, password_to_hmac(salt, 'test_pass' + str(node_id))))

        fp.write('daemon=0\n')
        fp.write('printtoconsole=0\n')
        fp.write('server=1\n')
        fp.write('discover=0\n')
        fp.write('listenonion=0\n')
        fp.write('bind=127.0.0.1\n')
        fp.write('debug=1\n')
        fp.write('debugexclude=libevent\n')

        fp.write('fallbackfee=0.01\n')
        fp.write('acceptnonstdtxn=0\n')
        fp.write('txindex=1\n')

        fp.write('findpeers=0\n')
        # minstakeinterval=5  # Using walletsettings stakelimit instead

        for i in range(0, NUM_NODES):
            if node_id == i:
                continue
            fp.write('addnode=127.0.0.1:{}\n'.format(BASE_PORT + i))


def waitForRPC(rpc_func, wallet=None):
    for i in range(5):
        try:
            rpc_func('getwalletinfo')
            return
        except Exception as ex:
            logging.warning('Can\'t connect to daemon RPC: %s.  Trying again in %d second/s.', str(ex), (1 + i))
            time.sleep(1 + i)
    raise ValueError('waitForRPC failed')


def make_rpc_func(node_id):
    node_id = node_id
    auth = 'test{0}:test_pass{0}'.format(node_id)

    def rpc_func(method, params=None, wallet=None):
        nonlocal node_id, auth
        return callrpc(BASE_RPC_PORT + node_id, auth, method, params, wallet)
    return rpc_func


def startDaemon(node_dir, bin_dir, daemon_bin, opts=[]):
    daemon_bin = os.path.expanduser(os.path.join(bin_dir, daemon_bin))

    args = [daemon_bin, '-datadir=' + os.path.expanduser(node_dir)] + opts
    logging.info('Starting node {} -datadir={}'.format(daemon_bin, node_dir))

    return subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def callnoderpc(node_id, method, params=[], wallet=None):
    auth = 'test{0}:test_pass{0}'.format(node_id)
    return callrpc(BASE_RPC_PORT + node_id, auth, method, params, wallet)


def make_int(v, precision=8, r=-1):  # r = 0, no rounding, fail, r > 0 round up, r < 0 floor
    if type(v) == float:
        v = str(v)
    elif type(v) == int:
        return v * 10 ** precision

    ep = 10 ** precision
    have_dp = False
    rv = 0
    for c in v:
        if c == '.':
            rv *= ep
            have_dp = True
            continue
        if not c.isdigit():
            raise ValueError('Invalid char')
        if have_dp:
            ep //= 10
            if ep <= 0:
                if r == 0:
                    raise ValueError('Mantissa too long')
                if r > 0:
                    # Round up
                    if int(c) > 4:
                        rv += 1
                break

            rv += ep * int(c)
        else:
            rv = rv * 10 + int(c)
    if not have_dp:
        rv *= ep
    return rv


class Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stop_nodes = False
        cls.update_thread = None
        cls.daemons = []
        cls.processes = []

        logger = logging.getLogger()
        logger.propagate = False
        logger.handlers = []
        logger.setLevel(logging.INFO)  # DEBUG shows many messages from requests.post
        formatter = logging.Formatter('%(asctime)s %(levelname)s : %(message)s')
        stream_stdout = logging.StreamHandler()
        stream_stdout.setFormatter(formatter)
        logger.addHandler(stream_stdout)

        if os.path.isdir(TEST_DIR):
            logging.info('Removing ' + TEST_DIR)
            shutil.rmtree(TEST_DIR)
        if not os.path.exists(TEST_DIR):
            os.makedirs(TEST_DIR)

        cls.stream_fp = logging.FileHandler(os.path.join(TEST_DIR, 'test.log'))
        cls.stream_fp.setFormatter(formatter)
        logger.addHandler(cls.stream_fp)

    @classmethod
    def tearDownClass(self):

        for p in self.processes:
            # p.terminate()
            try:
                os.kill(p.pid, signal.SIGINT)
            except Exception as e:
                logging.info('Interrupting %d, error %s', p.pid, str(e))
            p.join()
        self.processes = []

        for d in self.daemons:
            logging.info('Interrupting %d', d.pid)
            try:
                d.send_signal(signal.SIGINT)
            except Exception as e:
                logging.info('Interrupting %d, error %s', d.pid, str(e))
        for d in self.daemons:
            try:
                d.wait(timeout=20)
                if d.stdout:
                    d.stdout.close()
                if d.stderr:
                    d.stderr.close()
                if d.stdin:
                    d.stdin.close()
            except Exception as e:
                logging.info('Closing %d, error %s', d.pid, str(e))
        self.daemons = []

    def run_pool(self, args):
        args[0] = 'coldstakepool-run'
        args[1] += '/stakepool'
        with patch.object(sys, 'argv', args):
            runSystem.main()

    def test_regtest(self):
        testargs = ['coldstakepool-prepare', '--datadir={}/csp_regtest'.format(TEST_DIR), '--regtest']
        with patch.object(sys, 'argv', testargs):
            prepareSystem.main()

        settings_path = os.path.join(TEST_DIR, 'csp_regtest', 'stakepool', 'stakepool.json')
        with open(settings_path) as fs:
            pool_settings = json.load(fs)
        pool_settings['startheight'] = 0
        pool_settings['parameters'][0]['payoutthreshold'] = 0.005
        pool_settings['parameters'][0]['minblocksbetweenpayments'] = 10
        with open(settings_path, 'w') as fp:
            json.dump(pool_settings, fp, indent=4)

        for i in range(NUM_NODES - 1):
            prepareDataDir(TEST_DIR, i, 'particl.conf')

            with open(os.path.join(TEST_DIR, 'csp_regtest', 'particl.conf'), 'a') as fp:
                fp.write('addnode=127.0.0.1:{}\n'.format(BASE_PORT + i))

            self.daemons.append(startDaemon(os.path.join(TEST_DIR, str(i)), PARTICL_BINDIR, PARTICLD))
            logging.info('Started %s %d', PARTICLD, self.daemons[-1].pid)

            waitForRPC(make_rpc_func(i))
            callnoderpc(i, 'reservebalance', [True, 1000000])
            callnoderpc(i, 'walletsettings', ['stakingoptions', {'stakecombinethreshold': 100, 'stakesplitthreshold': 200}])

        # Start pool daemon
        self.daemons.append(startDaemon(os.path.join(TEST_DIR, 'csp_regtest'), PARTICL_BINDIR, PARTICLD, opts=['-noprinttoconsole', ]))
        logging.info('Started %s %d', PARTICLD, self.daemons[-1].pid)

        self.processes.append(multiprocessing.Process(target=self.run_pool, args=(testargs,)))
        self.processes[-1].start()

        callnoderpc(0, 'extkeyimportmaster', ['abandon baby cabbage dad eager fabric gadget habit ice kangaroo lab absorb'])
        assert(callnoderpc(0, 'getwalletinfo')['total_balance'] == 100000)

        callnoderpc(1, 'extkeyimportmaster', ['pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic', '', 'true'])
        callnoderpc(1, 'getnewextaddress', ['lblExtTest'])
        callnoderpc(1, 'rescanblockchain')
        assert(callnoderpc(1, 'getwalletinfo')['total_balance'] == 25000)

        # Wait for pool daemon to start
        authcookiepath = os.path.join(TEST_DIR, 'csp_regtest', 'regtest', '.cookie')
        for i in range(10):
            if not os.path.exists(authcookiepath):
                time.sleep(0.5)
        with open(authcookiepath) as fp:
            pool_rpc_auth = fp.read()

        pool_rpc_port = 51936

        for i in range(5):
            try:
                staking_options = callrpc(pool_rpc_port, pool_rpc_auth, 'walletsettings', ['stakingoptions'], wallet='pool_stake')
                break
            except Exception as e:
                logging.info('Waiting for stakepool to start %s', str(e))
                time.sleep(1)

        staking_options = staking_options['stakingoptions']
        staking_options['stakecombinethreshold'] = 100
        staking_options['stakesplitthreshold'] = 200
        staking_options['enabled'] = False
        staking_options = callrpc(pool_rpc_port, pool_rpc_auth, 'walletsettings', ['stakingoptions', staking_options], wallet='pool_stake')
        staking_options = callrpc(pool_rpc_port, pool_rpc_auth, 'walletsettings', ['stakingoptions'], wallet='pool_stake')['stakingoptions']
        assert(staking_options['stakecombinethreshold'] == 100)

        for i in range(5):
            try:
                with urllib.request.urlopen('http://localhost:9001/config') as conn:
                    page = conn.read().decode('utf8')
            except Exception as e:
                logging.info('Waiting for stakepool http server to start %s', str(e))
                time.sleep(1)
        pool_config = json.loads(page)
        addr_pool_stake = pool_config['pooladdress']

        callnoderpc(0, 'createwallet', ['pool'])
        callnoderpc(0, 'createwallet', ['pool_reward'])
        callnoderpc(0, 'createwallet', ['MS Wallet'])  # Wallet name containing spaces
        callnoderpc(1, 'createwallet', ['pool'])

        callnoderpc(0, 'extkeyimportmaster', [callnoderpc(0, 'mnemonic', ['new'])['mnemonic']], wallet='pool')
        callnoderpc(0, 'extkeyimportmaster', [callnoderpc(0, 'mnemonic', ['new'])['mnemonic']], wallet='pool_reward')
        callnoderpc(0, 'extkeyimportmaster', [callnoderpc(0, 'mnemonic', ['new'])['mnemonic']], wallet='MS Wallet')
        callnoderpc(1, 'extkeyimportmaster', [callnoderpc(1, 'mnemonic', ['new'])['mnemonic']], wallet='pool')

        callnoderpc(0, 'walletsettings', ['stakingoptions', {'enabled': 'false'}], wallet='pool')
        callnoderpc(0, 'walletsettings', ['stakingoptions', {'enabled': 'false'}], wallet='pool_reward')
        callnoderpc(0, 'walletsettings', ['stakingoptions', {'enabled': 'false'}], wallet='MS Wallet')
        callnoderpc(1, 'walletsettings', ['stakingoptions', {'enabled': 'false'}], wallet='pool')

        sxaddrnode0 = callnoderpc(0, 'getnewstealthaddress', wallet='pool_reward')

        ms_addrs = []
        ms_pubkeys = []

        ms_addrs.append(callnoderpc(0, 'getnewaddress', wallet='pool'))
        ms_addrs.append(callnoderpc(0, 'getnewaddress', wallet='MS Wallet'))
        ms_addrs.append(callnoderpc(1, 'getnewaddress', wallet='pool'))

        ms_pubkeys.append(callnoderpc(0, 'getaddressinfo', [ms_addrs[0]], wallet='pool')['pubkey'])
        ms_pubkeys.append(callnoderpc(0, 'getaddressinfo', [ms_addrs[1]], wallet='MS Wallet')['pubkey'])
        ms_pubkeys.append(callnoderpc(1, 'getaddressinfo', [ms_addrs[2]], wallet='pool')['pubkey'])

        ms_addr = callnoderpc(0, 'addmultisigaddress', [2, ms_pubkeys], wallet='MS Wallet')
        callnoderpc(0, 'importaddress', [ms_addr['redeemScript'], ], wallet='MS Wallet')
        logging.info('ms_addr %s', ms_addr['address'])

        pool_addrs_1 = []
        pool_addrs_1.append(callnoderpc(1, 'getnewaddress', ['pooled_spend', False, False, True], wallet='pool'))
        pool_addrs_1.append(callnoderpc(1, 'getnewaddress', ['pooled_spend', False, False, True], wallet='pool'))
        pool_addrs_1.append(callnoderpc(1, 'getnewaddress', ['pooled_spend', False, False, True], wallet='pool'))

        recipe = {'recipe': 'ifcoinstake', 'addrstake': addr_pool_stake, 'addrspend': pool_addrs_1[0]}
        toScript1 = callnoderpc(0, 'buildscript', [recipe])

        recipe = {'recipe': 'ifcoinstake', 'addrstake': addr_pool_stake, 'addrspend': pool_addrs_1[1]}
        toScript2 = callnoderpc(1, 'buildscript', [recipe])

        recipe = {'recipe': 'ifcoinstake', 'addrstake': addr_pool_stake, 'addrspend': pool_addrs_1[2]}
        toScript3 = callnoderpc(1, 'buildscript', [recipe])

        recipe = {'recipe': 'ifcoinstake', 'addrstake': addr_pool_stake, 'addrspend': ms_addr['address']}
        toScript4 = callnoderpc(1, 'buildscript', [recipe])

        outputs_node1 = [
            {
                'address': 'script',
                'amount': 5000,
                'script': toScript1['hex'],
            },
            {
                'address': 'script',
                'amount': 5000,
                'script': toScript2['hex'],
            },
            {
                'address': 'script',
                'amount': 20,
                'script': toScript3['hex'],
            },
            {
                'address': 'script',
                'amount': 10000,
                'script': toScript4['hex'],
            },
        ]

        pool_addrs_0 = []
        txids = []
        outputs = []
        for i in range(2):
            pool_addrs_0.append(callnoderpc(0, 'getnewaddress', ['pool', False, False, True], wallet='pool'))
            recipe = {'recipe': 'ifcoinstake', 'addrstake': addr_pool_stake, 'addrspend': pool_addrs_0[-1]}
            toScript = callnoderpc(0, 'buildscript', [recipe])
            outputs.append({
                'address': 'script',
                'amount': 10000,
                'script': toScript['hex'],
            })
        txids.append(callnoderpc(0, 'sendtypeto', ['part', 'part', outputs], wallet=''))

        outputs = []
        for i in range(600):
            pool_addrs_0.append(callnoderpc(0, 'getnewaddress', ['pool', False, False, True], wallet='pool'))
            recipe = {'recipe': 'ifcoinstake', 'addrstake': addr_pool_stake, 'addrspend': pool_addrs_0[-1]}
            toScript = callnoderpc(0, 'buildscript', [recipe])
            outputs.append({
                'address': 'script',
                'amount': 100,
                'script': toScript['hex'],
            })
        txids.append(callnoderpc(0, 'sendtypeto', ['part', 'part', outputs], wallet=''))

        # Faster than waiting for mempool
        for txid in txids:
            txhex = callnoderpc(0, 'getrawtransaction', [txid], wallet='')
            callrpc(pool_rpc_port, pool_rpc_auth, 'sendrawtransaction', [txhex])
            callnoderpc(1, 'sendrawtransaction', [txhex])

        logging.info('Mining a block from node1 to confirm txns from node0 to pool')
        callnoderpc(1, 'reservebalance', [False], wallet='')
        callnoderpc(1, 'walletsettings', ['stakelimit', {'height': 1}], wallet='')

        for i in range(10):
            r = callnoderpc(0, 'getblockchaininfo')
            print('btc1', r['blocks'])
            if r['blocks'] > 0:
                break
            time.sleep(1)

        # Send coin from node1 to pool
        txid = callnoderpc(1, 'sendtypeto', ['part', 'part', outputs_node1], wallet='')
        callrpc(pool_rpc_port, pool_rpc_auth, 'sendrawtransaction', [callnoderpc(1, 'getrawtransaction', [txid], wallet='')])

        staking_options['enabled'] = True
        rv = callrpc(pool_rpc_port, pool_rpc_auth, 'walletsettings', ['stakingoptions', staking_options], wallet='pool_stake')
        print('walletsettings', dumpj(rv))

        stake_blocks = 150
        rv = callrpc(pool_rpc_port, pool_rpc_auth, 'walletsettings', ['stakelimit', {'height': stake_blocks}], wallet='pool_stake')

        addr_node_1 = callnoderpc(1, 'getnewaddress', wallet='')
        for i in range(600):
            r = callrpc(pool_rpc_port, pool_rpc_auth, 'getblockchaininfo')
            logging.info('blocks: %d', r['blocks'])
            if r['blocks'] >= stake_blocks:
                break
            time.sleep(1)

        for i in range(30):
            with urllib.request.urlopen('http://localhost:9001/json') as conn:
                pool_end = json.loads(conn.read().decode('utf8'))
            logging.info('poolheight: %d', pool_end['poolheight'])
            if stake_blocks - 100 == pool_end['poolheight']:
                break
            time.sleep(1)

        accum_block_rewards = 0
        for i in range(2, pool_end['poolheight'] + 1):
            rv = callrpc(pool_rpc_port, pool_rpc_auth, 'getblockreward', [i])
            accum_block_rewards += make_int(rv['blockreward'])

        logging.info('accum_block_rewards: %d', accum_block_rewards)

        total_addr_accum = 0
        total_addr_pending = 0
        total_addr_paid = 0

        for addr in pool_addrs_0 + pool_addrs_1 + [ms_addr['address'], ]:
            with urllib.request.urlopen('http://localhost:9001/json/address/' + addr) as conn:
                r = json.loads(conn.read().decode('utf8'))
                if 'accumulated' in r:
                    total_addr_accum += r['accumulated']
                if 'rewardpending' in r:
                    total_addr_pending += r['rewardpending']
                if 'rewardpaidout' in r:
                    total_addr_paid += r['rewardpaidout']

        logging.info('total_addr_accum: %d', total_addr_accum)
        logging.info('total_addr_pending: %d', total_addr_pending)
        logging.info('total_addr_paid: %d', total_addr_paid)

        total_pool_users = total_addr_accum + total_addr_pending + total_addr_paid
        logging.info('accum_block_rewards: %d', accum_block_rewards)

        logging.info('poolrewardtotal: %d', pool_end['poolrewardtotal'])
        total_pool_users = total_pool_users // COIN
        total_pool = total_pool_users + pool_end['poolrewardtotal']
        logging.info('total_pool_users + pool_reward: %d', total_pool)
        assert(abs(accum_block_rewards - total_pool) < 10)

        changeaddress = {'address_standard': ms_addr['address']}
        callnoderpc(0, 'walletsettings', ['changeaddress', changeaddress], wallet='MS Wallet')

        addr_out = callnoderpc(1, 'getnewaddress', wallet='')
        rawtx = callnoderpc(0, 'createrawtransaction', [[], {addr_out: 1.0}], wallet='MS Wallet')
        funded_tx = callnoderpc(0, 'fundrawtransaction', [rawtx, {'includeWatching': True}], wallet='MS Wallet')

        callnoderpc(0, 'importaddress', [ms_addr['redeemScript'], ], wallet='pool')
        stx1 = callnoderpc(0, 'signrawtransactionwithwallet', [funded_tx['hex']], wallet='pool')
        stx2 = callnoderpc(0, 'signrawtransactionwithwallet', [stx1['hex']], wallet='MS Wallet')

        tx = callnoderpc(0, 'decoderawtransaction', [stx2['hex']], wallet='MS Wallet')
        change_n = 1 if tx['vout'][0]['scriptPubKey']['addresses'][0] == addr_out else 0
        assert(tx['vout'][change_n]['scriptPubKey']['addresses'][0] == ms_addr['address'])

        callnoderpc(0, 'sendrawtransaction', [stx2['hex']])


if __name__ == '__main__':
    unittest.main()
