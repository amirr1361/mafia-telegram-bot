"""فاز آشوب (Chaos) — سناریوی ماسون؛ همان منطق بازپرس، بدون تغییر بازپرس/مزاکره."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot

from bot.models import Game
from bot.room_mode import is_mason_scenario

if TYPE_CHECKING:
    from bot.game import GameManager


def mason_chaos_counts_met(game: Game, gm: "GameManager") -> bool:
    """۳ نفر زنده: دقیقاً ۱ مافیا و ۲ شهروند."""
    from bot.bazpors_narrator import _ki_as_counts_met

    return _ki_as_counts_met(game, gm)


def sync_mason_chaos_today(game: Game, gm: "GameManager") -> None:
    """تنظیم پرچم روز آشوب برای ماسون (از فیلد مشترک bazpors_ki_as_today)."""
    if not is_mason_scenario(game) or gm.check_winner(game):
        return
    game.bazpors_ki_as_today = mason_chaos_counts_met(game, gm)


def should_start_mason_chaos(game: Game, gm: "GameManager") -> bool:
    if not is_mason_scenario(game):
        return False
    if gm.check_winner(game):
        return False
    return mason_chaos_counts_met(game, gm)


async def start_mason_chaos_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """شروع فاز آشوب — پنل دست‌دادن و کمک‌کننده (همان مسیر بازپرس)."""
    if not should_start_mason_chaos(game, gm):
        return

    from bot.bazpors_narrator import CHAOS_DAY_HANDSHAKE, push_host_step
    from bot.chaos_handshake import start_chaos_handshake_round

    sync_mason_chaos_today(game, gm)
    game.bazpors_narrator_step = CHAOS_DAY_HANDSHAKE
    await start_chaos_handshake_round(bot, game, gm)
    await push_host_step(bot, game, gm)
