import unittest

import tests.test_prepare


def test_suite():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(tests.test_prepare)
    return suite
