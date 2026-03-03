from __future__ import annotations

import unittest

from utils.geometry import _safe_filename


class TestSafeFilename(unittest.TestCase):
    def test_case_sensitive_ids_do_not_collide(self) -> None:
        a = _safe_filename("AbC_12")
        b = _safe_filename("aBc_12")
        self.assertNotEqual(a, b)

    def test_underscore_and_uppercase_escape(self) -> None:
        self.assertEqual(_safe_filename("A_B"), "_a___b")
        self.assertEqual(_safe_filename("abc"), "abc")


if __name__ == "__main__":
    unittest.main()
