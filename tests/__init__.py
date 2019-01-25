import unittest
import os
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import test_prepare # noqa


def test_suite():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(test_prepare)
    return suite
