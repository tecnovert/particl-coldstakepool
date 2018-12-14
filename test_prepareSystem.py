#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

# $ python3 test_prepareSystem.py -v

import unittest
import sys
from io import StringIO
from unittest.mock import patch
import logging

import prepareSystem

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


if __name__ == '__main__':
    unittest.main()
