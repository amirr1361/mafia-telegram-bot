"""شب — انتخاب حدس کارآگاه توسط شیاد (مسیر گردانندگی بدون گرداننده).

شیاد یک بازیکن غیرمافیا را انتخاب و تأیید می‌کند.
اگر کارآگاه را درست حدس بزند، استعلام کارآگاه در این شب مختل می‌شود.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_SHIAD,
    Role,
    _advance_after_shiad,
    _alive,
    _night_title_fa,
    _visually_mafia,
    no_host_assistant_narrator_active,
    push_host_step,
)
from bot.game import bazpors_counts_as_mafia_faction, is_synthetic_player_uid
from bot.models import Game, Player
from bot.roles.registry import find_alive_role_holder, require_role_module

_shiad_role = require_role_module(Role.SHIAD)
from bot.roles.registry import find_alive_role_holder
from bot.no_host_night_common import (
    arm_no_host_role_pick_flow,
    no_host_after_role_night_pick,
    no_host_night_wait_phase_active,
    publish_no_host_night_wait_panel,
)
from bot.no_host_role_pick_common import (
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
    no_host_observer_registered,
    publish_mirror_prompt_pair,
    send_to_player,
)

if TYPE_CHECKING:
    from bot.game import GameManager


def _shiad_ui_key(game: Game, sh_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_shiad", sh_uid)


def _shiad_panel_already_sent_for_night(game: Game, nc: int) -> bool:
    """ورود شب و نوبت نریتور هر دو یک پنل انتخاب — فقط یک‌بار در هر شب."""
    sig = game.no_host_shiad_dm_signature
    return bool(sig and sig.startswith(f"{nc}:shiad:"))


def _player_button_name(p: Player | None, uid: int) -> str:
    return player_button_name(p, uid)


def _shiad_guess_pool(game: Game) -> list[Player]:
    return _shiad_role.guess_pool(game)


def _commit_shiad_pick(game: Game, tid: int) -> bool:
    return _shiad_role.commit_pick(game, tid)


def build_no_host_shiad_pick_html(game: Game) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"🎭 {night_lbl} - انتخاب شیاد\n\n"
        "🕵️ لطفاً از لیست زیر، بازیکنی را که فکر می‌کنید نقش "
        "<b>کارآگاه</b> دارد انتخاب کنید.\n\n"
        "📩 پس از تأیید، تا پایان فاز شب منتظر بمانید."
    )


def build_no_host_shiad_confirm_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    return (
        f"{build_no_host_shiad_pick_html(game)}\n\n"
        f"🎯 انتخاب شما: <b>{name}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_shiad_waiting_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"🎭 {night_lbl} - انتخاب شیاد\n\n"
        f"✅ حدس شما روی <b>{name}</b> ثبت شد.\n\n"
        "📩 نتیجه انتخاب پس از پایان فاز امشب برایتان ارسال می‌شود.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def build_no_host_shiad_result_html(game: Game, gm: "GameManager") -> str | None:
    if not game.no_host_shiad_pick_confirmed:
        return None
    snap = game.bazpors_alive_at_night_start or {}
    sh_uid = None
    for uid, pl in game.players.items():
        if pl.role == Role.SHIAD and snap.get(uid, pl.is_alive):
            sh_uid = uid
            break
    if sh_uid is None:
        return None

    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    tgt_uid = game.bazpors_shiad_target_uid
    if tgt_uid is None:
        return (
            f"🎭 {night_lbl} — نتیجه انتخاب شیاد\n\n"
            "انتخابی ثبت نشده است."
        )

    tgt = game.players.get(tgt_uid)
    name = html.escape(gm.format_player_tag(tgt) if tgt else str(tgt_uid))
    return (
        f"🎭 {night_lbl} — نتیجه انتخاب شیاد\n\n"
        f"🎯 هدف: <b>{name}</b>\n\n"
        "انتخاب شما ثبت شد."
    )


def _pick_keyboard(
    game: Game, sh_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    del gm
    return build_pick_keyboard(
        game,
        sh_uid,
        pick_act="sgt",
        players=_shiad_guess_pool(game),
    )


def _confirm_keyboard(game: Game, sh_uid: int) -> InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        game,
        sh_uid,
        confirm_act="sgc",
        back_act="sgb",
        confirm_text="✅ بله، تأیید",
        back_text="↩️ بازگشت",
    )


def _should_run_no_host_shiad_flow(game: Game) -> bool:
    return (
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "no_host"
        and no_host_assistant_narrator_active(game)
        and game.bazpors_narrator_step == NIGHT_ACTIONS
        and game.bazpors_night_substep == NS_SHIAD
    )


def _advance_past_shiad_if_cannot_act(game: Game) -> bool:
    if not _should_run_no_host_shiad_flow(game):
        return False
    sh = find_alive_role_holder(game, Role.SHIAD)
    if sh is None:
        from bot.bazpors_narrator import _goto_role_absent, _role_eliminated_from_game

        if _role_eliminated_from_game(game, Role.SHIAD):
            _goto_role_absent(game, Role.SHIAD)
        else:
            _advance_after_shiad(game)
        return True
    if not _shiad_guess_pool(game):
        _shiad_role.clear_pick(game)
        _advance_after_shiad(game)
        return True
    return False


async def start_no_host_shiad_night_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    at_night_entry: bool = False,
) -> bool:
    if at_night_entry:
        if not no_host_night_wait_phase_active(game):
            return False
    else:
        if not _should_run_no_host_shiad_flow(game):
            return False
        if _advance_past_shiad_if_cannot_act(game):
            return False
    sh = find_alive_role_holder(game, Role.SHIAD)
    if sh is None or not _shiad_guess_pool(game):
        return False

    nc = game.bazpors_narrator_night_count
    if game.no_host_shiad_pick_confirmed:
        return False
    if _shiad_panel_already_sent_for_night(game, nc):
        return False

    sig = f"{nc}:shiad:night_entry" if at_night_entry else f"{nc}:shiad:{NS_SHIAD}"
    game.no_host_shiad_flow_active = True
    game.no_host_shiad_pending_tid = None
    game.no_host_shiad_dm_signature = sig

    text = build_no_host_shiad_pick_html(game)
    kb = _pick_keyboard(game, sh.user_id, gm)
    ui_key = _shiad_ui_key(game, sh.user_id)

    await publish_mirror_prompt_pair(
        bot,
        game,
        sh.user_id,
        ui_key,
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
            "no_host.shiad_night_panel_sent",
            sh_uid=sh.user_id,
            night_count=nc,
        )
    except Exception:
        pass
    return True


async def dispatch_no_host_shiad_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.no_host_night_entry import complete_no_host_role_night_if_already_picked

    await complete_no_host_role_night_if_already_picked(bot, game, gm)
    if game.no_host_shiad_pick_confirmed:
        if not no_host_night_wait_phase_active(game):
            return
        sh = find_alive_role_holder(game, Role.SHIAD)
        if sh is not None:
            tid = game.bazpors_shiad_target_uid or game.no_host_shiad_pending_tid
            if tid is not None:
                await publish_no_host_night_wait_panel(
                    bot,
                    game,
                    sh.user_id,
                    _shiad_ui_key(game, sh.user_id),
                    "",
                    gm=gm,
                    selection_uid=tid,
                )
        return
    if _advance_past_shiad_if_cannot_act(game):
        await push_host_step(bot, game, gm)
        return
    nc = game.bazpors_narrator_night_count
    if _shiad_panel_already_sent_for_night(game, nc):
        arm_no_host_role_pick_flow(
            game,
            flow_active_attr="no_host_shiad_flow_active",
            pick_confirmed_attr="no_host_shiad_pick_confirmed",
            dm_signature_attr="no_host_shiad_dm_signature",
        )
        return
    await start_no_host_shiad_night_flow(bot, game, gm)


def no_host_shiad_act_active(game: Game, act: str) -> bool:
    return act in ("sgt", "sgc", "sgb")


def _actor_may_act(game: Game, actor_uid: int, sh_uid: int) -> bool:
    return actor_may_act_on_role_panel(game, actor_uid, sh_uid)


async def _sync_panel(
    bot: Bot,
    game: Game,
    sh_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await sync_role_mirror_panel(
        bot, game, _shiad_ui_key(game, sh_uid), sh_uid, text, kb
    )


async def flush_no_host_shiad_result_pending(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not game.no_host_shiad_result_pending:
        return
    game.no_host_shiad_result_pending = False
    await send_no_host_shiad_result_dm(bot, game, gm)


async def send_no_host_shiad_result_dm(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not (
        game.bazpors_host_mode == "no_host"
        and no_host_assistant_narrator_active(game)
    ):
        return
    nc = game.bazpors_narrator_night_count
    if game.no_host_shiad_result_sent_night == nc:
        return
    body = build_no_host_shiad_result_html(game, gm)
    if not body:
        return

    snap = game.bazpors_alive_at_night_start or {}
    sh_uid = None
    for uid, pl in game.players.items():
        if pl.role == Role.SHIAD and snap.get(uid, False):
            sh_uid = uid
            break
    if sh_uid is None:
        return

    sh = game.players.get(sh_uid)
    if sh and sh.is_alive:
        await send_to_player(
            bot,
            game,
            sh_uid,
            body,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await deliver_no_host_player_game_copy(
            bot,
            game,
            sh_uid,
            body,
            is_synthetic_uid=is_synthetic_player_uid,
            parse_mode="HTML",
        )
    game.no_host_shiad_result_sent_night = nc
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.shiad_result_sent",
            sh_uid=sh_uid,
            night_count=nc,
            target_uid=game.bazpors_shiad_target_uid,
        )
    except Exception:
        pass


async def dispatch_no_host_shiad_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    sh_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    arm_no_host_role_pick_flow(
        game,
        flow_active_attr="no_host_shiad_flow_active",
        pick_confirmed_attr="no_host_shiad_pick_confirmed",
        dm_signature_attr="no_host_shiad_dm_signature",
    )
    if not game.no_host_shiad_flow_active or game.no_host_shiad_pick_confirmed:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not no_host_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    sh = find_alive_role_holder(game, Role.SHIAD)
    if sh is None or sh.user_id != sh_uid:
        await callback.answer("شیاد در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, sh_uid):
        await callback.answer(
            "فقط شیاد می‌تواند این انتخاب را انجام دهد.", show_alert=True
        )
        return

    pool = _shiad_guess_pool(game)

    if act == "sgt":
        if not target_in_pool(tid, pool):
            await callback.answer("این بازیکن در لیست نیست.", show_alert=True)
            return
        game.no_host_shiad_pending_tid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        text = build_no_host_shiad_confirm_html(game, gm, tid)
        kb = _confirm_keyboard(game, sh_uid)
        await _sync_panel(bot, game, sh_uid, text, kb)
        return

    if act == "sgb":
        game.no_host_shiad_pending_tid = None
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_shiad_pick_html(game)
        kb = _pick_keyboard(game, sh_uid, gm)
        await _sync_panel(bot, game, sh_uid, text, kb)
        return

    if act == "sgc":
        pick = game.no_host_shiad_pending_tid
        if pick is None or not target_in_pool(pick, pool):
            await callback.answer("ابتدا یک بازیکن انتخاب کنید.", show_alert=True)
            return
        if game.no_host_shiad_pick_confirmed:
            await callback.answer("قبلاً ثبت شده است.", show_alert=True)
            return
        hit_det = _commit_shiad_pick(game, pick)
        game.no_host_shiad_pick_confirmed = True
        game.no_host_shiad_flow_active = False
        game.no_host_shiad_pending_tid = None

        await callback.answer("ثبت شد.")
        await publish_no_host_night_wait_panel(
            bot,
            game,
            sh_uid,
            _shiad_ui_key(game, sh_uid),
            "",
            gm=gm,
            selection_uid=pick,
        )

        await no_host_after_role_night_pick(
            bot, game, gm, expected_substep=NS_SHIAD, advance=_advance_after_shiad
        )
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.shiad_pick_confirmed",
                sh_uid=sh_uid,
                target_uid=pick,
                detective_hit=hit_det,
            )
        except Exception:
            pass
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
