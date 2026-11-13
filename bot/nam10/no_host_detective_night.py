"""شب — انتخاب استعلام محافظ (مسیر گردانندگی بدون گرداننده).

محافظ از لیست همهٔ بازیکنان زنده یک نفر را انتخاب و تأیید می‌کند.
نتیجهٔ استعلام تا پایان محاسبات شب (اعمال پایان شب) به او نشان داده نمی‌شود.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.nam10.roles_detective import (
    commit_pick as _commit_detective_pick_impl,
    load_result as load_detective_inquiry_result,
    void_pick as void_detective_inquiry_pick,
)
from bot.nam10.nmnd_narrator import (
    NIGHT_ACTIONS,
    NS_DET,
    Role,
    _advance_after_det,
    _alive,
    _night_title_fa,
    nam10_assistant_narrator_active,
    push_host_step,
)
from bot.nam10.engine import is_synthetic_player_uid
from bot.nam10.no_host_night_common import (
    arm_no_host_role_pick_flow,
    nam10_after_role_night_pick,
    nam10_night_wait_phase_active,
    publish_no_host_night_wait_panel,
)
from bot.models import Game, Player
from bot.nam10.mode import is_mozakere_scenario, is_no_host_player_room
from bot.nam10.role_registry import find_alive_role_holder
from bot.nam10.no_host_role_pick_common import (
    actor_may_act_on_role_panel,
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
    player_button_name,
    sync_role_mirror_panel,
    target_in_pool,
)
from bot.observer_delivery import (
    deliver_no_host_player_game_copy,
    mirror_ui_claim_key,
    no_host_observer_registered as nam10_observer_registered,
    publish_mirror_prompt_pair,
    register_mirror_prompt_pair,
    send_to_player,
)

if TYPE_CHECKING:
    from bot.nam10.engine import GameManager


def _detective_ui_key(game: Game, det_uid: int) -> str:
    return mirror_ui_claim_key(
        game.room_code, "nam10_detective", det_uid
    )


def build_no_host_detective_pick_html(game: Game) -> str:
    nc = max(1, game.nmnd_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"🕵️ {night_lbl} - ثبت انتخاب محافظ\n\n"
        "🎯 لطفاً یک نفر را از لیست زیر برای استعلام انتخاب کنید.\n\n"
        "📩 نتیجه استعلام شما پس از پایان فاز امشب به‌صورت پیام خصوصی "
        "برایتان ارسال خواهد شد."
    )


def build_no_host_detective_yaku_reselect_html(game: Game) -> str:
    return (
        "با توجه به اینکه یاکوزایی انجام شده، "
        "لطفاً مجدداً بازیکن مورد نظر برای استعلام را انتخاب کنید.\n\n"
        f"{build_no_host_detective_pick_html(game)}"
    )


def build_no_host_detective_yaku_started_reselect_html(game: Game) -> str:
    return (
        "با توجه به اینکه رییس مافیا یاکوزایی را تأیید کرده است، "
        "لطفاً مجدداً بازیکن مورد نظر برای استعلام را انتخاب کنید.\n\n"
        f"{build_no_host_detective_pick_html(game)}"
    )


def build_no_host_detective_confirm_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    return (
        f"{build_no_host_detective_pick_html(game)}\n\n"
        f"🎯 انتخاب شما: <b>{name}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_detective_waiting_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    nc = max(1, game.nmnd_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"🕵️ {night_lbl} - ثبت انتخاب محافظ\n\n"
        f"✅ استعلام روی <b>{name}</b> ثبت شد.\n\n"
        "📩 نتیجه استعلام پس از پایان فاز امشب برایتان ارسال می‌شود.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def build_no_host_detective_result_html(game: Game, gm: "GameManager") -> str | None:
    det = find_alive_role_holder(game, Role.DETECTIVE)
    if det is None and game.nmnd_det_no_inquiry:
        pass
    snap = game.nmnd_alive_at_night_start or {}
    det_uid = None
    for uid, pl in game.players.items():
        if pl.role == Role.DETECTIVE and snap.get(uid, pl.is_alive):
            det_uid = uid
            break
    if det_uid is None:
        return None

    nc = max(1, game.nmnd_narrator_night_count)
    night_lbl = _night_title_fa(nc)

    if game.nmnd_det_no_inquiry:
        return (
            f"🕵️ {night_lbl} — نتیجه استعلام\n\n"
            "شما این شب استعلام نگرفتید."
        )
    check_uid = game.actions.detective_check
    if check_uid is None:
        return (
            f"🕵️ {night_lbl} — نتیجه استعلام\n\n"
            "استعلامی ثبت نشده است."
        )
    tgt = game.players.get(check_uid)
    name = html.escape(
        gm.format_player_tag(tgt) if tgt else str(check_uid)
    )
    committed = load_detective_inquiry_result(game)
    if committed is None:
        return None
    result = committed.detail_fa()
    return (
        f"🕵️ {night_lbl} — نتیجه استعلام\n\n"
        f"🎯 هدف: <b>{name}</b>\n\n"
        f"📄 نتیجه: <b>{result}</b>"
    )


def _player_button_name(p: Player | None, uid: int) -> str:
    return player_button_name(p, uid)


def _pick_keyboard(
    game: Game, det_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    from bot.nam10 import roles_detective as det_mod
    from bot.nam10.roles_night_state import detective_night_state

    state = detective_night_state(game)
    pending = game.nam10_detective_pending_tid
    selected: list[int] = []
    if pending is not None:
        selected.append(pending)
    elif state.target_uid is not None:
        selected.append(state.target_uid)
    return build_pick_keyboard(
        game,
        det_uid,
        pick_act="ndp",
        players=det_mod.investigation_pool(game),
        selected_uids=selected,
        display_names=gm.user_display_names,
    )


def _confirm_keyboard(game: Game, det_uid: int) -> InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        game,
        det_uid,
        confirm_act="ndc",
        back_act="ndb",
        confirm_text="✅ تأیید انتخاب",
        back_text="↩️ بازگشت",
    )


def _should_run_no_host_detective_flow(game: Game) -> bool:
    return (
        is_no_host_player_room(game)
        and nam10_assistant_narrator_active(game)
        and game.nmnd_narrator_step == NIGHT_ACTIONS
        and game.nmnd_night_substep == NS_DET
    )


def _commit_detective_pick(game: Game, gm: "GameManager", tid: int) -> None:
    del gm
    _commit_detective_pick_impl(game, tid)


def _void_no_host_detective_night_pick(game: Game) -> None:
    """باطل کردن استعلام ثبت‌شدهٔ محافظ پیش از یاکوزایی."""
    void_detective_inquiry_pick(game)


async def _send_detective_pick_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    det_uid: int,
    *,
    sig: str,
    text: str,
) -> None:
    game.nam10_detective_flow_active = True
    game.nam10_detective_pending_tid = None
    game.nam10_detective_dm_signature = sig
    kb = _pick_keyboard(game, det_uid, gm)
    ui_key = _detective_ui_key(game, det_uid)
    await publish_mirror_prompt_pair(
        bot,
        game,
        det_uid,
        ui_key,
        text,
        kb,
        fresh_observer_copy=True,
        send_player=True,
        send_observer=nam10_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def apply_no_host_detective_yaku_reselect_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از تأیید یاکوزایی — اگر محافظ قبلاً استعلام را تأیید کرده، پنل را دوباره بفرست."""
    await _apply_no_host_detective_yaku_reselect_panel(
        bot,
        game,
        gm,
        signature_suffix="yaku_reselect",
        text=build_no_host_detective_yaku_reselect_html(game),
    )


async def apply_no_host_detective_yaku_started_reselect_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از تأیید عملیات یاکوزایی توسط رییس مافیا، پنل محافظ را در صورت نیاز باز می‌کند."""
    await _apply_no_host_detective_yaku_reselect_panel(
        bot,
        game,
        gm,
        signature_suffix="yaku_started_reselect",
        text=build_no_host_detective_yaku_started_reselect_html(game),
    )


async def _apply_no_host_detective_yaku_reselect_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    signature_suffix: str,
    text: str,
) -> None:
    if game.nmnd_host_mode != "no_host":
        return
    if not nam10_assistant_narrator_active(game):
        return
    det = find_alive_role_holder(game, Role.DETECTIVE)
    if det is None:
        return
    if not game.nam10_detective_pick_confirmed:
        return
    _void_no_host_detective_night_pick(game)
    game.nam10_detective_pick_confirmed = False
    nc = game.nmnd_narrator_night_count
    sig = f"{nc}:det:{signature_suffix}"
    await _send_detective_pick_panel(
        bot,
        game,
        gm,
        det.user_id,
        sig=sig,
        text=text,
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.detective_yaku_reselect_panel_sent",
            det_uid=det.user_id,
            night_count=nc,
        )
    except Exception:
        pass


async def start_no_host_detective_night_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    at_night_entry: bool = False,
) -> bool:
    if at_night_entry:
        if not nam10_night_wait_phase_active(game):
            return False
    elif not _should_run_no_host_detective_flow(game):
        return False
    if game.nmnd_detective_blocked:
        return False
    det = find_alive_role_holder(game, Role.DETECTIVE)
    if det is None:
        return False
    nc = game.nmnd_narrator_night_count

    if is_mozakere_scenario(game) and at_night_entry:
        sig = f"{nc}:det:mozakere_pick"
    else:
        sig = f"{nc}:det:night_entry" if at_night_entry else f"{nc}:det:{NS_DET}"
    if game.nam10_detective_dm_signature == sig and game.nam10_detective_flow_active:
        return False
    if game.nam10_detective_pick_confirmed:
        return False

    game.nam10_detective_flow_active = True
    game.nam10_detective_pending_tid = None
    game.nam10_detective_dm_signature = sig

    text = build_no_host_detective_pick_html(game)
    kb = _pick_keyboard(game, det.user_id, gm)
    ui_key = _detective_ui_key(game, det.user_id)

    await register_mirror_prompt_pair(
        bot,
        game,
        det.user_id,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=nam10_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.detective_night_panel_sent",
            det_uid=det.user_id,
            night_count=nc,
        )
    except Exception:
        pass
    return True


async def dispatch_no_host_detective_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.nam10.no_host_night_entry import complete_no_host_role_night_if_already_picked

    await complete_no_host_role_night_if_already_picked(bot, game, gm)
    if game.nam10_detective_pick_confirmed:
        if not nam10_night_wait_phase_active(game):
            return
        det = find_alive_role_holder(game, Role.DETECTIVE)
        if det is not None:
            pick = game.actions.detective_check or game.nam10_detective_pending_tid
            if pick is not None:
                await publish_no_host_night_wait_panel(
                    bot,
                    game,
                    det.user_id,
                    _detective_ui_key(game, det.user_id),
                    "",
                    gm=gm,
                    selection_uid=pick,
                )
        return
    await start_no_host_detective_night_flow(bot, game, gm)


async def flush_no_host_detective_result_pending(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not game.nam10_detective_result_pending:
        return
    game.nam10_detective_result_pending = False
    await send_no_host_detective_inquiry_result_dm(bot, game, gm)


async def send_no_host_detective_inquiry_result_dm(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not (
        game.nmnd_host_mode == "no_host"
        and nam10_assistant_narrator_active(game)
    ):
        return
    nc = game.nmnd_narrator_night_count
    if game.nam10_detective_result_sent_night == nc:
        return
    body = build_no_host_detective_result_html(game, gm)
    if not body:
        return
    det = find_alive_role_holder(game, Role.DETECTIVE)
    if det is None:
        snap = game.nmnd_alive_at_night_start or {}
        for uid, pl in game.players.items():
            if pl.role == Role.DETECTIVE and snap.get(uid, False):
                await deliver_no_host_player_game_copy(
                    bot,
                    game,
                    uid,
                    body,
                    is_synthetic_uid=is_synthetic_player_uid,
                    parse_mode="HTML",
                )
                game.nam10_detective_result_sent_night = nc
                return
        return
    await send_to_player(
        bot,
        game,
        det.user_id,
        body,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    game.nam10_detective_result_sent_night = nc
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.detective_result_sent",
            det_uid=det.user_id,
            night_count=nc,
        )
    except Exception:
        pass


def nam10_detective_act_active(game: Game, act: str) -> bool:
    return act in ("ndp", "ndc", "ndb")


def _actor_may_act(game: Game, actor_uid: int, det_uid: int) -> bool:
    return actor_may_act_on_role_panel(game, actor_uid, det_uid)


async def _sync_panel(
    bot: Bot,
    game: Game,
    det_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await sync_role_mirror_panel(
        bot, game, _detective_ui_key(game, det_uid), det_uid, text, kb
    )


async def dispatch_no_host_detective_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    det_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    arm_no_host_role_pick_flow(
        game,
        flow_active_attr="nam10_detective_flow_active",
        pick_confirmed_attr="nam10_detective_pick_confirmed",
        dm_signature_attr="nam10_detective_dm_signature",
    )
    if not game.nam10_detective_flow_active or game.nam10_detective_pick_confirmed:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not nam10_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    det = find_alive_role_holder(game, Role.DETECTIVE)
    if det is None or det.user_id != det_uid:
        await callback.answer("محافظ در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, det_uid):
        await callback.answer(
            "فقط محافظ می‌تواند این انتخاب را انجام دهد.",
            show_alert=True,
        )
        return

    if act == "ndp":
        from bot.nam10 import roles_detective as det_mod

        pool = det_mod.investigation_pool(game)
        if not target_in_pool(tid, pool):
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        game.nam10_detective_pending_tid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        text = build_no_host_detective_confirm_html(game, gm, tid)
        kb = _confirm_keyboard(game, det_uid)
        await _sync_panel(bot, game, det_uid, text, kb)
        return

    if act == "ndb":
        game.nam10_detective_pending_tid = None
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_detective_pick_html(game)
        kb = _pick_keyboard(game, det_uid, gm)
        await _sync_panel(bot, game, det_uid, text, kb)
        return

    if act == "ndc":
        pick = game.nam10_detective_pending_tid
        from bot.nam10 import roles_detective as det_mod

        pool = det_mod.investigation_pool(game)
        if pick is None or not target_in_pool(pick, pool):
            await callback.answer("ابتدا یک بازیکن انتخاب کنید.", show_alert=True)
            return
        if game.nam10_detective_pick_confirmed:
            await callback.answer("استعلام قبلاً ثبت شده است.", show_alert=True)
            return
        _commit_detective_pick(game, gm, pick)
        game.nam10_detective_pick_confirmed = True
        game.nam10_detective_flow_active = False
        game.nam10_detective_pending_tid = None

        await callback.answer("ثبت شد.")
        await publish_no_host_night_wait_panel(
            bot,
            game,
            det_uid,
            _detective_ui_key(game, det_uid),
            "",
            gm=gm,
            selection_uid=pick,
        )

        await nam10_after_role_night_pick(
            bot, game, gm, expected_substep=NS_DET, advance=_advance_after_det
        )
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.detective_pick_confirmed",
                det_uid=det_uid,
                target_uid=pick,
                actor_uid=actor_uid,
            )
        except Exception:
            pass
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
