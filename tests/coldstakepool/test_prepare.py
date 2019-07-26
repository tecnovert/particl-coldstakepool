#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018-2019 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

# coldstakepool]$ python setup.py test

import os
import sys
import unittest
import json
from io import StringIO
from unittest.mock import patch
import logging
import shutil

import bin.coldstakepool_prepare as prepareSystem

logger = logging.getLogger()
logger.level = logging.DEBUG
logger.addHandler(logging.StreamHandler(sys.stdout))


class Test(unittest.TestCase):

    @classmethod
    def tearDownClass(self):
        shutil.rmtree(os.path.expanduser('~/csp_mainnet'))
        shutil.rmtree(os.path.expanduser('~/csp_testnet'))
        shutil.rmtree(os.path.expanduser('~/csp_testnet_obs'))
        shutil.rmtree(os.path.expanduser('~/csp_regtest'))

    def test_mode_no_url(self):
        testargs = ['coldstakepool-prepare', '--mode=observer']
        with patch('sys.stderr', new=StringIO()) as fake_stderr:
            with patch.object(sys, 'argv', testargs):
                with self.assertRaises(SystemExit) as cm:
                    prepareSystem.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertTrue('observer mode requires configurl' in fake_stderr.getvalue())

    def test_example_config(self):
        settings_path = os.path.join(os.path.dirname(__file__), '..', '..', 'doc', 'config', 'stakepool.json')

        with open(settings_path) as fs:
            settings = json.load(fs)

    def test_prepare(self):
        testargs = ['coldstakepool-prepare', '--datadir=~/csp_mainnet', '--mainnet']
        with patch.object(sys, 'argv', testargs):
            prepareSystem.main()

        # Should fail when run on existing dir
        with patch('sys.stderr', new=StringIO()) as fake_stderr:
            with patch.object(sys, 'argv', testargs):
                with self.assertRaises(SystemExit) as cm:
                    prepareSystem.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertTrue('particl.conf exists' in fake_stderr.getvalue())

    def test_prepare_testnet(self):
        testargs = ['coldstakepool-prepare', '--datadir=~/csp_testnet', '--testnet']
        with patch.object(sys, 'argv', testargs):
            prepareSystem.main()

    def test_prepare_testnet_observer(self):
        testargs = ['coldstakepool-prepare', '--datadir=~/csp_testnet_obs', '--testnet', '--mode=observer', '--configurl=file://' + os.path.expanduser('~/csp_testnet/stakepool/stakepool.json')]
        with patch.object(sys, 'argv', testargs):
            prepareSystem.main()

        with open(os.path.expanduser('~/csp_testnet_obs/stakepool/stakepool.json')) as fp:
            settings = json.load(fp)
            assert(settings['mode'] == 'observer')

    def test_prepare_regtest(self):
        testargs = ['coldstakepool-prepare', '--datadir=~/csp_regtest', '--regtest']
        with patch.object(sys, 'argv', testargs):
            prepareSystem.main()


if __name__ == '__main__':
    unittest.main()
