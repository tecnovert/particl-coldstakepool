#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018-2019 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""
Particl Stake Pool - Proof of concept

Staking should be disabled in the rewards wallet:
    particl-cli -rpcwallet=pool_reward walletsettings stakingoptions "{\\"enabled\\":\\"false\\"}"


Dependencies:
    $ pacman -S python-pyzmq python-plyvel

"""

import sys
import os
import time
import datetime as dt
import decimal
import zmq
import threading
import traceback
import plyvel
import struct
from functools import wraps
from .util import (
    COIN,
    callrpc,
    decodeAddress,
    encodeAddress,
    format8,
    format16,
    bech32Encode,
    bech32Decode,
    dumpj,
    logmt,
    logm,
)

DEBUG = True

DBT_DATA = ord('d')
DBT_BAL = ord('b')
DBT_POOL_BAL = ord('p')
DBT_POOL_BLOCK = ord('B')  # Key height : data blockhash + blockreward + poolcointotal
DBT_POOL_PAYOUT = ord('P')  # Key height + txhash : data totalDisbursed
DBT_POOL_PENDING_PAYOUT = ord('Q')
DBT_POOL_METRICS = ord('M')  # Key Y-m : data nblocks + totalcoin


decimal.getcontext().prec = 8
mxDB = threading.Lock()


def getDBMutex(method):
    @wraps(method)
    def _impl(self, *method_args, **method_kwargs):
        mxDB.acquire()
        try:
            return method(self, *method_args, **method_kwargs)
        finally:
            mxDB.release()
    return _impl


class StakePool():
    def __init__(self, fp, dataDir, settings, chain):
        self.is_running = True
        self.fail_code = 0

        self.fp = fp
        self.dataDir = dataDir
        self.settings = settings

        self.blockBuffer = 100  # Work n blocks from the tip to avoid forks, should be > COINBASE_MATURITY

        self.mode = settings['mode'] if 'mode' in settings else 'master'
        self.binDir = os.path.expanduser(settings['particlbindir'])
        self.particlDataDir = os.path.expanduser(settings['particldatadir'])
        self.chain = chain
        self.debug = settings['debug'] if 'debug' in settings else DEBUG

        self.poolAddrHrp = 'pcs' if self.chain == 'mainnet' else 'tpcs'

        self.poolAddr = settings['pooladdress']
        self.poolAddrReward = settings['rewardaddress']

        self.poolHeight = settings['startheight'] if 'startheight' in settings else 0

        self.maxOutputsPerTx = settings['maxoutputspertx'] if 'maxoutputspertx' in settings else 48

        # Default parameters
        self.poolFeePercent = 2
        self.stakeBonusPercent = 5

        self.payoutThreshold = int(0.5 * COIN)
        self.minBlocksBetweenPayments = 100  # Minimum number of blocks between payment runs

        self.minOutputValue = int(0.1 * COIN)  # Ignore any outputs of lower value when accumulating rewards
        self.tx_fee_per_kb = None

        self.dbPath = os.path.join(dataDir, 'stakepooldb')

        db = plyvel.DB(self.dbPath, create_if_missing=True)
        n = db.get(bytes([DBT_DATA]) + b'current_height')
        if n is not None:
            self.poolHeight = struct.unpack('>i', n)[0]

        self.lastHeightParametersSet = -1
        self.setParameters(self.poolHeight)

        self.zmqContext = zmq.Context()
        self.zmqSubscriber = self.zmqContext.socket(zmq.SUB)

        self.zmqSubscriber.connect(self.settings['zmqhost'] + ':' + str(self.settings['zmqport']))
        self.zmqSubscriber.setsockopt_string(zmq.SUBSCRIBE, 'hashblock')

        self.debugDir = os.path.join(dataDir, 'poolDebug')
        if self.debug and not os.path.exists(self.debugDir):
            os.makedirs(self.debugDir)
            with open(os.path.join(self.debugDir, 'pool.csv'), 'a') as fp:
                fp.write('height,blockReward,blockOutput,poolReward,poolRewardTotal,poolCoinTotal,Disbursed,fees,totalFees\n')

        if self.mode == 'master':
            try:
                self.min_blocks_between_withdrawals = self.settings['poolownerwithdrawal']['frequency']
                assert(self.min_blocks_between_withdrawals > self.blockBuffer)
                self.owner_withdrawal_addr = self.settings['poolownerwithdrawal']['address']
                assert(self.settings['poolownerwithdrawal']['reserve'] >= 0.005)
                assert(self.settings['poolownerwithdrawal']['threshold'] >= 0.0)
                self.have_withdrawal_info = True
            except Exception:
                traceback.print_exc()
                self.have_withdrawal_info = False

            # If pool was synced in observer mode 'pool_fees_detected' may be higher than 'pool_fees'
            # 'pool_fees_detected' is tracked at chain tip - buffer, while 'pool_fees' is tracked as the pool makes transactions
            n = db.get(bytes([DBT_DATA]) + b'pool_fees_detected')
            pool_fees_detected = 0 if n is None else int.from_bytes(n, 'big')

            dbkey = bytes([DBT_DATA]) + b'pool_fees'
            n = db.get(dbkey)
            pool_fees = 0 if n is None else int.from_bytes(n, 'big')

            if pool_fees_detected > pool_fees:
                logmt(self.fp, 'Replacing pool_fees with pool_fees_detected: %s, %s' % (format8(pool_fees), format8(pool_fees_detected)))
                db.put(dbkey, pool_fees_detected.to_bytes(8, 'big'))
        else:
            self.have_withdrawal_info = False

        addr = db.get(bytes([DBT_DATA]) + b'pool_addr')
        if addr is not None:
            self.poolAddr = bech32Encode(self.poolAddrHrp, addr)
        else:
            db.put(bytes([DBT_DATA]) + b'pool_addr', bech32Decode(self.poolAddrHrp, self.poolAddr))

        addr = db.get(bytes([DBT_DATA]) + b'reward_addr')
        if addr is not None:
            self.poolAddrReward = encodeAddress(addr)
        else:
            db.put(bytes([DBT_DATA]) + b'reward_addr', decodeAddress(self.poolAddrReward))
        db.close()

        # Wait for daemon to start
        authcookiepath = os.path.join(self.particlDataDir, '' if self.chain == 'mainnet' else self.chain, '.cookie')
        for i in range(10):
            if not os.path.exists(authcookiepath):
                time.sleep(0.5)
        with open(authcookiepath) as fp:
            self.rpc_auth = fp.read()

        # Todo: read rpc port from .conf file
        self.rpc_port = settings['rpcport'] if 'rpcport' in settings else (51735 if self.chain == 'mainnet' else 51935)

        logmt(self.fp, 'Starting StakePool at height %d\nPool Address: %s, Reward Address: %s, Mode %s\n' % (self.poolHeight, self.poolAddr, self.poolAddrReward, self.mode))

        if self.mode == 'master':
            self.runSanityChecks()

    def stopRunning(self, with_code=0):
        self.fail_code = with_code
        self.is_running = False

    def setParameters(self, height):
        if 'parameters' in self.settings:
            if self.lastHeightParametersSet < 0:
                # Sort by height ascending
                self.settings['parameters'].sort(key=lambda x: x['height'])

            for p in self.settings['parameters']:
                if p['height'] <= self.lastHeightParametersSet:
                    continue
                if p['height'] > height:
                    break

                logmt(self.fp, 'Set parameters at height %d %s' % (height, dumpj(p)))

                if 'poolfeepercent' in p:
                    self.poolFeePercent = p['poolfeepercent']
                if 'stakebonuspercent' in p:
                    self.stakeBonusPercent = p['stakebonuspercent']
                if 'payoutthreshold' in p:
                    self.payoutThreshold = int(p['payoutthreshold'] * COIN)
                if 'minblocksbetweenpayments' in p:
                    self.minBlocksBetweenPayments = p['minblocksbetweenpayments']
                if 'minoutputvalue' in p:
                    self.minOutputValue = int(p['minoutputvalue'] * COIN)
                if 'txfeerate' in p:
                    self.tx_fee_per_kb = p['txfeerate']

                self.lastHeightParametersSet = p['height']

    def runSanityChecks(self):
        for i in range(21):
            if i == 20:
                logmt(self.fp, 'Can\'t connect to daemon RPC, exiting.')
                self.stopRunning(1)  # exit with error so systemd will try restart it
                return
            try:
                r = callrpc(self.rpc_port, self.rpc_auth, 'walletsettings', ['stakingoptions'], 'pool_stake')
                break
            except Exception as ex:
                traceback.print_exc()
                logmt(self.fp, 'Can\'t connect to daemon RPC, trying again in %d second/s.' % (1 + i))
                time.sleep(1 + i)
        try:
            if r['stakingoptions']['rewardaddress'] != self.poolAddrReward:
                logmt(self.fp, 'Warning: Mismatched reward address!')
        except Exception:
            logmt(self.fp, 'Warning: \'pool_stake\' wallet reward address isn\'t set!')

        r = callrpc(self.rpc_port, self.rpc_auth, 'walletsettings', ['stakingoptions'], 'pool_reward')
        try:
            if r['stakingoptions']['enabled'] is not False:
                if r['stakingoptions']['enabled'].lower() != 'false':
                    logmt(self.fp, 'Warning: Staking is not disabled on the \'pool_reward\' wallet!')
        except Exception:
            logmt(self.fp, 'Warning: Staking is not disabled on the \'pool_reward\' wallet!')

        if self.have_withdrawal_info:
            try:
                r = callrpc(self.rpc_port, self.rpc_auth, 'validateaddress', [self.owner_withdrawal_addr])
                assert(r['isvalid'] is True)
            except Exception:
                self.have_withdrawal_info = False
                logmt(self.fp, 'Warning: Invalid \'owner_withdrawal_addr\'.')

        if self.have_withdrawal_info:
            logmt(self.fp, 'Withdraw pool rewards to address: %s.\nMin blocks between withdrawals:%d' % (self.owner_withdrawal_addr, self.min_blocks_between_withdrawals))
        else:
            logmt(self.fp, 'Withdraw pool rewards to address: Disabled.')

    def getBalance(self, key, db, batchBalances):
        n = batchBalances.get(key)
        if n is None:
            n = db.get(key)
        return n

    def setBalance(self, key, value, b, batchBalances):
        b.put(key, value)
        batchBalances[key] = value

    @getDBMutex
    def processBlock(self, height):
        logmt(self.fp, 'processBlock height %d' % (height))

        reward = callrpc(self.rpc_port, self.rpc_auth, 'getblockreward', [height, ])

        db = plyvel.DB(self.dbPath, create_if_missing=True)

        n = db.get(bytes([DBT_DATA]) + b'current_height')
        if n is not None:
            poolDBHeight = struct.unpack('>i', n)[0]
            if poolDBHeight >= height:
                logmt(self.fp, 'Block %d already processed, pooldb height %d' % (height, poolDBHeight))
                self.poolHeight = poolDBHeight
                db.close()
                return

        self.setParameters(height)

        if 'coinstake' not in reward:
            # logm('No coinstake txn found in block ' + str(height))
            db.put(bytes([DBT_DATA]) + b'current_height', struct.pack('>i', height))
            db.close()
            self.poolHeight = height
            return

        batchBalances = dict()
        b = db.write_batch(transaction=True)
        b.put(bytes([DBT_DATA]) + b'current_height', struct.pack('>i', height))

        self.findPayments(height, reward['coinstake'], db, b, batchBalances)

        for out in reward['outputs']:
            try:
                if self.poolAddrReward == out['script']['spendaddr']:
                    if out['value'] != reward['blockreward']:
                        logmt(self.fp, 'WARNING: Pool reward mismatch at height %d\n' % (height))
                    try:
                        self.processPoolBlock(height, reward, db, b, batchBalances)
                    except Exception:
                        exc_type, exc_value, exc_tb = sys.exc_info()
                        traceback.print_exception(exc_type, exc_value, exc_tb)
                        traceback.print_exception(exc_type, exc_value, exc_tb, file=self.fp)
                        self.fp.flush()
                    break
            except Exception:
                pass

        b.write()

        n = db.get(bytes([DBT_DATA]) + b'last_payment_run')
        lastPaymentRunHeight = 0 if n is None else struct.unpack('>i', n)[0]
        if lastPaymentRunHeight + self.minBlocksBetweenPayments <= height:
            with db.write_batch(transaction=True) as b:
                self.processPayments(height, db, b)

        if self.have_withdrawal_info:
            n = db.get(bytes([DBT_DATA]) + b'last_withdrawal_run')
            last_withdrawal_run = 0 if n is None else struct.unpack('>i', n)[0]
            if last_withdrawal_run + self.min_blocks_between_withdrawals <= height:
                with db.write_batch(transaction=True) as b:
                    self.processPoolRewardWithdrawal(height, db, b)

        db.close()
        self.poolHeight = height

    def processPoolBlock(self, height, reward, db, b, batchBalances):
        logmt(self.fp, 'Found block at ' + str(height))
        opts = {'mature_only': True, 'all_staked': True}
        outputs = callrpc(self.rpc_port, self.rpc_auth, 'listcoldstakeunspent', [self.poolAddr, height - 1, opts])

        totals = dict()
        poolCoinTotal = 0
        lowValueOutputs = 0
        for o in outputs:
            v = o['value']
            if v < self.minOutputValue:
                lowValueOutputs += 1
                continue

            if o['addrspend'] in totals:
                totals[o['addrspend']] += v
            else:
                totals[o['addrspend']] = v
            poolCoinTotal += v

        if lowValueOutputs > 0 and self.debug:
            logmt(self.fp, 'Ignoring %d low value outputs at height %d' % (lowValueOutputs, height))

        blockReward = int(decimal.Decimal(reward['blockreward']) * COIN)

        # Coin paid to the pool operator
        poolReward = int((blockReward * (self.poolFeePercent * (COIN // 100))) // COIN)

        stakeBonus = 0
        if self.stakeBonusPercent > 0:
            stakeBonus = int((blockReward * (self.stakeBonusPercent * (COIN // 100))) // COIN)

        # Coin paid to the pool participants
        poolRewardClients = int(blockReward - (poolReward + stakeBonus))

        b.put(bytes([DBT_DATA]) + b'current_height', struct.pack('>i', height))
        b.put(bytes([DBT_POOL_BLOCK]) + struct.pack('>i', height), bytes.fromhex(reward['blockhash']) + blockReward.to_bytes(8, 'big') + poolCoinTotal.to_bytes(8, 'big'))

        dbkey = bytes([DBT_DATA]) + b'blocks_found'
        n = db.get(dbkey)
        blocksFound = 1 if n is None else struct.unpack('>i', n)[0] + 1
        b.put(dbkey, struct.pack('>i', blocksFound))

        if 'blocktime' in reward:
            date = dt.datetime.fromtimestamp(int(reward['blocktime'])).strftime('%Y-%m')
        else:
            # TODO: Remove
            blockinfo = callrpc(self.rpc_port, self.rpc_auth, 'getblock', [reward['blockhash']])
            date = dt.datetime.fromtimestamp(int(blockinfo['time'])).strftime('%Y-%m')

        dbkey = bytes([DBT_POOL_METRICS]) + bytes(date, 'UTF-8')
        m = db.get(dbkey)
        data = [1, poolCoinTotal]
        month_metrics = data if m is None else [struct.unpack('>i', m[:4])[0] + data[0], int.from_bytes(m[4:20], 'big') + data[1]]
        db.put(dbkey, struct.pack('>i', month_metrics[0]) + month_metrics[1].to_bytes(16, 'big'))

        poolRewardClients = int(poolRewardClients)
        for k, v in totals.items():

            addrReward = int((poolRewardClients * COIN * v) // (poolCoinTotal))
            addrTotal = addrReward

            assignedStakeBonus = 0
            if stakeBonus > 0 and k == reward['kernelscript']['spendaddr']:
                # if self.debug:
                #    logm(self.fp, 'Assigning stake bonus to %s %s\n' % (k, format8(stakeBonus)))
                addrTotal += int(stakeBonus * COIN)
                assignedStakeBonus = stakeBonus
                stakeBonus = 0

            dbkey = bytes([DBT_BAL]) + decodeAddress(k)
            n = self.getBalance(dbkey, db, batchBalances)
            if n is not None:
                addrTotal += int.from_bytes(n[:16], 'big')
                self.setBalance(dbkey, addrTotal.to_bytes(16, 'big') + n[16:32] + v.to_bytes(8, 'big'), b, batchBalances)
            else:
                addrPending = 0
                addrPaidout = 0
                self.setBalance(dbkey, addrTotal.to_bytes(16, 'big') + addrPending.to_bytes(8, 'big') + addrPaidout.to_bytes(8, 'big') + v.to_bytes(8, 'big'), b, batchBalances)

            if self.debug:
                with open(os.path.join(self.debugDir, k + '.csv'), 'a') as fp:
                    fp.write('%d,%s,%s,%s,%s,%s\n'
                             % (height,
                                format8(poolCoinTotal),
                                format8(v),
                                format8(assignedStakeBonus),
                                format16(addrReward),
                                format16(addrTotal)))

        if stakeBonus > 0:  # An output < minOutputValue may have staked
            if self.debug:
                logmt(self.fp, 'Unassigned stake bonus: %s %s\n' % (reward['kernelscript']['spendaddr'], format8(stakeBonus)))

        poolRewardTotal = int(poolReward + stakeBonus)
        dbkey = bytes([DBT_POOL_BAL]) + decodeAddress(self.poolAddrReward)
        n = db.get(dbkey)
        if n is not None:
            poolRewardTotal += int.from_bytes(n, 'big')
        b.put(dbkey, poolRewardTotal.to_bytes(8, 'big'))

        if self.debug:
            blockOutput = 0
            for out in reward['outputs']:
                blockOutput += int(decimal.Decimal(out['value']) * COIN)
            with open(os.path.join(self.debugDir, 'pool.csv'), 'a') as fp:
                fp.write('%d,%s,%s,%s,%s,%s\n'
                         % (height,
                            format8(blockReward),
                            format8(blockOutput),
                            format8(poolReward),
                            format8(poolRewardTotal),
                            format8(poolCoinTotal)))

    def processPayments(self, height, db, b):
        logmt(self.fp, 'processPayments height: %d\n' % (height))

        b.put(bytes([DBT_DATA]) + b'last_payment_run', struct.pack('>i', height))

        ro = callrpc(self.rpc_port, self.rpc_auth, 'getblockchaininfo')
        if ro['blocks'] >= self.poolHeight + self.blockBuffer + 5:
            logmt(self.fp, 'Warning: Pool height is below node height, skipping disbursement, %d, %d.\n' % (self.poolHeight, ro['blocks']))
            return

        totalDisbursed = 0
        txns = []
        outputs = []
        for key, value in db.iterator(prefix=bytes([DBT_BAL])):
            addrAccumulated = int.from_bytes(value[:16], 'big')

            if (addrAccumulated // COIN) < self.payoutThreshold:
                continue

            addrPending = int.from_bytes(value[16:24], 'big')
            addrPaidout = int.from_bytes(value[24:32], 'big')
            address = encodeAddress(key[1:])

            payout = addrAccumulated // COIN
            totalDisbursed += payout
            addrAccumulated -= payout * COIN

            outputs.append({'address': address, 'amount': format8(payout)})
            addrPending += payout

            b.put(key, addrAccumulated.to_bytes(16, 'big') + addrPending.to_bytes(8, 'big') + addrPaidout.to_bytes(8, 'big') + value[32:])

        if len(outputs) < 1:
            return

        if self.mode != 'master':
            return

        txfees = 0
        for i in range(0, len(outputs), self.maxOutputsPerTx):
            sl = outputs[i:i + self.maxOutputsPerTx]

            totalDisbursedInTx = 0
            for o in sl:
                totalDisbursedInTx += int(decimal.Decimal(o['amount']) * COIN)
            # Send change back to the pool reward address for easier tracking by observers
            opts = {
                'show_fee': True,
                'changeaddress': self.poolAddrReward
            }

            if self.tx_fee_per_kb is not None:
                opts['feeRate'] = self.tx_fee_per_kb

            ro = callrpc(self.rpc_port, self.rpc_auth, 'sendtypeto',
                         ['part', 'part', sl, '', '', 4, 64, False, opts], 'pool_reward')

            txfees += int(decimal.Decimal(ro['fee']) * COIN)
            txns.append(ro['txid'])

            b.put(bytes([DBT_POOL_PENDING_PAYOUT]) + bytes.fromhex(ro['txid']), totalDisbursedInTx.to_bytes(8, 'big') + txfees.to_bytes(8, 'big'))

            if self.debug:
                for o in sl:
                    with open(os.path.join(self.debugDir, o['address'] + '.csv'), 'a') as fp:
                        fp.write('%d,%s,%s,%s,%s,%s,%s,%s\n'
                                 % (height,
                                    '',
                                    '',
                                    '',
                                    '',
                                    format16(addrAccumulated),
                                    o['amount'],
                                    ro['txid'],
                                    ))

        dbkey = bytes([DBT_DATA]) + b'pool_fees'
        n = db.get(dbkey)
        totalPoolFees = txfees if n is None else txfees + int.from_bytes(n, 'big')
        b.put(dbkey, totalPoolFees.to_bytes(8, 'big'))

        if self.debug:
            with open(os.path.join(self.debugDir, 'pool.csv'), 'a') as fp:
                fp.write('%d,%s,%s,%s,%s,%s,%s,%s,%s\n'
                         % (height,
                            '',
                            '',
                            '',
                            '',
                            format8(totalDisbursed),
                            format8(txfees),
                            format8(totalPoolFees),
                            '|'.join(txns)
                            ))

    def findPayments(self, height, coinstakeid, db, b, batchBalances):
        # logm(self.fp, 'findPayments')
        opts = {
            'addresses': [self.poolAddrReward],
            'start': height,
            'end': height,
        }
        ro = callrpc(self.rpc_port, self.rpc_auth, 'getaddressdeltas', [opts, ])

        txids = set()
        for delta in ro:
            if delta['txid'] == coinstakeid:
                if delta['satoshis'] < 0:
                    logmt(self.fp, 'WARNING: Pool reward coin spent in coinstake %s\n' % (coinstakeid))
                continue
            txids.add(delta['txid'])

        if len(txids) < 1:
            return

        for txid in txids:
            ro = callrpc(self.rpc_port, self.rpc_auth, 'getrawtransaction', [txid, True])

            have_blinded = False
            total_input_value = 0
            total_output_value = 0
            for n, inp in enumerate(ro['vin']):
                try:
                    ri = callrpc(self.rpc_port, self.rpc_auth, 'getrawtransaction', [inp['txid'], True])
                    prevout = ri['vout'][inp['vout']]
                    if prevout['type'] == 'blind':
                        have_blinded = True
                    else:
                        total_input_value += int(decimal.Decimal(prevout['value']) * COIN)
                except Exception:
                    logmt(self.fp, 'WARNING: Could not get prevout value input %s.%d.\n' % (txid, n))

            totalDisbursed = 0
            for out in ro['vout']:
                try:
                    if out['type'] == 'data':
                        continue
                    if out['type'] == 'blind':
                        logmt(self.fp, 'WARNING: Found txn %s paying to blinded output.\n' % (txid))
                        have_blinded = True
                        continue
                    if out['type'] == 'anon':
                        logmt(self.fp, 'WARNING: Found txn %s paying to anon output.\n' % (txid))
                        have_blinded = True
                        continue
                except Exception:
                    logmt(self.fp, 'WARNING: Found txn %s paying to unknown output type.\n' % (txid))
                    continue

                v = int(decimal.Decimal(out['value']) * COIN)
                total_output_value += v

                address = None
                try:
                    address = out['scriptPubKey']['addresses'][0]
                except Exception:
                    logmt(self.fp, 'WARNING: Found txn %s paying to unknown address.\n' % (txid))
                    continue

                if address == self.poolAddrReward:
                    # Change output
                    continue

                dbkey = bytes([DBT_BAL]) + decodeAddress(address)
                n = self.getBalance(dbkey, db, batchBalances)
                if n is None:
                    logmt(self.fp, 'Withdrawal detected from pool reward balance %s %d %s.\n' % (txid, out['n'], format8(v)))

                    dbkey = bytes([DBT_DATA]) + b'pool_withdrawn'
                    n = db.get(dbkey)
                    poolWithdrawnTotal = v if n is None else v + int.from_bytes(n, 'big')
                    b.put(dbkey, poolWithdrawnTotal.to_bytes(8, 'big'))

                    if self.debug:
                        with open(os.path.join(self.debugDir, 'pool_withdrawals.csv'), 'a') as fp:
                            fp.write('%d,%s,%d,%s,%s\n'
                                     % (height, txid, out['n'], address, format8(v)))
                    continue

                addrReward = int.from_bytes(n[:16], 'big')
                addrPending = int.from_bytes(n[16:24], 'big')
                addrPaidout = int.from_bytes(n[24:32], 'big')
                addrPending -= v
                addrPaidout += v
                totalDisbursed += v
                if addrPending < 0:
                    logmt(self.fp, 'WARNING: txn %s overpays address %s more than pending payout, pending: %d, paid: %d.\n' % (txid, address, addrPending + v, v), True, True)
                    if addrReward + addrPending < 0:
                        logmt(self.fp, 'WARNING: txn %s overpays address %s more than accumulated reward %d, paid: %d.\n' % (txid, address, addrPending + v, v), True, True)
                    else:
                        addrReward += addrPending
                    addrPending = 0

                self.setBalance(dbkey, addrReward.to_bytes(16, 'big') + addrPending.to_bytes(8, 'big') + addrPaidout.to_bytes(8, 'big') + n[32:], b, batchBalances)

                if self.debug:
                    logmt(self.fp, 'Payout to %s: %s %d %s.\n' % (address, txid, out['n'], format8(v)))

            if totalDisbursed > 0:
                b.put(bytes([DBT_POOL_PAYOUT]) + struct.pack('>i', height) + bytes.fromhex(txid), totalDisbursed.to_bytes(8, 'big'))
                b.delete(bytes([DBT_POOL_PENDING_PAYOUT]) + bytes.fromhex(txid))

            try:
                if have_blinded:
                    fee = ro['vout'][0]['ct_fee']
                else:
                    fee = total_input_value - total_output_value

                if self.debug:
                    logmt(self.fp, 'Payout tx %s, input %s, output %s, fee %s.\n' % (txid, format8(total_input_value), format8(total_output_value), format8(fee)))

                dbkey = bytes([DBT_DATA]) + b'pool_fees_detected'
                n = db.get(dbkey)
                totalPoolFees = fee if n is None else fee + int.from_bytes(n, 'big')
                b.put(dbkey, totalPoolFees.to_bytes(8, 'big'))
            except Exception:
                exc_type, exc_value, exc_tb = sys.exc_info()
                traceback.print_exception(exc_type, exc_value, exc_tb)
                traceback.print_exception(exc_type, exc_value, exc_tb, file=self.fp)
                self.fp.flush()

    def processPoolRewardWithdrawal(self, height, db, b):
        logmt(self.fp, 'processPoolRewardWithdrawal height: %d\n' % (height))

        b.put(bytes([DBT_DATA]) + b'last_withdrawal_run', struct.pack('>i', height))

        r = callrpc(self.rpc_port, self.rpc_auth, 'getwalletinfo', [], 'pool_reward')

        n = db.get(bytes([DBT_POOL_BAL]) + decodeAddress(self.poolAddrReward))
        pool_reward = 0 if n is None else int.from_bytes(n, 'big')

        n = db.get(bytes([DBT_DATA]) + b'pool_fees')
        poolfees = 0 if n is None else int.from_bytes(n, 'big')

        n = db.get(bytes([DBT_DATA]) + b'pool_withdrawn')
        pool_reward_withdrawn = 0 if n is None else int.from_bytes(n, 'big')
        pool_reward_bal = float(decimal.Decimal((pool_reward - (poolfees + pool_reward_withdrawn)) / COIN))

        reserve = self.settings['poolownerwithdrawal']['reserve']
        threshold = self.settings['poolownerwithdrawal']['threshold']

        if self.debug:
            logm(self.fp, 'Balance %f, reserve %f, threshold %f\npool_reward %s, poolfees %s, pool_reward_withdrawn %s, pool_reward_bal %f' %
                          (r['balance'], reserve, threshold, format8(decimal.Decimal(pool_reward)), format8(decimal.Decimal(poolfees)), format8(decimal.Decimal(pool_reward_withdrawn)), pool_reward_bal))

        if r['balance'] <= reserve or pool_reward_bal < reserve + threshold:
            return

        ro = callrpc(self.rpc_port, self.rpc_auth, 'getblockchaininfo')
        if ro['blocks'] >= self.poolHeight + self.blockBuffer + 5:
            logmt(self.fp, 'Warning: Pool height is below node height, skipping withdrawal, %d, %d.\n' % (self.poolHeight, ro['blocks']))
            return

        try:
            withdraw_amount = format8(decimal.Decimal(pool_reward_bal - reserve) * COIN)

            # Send change back to the pool reward address for easier tracking by observers
            opts = {
                'show_fee': True,
                'changeaddress': self.poolAddrReward
            }

            if self.tx_fee_per_kb is not None:
                opts['feeRate'] = self.tx_fee_per_kb

            outputs = [{'address': self.owner_withdrawal_addr, 'amount': withdraw_amount}]
            ro = callrpc(self.rpc_port, self.rpc_auth, 'sendtypeto',
                         ['part', 'part', outputs, '', '', 4, 64, False, opts], 'pool_reward')

            txfee = int(decimal.Decimal(ro['fee']) * COIN)
            logmt(self.fp, 'Withdrawing %s to %s in tx: %s\n' % (withdraw_amount, self.owner_withdrawal_addr, ro['txid']))

            dbkey = bytes([DBT_DATA]) + b'pool_fees'
            n = db.get(dbkey)
            totalPoolFees = txfee if n is None else txfee + int.from_bytes(n, 'big')
            b.put(dbkey, totalPoolFees.to_bytes(8, 'big'))

            if self.debug:
                with open(os.path.join(self.debugDir, 'pool_withdrawals.csv'), 'a') as fp:
                    fp.write('%d,%s,%d,%s,%s\n'
                             % (height, ro['txid'], -1, self.owner_withdrawal_addr, withdraw_amount))

                r = callrpc(self.rpc_port, self.rpc_auth, 'getwalletinfo', [], 'pool_reward')
                logm(self.fp, 'Available balance after withdrawal %f' % (r['balance']))

        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)
            traceback.print_exception(exc_type, exc_value, exc_tb, file=self.fp)
            self.fp.flush()

    def checkBlocks(self, limit_blocks=-1):
        try:
            message = self.zmqSubscriber.recv(flags=zmq.NOBLOCK)
            if message == b'hashblock':
                message = self.zmqSubscriber.recv()
                seq = self.zmqSubscriber.recv()
                r = callrpc(self.rpc_port, self.rpc_auth, 'getblockchaininfo')
                while r['blocks'] - self.blockBuffer > self.poolHeight and self.is_running:
                    self.processBlock(self.poolHeight + 1)
                    if limit_blocks < 0:
                        continue
                    limit_blocks -= 1
                    if limit_blocks == 0:
                        break
        except zmq.Again as e:
            pass
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)
            traceback.print_exception(exc_type, exc_value, exc_tb, file=self.fp)
            self.fp.flush()

    @getDBMutex
    def getAddressSummary(self, address_str):
        rv = {}

        # TODO: bech32 decode and test chain
        address = decodeAddress(address_str)
        if address is None or len(address) != 33:
            raise ValueError('Invalid address')

        db = plyvel.DB(self.dbPath)

        dbkey = bytes([DBT_BAL]) + address
        n = db.get(dbkey)
        if n is not None:
            rv['accumulated'] = int.from_bytes(n[:16], 'big')
            rv['rewardpending'] = int.from_bytes(n[16:24], 'big')
            rv['rewardpaidout'] = int.from_bytes(n[24:32], 'big')
            rv['laststaking'] = int.from_bytes(n[32:40], 'big')
            # TODO: get total staking from csindex?

        db.close()

        utxos = callrpc(self.rpc_port, self.rpc_auth, 'listunspent',
                        [1, 9999999, [address_str, ], True, {'include_immature': True}], 'pool_stake')

        totalCoinCurrent = 0
        for utxo in utxos:
            totalCoinCurrent += int(decimal.Decimal(utxo['amount']) * COIN)
        rv['currenttotal'] = totalCoinCurrent

        return rv

    @getDBMutex
    def rebuildMetrics(self):

        # Remove old cache
        db = plyvel.DB(self.dbPath)
        it = db.iterator(prefix=bytes([DBT_POOL_METRICS]))
        try:
            while True:
                k, v = next(it)
                db.delete(k)
        except Exception:
            pass
        it.close()

        num_blocks = 0
        it = db.iterator(prefix=bytes([DBT_POOL_BLOCK]), reverse=True)
        try:
            while True:
                k, v = next(it)
                foundblock = (struct.unpack('>i', k[1:])[0], v[:32].hex(), int.from_bytes(v[32:40], 'big'), int.from_bytes(v[40:48], 'big'))

                blockinfo = callrpc(self.rpc_port, self.rpc_auth, 'getblock', [foundblock[1]])
                date = dt.datetime.fromtimestamp(int(blockinfo['time'])).strftime('%Y-%m')

                dbkey = bytes([DBT_POOL_METRICS]) + bytes(date, 'UTF-8')
                m = db.get(dbkey)
                data = [1, foundblock[3]]
                month_metrics = data if m is None else [struct.unpack('>i', m[:4])[0] + data[0], int.from_bytes(m[4:20], 'big') + data[1]]
                db.put(dbkey, struct.pack('>i', month_metrics[0]) + month_metrics[1].to_bytes(16, 'big'))

                num_blocks += 1
        except Exception:
            pass
        it.close()
        db.close()

        return {'processedblocks': num_blocks}

    @getDBMutex
    def getMetrics(self):

        db = plyvel.DB(self.dbPath)
        month_metrics = []
        it = db.iterator(prefix=bytes([DBT_POOL_METRICS]), reverse=True)
        try:
            for i in range(12):
                k, v = next(it)
                data = (struct.unpack('>i', v[:4])[0], int.from_bytes(v[4:20], 'big'))
                month_metrics.append([k[1:].decode('UTF-8'), data[0], data[1] // data[0]])
        except Exception:
            pass
        it.close()
        db.close()

        return month_metrics

    @getDBMutex
    def getSummary(self, opts=None):
        rv = {}

        rv['poolmode'] = self.mode

        db = plyvel.DB(self.dbPath)

        n = db.get(bytes([DBT_DATA]) + b'current_height')
        rv['poolheight'] = 0 if n is None else struct.unpack('>i', n)[0]

        n = db.get(bytes([DBT_DATA]) + b'blocks_found')
        rv['blocksfound'] = 0 if n is None else struct.unpack('>i', n)[0]

        n = db.get(bytes([DBT_POOL_BAL]) + decodeAddress(self.poolAddrReward))
        rv['poolrewardtotal'] = 0 if n is None else int.from_bytes(n, 'big')

        n = db.get(bytes([DBT_DATA]) + (b'pool_fees' if self.mode == 'master' else b'pool_fees_detected'))
        rv['poolfeestotal'] = 0 if n is None else int.from_bytes(n, 'big')

        n = db.get(bytes([DBT_DATA]) + b'pool_withdrawn')
        rv['poolwithdrawntotal'] = 0 if n is None else int.from_bytes(n, 'big')

        n = db.get(bytes([DBT_DATA]) + b'last_payment_run')
        rv['lastpaymentrunheight'] = 0 if n is None else struct.unpack('>i', n)[0]

        lastBlocks = []
        it = db.iterator(prefix=bytes([DBT_POOL_BLOCK]), reverse=True)
        try:
            for i in range(5):
                k, v = next(it)
                lastBlocks.append((struct.unpack('>i', k[1:])[0], v[:32].hex(), int.from_bytes(v[32:40], 'big'), int.from_bytes(v[40:48], 'big')))
        except Exception:
            pass
        it.close()

        pendingPayments = []
        it = db.iterator(prefix=bytes([DBT_POOL_PENDING_PAYOUT]), reverse=True)
        try:
            for i in range(5):
                k, v = next(it)
                pendingPayments.append((k[1:].hex(), int.from_bytes(v[:8], 'big'), int.from_bytes(v[8:16], 'big')))
        except Exception:
            pass
        it.close()

        lastPayments = []
        it = db.iterator(prefix=bytes([DBT_POOL_PAYOUT]), reverse=True)
        try:
            for i in range(5):
                k, v = next(it)
                lastPayments.append((struct.unpack('>i', k[1:5])[0], k[5:38].hex(), int.from_bytes(v[:8], 'big')))
        except Exception:
            pass
        it.close()

        db.close()

        rv['lastblocks'] = lastBlocks
        rv['pendingpayments'] = pendingPayments
        rv['lastpayments'] = lastPayments

        # TODO: cache at height
        try:
            stakinginfo = callrpc(self.rpc_port, self.rpc_auth, 'getstakinginfo', [], 'pool_stake')
            rv['stakeweight'] = stakinginfo['weight']
        except Exception:
            rv['stakeweight'] = 0

        try:
            walletinfo = callrpc(self.rpc_port, self.rpc_auth, 'getwalletinfo', [], 'pool_stake')
            rv['watchonlytotalbalance'] = walletinfo['watchonly_total_balance']
            rv['stakedbalance'] = walletinfo['watchonly_staked_balance']
        except Exception:
            rv['watchonlytotalbalance'] = 0
            rv['stakedbalance'] = 0

        return rv
