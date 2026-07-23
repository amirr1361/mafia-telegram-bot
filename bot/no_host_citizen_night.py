"""شب — یادآوری شهروند ساده (مسیر گردانندگی بدون گرداننده).

با ورود به فاز شب (NIGHT_START)، به هر شهروند سادهٔ زنده پیام انتظار + تأیید ارسال می‌شود.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import NIGHT_START, Role
from bot.no_host_night_common import (
    no_host_night_wait_phase_active,
    no_host_role_ack_keyboard,
)
from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.roles.registry import find_alive_players, get_role_module
from bot.observer_delivery import (
    PlayerMirrorCb,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)

if TYPE_CHECKING:
    from bot.game import GameManager


def _citizen_ui_key(game: Game, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_citizen", uid)


def _alive_citizens(game: Game) -> list[Player]:
    return find_alive_players(game, Role.CITIZEN)


def build_no_host_citizen_night_html(*, confirmed: bool = False) -> str:
    if confirmed:
        return (
            "🙂 <b>شهروند ساده</b>\n\n"
            "✅ تأیید شما ثبت شد.\n\n"
            "⏳ لطفاً منتظر بمانید تا عملیات فاز شب انجام شود."
        )
    return (
        "🙂 <b>شهروند ساده</b>\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید."
    )


def _confirm_keyboard(game: Game, uid: int) -> InlineKeyboardMarkup:
    return no_host_role_ack_keyboard(game, uid, "cic")


def _should_send_no_host_citizen_night(game: Game) -> bool:
    return (
        no_host_night_wait_phase_active(game)
        and game.bazpors_narrator_step == NIGHT_START
    )


def _citizen_confirmed(game: Game, uid: int) -> bool:
    from bot.roles.night_state import passive_night_state

    return passive_night_state(game).citizen_is_confirmed(uid)


def _mark_citizen_confirmed(game: Game, uid: int) -> None:
    from bot.roles.night_state import passive_night_state

    passive_night_state(game).citizen_confirm(uid)


async def start_no_host_citizen_night_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> bool:
    if not _should_send_no_host_citizen_night(game):
        return False
    citizens = _alive_citizens(game)
    if not citizens:
        return False

    nc = game.bazpors_narrator_night_count
    sig = f"{nc}:citizen:{NIGHT_START}"
    from bot.roles.night_state import passive_night_state

    passive = passive_night_state(game)
    if passive.citizen_batch_signature == sig:
        return False

    passive.reset_citizen_batch(sig)

    text = build_no_host_citizen_night_html(confirmed=False)
    sent = 0
    for pl in citizens:
        kb = _confirm_keyboard(game, pl.user_id)
        ui_key = _citizen_ui_key(game, pl.user_id)
        await register_mirror_prompt_pair(
            bot,
            game,
            pl.user_id,
            ui_key,
            text,
            kb,
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
        sent += 1

    if sent:
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.citizen_night_panels_sent",
                night_count=nc,
                citizen_count=sent,
            )
        except Exception:
            pass
    return sent > 0


async def dispatch_no_host_citizen_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    await start_no_host_citizen_night_flow(bot, game, gm)


def no_host_citizen_act_active(game: Game, act: str) -> bool:
    return act == "cic"


def _actor_may_act(game: Game, actor_uid: int, cit_uid: int) -> bool:
    if actor_uid == cit_uid:
        return True
    return bool(
        is_synthetic_player_uid(cit_uid)
        and no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


async def dispatch_no_host_citizen_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    cit_uid: int,
    actor_uid: int,
) -> None:
    if not no_host_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    pl = game.players.get(cit_uid)
    citizen_mod = get_role_module(Role.CITIZEN)
    if (
        pl is None
        or not pl.is_alive
        or citizen_mod is None
        or not citizen_mod.is_simple_citizen(pl)
    ):
        await callback.answer("شهروند ساده در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, cit_uid):
        await callback.answer(
            "فقط همان بازیکن می‌تواند این دکمه را بزند.", show_alert=True
        )
        return
    if _citizen_confirmed(game, cit_uid):
        await callback.answer("قبلاً تأیید کرده‌اید.")
        return

    _mark_citizen_confirmed(game, cit_uid)
    await callback.answer("تأیید ثبت شد.")
    text = build_no_host_citizen_night_html(confirmed=True)
    ui_key = _citizen_ui_key(game, cit_uid)
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        text,
        None,
        assistant_uid=cit_uid,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.citizen_night_confirmed",
            cit_uid=cit_uid,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass

    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)
