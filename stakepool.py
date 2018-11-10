#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

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
import json
import zmq
import threading
import traceback
import plyvel
import struct
import signal
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import http.client
from functools import wraps
from util import *

DEBUG = True
WRITE_TO_LOG_FILE = True


PARTICL_CLI = os.getenv("PARTICL_CLI", "particl-cli")
COIN = 100000000

DBT_DATA = ord('d')
DBT_BAL = ord('b')
DBT_POOL_BAL = ord('p')
DBT_POOL_BLOCK = ord('B')  # Key height : data blockhash + blockreward + poolcointotal
DBT_POOL_PAYOUT = ord('P')  # Key height + txhash : data totalDisbursed
DBT_POOL_PENDING_PAYOUT = ord('Q')
DBT_POOL_METRICS = ord('M')  # Key Y-m : data nblocks + totalcoin


decimal.getcontext().prec = 8


def format8(i):
    n = abs(i)
    quotient = n // COIN
    remainder = n % COIN
    rv = "%d.%08d" % (quotient, remainder)
    if i < 0:
        rv = '-' + rv
    return rv


def format16(i):
    n = abs(i)
    quotient = n // (COIN * COIN)
    remainder = n % (COIN * COIN)
    rv = "%d.%016d" % (quotient, remainder)
    if i < 0:
        rv = '-' + rv
    return rv


mxLog = threading.Lock()
def logm(fp, s, tag='', printstd=True, writetofile=WRITE_TO_LOG_FILE):
    mxLog.acquire()
    try:
        if printstd:
            print(s)

        if writetofile:
            fp.write(tag + s + '\n')
            fp.flush()
    finally:
        mxLog.release()


def logmt(fp, s, printstd=True, writetofile=WRITE_TO_LOG_FILE):
    logm(fp, time.strftime('%y-%m-%d_%H-%M-%S', time.localtime()) + '\t' + s, printstd=printstd, writetofile=writetofile)


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
                stopRunning(1)  # exit with error so systemd will try restart it
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
            #logm('No coinstake txn found in block ' + str(height))
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
                        traceback.print_exc()
                    break
            except Exception:
                pass

        b.write()

        lastPaymentRunHeight = 0
        n = db.get(bytes([DBT_DATA]) + b'last_payment_run')
        if n is not None:
            lastPaymentRunHeight = struct.unpack('>i', n)[0]

        if lastPaymentRunHeight + self.minBlocksBetweenPayments <= height:
            with db.write_batch(transaction=True) as b:
                self.processPayments(height, db, b)

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
        poolReward = (blockReward * (self.poolFeePercent * (COIN // 100))) // COIN

        stakeBonus = 0
        if self.stakeBonusPercent > 0:
            stakeBonus = (blockReward * (self.stakeBonusPercent * (COIN // 100))) // COIN

        # Coin paid to the pool participants
        poolRewardClients = blockReward - (poolReward + stakeBonus)

        #addrsToPay = []

        b.put(bytes([DBT_DATA]) + b'current_height', struct.pack('>i', height))
        b.put(bytes([DBT_POOL_BLOCK]) + struct.pack('>i', height), bytes.fromhex(reward['blockhash']) + blockReward.to_bytes(8, 'big') + poolCoinTotal.to_bytes(8, 'big'))

        dbkey = bytes([DBT_DATA]) + b'blocks_found'
        n = db.get(dbkey)
        blocksFound = 1 if n is None else struct.unpack('>i', n)[0] + 1
        b.put(dbkey, struct.pack('>i', blocksFound))

        # TODO: add time to getblockreward
        blockinfo = callrpc(self.rpc_port, self.rpc_auth, 'getblock', [reward['blockhash']])
        date = dt.datetime.fromtimestamp(int(blockinfo['time'])).strftime('%Y-%m')

        dbkey = bytes([DBT_POOL_METRICS]) + bytes(date, 'UTF-8')
        m = db.get(dbkey)
        data = [1, poolCoinTotal]
        month_metrics = data if m is None else [struct.unpack('>i', m[:4])[0] + data[0], int.from_bytes(m[4:20], 'big') + data[1]]
        db.put(dbkey, struct.pack('>i', month_metrics[0]) + month_metrics[1].to_bytes(16, 'big'))

        poolRewardClients = int(poolRewardClients)
        for k, v in totals.items():

            addrReward = (poolRewardClients * COIN * v) // (poolCoinTotal)
            addrTotal = addrReward

            assignedStakeBonus = 0
            if stakeBonus > 0 and k == reward['kernelscript']['spendaddr']:
                #if self.debug:
                #    logm(self.fp, 'Assigning stake bonus to %s %s\n' % (k, format8(stakeBonus)))
                addrTotal += stakeBonus * COIN
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

            #if (addrTotal // COIN) > self.payoutThreshold:
            #    addrsToPay.append(k)

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

        poolRewardTotal = poolReward + stakeBonus
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

        """
        lastPaymentRunHeight = 0
        n = db.get(bytes([DBT_DATA]) + b'last_payment_run')
        if n != None:
            lastPaymentRunHeight = struct.unpack('>i', n)[0]


        print('lastPaymentRunHeight', lastPaymentRunHeight)
        print('lastPaymentRunHeight + self.minBlocksBetweenPayments', lastPaymentRunHeight + self.minBlocksBetweenPayments)
        print('height', height)
        if lastPaymentRunHeight + self.minBlocksBetweenPayments <= height:
            self.processPayments(addrsToPay, height, db, b, batchBalances)
        """

    def processPayments(self, height, db, b):
        logmt(self.fp, 'processPayments height: %d\n' % (height))

        b.put(bytes([DBT_DATA]) + b'last_payment_run', struct.pack('>i', height))

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

        if self.mode != 'master':
            return

        if len(outputs) < 1:
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

            #ro = callrpc_cli(self.binDir, self.particlDataDir, self.chain, '-rpcwallet=pool_reward sendtypeto part part "%s" "" "" 4 64 true "%s"' % (dumpje(sl), dumpje(opts)))
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

        totalPoolFees = txfees
        dbkey = bytes([DBT_DATA]) + b'pool_fees'
        n = db.get(dbkey)
        if n is not None:
            totalPoolFees += int.from_bytes(n, 'big')
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
        #logm(self.fp, 'findPayments')
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

            totalDisbursed = 0
            for out in ro['vout']:
                address = None
                try:
                    address = out['scriptPubKey']['addresses'][0]
                except Exception:
                    logmt(self.fp, 'WARNING: Found txn %s paying to unknown address.\n' % (txid))
                    continue

                if address == self.poolAddrReward:
                    # Change output
                    continue

                v = int(decimal.Decimal(out['value']) * COIN)
                dbkey = bytes([DBT_BAL]) + decodeAddress(address)
                n = self.getBalance(dbkey, db, batchBalances)
                if n is None:
                    logmt(self.fp, 'Withdrawal detected from pool reward balance %s %d %s.\n' % (txid, out['n'], format8(v)))

                    poolWithdrawnTotal = v
                    dbkey = bytes([DBT_DATA]) + b'pool_withdrawn'
                    n = db.get(dbkey)
                    if n is not None:
                        poolWithdrawnTotal += int.from_bytes(n, 'big')
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

    def checkBlocks(self):
        try:
            message = self.zmqSubscriber.recv(flags=zmq.NOBLOCK)
            if message == b'hashblock':
                message = self.zmqSubscriber.recv()
                seq = self.zmqSubscriber.recv()
                r = callrpc(self.rpc_port, self.rpc_auth, 'getblockchaininfo')
                while r['blocks'] - self.blockBuffer > self.poolHeight and is_running:
                    self.processBlock(self.poolHeight + 1)
        except zmq.Again as e:
            pass
        except Exception as ex:
            traceback.print_exc()

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

        n = db.get(bytes([DBT_DATA]) + b'pool_fees')
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
        except Exception:
            rv['watchonlytotalbalance'] = 0

        return rv


class HttpHandler(BaseHTTPRequestHandler):

    def page_error(self, error_str):
        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Error</title></head>' \
            + '<body>' \
            + '<p>Error: ' + error_str + '</p>' \
            + '<p><a href=\'/\'>home</a></p>' \
            + '</body></html>'
        return bytes(content, 'UTF-8')

    def js_error(self, error_str):
        error_str_json = json.dumps({'error': error_str})
        return bytes(error_str_json, 'UTF-8')

    def js_address(self, urlSplit):

        if len(urlSplit) < 4:
            return self.js_error('Must specify address')

        address_str = urlSplit[3]
        stakePool = self.server.stakePool
        try:
            return bytes(json.dumps(stakePool.getAddressSummary(address_str)), 'UTF-8')
        except Exception as e:
            return self.js_error(str(e))

    def js_metrics(self, urlSplit):
        stakePool = self.server.stakePool
        if len(urlSplit) > 3:
            code_str = urlSplit[3]
            salt = 'ajf8923ol2xcv.'
            hashed = hashlib.sha256(str(code_str + salt).encode('utf-8')).hexdigest()
            if not hashed == 'fd5816650227b75143e60c61b19e113f43f5dcb57e2aa5b6161a50973f2033df':
                return self.js_error('Unknown argument')
            try:
                return bytes(json.dumps(stakePool.rebuildMetrics()), 'UTF-8')
            except Exception as e:
                return self.js_error(str(e))
        try:
            return bytes(json.dumps(stakePool.getMetrics()), 'UTF-8')
        except Exception as e:
            return self.js_error(str(e))

    def js_index(self, urlSplit):
        try:
            return bytes(json.dumps(self.server.stakePool.getSummary()), 'UTF-8')
        except Exception as e:
            return self.js_error(str(e))

    def page_config(self, urlSplit):
        settingsPath = os.path.join(self.server.stakePool.dataDir, 'stakepool.json')

        if not os.path.exists(settingsPath):
            return self.page_error('Settings file not found.')

        with open(settingsPath) as fs:
            return bytes(fs.read(), 'UTF-8')

    def page_address(self, urlSplit):

        if len(urlSplit) < 3:
            return self.page_error('Must specify address')

        address_str = urlSplit[2]
        stakePool = self.server.stakePool
        try:
            summary = stakePool.getAddressSummary(address_str)
        except Exception as e:
            return self.page_error(str(e))

        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Address </title></head>' \
            + '<body>' \
            + '<h2>Spend Address ' + address_str + '</h2>' \
            + '<h4>Pool Address ' + stakePool.poolAddr + '</h4>'

        if 'accumulated' in summary:
            content += '<table>' \
                + '<tr><td>Accumulated:</td><td>' + format16(summary['accumulated']) + '</td></tr>' \
                + '<tr><td>Payout Pending:</td><td>' + format8(summary['rewardpending']) + '</td></tr>' \
                + '<tr><td>Paid Out:</td><td>' + format8(summary['rewardpaidout']) + '</td></tr>' \
                + '<tr><td>Last Total Staking:</td><td>' + format8(summary['laststaking']) + '</td></tr>' \
                + '<tr><td>Current Total in Pool:</td><td>' + format8(summary['currenttotal']) + '</td></tr>' \
                + '</table>'
        else:
            content += '<table>' \
                + '<tr><td>Current Total in Pool:</td><td>' + format8(summary['currenttotal']) + '</td></tr>' \
                + '</table>'

        content += '<p><a href=\'/\'>home</a></p>' \
            + '</body></html>'
        return bytes(content, 'UTF-8')

    def page_index(self):
        stakePool = self.server.stakePool

        try:
            summary = stakePool.getSummary()
        except Exception as e:
            return self.page_error(str(e))

        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Demo</title></head>' \
            + '<body>' \
            + '<h2>Particl Stake Pool Demo</h2>' \
            + '<p>' \
            + 'Mode: ' + summary['poolmode'] + '<br/>' \
            + 'Pool Address: ' + stakePool.poolAddr + '<br/>' \
            + 'Pool Fee: ' + str(stakePool.poolFeePercent) + '%<br/>' \
            + 'Stake Bonus: ' + str(stakePool.stakeBonusPercent) + '%<br/>' \
            + 'Payout Threshold: ' + format8(stakePool.payoutThreshold) + '<br/>' \
            + 'Blocks Between Payment Runs: ' + str(stakePool.minBlocksBetweenPayments) + '<br/>' \
            + 'Minimum output value: ' + format8(stakePool.minOutputValue) + '<br/>' \
            + '</p><p>' \
            + 'Synced Height: ' + str(summary['poolheight']) + '<br/>' \
            + 'Blocks Found: ' + str(summary['blocksfound']) + '<br/>' \
            + 'Last Payment Run: ' + str(summary['lastpaymentrunheight']) + '<br/>' \
            + '<br/>' \
            + 'Total Pool Rewards: ' + format8(summary['poolrewardtotal']) + '<br/>' \
            + 'Total Pool Fees: ' + format8(summary['poolfeestotal']) + '<br/>' \
            + 'Total Pool Rewards Withdrawn: ' + format8(summary['poolwithdrawntotal']) + '<br/>' \
            + '<br/>' \
            + 'Total Pooled Coin: ' + format8(int(decimal.Decimal(summary['watchonlytotalbalance']) * COIN)) + '<br/>' \
            + 'Currently Staking: ' + format8(summary['stakeweight']) + '<br/>' \
            + '</p>'

        content += '<br/><h3>Recent Blocks</h3><table><tr><th>Height</th><th>Block Hash</th><th>Block Reward</th><th>Total Coin Staking</th></tr>'
        for b in summary['lastblocks']:
            content += '<tr><td>' + str(b[0]) + '</td><td>' + b[1] + '</td><td>' + format8(b[2]) + '</td><td>' + format8(b[3]) + '</td></tr>'
        content += '</table>'

        content += '<br/><h3>Pending Payments</h3><table><tr><th>Txid</th><th>Disbursed</th></tr>'
        for b in summary['pendingpayments']:
            content += '<tr><td>' + b[0] + '</td><td>' + format8(b[1]) + '</td></tr>'
        content += '</table>'

        content += '<br/><h3>Last Payments</h3><table><tr><th>Height</th><th>Txid</th><th>Disbursed</th></tr>'
        for b in summary['lastpayments']:
            content += '<tr><td>' + str(b[0]) + '</td><td>' + b[1] + '</td><td>' + format8(b[2]) + '</td></tr>'
        content += '</table>'

        content += '</body></html>'
        return bytes(content, 'UTF-8')
        '''
        + '<h3>Help</h3>' \
        + '<p>' \
        + '</p>' \

        + '<form method="get" action="/address">' \
        + "<input type='text' name='' />" \
        + "<input type='submit' value='Go'/>" \
        + '</form>' \
        '''

    def putHeaders(self, status_code, content_type):
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.end_headers()

    def handle_http(self, status_code, path):

        urlSplit = self.path.split('/')
        if len(urlSplit) > 1:
            if urlSplit[1] == 'address':
                self.putHeaders(status_code, 'text/html')
                return self.page_address(urlSplit)
            if urlSplit[1] == 'config':
                self.putHeaders(status_code, 'text/plain')
                return self.page_config(urlSplit)
            if urlSplit[1] == 'json':
                self.putHeaders(status_code, 'text/plain')
                if len(urlSplit) > 2:
                    if urlSplit[2] == 'address':
                        return self.js_address(urlSplit)
                    if urlSplit[2] == 'metrics':
                        return self.js_metrics(urlSplit)
                return self.js_index(urlSplit)

        self.putHeaders(status_code, 'text/html')
        return self.page_index()

    def do_GET(self):
        response = self.handle_http(200, self.path)
        self.wfile.write(response)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()


class HttpThread(threading.Thread, HTTPServer):
    def __init__(self, fp, hostName, portNo, stakePool):
        threading.Thread.__init__(self)

        self.stop_event = threading.Event()
        self.fp = fp
        self.hostName = hostName
        self.portNo = portNo
        self.stakePool = stakePool

        self.timeout = 60
        HTTPServer.__init__(self, (self.hostName, self.portNo), HttpHandler)

    def stop(self):
        self.stop_event.set()

        # Send fake request
        conn = http.client.HTTPConnection(self.hostName, self.portNo)
        conn.connect()
        conn.request("GET", "/none")
        response = conn.getresponse()
        data = response.read()
        conn.close()

    def stopped(self):
        return self.stop_event.is_set()

    def serve_forever(self):
        while not self.stopped():
            self.handle_request()

    def run(self):
        self.serve_forever()


is_running = True
fail_code = 0
def stopRunning(with_code=0):
    global is_running
    global fail_code
    fail_code = with_code
    is_running = False


def signal_handler(sig, frame):
    print('signal %d detected, ending program.' % (sig))
    stopRunning()


def runStakePool(fp, dataDir, chain):

    settingsPath = os.path.join(dataDir, 'stakepool.json')

    if not os.path.exists(settingsPath):
        raise ValueError('Settings file not found: ' + str(settingsPath))

    with open(settingsPath) as fs:
        settings = json.load(fs)

    stakePool = StakePool(fp, dataDir, settings, chain)

    threads = []
    if 'htmlhost' in settings:
        logmt(fp, 'Starting server at %s:%d.' % (settings['htmlhost'], settings['htmlport']))
        tS1 = HttpThread(fp, settings['htmlhost'], settings['htmlport'], stakePool)
        threads.append(tS1)
        tS1.start()

    try:
        r = callrpc(stakePool.rpc_port, stakePool.rpc_auth, 'getblockchaininfo')
        while r['blocks'] - stakePool.blockBuffer > stakePool.poolHeight and is_running:
            stakePool.processBlock(stakePool.poolHeight + 1)
    except Exception as ex:
        traceback.print_exc()

    while is_running:
        time.sleep(0.5)
        stakePool.checkBlocks()

    logmt(fp, 'Stopping threads.')
    for t in threads:
        t.stop()
        t.join()


def printHelp():
    print('stakepool.py --datadir=path -testnet')


def main():
    dataDir = None
    chain = 'mainnet'

    for v in sys.argv[1:]:
        if len(v) < 2 or v[0] != '-':
            print('Unknown argument', v)
            continue

        s = v.split('=')
        name = s[0].strip()

        for i in range(2):
            if name[0] == '-':
                name = name[1:]

        if name == 'h' or name == 'help':
            printHelp()
            return 0
        if name == 'testnet':
            chain = 'testnet'
            continue
        if name == 'regtest':
            chain = 'regtest'
            continue

        if len(s) == 2:
            if name == 'datadir':
                dataDir = os.path.expanduser(s[1])
                continue

        print('Unknown argument', v)

    if dataDir is None:
        dataDir = os.path.join(os.path.expanduser('~/.particl'), ('' if chain == 'mainnet' else chain), 'stakepool')

    print('dataDir:', dataDir)
    if chain != 'mainnet':
        print('chain:', chain)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    print('Ctrl + c to exit.')

    if not os.path.exists(dataDir):
        os.makedirs(dataDir)

    with open(os.path.join(dataDir, 'stakepool_log.txt'), 'w') as fp:
        logmt(fp, os.path.basename(sys.argv[0]) + '\n\n')
        runStakePool(fp, dataDir, chain)

    print('Done.')
    return fail_code


if __name__ == '__main__':
    main()
