"""تبدیل ارقام لاتین به فارسی برای نمایش در پیام‌های ربات."""

from __future__ import annotations

_FA_DIGIT_TRANSLATE = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(n: int) -> str:
    return str(n).translate(_FA_DIGIT_TRANSLATE)
