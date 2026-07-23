"""Singletonهای مشترک بین main و routerها — جلوگیری از import چرخه‌ای."""

from __future__ import annotations

import asyncio

from bot.game import GameManager

manager = GameManager()

ROLE_DEAL_IN_PROGRESS_MSG = "⏳ پخش نقش در حال انجام است؛ چند ثانیه صبر کنید."

# جلسهٔ تازهٔ پایان‌یافته → اسنپ‌شات تا بعد از تمام شدن مدال‌ها برای همه پخش شود
PENDING_SESSION_RECAP: dict[int, dict[str, object]] = {}
_ROLE_DEAL_LOCKS: dict[str, asyncio.Lock] = {}

waiting_join_user_ids: set[int] = set()
waiting_myname_user_ids: set[int] = set()
panic_password_pending: dict[int, float] = {}
PANIC_PASSWORD_TTL_SEC = 120
