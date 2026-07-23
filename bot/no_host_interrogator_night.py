"""شب — انتخاب بازپرسی بازپرس (مسیر گردانندگی بدون گرداننده).

پنل فقط برای بازپرس زنده و ناظر (آینه)؛ نه پزشک/دستیار/بقیه.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    Role,
    _night_title_fa,
    no_host_assistant_narrator_active,
)
from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.roles.registry import find_alive_role_holder
from bot.roles.registry import require_role_module

_interrogator_role = require_role_module(Role.INTERROGATOR)
from bot.no_host_night_common import (
    arm_no_host_role_pick_flow,
    finalize_no_host_role_pick_message,
    format_night_selection_label,
    no_host_night_wait_phase_active,
    publish_no_host_night_ack_panel,
    publish_no_host_night_wait_panel,
)
from bot.observer_delivery import (
    PlayerMirrorCb,
    ensure_observer_mirror_prompt,
    mirror_ui_claim_key,
    no_host_observer_registered,
    publish_mirror_prompt_pair,
    update_mirror_prompt_pair,
)

if TYPE_CHECKING:
    from bot.game import GameManager

PHASE_INT1 = "int1"
PHASE_INT2 = "int2"
PHASE_SKIP_ACK = "skip_ack"


def _interrog_ui_key(game: Game, int_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_interrog", int_uid)


def _player_button_name(p: Player | None, uid: int) -> str:
    if p is None:
        return str(uid)
    return p.full_name or str(uid)


def build_no_host_interrog_int1_html(game: Game) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"⚖️ {night_lbl} — بازپرس\n\n"
        "🪪 <b>نفر اول بازپرسی</b> را از لیست زیر انتخاب کنید.\n\n"
        "➡️ پس از انتخاب نفر اول، مرحلهٔ انتخاب نفر دوم باز می‌شود.\n\n"
        "🚫 اگر این شب بازپرسی انجام نمی‌شود، «کسی را انتخاب نکردم» را بزنید.\n\n"
        "📜 بازپرس فقط یک‌بار در کل بازی می‌تواند از این قابلیت استفاده کند."
    )


def build_no_host_interrog_int2_html(game: Game, gm: "GameManager") -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    fu = game.bazpors_interrog_pick_uid or game.bazpors_interrog_first_uid
    first = ""
    if fu is not None:
        p = game.players.get(fu)
        first = html.escape(gm.format_player_tag(p) if p else str(fu))
    return (
        f"⚖️ {night_lbl} — بازپرس (نفر دوم)\n\n"
        f"🪪 نفر اول: <b>{first}</b>\n\n"
        "🎯 نفر دوم بازپرسی را از لیست انتخاب کنید."
    )


def build_no_host_interrog_skip_ack_html(game: Game) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"⚖️ {night_lbl} — بازپرس\n\n"
        "🎯 بازپرسی قبلاً یک‌بار در این بازی انجام شده؛ "
        "نیازی به انتخاب شبانه نیست.\n\n"
        "دکمهٔ تأیید را بزنید."
    )


def build_no_host_interrog_waiting_html(game: Game, gm: "GameManager") -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    u1, u2 = game.bazpors_interrog_first_uid, game.bazpors_interrog_second_uid
    if game.bazpors_interrog_night_finished and u1 is not None and u2 is not None:
        t1 = html.escape(
            gm.format_player_tag(game.players[u1])
            if u1 in game.players
            else str(u1)
        )
        t2 = html.escape(
            gm.format_player_tag(game.players[u2])
            if u2 in game.players
            else str(u2)
        )
        body = f"بازپرسی: <b>{t1}</b> و <b>{t2}</b> ثبت شد."
    elif u1 is None and u2 is None and not game.bazpors_interrog_night_finished:
        body = "این شب بازپرسی انجام نمی‌شود (ثبت شد)."
    else:
        body = "انتخاب شما ثبت شد."
    return (
        f"⚖️ {night_lbl} — بازپرس\n\n"
        f"✅ {body}\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def _int1_keyboard(game: Game, int_uid: int, gm: "GameManager") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sorted(
        _interrogator_role.int1_pool(game),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        name = html.escape(_player_button_name(p, p.user_id)[:32])
        cb = PlayerMirrorCb(
            code=game.room_code, act="nii1", as_uid=int_uid, tid=p.user_id
        ).pack()
        row.append(InlineKeyboardButton(text=name, callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="⭕ کسی را انتخاب نکردم",
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act="nii1s", as_uid=int_uid
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _int2_keyboard(game: Game, int_uid: int, gm: "GameManager") -> InlineKeyboardMarkup:
    pool = _interrogator_role.int2_pool(game)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sorted(
        pool,
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        name = html.escape(_player_button_name(p, p.user_id)[:32])
        cb = PlayerMirrorCb(
            code=game.room_code, act="nii2", as_uid=int_uid, tid=p.user_id
        ).pack()
        row.append(InlineKeyboardButton(text=name, callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="⭕ از بازپرسی منصرف شدم",
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act="nii2a", as_uid=int_uid
                ).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ انتخاب مجدد نفر اول",
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act="nii2r", as_uid=int_uid
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _skip_ack_keyboard(game: Game, int_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="niisk", as_uid=int_uid
                    ).pack(),
                )
            ]
        ]
    )


def _interrog_panel_already_sent_for_night(game: Game, nc: int) -> bool:
    """ورود شب و نوبت نریتور هر دو یک پنل — فقط یک‌بار در هر شب."""
    sig = game.no_host_interrog_dm_signature
    return bool(sig and sig.startswith(f"{nc}:interrog:"))


def _mark_interrog_confirmed(game: Game, *, int_uid: int | None = None) -> None:
    game.no_host_interrog_pick_confirmed = True
    game.no_host_interrog_flow_active = False
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.interrog_pick_confirmed",
            interrog_uid=int_uid,
            night_count=game.bazpors_narrator_night_count,
            phase=game.no_host_interrog_ui_phase,
        )
    except Exception:
        pass


async def _sync_panel(
    bot: Bot,
    game: Game,
    int_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await update_mirror_prompt_pair(
        bot,
        game,
        _interrog_ui_key(game, int_uid),
        text,
        kb,
        assistant_uid=int_uid,
        parse_mode="HTML",
    )


async def _ensure_interrogator_observer_mirror(
    bot: Bot, game: Game, gm: "GameManager"
) -> bool:
    """اگر پنل بازپرس برای ناظر نرفته (مثلاً در burst موازی شب)، یک‌بار بفرست."""
    if not no_host_observer_registered(game):
        return False
    if game.no_host_interrog_pick_confirmed:
        return False
    intr = find_alive_role_holder(game, Role.INTERROGATOR)
    if intr is None:
        return False
    int_uid = intr.user_id
    ui_key = _interrog_ui_key(game, int_uid)
    entry = game.mirror_prompt_messages.get(ui_key) or {}
    if entry.get("observer"):
        return False
    phase = game.no_host_interrog_ui_phase or PHASE_INT1
    if _interrogator_role.ability_used(game) or phase == PHASE_SKIP_ACK:
        int_text = build_no_host_interrog_skip_ack_html(game)
        int_kb = _skip_ack_keyboard(game, int_uid)
    elif phase == PHASE_INT2:
        int_text = build_no_host_interrog_int2_html(game, gm)
        int_kb = _int2_keyboard(game, int_uid, gm)
    else:
        int_text = build_no_host_interrog_int1_html(game)
        int_kb = _int1_keyboard(game, int_uid, gm)
    return await ensure_observer_mirror_prompt(
        bot,
        game,
        int_uid,
        ui_key,
        int_text,
        int_kb,
        parse_mode="HTML",
    )


def no_host_interrog_act_active(game: Game, act: str) -> bool:
    return act in ("nii1", "nii1s", "nii2", "nii2a", "nii2r", "niisk")


def _actor_may_act(game: Game, actor_uid: int, int_uid: int) -> bool:
    if actor_uid == int_uid:
        return True
    return bool(
        is_synthetic_player_uid(int_uid)
        and no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


async def start_no_host_interrogator_night_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    at_night_entry: bool = False,
) -> bool:
    if at_night_entry:
        if not no_host_night_wait_phase_active(game):
            return False
    elif not (
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "no_host"
        and no_host_assistant_narrator_active(game)
    ):
        return False

    intr = find_alive_role_holder(game, Role.INTERROGATOR)
    if intr is None:
        game.no_host_interrog_pick_confirmed = True
        return False

    nc = game.bazpors_narrator_night_count
    if game.no_host_interrog_pick_confirmed:
        return False
    if _interrog_panel_already_sent_for_night(game, nc):
        if not game.no_host_interrog_pick_confirmed:
            game.no_host_interrog_flow_active = True
            await _ensure_interrogator_observer_mirror(bot, game, gm)
        return False
    sig = f"{nc}:interrog:night_entry" if at_night_entry else f"{nc}:interrog:flow"

    game.no_host_interrog_flow_active = True
    game.no_host_interrog_dm_signature = sig
    _interrogator_role.clear_night_pick(game)

    int_uid = intr.user_id
    if _interrogator_role.ability_used(game):
        game.no_host_interrog_ui_phase = PHASE_SKIP_ACK
        text = build_no_host_interrog_skip_ack_html(game)
        kb = _skip_ack_keyboard(game, int_uid)
    else:
        game.no_host_interrog_ui_phase = PHASE_INT1
        text = build_no_host_interrog_int1_html(game)
        kb = _int1_keyboard(game, int_uid, gm)

    await publish_mirror_prompt_pair(
        bot,
        game,
        int_uid,
        _interrog_ui_key(game, int_uid),
        text,
        kb,
        fresh_observer_copy=True,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.interrogator_night_panel_sent",
            interrog_uid=int_uid,
            night_count=nc,
            phase=game.no_host_interrog_ui_phase,
        )
    except Exception:
        pass
    return True


async def dispatch_no_host_interrogator_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    nc = game.bazpors_narrator_night_count
    if _interrog_panel_already_sent_for_night(game, nc):
        arm_no_host_role_pick_flow(
            game,
            flow_active_attr="no_host_interrog_flow_active",
            pick_confirmed_attr="no_host_interrog_pick_confirmed",
            dm_signature_attr="no_host_interrog_dm_signature",
        )
        if not game.no_host_interrog_pick_confirmed:
            await _ensure_interrogator_observer_mirror(bot, game, gm)
        return
    if game.no_host_interrog_pick_confirmed:
        if not no_host_night_wait_phase_active(game):
            return
        intr = find_alive_role_holder(game, Role.INTERROGATOR)
        if intr is not None:
            await publish_no_host_night_ack_panel(
                bot,
                game,
                intr.user_id,
                _interrog_ui_key(game, intr.user_id),
                build_no_host_interrog_waiting_html(game, gm),
            )
        return
    await start_no_host_interrogator_night_flow(bot, game, gm)
    await _ensure_interrogator_observer_mirror(bot, game, gm)


async def _after_interrog_commit(
    bot: Bot, game: Game, gm: "GameManager", int_uid: int
) -> None:
    ui_key = _interrog_ui_key(game, int_uid)
    if game.bazpors_interrog_once_done or (
        game.no_host_interrog_ui_phase == PHASE_SKIP_ACK
    ):
        await publish_no_host_night_ack_panel(
            bot,
            game,
            int_uid,
            ui_key,
            build_no_host_interrog_waiting_html(game, gm),
        )
        return
    u1, u2 = game.bazpors_interrog_first_uid, game.bazpors_interrog_second_uid
    if u1 is not None and u2 is not None:
        t1 = format_night_selection_label(game, gm, u1)
        t2 = format_night_selection_label(game, gm, u2)
        label = f"{t1} و {t2}"
    else:
        label = "ثبت شد"
    await finalize_no_host_role_pick_message(
        bot, game, gm, int_uid, ui_key, label
    )
    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)


async def dispatch_no_host_interrogator_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    int_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    arm_no_host_role_pick_flow(
        game,
        flow_active_attr="no_host_interrog_flow_active",
        pick_confirmed_attr="no_host_interrog_pick_confirmed",
        dm_signature_attr="no_host_interrog_dm_signature",
    )
    if not game.no_host_interrog_flow_active or game.no_host_interrog_pick_confirmed:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not no_host_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    intr = find_alive_role_holder(game, Role.INTERROGATOR)
    if intr is None or intr.user_id != int_uid:
        await callback.answer("بازپرس در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, int_uid):
        await callback.answer("فقط بازپرس می‌تواند این انتخاب را انجام دهد.", show_alert=True)
        return

    phase = game.no_host_interrog_ui_phase

    if act == "niisk":
        if phase != PHASE_SKIP_ACK:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        _mark_interrog_confirmed(game, int_uid=int_uid)
        await callback.answer("ثبت شد.")
        await _after_interrog_commit(bot, game, gm, int_uid)
        return

    if act == "nii1":
        if phase != PHASE_INT1:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        if not _interrogator_role.first_target_valid(game, tid):
            await callback.answer("بازیکن نامعتبر.", show_alert=True)
            return
        _interrogator_role.commit_first_nominee(game, tid)
        game.no_host_interrog_ui_phase = PHASE_INT2
        await callback.answer("نفر اول ثبت شد؛ نفر دوم را انتخاب کنید.")
        text = build_no_host_interrog_int2_html(game, gm)
        kb = _int2_keyboard(game, int_uid, gm)
        await _sync_panel(bot, game, int_uid, text, kb)
        return

    if act == "nii1s":
        if phase != PHASE_INT1:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        _interrogator_role.clear_night_pick(game)
        _mark_interrog_confirmed(game, int_uid=int_uid)
        await callback.answer("ثبت شد.")
        await _after_interrog_commit(bot, game, gm, int_uid)
        return

    if act == "nii2":
        if phase != PHASE_INT2:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        if not _interrogator_role.second_target_valid(game, tid):
            await callback.answer("باید غیر از نفر اول باشد.", show_alert=True)
            return
        _interrogator_role.commit_second_nominee(game, tid)
        _mark_interrog_confirmed(game, int_uid=int_uid)
        await callback.answer("بازپرسی ثبت شد.")
        await _after_interrog_commit(bot, game, gm, int_uid)
        return

    if act == "nii2a":
        if phase != PHASE_INT2:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        _interrogator_role.clear_night_pick(game)
        _mark_interrog_confirmed(game, int_uid=int_uid)
        await callback.answer("از بازپرسی منصرف شدید.")
        await _after_interrog_commit(bot, game, gm, int_uid)
        return

    if act == "nii2r":
        if phase != PHASE_INT2:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        _interrogator_role.clear_night_pick(game)
        game.no_host_interrog_ui_phase = PHASE_INT1
        await callback.answer("انتخاب مجدد نفر اول.")
        text = build_no_host_interrog_int1_html(game)
        kb = _int1_keyboard(game, int_uid, gm)
        await _sync_panel(bot, game, int_uid, text, kb)
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
