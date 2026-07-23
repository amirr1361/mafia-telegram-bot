"""شب ۱ — انتخاب هانتر توسط خود بازیکن (حالت بدون گرداننده)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NS_HUNTER,
    Role,
    _advance_after_hunter,
    _night_title_fa,
    push_host_step,
)
from bot.roles.registry import require_role_module

_hunter_role = require_role_module(Role.HUNTER)
from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.roles.registry import find_alive_role_holder
from bot.no_host_role_pick_common import (
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
    sync_role_mirror_panel,
)
from bot.observer_delivery import (
    deliver_no_host_player_game_copy,
    mirror_ui_claim_key,
    no_host_observer_registered,
    player_should_receive_game_messages,
    publish_mirror_prompt_pair,
)

if TYPE_CHECKING:
    from bot.game import GameManager


def build_no_host_hunter_rules_html() -> str:
    return (
        "📜 <b>قوانین هانتر:</b>\n\n"
        "🔗 هانتر هر شب می‌تواند خود را به یکی از بازیکنان وصل کند.\n\n"
        "💀 اگر هانتر با شات، ناتویی یا رأی‌گیری از بازی خارج شود:\n\n"
        "👑 اگر به رییس مافیا وصل باشد:\n"
        "• در شات ➜ فقط هانتر خارج می‌شود؛ رئیس می‌ماند.\n"
        "• در ناتویی موفق ➜ فقط هانتر خارج می‌شود.\n\n"
        "🩸 اگر به مافیایی غیر از رییس مافیا وصل باشد:\n"
        "• در شات یا ناتویی موفق ➜ هر دو از بازی خارج می‌شوند.\n\n"
        "🛡️ اگر به شهروند وصل باشد:\n"
        "• در شات یا ناتویی موفق ➜ فقط هانتر خارج می‌شود."
    )


def build_no_host_hunter_night1_pick_html(game: Game) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    return (
        f"🌙 <b>{_night_title_fa(nc)} — ثبت انتخاب هانتر</b>\n\n"
        "🏹 لطفاً از لیست زیر، نام بازیکنی را که می‌خواهید خود را به او "
        "ببندید انتخاب کنید.\n\n"
        "🚫 شما نمی‌توانید خودتان را انتخاب کنید."
    )


def build_no_host_hunter_night1_waiting_html(pick_uid: int | None, gm: "GameManager", game: Game) -> str:
    if pick_uid is None:
        body = "شما «به کسی وصل نمی‌شوم» را انتخاب کردید."
    else:
        p = game.players.get(pick_uid)
        tag = html.escape(gm.format_player_tag(p) if p else str(pick_uid))
        body = f"وصل به <b>{tag}</b> ثبت شد."
    nc = max(1, game.bazpors_narrator_night_count)
    return (
        f"🌙 <b>{_night_title_fa(nc)} — انتخاب هانتر</b>\n\n"
        f"✅ {body}\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def build_no_host_hunter_night1_confirm_html(game: Game, gm: "GameManager", target_uid: int) -> str:
    p = game.players.get(target_uid)
    tag = html.escape(gm.format_player_tag(p) if p else str(target_uid))
    nc = max(1, game.bazpors_narrator_night_count)
    return (
        f"🌙 <b>{_night_title_fa(nc)} — تایید انتخاب هانتر</b>\n\n"
        f"🏹 انتخاب شما: <b>{tag}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def _hunter_night1_ui_key(game: Game, hunter_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "night1_hunter", hunter_uid)


def _hunter_pick_keyboard(
    game: Game, hunter_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    pool = [
        pl
        for pl in game.players.values()
        if pl.is_alive and pl.user_id != hunter_uid
    ]

    def _label(p: Player) -> str:
        return html.escape(gm.format_player_tag(p)[:28])

    return build_pick_keyboard(
        game,
        hunter_uid,
        pick_act="hnp",
        players=pool,
        none_act="hns",
        none_text="⭕ به کسی وصل نمی‌شوم",
        label_for_player=_label,
    )


def _hunter_confirm_keyboard(game: Game, hunter_uid: int) -> InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        game,
        hunter_uid,
        confirm_act="hnc",
        back_act="hnb",
        confirm_text="🔹 بله، تأیید انتخاب",
        back_text="🔹 بازگشت و تصحیح انتخاب",
    )


def _apply_hunter_pick_to_game(game: Game, pick_uid: int | None) -> None:
    _hunter_role.apply_pick(game, pick_uid)


async def _finalize_hunter_night1(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    pick_uid: int | None,
) -> None:
    if game.no_host_night1_hunter_done:
        return
    game.no_host_night1_hunter_flow_active = False
    game.no_host_night1_hunter_done = True
    game.no_host_hunter_pending_pick_uid = None
    game.no_host_hunter_awaiting_confirm = False

    _apply_hunter_pick_to_game(game, pick_uid)
    if (
        game.bazpors_night_substep == NS_HUNTER
        and not game.no_host_night_parallel_collect_active
    ):
        _advance_after_hunter(game)

    hunter = find_alive_role_holder(game, Role.HUNTER)
    if hunter and player_should_receive_game_messages(game, hunter.user_id):
        from bot.no_host_night_common import (
            finalize_no_host_role_pick_message,
            format_night_selection_label,
        )

        ui_key = _hunter_night1_ui_key(game, hunter.user_id)
        if pick_uid is None:
            label = "وصلی ندارم"
        else:
            label = f"وصل: {format_night_selection_label(game, gm, pick_uid)}"
        await finalize_no_host_role_pick_message(
            bot, game, gm, hunter.user_id, ui_key, label
        )

    from bot.no_host_night_ready import (
        maybe_finish_no_host_parallel_night,
        no_host_parallel_night_collect_active,
    )

    if no_host_parallel_night_collect_active(game):
        await maybe_finish_no_host_parallel_night(bot, game, gm)
    else:
        from bot.no_host_phase import no_host_maybe_continue_after_night1_assistant

        await no_host_maybe_continue_after_night1_assistant(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night1_hunter_done",
            pick_uid=pick_uid,
        )
    except Exception:
        pass


async def start_no_host_night1_hunter_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if game.bazpors_host_mode != "no_host":
        return
    if game.no_host_night1_hunter_done:
        return

    hunter = find_alive_role_holder(game, Role.HUNTER)
    if hunter is None:
        game.no_host_night1_hunter_done = True
        game.no_host_night1_hunter_flow_active = False
        if game.bazpors_night_substep == NS_HUNTER:
            _advance_after_hunter(game)
        return

    game.no_host_night1_hunter_flow_active = True
    game.no_host_hunter_pending_pick_uid = None
    game.no_host_hunter_awaiting_confirm = False

    if player_should_receive_game_messages(game, hunter.user_id):
        await deliver_no_host_player_game_copy(
            bot,
            game,
            hunter.user_id,
            build_no_host_hunter_rules_html(),
            is_synthetic_uid=is_synthetic_player_uid,
            parse_mode="HTML",
        )

    text = build_no_host_hunter_night1_pick_html(game)
    kb = _hunter_pick_keyboard(game, hunter.user_id, gm)
    ui_key = _hunter_night1_ui_key(game, hunter.user_id)
    synthetic = is_synthetic_player_uid(hunter.user_id)
    await publish_mirror_prompt_pair(
        bot,
        game,
        hunter.user_id,
        ui_key,
        text,
        kb,
        fresh_observer_copy=True,
        send_player=not synthetic,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def on_no_host_entered_night1(bot: Bot, game: Game, gm: "GameManager") -> None:
    await on_no_host_entered_night(bot, game, gm)


async def on_no_host_entered_night(bot: Bot, game: Game, gm: "GameManager") -> None:
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.mason_helper_flow import mason_on_no_host_entered_night

        await mason_on_no_host_entered_night(bot, game, gm)
        return
    from bot.no_host_phase import run_no_host_night1_phase

    await run_no_host_night1_phase(bot, game, gm)


def hunter_night1_act_active(game: Game, act: str) -> bool:
    return act in ("hnp", "hns", "hnc", "hnb")


async def dispatch_no_host_hunter_night1(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    hunter_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    if not game.no_host_night1_hunter_flow_active or game.no_host_night1_hunter_done:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if actor_uid != hunter_uid and actor_uid != game.observer_user_id:
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return

    hunter = find_alive_role_holder(game, Role.HUNTER)
    if hunter is None or hunter.user_id != hunter_uid:
        await callback.answer("هانتر در بازی نیست.", show_alert=True)
        return

    ui_key = _hunter_night1_ui_key(game, hunter_uid)

    if act == "hnp":
        if game.no_host_hunter_awaiting_confirm:
            pass
        if tid == hunter_uid or tid not in game.players or not game.players[tid].is_alive:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        game.no_host_hunter_pending_pick_uid = tid
        game.no_host_hunter_awaiting_confirm = True
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        confirm_text = build_no_host_hunter_night1_confirm_html(game, gm, tid)
        confirm_kb = _hunter_confirm_keyboard(game, hunter_uid)
        await sync_role_mirror_panel(
            bot, game, ui_key, hunter_uid, confirm_text, confirm_kb
        )
        return

    if act == "hns":
        game.no_host_hunter_pending_pick_uid = None
        game.no_host_hunter_awaiting_confirm = False
        await callback.answer("ثبت شد.")
        await _finalize_hunter_night1(bot, game, gm, None)
        return

    if act == "hnb":
        game.no_host_hunter_pending_pick_uid = None
        game.no_host_hunter_awaiting_confirm = False
        await callback.answer("بازگشت به لیست.")
        pick_text = build_no_host_hunter_night1_pick_html(game)
        pick_kb = _hunter_pick_keyboard(game, hunter_uid, gm)
        await sync_role_mirror_panel(
            bot, game, ui_key, hunter_uid, pick_text, pick_kb
        )
        return

    if act == "hnc":
        pick = game.no_host_hunter_pending_pick_uid
        if pick is None or pick not in game.players:
            await callback.answer("ابتدا یک بازیکن انتخاب کنید.", show_alert=True)
            return
        await callback.answer("تأیید شد.")
        await _finalize_hunter_night1(bot, game, gm, pick)
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
