"""شب — یادآوری رویین‌تن (مسیر گردانندگی بدون گرداننده).

با ورود به فاز شب (NIGHT_START)، اگر رویین‌تن زنده باشد پیام انتظار + تأیید ارسال می‌شود.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import NIGHT_START, Role
from bot.roles.registry import find_alive_role_holder
from bot.no_host_night_common import (
    no_host_night_wait_phase_active,
    no_host_role_ack_keyboard,
)
from bot.game import is_synthetic_player_uid
from bot.models import Game
from bot.observer_delivery import (
    PlayerMirrorCb,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)

if TYPE_CHECKING:
    from bot.game import GameManager


def _ruintan_ui_key(game: Game, ru_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_ruintan", ru_uid)


def build_no_host_ruintan_night_html(*, confirmed: bool = False) -> str:
    if confirmed:
        return (
            "🛡️ <b>رویین‌تن</b>\n\n"
            "✅ تأیید شما ثبت شد.\n\n"
            "⏳ لطفاً منتظر بمانید تا عملیات فاز شب انجام شود."
        )
    return (
        "🛡️ <b>رویین‌تن</b>\n\n"
        "📜 نقش شما: <b>رویین‌تن</b>\n\n"
        "💠 شما در فاز شب از بازی خارج نخواهید شد.\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید."
    )


def _confirm_keyboard(game: Game, ru_uid: int) -> InlineKeyboardMarkup:
    return no_host_role_ack_keyboard(game, ru_uid, "ruc")


def _should_send_no_host_ruintan_night(game: Game) -> bool:
    return (
        no_host_night_wait_phase_active(game)
        and game.bazpors_narrator_step == NIGHT_START
    )


async def start_no_host_ruintan_night_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> bool:
    if not _should_send_no_host_ruintan_night(game):
        return False
    ru = find_alive_role_holder(game, Role.RUINTAN)
    if ru is None:
        return False

    nc = game.bazpors_narrator_night_count
    sig = f"{nc}:ruintan:{NIGHT_START}"
    from bot.roles.night_state import passive_night_state

    passive = passive_night_state(game)
    if passive.ruintan_dm_signature == sig:
        return False

    passive.ruintan_dm_signature = sig
    passive.ruintan_rules_sent_night = nc
    passive.ruintan_night_confirmed = False

    text = build_no_host_ruintan_night_html(confirmed=False)
    kb = _confirm_keyboard(game, ru.user_id)
    ui_key = _ruintan_ui_key(game, ru.user_id)

    await register_mirror_prompt_pair(
        bot,
        game,
        ru.user_id,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.ruintan_night_panel_sent",
            ru_uid=ru.user_id,
            night_count=nc,
        )
    except Exception:
        pass
    return True


async def dispatch_no_host_ruintan_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    await start_no_host_ruintan_night_flow(bot, game, gm)


def no_host_ruintan_act_active(game: Game, act: str) -> bool:
    return act == "ruc"


def _actor_may_act(game: Game, actor_uid: int, ru_uid: int) -> bool:
    if actor_uid == ru_uid:
        return True
    return bool(
        is_synthetic_player_uid(ru_uid)
        and no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


async def dispatch_no_host_ruintan_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    ru_uid: int,
    actor_uid: int,
) -> None:
    if not no_host_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    ru = find_alive_role_holder(game, Role.RUINTAN)
    if ru is None or ru.user_id != ru_uid:
        await callback.answer("رویین‌تن در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, ru_uid):
        await callback.answer(
            "فقط رویین‌تن می‌تواند این دکمه را بزند.", show_alert=True
        )
        return
    from bot.roles.night_state import passive_night_state

    passive = passive_night_state(game)
    if passive.ruintan_night_confirmed:
        await callback.answer("قبلاً تأیید کرده‌اید.")
        return

    passive.ruintan_night_confirmed = True
    await callback.answer("تأیید ثبت شد.")
    text = build_no_host_ruintan_night_html(confirmed=True)
    ui_key = _ruintan_ui_key(game, ru_uid)
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        text,
        None,
        assistant_uid=ru_uid,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.ruintan_night_confirmed",
            ru_uid=ru_uid,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass

    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)
