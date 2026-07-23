"""جملهٔ تصادفی بزرگان در شروع شب — فقط سرگرمی (بدون لاگ)."""

from __future__ import annotations

import html
import random
from typing import TYPE_CHECKING

from bot.game import is_synthetic_player_uid
from bot.observer_delivery import (
    mirror_per_player_to_observer,
    no_host_observer_registered,
    player_should_receive_game_messages,
)
from bot.no_host_night_common import no_host_should_dispatch_night_entry
from bot.tg_send import safe_send_message

from bot.data.no_host_sage_quotes import SAGE_QUOTES as _SAGE_QUOTES

if TYPE_CHECKING:
    from aiogram import Bot

    from bot.models import Game


def _pick_quote_for_player(game: Game, player_uid: int) -> str:
    night = max(0, int(game.bazpors_narrator_night_count or 0))
    rng = random.Random((player_uid * 1_000_003) ^ (night * 97) ^ hash(game.room_code))
    return rng.choice(_SAGE_QUOTES)


def build_no_host_night_sage_quote_html(game: Game, player_uid: int) -> str:
    quote = html.escape(_pick_quote_for_player(game, player_uid))
    return f"💭 <b>یه جمله از بزرگان:</b>\n<i>{quote}</i>"


def alive_no_host_night_sage_recipient_uids(game: Game) -> list[int]:
    """همهٔ بازیکنان زنده — شهروند، مافیا، شیاد، … بدون استثناء نقش."""
    alive = [p for p in game.players.values() if p.is_alive]
    alive.sort(key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id))
    return [pl.user_id for pl in alive]


def alive_synthetic_no_host_night_sage_uids(game: Game) -> list[int]:
    return [uid for uid in alive_no_host_night_sage_recipient_uids(game) if is_synthetic_player_uid(uid)]


async def send_no_host_night_sage_quote(
    bot: Bot,
    game: Game,
    player_uid: int,
) -> None:
    """پیام جدا بدون دکمه — بازیکن واقعی: DM؛ میز مصنوعی: آینهٔ ناظر."""
    if game.bazpors_host_mode != "no_host":
        return
    pl = game.players.get(player_uid)
    if pl is None or not pl.is_alive:
        return

    text = build_no_host_night_sage_quote_html(game, player_uid)

    if is_synthetic_player_uid(player_uid):
        if no_host_observer_registered(game):
            await mirror_per_player_to_observer(
                bot, game, player_uid, text, parse_mode="HTML"
            )
        return

    if not player_should_receive_game_messages(game, player_uid):
        return

    await safe_send_message(bot, player_uid, text, parse_mode="HTML")
    if (
        no_host_observer_registered(game)
        and game.observer_user_id is not None
        and game.observer_user_id != player_uid
    ):
        await mirror_per_player_to_observer(
            bot, game, player_uid, text, parse_mode="HTML"
        )


async def dispatch_no_host_night_sage_quotes_at_entry(
    bot: Bot,
    game: Game,
) -> None:
    """با شروع شب — قبل از پنل‌های نقش، به هر بازیکن زنده جمله بفرست."""
    if not no_host_should_dispatch_night_entry(game):
        return
    nc = game.bazpors_narrator_night_count
    if game.no_host_night_sage_dispatched_night == nc:
        return
    game.no_host_night_sage_dispatched_night = nc
    game.no_host_sage_needs_observer_resync = not no_host_observer_registered(game)
    for uid in alive_no_host_night_sage_recipient_uids(game):
        await send_no_host_night_sage_quote(bot, game, uid)


async def resync_observer_night_sage_quotes(
    bot: Bot,
    game: Game,
) -> None:
    """ناظر بعد از شروع شب ثبت شد — جملهٔ بزرگان برای میزهای مصنوعی (مافیا، …)."""
    if game.bazpors_host_mode != "no_host":
        return
    if not no_host_observer_registered(game):
        return
    if not game.no_host_sage_needs_observer_resync:
        return
    nc = game.bazpors_narrator_night_count
    if game.no_host_night_sage_dispatched_night != nc:
        return
    for uid in alive_synthetic_no_host_night_sage_uids(game):
        await send_no_host_night_sage_quote(bot, game, uid)
    game.no_host_sage_needs_observer_resync = False
