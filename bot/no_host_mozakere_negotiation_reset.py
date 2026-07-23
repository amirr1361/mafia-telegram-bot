"""پس از commit مذاکره — ریست پزشک/کارآگاه/تک‌تیرانداز (فقط سناریوی مذاکره)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from bot.models import Game
from bot.no_host_role_pick_common import build_single_action_keyboard
from bot.observer_delivery import update_mirror_prompt_pair
from bot.room_mode import is_mozakere_scenario
from bot.roles.registry import find_alive_role_holder
from bot.roles.night_state import doctor_night_state
from bot.bazpors_narrator import Role
from bot.bazpors_detective_inquiry import void_detective_inquiry_pick

if TYPE_CHECKING:
    from bot.game import GameManager

MOZAKERE_DOCTOR_NEGOTIATION_SKIP_HTML = (
    "چون امشب مذاکره انجام شده، نیازی به انتخاب پزشک نیست. منتظر بمانید."
)

MOZAKERE_DOCTOR_NEGOTIATION_CLEARED_HTML = (
    "چون امشب مذاکره انجام شده، انتخاب قبلی شما لغو شد.\n\n"
    "⏳ لطفاً منتظر اتمام فاز شب بمانید."
)


def mozakere_doctor_negotiation_skip_signature(game: Game) -> str:
    nc = game.bazpors_narrator_night_count
    return f"{nc}:doc:mozakere_neg"


def mozakere_doctor_negotiation_skip_active(game: Game) -> bool:
    return game.no_host_doctor_dm_signature == mozakere_doctor_negotiation_skip_signature(
        game
    )


def void_mozakere_doctor_night_pick(game: Game) -> None:
    """باطل کردن انتخاب پزشک در شب مذاکره؛ شمارندهٔ نجات خودی را برگردان."""
    state = doctor_night_state(game)
    state.clear_save()
    state.clear_no_host_pending_save_uids()
    state.rollback_self_save_count_to_baseline()


def reset_mozakere_detective_after_negotiation(game: Game) -> bool:
    """اگر کارآگاه قبلاً تأیید کرده بود، state را صفر کن و True برگردان (ارسال مجدد پنل)."""
    if find_alive_role_holder(game, Role.DETECTIVE) is None:
        return False
    if not game.no_host_detective_pick_confirmed:
        return False
    void_detective_inquiry_pick(game)
    game.no_host_detective_pick_confirmed = False
    game.no_host_detective_flow_active = False
    game.no_host_detective_pending_tid = None
    game.no_host_detective_dm_signature = None
    return True


def reset_mozakere_sniper_after_negotiation(game: Game) -> bool:
    """اگر تک‌تیرانداز قبلاً تأیید کرده بود، state و شمارندهٔ تیر را برگردان."""
    from bot.roles import sniper as sniper_role

    if find_alive_role_holder(game, Role.SNIPER) is None:
        return False
    if not game.no_host_sniper_pick_confirmed:
        return False
    baseline = game.mozakere_sniper_shots_used_at_night_start
    game.mozakere_sniper_shots_used = max(0, baseline)
    sniper_role.clear_pick(game)
    game.no_host_sniper_pick_confirmed = False
    game.no_host_sniper_flow_active = False
    game.no_host_sniper_pending_target_uid = None
    game.no_host_sniper_dm_signature = None
    return True


def _mozakere_doctor_negotiation_skip_keyboard(
    game: Game, doc_uid: int
) -> InlineKeyboardMarkup:
    return build_single_action_keyboard(
        game, doc_uid, act="dkng", text="✅ اوکی"
    )


async def _reset_mozakere_doctor_after_negotiation(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.no_host_doctor_night import _doctor_ui_key

    doc = find_alive_role_holder(game, Role.DOCTOR)
    if doc is None:
        return
    had_confirmed = game.no_host_doctor_pick_confirmed
    void_mozakere_doctor_night_pick(game)
    game.no_host_doctor_flow_active = False
    game.no_host_doctor_pick_confirmed = True
    game.no_host_doctor_dm_signature = mozakere_doctor_negotiation_skip_signature(game)
    ui_key = _doctor_ui_key(game, doc.user_id)
    if had_confirmed:
        body = MOZAKERE_DOCTOR_NEGOTIATION_CLEARED_HTML
        kb = None
    else:
        body = MOZAKERE_DOCTOR_NEGOTIATION_SKIP_HTML
        kb = _mozakere_doctor_negotiation_skip_keyboard(game, doc.user_id)
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        body,
        kb,
        assistant_uid=doc.user_id,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.mozakere_doctor_negotiation_reset",
            doc_uid=doc.user_id,
            had_confirmed=had_confirmed,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass


async def apply_mozakere_negotiation_citizen_resets(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از negc — ریست نقش‌های شهروند و به‌روزرسانی readiness."""
    if not is_mozakere_scenario(game):
        return

    await _reset_mozakere_doctor_after_negotiation(bot, game, gm)

    det_resend = reset_mozakere_detective_after_negotiation(game)
    if det_resend:
        from bot.no_host_detective_night import start_no_host_detective_night_flow

        await start_no_host_detective_night_flow(
            bot, game, gm, at_night_entry=True
        )

    sn_resend = reset_mozakere_sniper_after_negotiation(game)
    if sn_resend:
        from bot.roles import sniper as sniper_role
        from bot.no_host_sniper_night import start_no_host_sniper_night_flow

        if sniper_role.can_shoot(game):
            await start_no_host_sniper_night_flow(
                bot, game, gm, at_night_entry=True
            )
        else:
            game.no_host_sniper_pick_confirmed = True

    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)
