# -*- coding: utf-8 -*-

# Copyright (c) 2020 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

chainparams = {
    'name': 'particl',
    'ticker': 'PART',
    'message_magic': 'Bitcoin Signed Message:\n',
    'blocks_target': 60 * 2,
    'mainnet': {
        'rpcport': 51735,
        'pubkey_address': 0x38,
        'script_address': 0x3c,
        'key_prefix': 0x6c,
        'hrp': 'pw',
        'bip44': 44,
    },
    'testnet': {
        'rpcport': 51935,
        'pubkey_address': 0x76,
        'script_address': 0x7a,
        'key_prefix': 0x2e,
        'hrp': 'tpw',
        'bip44': 1,
    },
    'regtest': {
        'rpcport': 51936,
        'pubkey_address': 0x76,
        'script_address': 0x7a,
        'key_prefix': 0x2e,
        'hrp': 'rtpw',
        'bip44': 1,
    }
}


def is_script_prefix(prefix):
    for chain in ('mainnet', 'testnet', 'regtest'):
        if prefix == chainparams[chain]['script_address']:
            return True
    return False
