#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018-2024 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""
Particl Stake Pool - Proof of concept
"""

import os
import sys
import json
import time
import signal
import traceback

from coldstakepool import __version__
from coldstakepool.stakepool import StakePool
from coldstakepool.http_server import HttpThread
from coldstakepool.util import (
    logmt,
    callrpc,
    LOG_TIME,
)

ALLOW_CORS = True
stakePool = None


def signal_handler(sig, frame):
    print('signal %d detected, ending program.' % (sig))
    if stakePool is not None:
        stakePool.stopRunning()


def runStakePool(dataDir, chain):
    global stakePool
    settings_path = os.path.join(dataDir, 'stakepool.json')

    if not os.path.exists(settings_path):
        raise ValueError('Settings file not found: ' + str(settings_path))

    with open(settings_path) as fs:
        settings = json.load(fs)

    fp = None
    try:
        if settings.get('writelogfile', True):
            fp = open(os.path.join(dataDir, 'stakepool.log'), 'w')

        LOG_TIME = settings.get('logtime', True)
        logmt(fp, os.path.basename(sys.argv[0]) + ', version: ' + __version__ + '\n\n')

        stakePool = StakePool(fp, dataDir, settings, chain)
        stakePool.start()

        threads = []
        if 'htmlhost' in settings:
            logmt(fp, 'Starting server at %s:%d.' % (settings['htmlhost'], settings['htmlport']))
            allow_cors = settings.get('allowcors', ALLOW_CORS)
            key_salt = settings.get('management_key_salt', None)
            key_hash = settings.get('management_key_hash', None)
            tS1 = HttpThread(fp, settings['htmlhost'], settings['htmlport'], allow_cors, stakePool, key_salt, key_hash)
            threads.append(tS1)
            tS1.start()

        try:
            r = callrpc(stakePool.rpc_port, stakePool.rpc_auth, 'getblockchaininfo')
            while r['blocks'] - stakePool.blockBuffer > stakePool.poolHeight and stakePool.is_running:
                stakePool.processBlock(stakePool.poolHeight + 1)
        except Exception as ex:
            traceback.print_exc()

        while stakePool.is_running:
            time.sleep(0.5)
            stakePool.checkBlocks()

        logmt(fp, 'Stopping threads.')
        for t in threads:
            t.stop()
            t.join()
    finally:
        if fp:
            fp.close()


def printVersion():
    print('Particl coldstakepool version:', __version__)


def printHelp():
    print('coldstakepool-run --datadir=path -testnet')


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

        if name == 'v' or name == 'version':
            printVersion()
            return 0
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

    runStakePool(dataDir, chain)

    print('Done.')
    return stakePool.fail_code if stakePool is not None else 0


if __name__ == '__main__':
    main()
