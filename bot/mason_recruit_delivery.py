"""ارسال پیام عضویت تیم ماسون — فقط سناریوی ماسون.

پیام عضویت تا READY شدن گیرنده (پایان اقدام خودِ گیرنده در فاز جاری) نگه
داشته می‌شود؛ پس از آماده‌شدن، خودکار و دقیقاً یک‌بار ارسال می‌شود.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bot.models import Game
from bot.room_mode import is_mason_scenario

if TYPE_CHECKING:
    from aiogram import Bot

    from bot.game import GameManager

logger = logging.getLogger(__name__)


async def deliver_mason_recruit_membership_message(
    bot: "Bot",
    game: Game,
    recruit_uid: int,
    message: str,
) -> None:
    """پیام عضویت به بازیکن جذب‌شده؛ اگر گیرنده هنوز READY نیست، در انتظار."""
    if not is_mason_scenario(game) or not message.strip():
        return
    from bot.mason_night_ready import mason_recipient_ready_for_pending_delivery

    if not mason_recipient_ready_for_pending_delivery(game, recruit_uid):
        pending = list(game.mason_recruit_pending_deliveries)
        if not any(int(item[0]) == recruit_uid for item in pending):
            pending.append([recruit_uid, message])
        game.mason_recruit_pending_deliveries = pending
        logger.info(
            "mason recruit delivery held (recipient not ready) room=%s uid=%s",
            game.room_code,
            recruit_uid,
        )
        return
    await _deliver_mason_recruit_now(bot, game, recruit_uid, message)


async def _deliver_mason_recruit_now(
    bot: "Bot",
    game: Game,
    recruit_uid: int,
    message: str,
) -> bool:
    """یک‌بار ارسال واقعی؛ True = تحویل موفق (آینه برای ناظر/صندلی مصنوعی)."""
    from bot.game import is_synthetic_player_uid
    from bot.observer_delivery import deliver_no_host_player_game_copy

    try:
        await deliver_no_host_player_game_copy(
            bot,
            game,
            recruit_uid,
            message,
            is_synthetic_uid=is_synthetic_player_uid,
        )
        return True
    except Exception:
        logger.exception(
            "mason recruit delivery failed room=%s uid=%s", game.room_code, recruit_uid
        )
        return False


async def flush_pending_mason_recruit_deliveries(
    bot: "Bot",
    game: Game,
    gm: "GameManager | None" = None,
) -> None:
    """ارسال پیام‌های عضویتِ در انتظارِ گیرنده‌هایی که الان READY شده‌اند.

    دقیقاً یک‌بار: آیتم فقط پس از تحویل موفق حذف می‌شود؛ خطای تلگرام = تلاش
    دوباره در فرصت بعدی. فراخوانی تکراری/هم‌زمان بی‌خطر است.
    """
    if not is_mason_scenario(game):
        return
    if getattr(game, "mason_recruit_flush_running", False):
        return
    pending = list(game.mason_recruit_pending_deliveries)
    if not pending:
        return
    from bot.mason_night_ready import mason_recipient_ready_for_pending_delivery

    game.mason_recruit_flush_running = True
    try:
        remaining: list[list] = []
        for item in pending:
            uid, message = int(item[0]), str(item[1])
            if not mason_recipient_ready_for_pending_delivery(game, uid):
                remaining.append([uid, message])
                continue
            if not await _deliver_mason_recruit_now(bot, game, uid, message):
                remaining.append([uid, message])
        game.mason_recruit_pending_deliveries = remaining
        if remaining:
            logger.info(
                "mason recruit deliveries still pending room=%s count=%s",
                game.room_code,
                len(remaining),
            )
    finally:
        game.mason_recruit_flush_running = False
