"""پس از commit مذاکره — ریست پزشک/کارآگاه/تک‌تیرانداز (فقط سناریوی مذاکره)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from bot.models import Game
from bot.no_host_role_pick_common import (
    build_single_action_keyboard,
    close_mirror_panel_refs,
    sync_role_mirror_panel,
)
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

    # Commit processing resolves the pending negotiation window; the
    # doctor/detective/sniper callback guards must be lifted from here
    # on (idempotent — the negc dispatch already sets this flag).
    game.no_host_negotiator_pick_confirmed = True

    await _reset_mozakere_doctor_after_negotiation(bot, game, gm)

    det = find_alive_role_holder(game, Role.DETECTIVE)
    det_resend = reset_mozakere_detective_after_negotiation(game)
    if det is not None and (
        det_resend or not game.no_host_detective_pick_confirmed
    ):
        from bot.no_host_detective_night import (
            _detective_ui_key,
            start_no_host_detective_night_flow,
        )

        # Close the invalidated (or negotiation-suspended) detective
        # panel (player and observer mirror) BEFORE delivering the
        # replacement, so its refs are not overwritten and no stale
        # keyboard survives.
        if not det_resend:
            # Panel was suspended during the pending negotiation
            # window: re-open an actionable panel now that the
            # negotiation is committed and the night can proceed.
            game.no_host_detective_dm_signature = None
        await close_mirror_panel_refs(
            bot, game, _detective_ui_key(game, det.user_id)
        )
        await start_no_host_detective_night_flow(
            bot, game, gm, at_night_entry=True
        )

    sn = find_alive_role_holder(game, Role.SNIPER)
    from bot.roles import sniper as sniper_role

    sn_resend = reset_mozakere_sniper_after_negotiation(game)
    if sn is not None and sn_resend:
        from bot.no_host_sniper_night import (
            _sniper_ui_key,
            start_no_host_sniper_night_flow,
        )

        if sniper_role.can_shoot(game):
            # Close the invalidated pre-negotiation sniper panel before
            # delivering the replacement (same stale-ref protection).
            await close_mirror_panel_refs(
                bot, game, _sniper_ui_key(game, sn.user_id)
            )
            await start_no_host_sniper_night_flow(
                bot, game, gm, at_night_entry=True
            )
        else:
            game.no_host_sniper_pick_confirmed = True
    elif (
        sn is not None
        and not game.no_host_sniper_pick_confirmed
        and sniper_role.can_shoot(game)
    ):
        # Panel was suspended during the pending negotiation window:
        # re-open an actionable sniper panel now that the negotiation
        # is committed and the night can proceed.
        from bot.no_host_sniper_night import (
            _sniper_ui_key,
            start_no_host_sniper_night_flow,
        )

        game.no_host_sniper_dm_signature = None
        await close_mirror_panel_refs(
            bot, game, _sniper_ui_key(game, sn.user_id)
        )
        await start_no_host_sniper_night_flow(
            bot, game, gm, at_night_entry=True
        )

    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)


MOZAKERE_NEGOTIATION_PENDING_ALERT = (
    "هم‌اکنون مذاکرهٔ مافیا در جریان است؛ لطفاً چند لحظه منتظر بمانید."
)

MOZAKERE_NEGOTIATION_PANEL_SUSPENDED_HTML = (
    "🤝 <b>تیم مافیا در حال مذاکره است.</b>\n\n"
    "⏳ انتخاب شما تا پایان مذاکره غیرفعال است؛ لطفاً منتظر بمانید."
)


def mozakere_negotiation_pending(game: Game) -> bool:
    """مذاکره انتخاب شده ولی هدفش هنوز تأیید نشده — پنجرهٔ تعلیق."""
    if not is_mozakere_scenario(game):
        return False
    from bot.roles.night_state import mozakere_negotiation_night_state

    return bool(mozakere_negotiation_night_state(game).tonight) and (
        not game.no_host_negotiator_pick_confirmed
    )


def _mozakere_sniper_can_shoot(game: Game) -> bool:
    from bot.roles import sniper as sniper_role

    return sniper_role.can_shoot(game)


def _mozakere_negotiation_suspension_targets(
    game: Game,
) -> list[tuple[int, str]]:
    """(uid, ui_key) of the LIVE, unconfirmed pick panels to suspend.

    Confirmed holders already sit on keyboard-less waiting panels, so
    only unconfirmed holders hold actionable keyboards right now.
    """
    from bot.no_host_detective_night import _detective_ui_key
    from bot.no_host_doctor_night import _doctor_ui_key
    from bot.no_host_sniper_night import _sniper_ui_key

    targets: list[tuple[int, str]] = []
    doc = find_alive_role_holder(game, Role.DOCTOR)
    if doc is not None and not game.no_host_doctor_pick_confirmed:
        targets.append((doc.user_id, _doctor_ui_key(game, doc.user_id)))
    det = find_alive_role_holder(game, Role.DETECTIVE)
    if det is not None and not game.no_host_detective_pick_confirmed:
        targets.append((det.user_id, _detective_ui_key(game, det.user_id)))
    sn = find_alive_role_holder(game, Role.SNIPER)
    if (
        sn is not None
        and not game.no_host_sniper_pick_confirmed
        and _mozakere_sniper_can_shoot(game)
    ):
        targets.append((sn.user_id, _sniper_ui_key(game, sn.user_id)))
    return targets


async def suspend_mozakere_town_panels_for_negotiation(
    bot: "Bot", game: Game
) -> int:
    """Initiation-time suspension (Mozakere-only, Room 44 fix).

    The moment «تیم مافیا در حال مذاکره» is announced, the live
    doctor/detective/sniper pick panels — player AND observer
    mirrors — are edited IN PLACE to a keyboard-less neutral state.
    No new messages are created, tracked refs are preserved, and
    confirmed/pending pick state is NOT touched here: voiding stays
    at commit (apply_mozakere_negotiation_citizen_resets).
    Returns the number of suspended panels.
    """
    if not mozakere_negotiation_pending(game):
        return 0
    suspended = 0
    for uid, ui_key in _mozakere_negotiation_suspension_targets(game):
        entry = game.mirror_prompt_messages.get(ui_key)
        if not isinstance(entry, dict):
            continue
        if not (entry.get("player") or entry.get("observer")):
            continue
        try:
            await sync_role_mirror_panel(
                bot,
                game,
                ui_key,
                uid,
                MOZAKERE_NEGOTIATION_PANEL_SUSPENDED_HTML,
                None,
            )
            suspended += 1
        except Exception:
            continue
    if suspended:
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.mozakere_town_panels_suspended",
                count=suspended,
            )
        except Exception:
            pass
    return suspended
