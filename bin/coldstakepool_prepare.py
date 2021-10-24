#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018-2021 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""

Minimal example to start a Particl stake pool.

1. Download and verify a particl-core release.

2. Create a particl.conf that:
    - Starts 2 wallets
    - Enables zmqpubhashblock
    - Enables csindex and addressindex

3. Generate and import a recovery phrase for both wallets.
4. Generate the pool_stake_address from the staking wallet.
    - The address pool participants will set their outputs to stake with.
5. Generate the pool_reward_address from the reward wallet.
    - The address that will collect the rewards for blocks staked by the pool.
6. Disable staking on the reward wallet.
7. Set the reward address of the staking wallet.
8. Create the stakepool.json configuration file.


Install dependencies:
apt-get install wget gnupg

Run the prepare script:
coldstakepool-prepare.py -datadir=~/stakepoolDemoTest -testnet

Start the daemon:
~/particl-binaries/particld -datadir=/home/$(id -u -n)/stakepoolDemoTest

Start the pool script:
coldstakepool-run.py -datadir=~/stakepoolDemoTest/stakepool -testnet


"""

import os
import sys
import mmap
import time
import json
import stat
import base64
import random
import hashlib
import tarfile
import subprocess
import urllib.request
from coldstakepool.util import (
    make_rpc_func,
)


PARTICL_BINDIR = os.path.expanduser(os.getenv('PARTICL_BINDIR', '~/particl-binaries'))
PARTICLD = os.getenv('PARTICLD', 'particld')
PARTICL_TX = os.getenv('PARTICL_TX', 'particl-tx')
PARTICL_CLI = os.getenv('PARTICL_CLI', 'particl-cli')

PARTICL_VERSION = os.getenv('PARTICL_VERSION', '0.19.2.16')
PARTICL_VERSION_TAG = os.getenv('PARTICL_VERSION_TAG', '')
PARTICL_ARCH = os.getenv('PARTICL_ARCH', 'x86_64-linux-gnu_nousb.tar.gz')
PARTICL_REPO = os.getenv('PARTICL_REPO', 'particl')

RPC_HOST = os.getenv('RPC_HOST', '127.0.0.1')


def startDaemon(nodeDir, bindir):
    command_cli = os.path.join(bindir, PARTICLD)

    args = [command_cli, '-daemon', '-noconnect', '-nostaking', '-nodnsseed', '-datadir=' + nodeDir]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()

    if len(out[1]) > 0:
        raise ValueError('Daemon error ' + str(out[1]))
    return out[0]


def downloadParticlCore():
    print('Download and verify Particl core release.')

    if not os.path.exists(PARTICL_BINDIR):
        os.makedirs(PARTICL_BINDIR)

    if 'osx' in PARTICL_ARCH:
        os_dir_name = 'osx-unsigned'
        os_name = 'osx'
    elif 'win32-setup' in PARTICL_ARCH or 'win64-setup' in PARTICL_ARCH:
        os_dir_name = 'win-signed'
        os_name = 'win-signer'
    elif 'win32' in PARTICL_ARCH or 'win64' in PARTICL_ARCH:
        os_dir_name = 'win-unsigned'
        os_name = 'win'
    else:
        os_dir_name = 'linux'
        os_name = 'linux'

    signing_key_fingerprint = '8E517DC12EC1CC37F6423A8A13F13651C9CF0D6B'
    signing_key_name = 'tecnovert'

    if os_dir_name == 'win-signed':
        assert_filename = 'particl-{}-build.assert'.format(os_name)
    else:
        assert_filename = 'particl-{}-{}-build.assert'.format(os_name, PARTICL_VERSION)

    assert_url = 'https://api.github.com/repos/{}/gitian.sigs/contents/{}-{}/{}/{}'.format(PARTICL_REPO, PARTICL_VERSION + PARTICL_VERSION_TAG, os_dir_name, signing_key_name, assert_filename)
    assert_path = os.path.join(PARTICL_BINDIR, assert_filename)

    release_filename = 'particl-{}-{}'.format(PARTICL_VERSION, PARTICL_ARCH)
    release_url = 'https://github.com/%s/particl-core/releases/download/v%s/%s' % (PARTICL_REPO, PARTICL_VERSION + PARTICL_VERSION_TAG, release_filename)

    if not os.path.exists(assert_path):
        print('assert_url', assert_url)
        r = urllib.request.urlopen(assert_url)
        rj = json.loads(r.read().decode('utf-8'))
        with open(assert_path, 'wb') as fp:
            fp.write(base64.b64decode(rj['content']))

    sig_path = os.path.join(PARTICL_BINDIR, 'particl-%s-%s-build.assert.sig' % (os_name, PARTICL_VERSION))
    if not os.path.exists(sig_path):
        print('assert_url' + '.sig', assert_url + '.sig')
        r = urllib.request.urlopen(assert_url + '.sig')
        rj = json.loads(r.read().decode('utf-8'))
        with open(sig_path, 'wb') as fp:
            fp.write(base64.b64decode(rj['content']))

    packed_path = os.path.join(PARTICL_BINDIR, release_filename)
    if not os.path.exists(packed_path):
        subprocess.check_call(['wget', release_url, '-P', PARTICL_BINDIR])

    hasher = hashlib.sha256()
    with open(packed_path, 'rb') as fp:
        hasher.update(fp.read())
    release_hash = hasher.digest()

    print('Release hash:', release_hash.hex())
    with open(assert_path, 'rb', 0) as fp, mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ) as s:
        if s.find(bytes(release_hash.hex(), 'utf-8')) == -1:
            sys.stderr.write('Error: release hash %s not found in assert file.' % (release_hash.hex()))
            exit(1)
        else:
            print('Found release hash %s in assert file.' % (release_hash.hex()))

    try:
        subprocess.check_call(['gpg', '--list-keys', signing_key_fingerprint])
    except Exception:
        print('Downloading release signing pubkey')
        keyservers = [
            'hkps://keys.openpgp.org',
            'keyserver.ubuntu.com',
            'keys.gnupg.net',
            'pgp.mit.edu',
            'keyserver.pgp.com',
            'ha.pool.sks-keyservers.net',
            'hkp://subset.pool.sks-keyservers.net:80'
        ]

        random.shuffle(keyservers)
        for ks in keyservers:
            print('Trying {}'.format(ks))
            try:
                subprocess.check_call(['gpg', '--keyserver', ks, '--recv-keys', signing_key_fingerprint])
            except Exception:
                continue
            break
        subprocess.check_call(['gpg', '--list-keys', signing_key_fingerprint])

    try:
        subprocess.check_call(['gpg', '--verify', sig_path, assert_path])
    except Exception:
        sys.stderr.write('Error: Signature verification failed!')
        exit(1)


def extractParticlCore():
    packed_path = os.path.join(PARTICL_BINDIR, 'particl-{}-{}'.format(PARTICL_VERSION, PARTICL_ARCH))
    daemon_path = os.path.join(PARTICL_BINDIR, PARTICLD)
    bin_prefix = PARTICL_BINDIR

    bins = [PARTICLD, PARTICL_CLI, PARTICL_TX]
    with tarfile.open(packed_path) as ft:
        for b in bins:
            out_path = os.path.join(bin_prefix, b)
            fi = ft.extractfile('{}-{}/bin/{}'.format('particl', PARTICL_VERSION, b))
            with open(out_path, 'wb') as fout:
                fout.write(fi.read())
            fi.close()
            os.chmod(out_path, stat.S_IRWXU | stat.S_IXGRP | stat.S_IXOTH)

    output = subprocess.check_output([daemon_path, '--version'])
    version = output.splitlines()[0].decode('utf-8')
    print('particld --version\n' + version)
    assert(PARTICL_VERSION in version)


def printVersion():
    from coldstakepool import __version__
    print('Particl coldstakepool version:', __version__)


def printHelp():
    print('Usage: coldstakepool-prepare ')
    print('\n--help, -h                 Print help.')
    print('--version, -v              Print version.')
    print('--update_core              Download, verify and extract Particl core release and exit.')
    print('--download_core            Download and verify Particl core release and exit.')
    print('--datadir=PATH             Path to Particl data directory, default:~/.particl.')
    print('--pooldir=PATH             Path to stakepool data directory, default:{datadir}/stakepool.')
    print('--mainnet                  Run Particl in mainnet mode.')
    print('--testnet                  Run Particl in testnet mode.')
    print('--regtest                  Run Particl in regtest mode.')
    print('--stake_wallet_mnemonic=   Recovery phrase to use for the staking wallet, default is randomly generated.')
    print('--reward_wallet_mnemonic=  Recovery phrase to use for the reward wallet, default is randomly generated.')
    print('--mode=master/observer     Mode stakepool is initialised to. observer mode requires configurl to be specified, default:master.')
    print('--configurl=url            Url to pull the stakepool config file from when initialising for observer mode.')
    print('--regtest                  Run Particl in regtest mode.')
    print('--noprepare_binaries       Skip preparing core binaries.')
    print('--noprepare_daemon         Skip preparing particl data dir.')
    print('--rpcauth=                 RPC auth to connect to a running node.')
    print('--rescan_from=             Timestamp to rescan wallets from, -1 to disable.')


def main():
    dataDir = None
    poolDir = None
    chain = 'mainnet'
    mode = 'master'
    configurl = None
    stake_wallet_mnemonic = None
    reward_wallet_mnemonic = None
    prepare_binaries = True
    prepare_daemon = True
    rpc_auth = None
    rpc_auth_specified = False
    rescan_from = 0
    stake_mnemonic_passphrase = ''
    reward_mnemonic_passphrase = ''

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
        if name == 'update_core':
            downloadParticlCore()
            extractParticlCore()
            return 0
        if name == 'download_core':
            downloadParticlCore()
            return 0
        if name == 'mainnet':
            continue
        if name == 'testnet':
            chain = 'testnet'
            continue
        if name == 'regtest':
            chain = 'regtest'
            continue
        if name == 'noprepare_binaries':
            prepare_binaries = False
            continue
        if name == 'noprepare_daemon':
            prepare_daemon = False
            continue

        if len(s) == 2:
            if name == 'datadir':
                dataDir = os.path.expanduser(s[1])
                continue
            if name == 'pooldir':
                poolDir = os.path.expanduser(s[1])
                continue
            if name == 'stake_wallet_mnemonic':
                stake_wallet_mnemonic = s[1]
                continue
            if name == 'reward_wallet_mnemonic':
                reward_wallet_mnemonic = s[1]
                continue
            if name == 'mode':
                mode = s[1]
                if mode != 'master' and mode != 'observer':
                    sys.stderr.write('Unknown value for mode:' + mode)
                    exit(1)
                continue
            if name == 'configurl':
                configurl = s[1]
                continue
            if name == 'rpcauth':
                rpc_auth = s[1]
                rpc_auth_specified = True
                continue
            if name == 'rescan_from':
                rescan_from = int(s[1])
                continue

        print('Unknown argument', v)

    if mode == 'observer' and configurl is None:
        sys.stderr.write('observer mode requires configurl set\n')
        exit(1)

    # 1. Download and verify the specified version of particl-core
    if prepare_binaries:
        if not os.path.exists(PARTICL_BINDIR):
            os.makedirs(PARTICL_BINDIR)

        downloadParticlCore()
        extractParticlCore()

    dataDirWasNone = False
    if dataDir is None:
        dataDir = os.path.expanduser('~/.particl')
        dataDirWasNone = True
    if poolDir is None:
        if dataDirWasNone:
            poolDir = os.path.join(os.path.expanduser(dataDir), ('' if chain == 'mainnet' else chain), 'stakepool')
        else:
            poolDir = os.path.join(os.path.expanduser(dataDir), 'stakepool')
    print('poolDir:', poolDir)
    if chain != 'mainnet':
        print('chain:', chain)

    # 2. Create a particl.conf
    zmq_port = 207922 if chain == 'mainnet' else 208922 if chain == 'testnet' else 209922
    rpc_port = 51735 if chain == 'mainnet' else 51935 if chain == 'testnet' else 51936
    if prepare_daemon:
        print('dataDir:', dataDir)

        if not os.path.exists(dataDir):
            os.makedirs(dataDir)

        daemonConfFile = os.path.join(dataDir, 'particl.conf')
        if os.path.exists(daemonConfFile):
            sys.stderr.write('Error: %s exists, exiting.' % (daemonConfFile))
            exit(1)

        with open(daemonConfFile, 'w') as fp:
            if chain != 'mainnet':
                fp.write(chain + '=1\n\n')

            fp.write('zmqpubhashblock=tcp://127.0.0.1:%d\n' % (zmq_port))

            chain_id = 'test.' if chain == 'testnet' else 'regtest.' if chain == 'regtest' else ''
            fp.write(chain_id + 'wallet=pool_stake\n')
            fp.write(chain_id + 'wallet=pool_reward\n')

            fp.write('txindex=1\n')
            fp.write('csindex=1\n')
            fp.write('addressindex=1\n')

        startDaemon(dataDir, PARTICL_BINDIR)

        authcookiepath = os.path.join(dataDir, '' if chain == 'mainnet' else chain, '.cookie')
        for i in range(10):
            if not os.path.exists(authcookiepath):
                time.sleep(0.5)
        with open(authcookiepath) as fp:
            rpc_auth = fp.read()

    rpc_func = make_rpc_func(RPC_HOST, rpc_port, rpc_auth)

    # Delay until responding
    for k in range(10):
        time.sleep(1)
        try:
            rpc_func('getwalletinfo', wallet='pool_stake')
            break
        except Exception as e:
            pass

    if not os.path.exists(poolDir):
        os.makedirs(poolDir)

    try:
        if mode == 'observer':
            print('Preparing observer config.')

            settings = json.loads(urllib.request.urlopen(configurl).read().decode('utf-8'))

            settings['mode'] = 'observer'
            settings['particlbindir'] = PARTICL_BINDIR
            settings['particldatadir'] = dataDir
            pool_stake_address = settings['pooladdress']
            pool_reward_address = settings['rewardaddress']

            v = rpc_func('validateaddress', [pool_stake_address])
            assert('isvalid' in v)
            assert(v['isvalid'] is True)

            rpc_func('importaddress', [v['address']], wallet='pool_stake')
            rpc_func('importaddress', [pool_reward_address], wallet='pool_reward')

            poolConfFile = os.path.join(poolDir, 'stakepool.json')
            if os.path.exists(poolConfFile):
                sys.stderr.write('Error: %s exists, exiting.' % (poolConfFile))
                exit(1)
            with open(poolConfFile, 'w') as fp:
                json.dump(settings, fp, indent=4)

            print('Done.')
            return 0

        # 3. Generate and import a recovery phrase for both wallets.
        if stake_wallet_mnemonic is None:
            stake_wallet_mnemonic = rpc_func('mnemonic', ['new'])['mnemonic']

        if reward_wallet_mnemonic is None:
            reward_wallet_mnemonic = rpc_func('mnemonic', ['new'])['mnemonic']

        rpc_func('extkeyimportmaster', [stake_wallet_mnemonic, stake_mnemonic_passphrase, False, 'pool_stake_key', 'pool_stake_acc', rescan_from], wallet='pool_stake')
        rpc_func('extkeyimportmaster', [reward_wallet_mnemonic, reward_mnemonic_passphrase, False, 'pool_reward_key', 'pool_reward_acc', rescan_from], wallet='pool_reward')

        # 4. Generate the pool_stake_address from the staking wallet.
        pool_stake_address = rpc_func('getnewaddress', wallet='pool_stake')
        pool_stake_address = rpc_func('validateaddress', [pool_stake_address, True], wallet='pool_stake')['stakeonly_address']

        # 5. Generate the pool_reward_address from the reward wallet.
        pool_reward_address = rpc_func('getnewaddress', wallet='pool_reward')

        # 6. Disable staking on the reward wallet.
        rpc_func('walletsettings', ['stakingoptions', {'enabled': False}], wallet='pool_reward')

        # 7. Set the reward address of the staking wallet.
        rpc_func('walletsettings', ['stakingoptions', {'rewardaddress': pool_reward_address}], wallet='pool_stake')

    finally:
        if prepare_daemon:
            rpc_func('stop')

    # 8. Create the stakepool.json configuration file.
    html_port = 9000 if chain == 'mainnet' else 9001
    poolsettings = {
        'mode': 'master',
        'debug': True,
        'particlbindir': PARTICL_BINDIR,
        'particldatadir': dataDir,
        'startheight': 200000,  # Set to a block height before the pool begins operating
        'pooladdress': pool_stake_address,
        'rewardaddress': pool_reward_address,
        'zmqhost': 'tcp://' + RPC_HOST,
        'zmqport': zmq_port,
        'rpcport': rpc_port,
        'htmlhost': 'localhost',
        'htmlport': html_port,
        'parameters': [
            {
                'height': 0,
                'poolfeepercent': 3,
                'stakebonuspercent': 5,
                'payoutthreshold': 0.5,
                'minblocksbetweenpayments': 100,
                'minoutputvalue': 0.1,
            },
        ]
    }

    if rpc_auth_specified:
        poolsettings['rpcauth'] = rpc_auth
    if RPC_HOST != '127.0.0.1':
        poolsettings['rpchost'] = RPC_HOST

    poolConfFile = os.path.join(poolDir, 'stakepool.json')
    if os.path.exists(poolConfFile):
        sys.stderr.write('Error: %s exists, exiting.' % (poolConfFile))
        exit(1)
    with open(poolConfFile, 'w') as fp:
        json.dump(poolsettings, fp, indent=4)

    print('NOTE: Save both the recovery phrases:')
    print('Stake wallet recovery phrase:', stake_wallet_mnemonic)
    print('Reward wallet recovery phrase:', reward_wallet_mnemonic)
    print('Stake address:', pool_stake_address)
    print('Reward address:', pool_reward_address)

    print('Done.')


if __name__ == '__main__':
    main()
