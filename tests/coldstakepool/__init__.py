import unittest

import tests.coldstakepool.test_prepare as test_prepare
import tests.coldstakepool.test_run as test_run


def test_suite():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(test_prepare)
    suite.addTests(loader.loadTestsFromModule(test_run))
    return suite
