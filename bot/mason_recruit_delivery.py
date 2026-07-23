"""ارسال پیام عضویت تیم ماسون — فقط سناریوی ماسون."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.models import Game
from bot.room_mode import is_mason_scenario

if TYPE_CHECKING:
    from aiogram import Bot


async def deliver_mason_recruit_membership_message(
    bot: "Bot",
    game: Game,
    recruit_uid: int,
    message: str,
) -> None:
    """پیام عضویت به بازیکن جذب‌شده؛ آینه برای ناظر (صندلی مصنوعی فقط آینه)."""
    if not is_mason_scenario(game) or not message.strip():
        return
    from bot.game import is_synthetic_player_uid
    from bot.observer_delivery import deliver_no_host_player_game_copy

    await deliver_no_host_player_game_copy(
        bot,
        game,
        recruit_uid,
        message,
        is_synthetic_uid=is_synthetic_player_uid,
    )
