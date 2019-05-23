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
import json
import traceback
import signal

from coldstakepool import __version__
from coldstakepool.stakepool import StakePool
from coldstakepool.http_server import HttpThread
from coldstakepool.util import (
    logmt,
    callrpc,
)

ALLOW_CORS = True
stakePool = None


def signal_handler(sig, frame):
    print('signal %d detected, ending program.' % (sig))
    if stakePool is not None:
        stakePool.stopRunning()


def runStakePool(fp, dataDir, chain):
    global stakePool
    settings_path = os.path.join(dataDir, 'stakepool.json')

    if not os.path.exists(settings_path):
        raise ValueError('Settings file not found: ' + str(settings_path))

    with open(settings_path) as fs:
        settings = json.load(fs)

    stakePool = StakePool(fp, dataDir, settings, chain)
    stakePool.start()

    threads = []
    if 'htmlhost' in settings:
        logmt(fp, 'Starting server at %s:%d.' % (settings['htmlhost'], settings['htmlport']))
        allow_cors = settings['allowcors'] if 'allowcors' in settings else ALLOW_CORS
        key_salt = settings['management_key_salt'] if 'management_key_salt' in settings else None
        key_hash = settings['management_key_hash'] if 'management_key_hash' in settings else None
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


def printVersion():
    print('Particl coldstakepool version:', __version__)


def printHelp():
    print('coldstakepool-run.py --datadir=path -testnet')


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

    with open(os.path.join(dataDir, 'stakepool.log'), 'w') as fp:
        logmt(fp, os.path.basename(sys.argv[0]) + ', version: ' + __version__ + '\n\n')
        runStakePool(fp, dataDir, chain)

    print('Done.')
    return stakePool.fail_code if stakePool is not None else 0


if __name__ == '__main__':
    main()
