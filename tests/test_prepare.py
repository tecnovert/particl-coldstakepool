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

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))
import coldstakepool_prepare as prepareSystem  # noqa: E402

logger = logging.getLogger()
logger.level = logging.DEBUG
logger.addHandler(logging.StreamHandler(sys.stdout))


class Test(unittest.TestCase):

    def test_mode_no_url(self):
        testargs = ['prepareSystem.py', '--mode=observer']
        with patch('sys.stderr', new=StringIO()) as fake_out:
            with patch.object(sys, 'argv', testargs):
                with self.assertRaises(SystemExit) as cm:
                    prepareSystem.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertTrue('observer mode requires configurl' in fake_out.getvalue())

    def test_example_config(self):
        settings_path = os.path.join(os.path.dirname(__file__), '..', 'doc', 'config', 'stakepool.json')

        with open(settings_path) as fs:
            settings = json.load(fs)


if __name__ == '__main__':
    unittest.main()
