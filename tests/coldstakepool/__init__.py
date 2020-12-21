import unittest

import tests.coldstakepool.test_prepare as test_prepare


def test_suite():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(test_prepare)
    return suite
