"""تست fa_digits."""

from __future__ import annotations

import unittest

from bot.text_fa import fa_digits


class FaDigitsTests(unittest.TestCase):
    def test_translates_digits(self) -> None:
        self.assertEqual(fa_digits(38), "۳۸")
        self.assertEqual(fa_digits(12345), "۱۲۳۴۵")


if __name__ == "__main__":
    unittest.main()
