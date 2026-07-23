"""شب ۱ — انتخاب هدف شات توسط تیم مافیا (حالت بدون گرداننده)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NS_MAFIA_SHOT,
    _advance_after_mafia_menu_done,
    _alive,
    _night_title_fa,
    push_host_step,
)
from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.no_host_mafia_chooser import (
    maybe_start_shiad_parallel_night_panels,
    resolve_mafia_shot_chooser,
)
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_SHOT,
    _actor_may_use_mafia_copy,
    _mafia_panel_has_uid,
    _sync_mafia_ref_from_mirror,
    notify_all_alive_mafia_team,
)
from bot.no_host_night_common import (
    finalize_no_host_role_pick_message,
    format_night_selection_label,
)
from bot.observer_delivery import (
    PlayerMirrorCb,
    apply_mirror_claim_winner,
    mirror_ui_claim_key,
    no_host_observer_registered,
    player_should_receive_game_messages,
    publish_mirror_prompt_pair,
    update_mirror_prompt_pair,
)

from bot.no_host_role_pick_common import player_button_name
from bot.room_mode import is_mason_scenario, is_mozakere_scenario

if TYPE_CHECKING:
    from bot.game import GameManager


def _mafia_shot_ui_key(game: Game, mafia_uid: int) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    return mirror_ui_claim_key(game.room_code, f"mafia_shot_n{nc}", mafia_uid)


def _mafia_shot_confirm_claim_key(game: Game) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    return mirror_ui_claim_key(game.room_code, f"mafia_shot_confirm_n{nc}", 0)


def _mafia_shot_mirror_ui_key(game: Game, mafia_uid: int) -> str:
    """پنل شلیک — در ماسون اگر بازیکن پنل نقش جدا دارد، کلید مستقل."""
    if is_mason_scenario(game):
        from bot.mason_responsibilities import mason_mafia_shot_uses_dedicated_panel

        if mason_mafia_shot_uses_dedicated_panel(game, mafia_uid):
            return _mafia_shot_ui_key(game, mafia_uid)
    from bot.no_host_mafia_night1 import _mafia_night1_ui_key

    n1_key = _mafia_night1_ui_key(game, mafia_uid)
    if game.mirror_prompt_messages.get(n1_key):
        return n1_key
    return _mafia_shot_ui_key(game, mafia_uid)


async def _sync_mafia_shot_mirror_panel(
    bot: Bot,
    game: Game,
    mafia_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    ui_key = _mafia_shot_mirror_ui_key(game, mafia_uid)
    if game.mirror_prompt_messages.get(ui_key):
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            text,
            kb,
            assistant_uid=mafia_uid,
            parse_mode="HTML",
        )
    else:
        await publish_mirror_prompt_pair(
            bot,
            game,
            mafia_uid,
            ui_key,
            text,
            kb,
            fresh_observer_copy=False,
            send_player=(
                player_should_receive_game_messages(game, mafia_uid)
                and not is_synthetic_player_uid(mafia_uid)
            ),
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
    _sync_mafia_ref_from_mirror(game, mafia_uid)


def build_no_host_mafia_shot_pick_html(game: Game) -> str:
    night_lbl = _night_title_fa(max(1, game.bazpors_narrator_night_count))
    return (
        f"🌙 <b>{night_lbl} — ثبت هدف شات</b>\n\n"
        "🔫 از لیست زیر، نام بازیکنی را که می‌خواهید شلیک کنید انتخاب کنید.\n\n"
        "حداقل و حداکثر یک نفر باید انتخاب شود."
    )


def build_no_host_mafia_shot_confirm_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    tag = html.escape(gm.format_player_tag(p) if p else str(target_uid))
    night_lbl = _night_title_fa(max(1, game.bazpors_narrator_night_count))
    return (
        f"🌙 <b>{night_lbl} — تأیید هدف شات</b>\n\n"
        f"🔫 هدف شما: <b>{tag}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_mafia_shot_team_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    tag = html.escape(gm.format_player_tag(p) if p else str(target_uid))
    night_lbl = _night_title_fa(max(1, game.bazpors_narrator_night_count))
    return (
        f"🌙 <b>{night_lbl} — شات تیم مافیا</b>\n\n"
        f"🔫 تیم شما شات کرد — هدف شما: <b>{tag}</b>\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def build_no_host_mafia_shot_waiting_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    return build_no_host_mafia_shot_team_html(game, gm, target_uid)


async def notify_mafia_team_shot_result(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    target_uid: int,
) -> None:
    """اطلاع شات ثبت‌شده به همهٔ مافیاهای زنده و ناظر (بدون دکمه)."""
    text = build_no_host_mafia_shot_team_html(game, gm, target_uid)
    await notify_all_alive_mafia_team(bot, game, text)


def _shot_target_button_text(game: Game, gm: "GameManager", p: Player) -> str:
    if is_mozakere_scenario(game):
        from bot.bazpors_narrator import _visually_mafia

        name = player_button_name(p, p.user_id)
        if _visually_mafia(game, p):
            return f"🔴 {name[:30]}"
        return name[:32]
    return html.escape(gm.format_player_tag(p)[:28])


def _shot_pick_keyboard(
    game: Game, mafia_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sorted(
        _alive(game),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        name = _shot_target_button_text(game, gm, p)
        cb = PlayerMirrorCb(
            code=game.room_code, act="msk", as_uid=mafia_uid, tid=p.user_id
        ).pack()
        row.append(InlineKeyboardButton(text=name, callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _shot_confirm_keyboard(game: Game, mafia_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔹 بله، تأیید انتخاب",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="msc", as_uid=mafia_uid
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔹 بازگشت و تصحیح انتخاب",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="msb", as_uid=mafia_uid
                    ).pack(),
                )
            ],
        ]
    )


def _apply_shot_target_to_game(game: Game, target_uid: int) -> None:
    from bot.roles.night_state import mafia_night_state

    mafia_night_state(game).commit_shot(target_uid)
    if game.bazpors_night_substep == NS_MAFIA_SHOT:
        _advance_after_mafia_menu_done(game)


def _ensure_mason_mafia_night1_flags_after_shot(
    game: Game, *, mafia_uid: int
) -> None:
    if not is_mason_scenario(game):
        return
    if game.no_host_mafia_night1_done:
        return
    game.no_host_mafia_night1_done = True
    if game.no_host_mafia_night1_chosen_action is None:
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
    if game.no_host_mafia_night1_chooser_uid is None:
        game.no_host_mafia_night1_chooser_uid = mafia_uid
    if mafia_uid not in game.no_host_mafia_night1_panel_uids:
        game.no_host_mafia_night1_panel_uids = [mafia_uid]


async def _maybe_redispatch_saboteur_panel_after_mafia_shot(
    bot: Bot, game: Game, gm: "GameManager", *, mafia_uid: int
) -> None:
    from bot.mason_responsibilities import redispatch_mason_role_panel_after_mafia_shot

    await redispatch_mason_role_panel_after_mafia_shot(
        bot, game, gm, mafia_uid=mafia_uid
    )


async def _finalize_mafia_shot(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    mafia_uid: int,
    actor_uid: int,
    target_uid: int,
) -> None:
    from bot.roles.night_state import mafia_night_state

    mafia = mafia_night_state(game)
    if mafia.no_host_done:
        return
    mafia.finalize_no_host_shot()

    _ensure_mason_mafia_night1_flags_after_shot(game, mafia_uid=mafia_uid)
    _apply_shot_target_to_game(game, target_uid)

    label = format_night_selection_label(game, gm, target_uid)
    await finalize_no_host_role_pick_message(
        bot,
        game,
        gm,
        mafia_uid,
        _mafia_shot_mirror_ui_key(game, mafia_uid),
        f"هدف شات: {label}",
    )

    await notify_mafia_team_shot_result(
        bot, game, gm, target_uid=target_uid
    )

    from bot.no_host_night_ready import (
        maybe_finish_no_host_parallel_night,
        no_host_parallel_night_collect_active,
    )

    if no_host_parallel_night_collect_active(game):
        await maybe_finish_no_host_parallel_night(bot, game, gm)
    elif not is_mozakere_scenario(game):
        await push_host_step(bot, game, gm)

    await _maybe_redispatch_saboteur_panel_after_mafia_shot(
        bot, game, gm, mafia_uid=mafia_uid
    )

    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night1_mafia_shot_done",
            target_uid=target_uid,
            mafia_uid=mafia_uid,
        )
    except Exception:
        pass


def no_host_requires_mafia_shot_pick(game: Game) -> bool:
    """آیا این شب باید هدف شات توسط تیم مافیا ثبت شود؟"""
    from bot.bazpors_narrator import _mafia_alive_n, mafia_shot_allowed

    if game.bazpors_narrator_night_count < 1:
        return False
    if _mafia_alive_n(game) < 1:
        return False
    return mafia_shot_allowed(game)


def _mafia_shot_panel_uids(game: Game) -> list[int]:
    chooser = resolve_mafia_shot_chooser(game)
    if chooser is None:
        return []
    if not player_should_receive_game_messages(game, chooser.user_id):
        return []
    return [chooser.user_id]


async def dispatch_no_host_mafia_shot_at_night_entry(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """فقط پس از انتخاب «شات» از منوی تیم مافیا — نه هم‌زمان با منوی کامل ورود شب."""
    if game.bazpors_host_mode != "no_host":
        return
    if game.bazpors_narrator_night_count < 2:
        return
    if game.no_host_mafia_shot_done or game.no_host_mafia_shot_flow_active:
        return
    if not no_host_requires_mafia_shot_pick(game):
        game.no_host_mafia_shot_done = True
        return

    panel_uids = _mafia_shot_panel_uids(game)
    if not panel_uids:
        if is_mason_scenario(game):
            game.no_host_mafia_night1_done = True
            game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        return

    game.no_host_mafia_night1_panel_uids = list(panel_uids)
    if panel_uids:
        game.no_host_mafia_night1_chooser_uid = panel_uids[0]
    await start_no_host_mafia_shot_flow(bot, game, gm)
    await maybe_start_shiad_parallel_night_panels(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.mafia_shot_panel_sent",
            night_count=game.bazpors_narrator_night_count,
            panel_uids=panel_uids,
        )
    except Exception:
        pass


async def start_no_host_mafia_shot_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if game.bazpors_host_mode != "no_host":
        return
    nc = game.bazpors_narrator_night_count
    if nc == 1:
        if game.no_host_mafia_night1_chosen_action != MAFIA_ACTION_SHOT:
            return
    elif not no_host_requires_mafia_shot_pick(game):
        return
    if game.no_host_mafia_shot_done:
        return
    if game.no_host_mafia_shot_flow_active and nc == 1:
        return

    panel_uids = list(game.no_host_mafia_night1_panel_uids)
    if not panel_uids:
        panel_uids = _mafia_shot_panel_uids(game)
        game.no_host_mafia_night1_panel_uids = list(panel_uids)
    if not panel_uids:
        if is_mason_scenario(game):
            game.no_host_mafia_night1_done = True
            game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        return

    game.no_host_mafia_shot_flow_active = True
    game.no_host_mafia_shot_pending_uid = None
    game.no_host_mafia_shot_awaiting_confirm = False

    text = build_no_host_mafia_shot_pick_html(game)
    for mafia_uid in panel_uids:
        kb = _shot_pick_keyboard(game, mafia_uid, gm)
        ui_key = _mafia_shot_ui_key(game, mafia_uid)
        await publish_mirror_prompt_pair(
            bot,
            game,
            mafia_uid,
            ui_key,
            text,
            kb,
            fresh_observer_copy=True,
            send_player=(
                player_should_receive_game_messages(game, mafia_uid)
                and not is_synthetic_player_uid(mafia_uid)
            ),
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
        _sync_mafia_ref_from_mirror(game, mafia_uid)


def mafia_shot_act_active(game: Game, act: str) -> bool:
    return act in ("msk", "msc", "msb")


async def dispatch_no_host_mafia_shot(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    mafia_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    from bot.mason_force_finish_night import reject_mason_night_callback_if_closed

    if await reject_mason_night_callback_if_closed(callback, game):
        return
    if not game.no_host_mafia_shot_flow_active or game.no_host_mafia_shot_done:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not _actor_may_use_mafia_copy(game, actor_uid, mafia_uid):
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return
    if not _mafia_panel_has_uid(game, mafia_uid):
        await callback.answer("شما پنل انتخاب ندارید.", show_alert=True)
        return

    if act == "msk":
        if tid not in game.players or not game.players[tid].is_alive:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        game.no_host_mafia_shot_pending_uid = tid
        game.no_host_mafia_shot_awaiting_confirm = True
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        confirm_text = build_no_host_mafia_shot_confirm_html(game, gm, tid)
        confirm_kb = _shot_confirm_keyboard(game, mafia_uid)
        await _sync_mafia_shot_mirror_panel(
            bot, game, mafia_uid, confirm_text, confirm_kb
        )
        return

    if act == "msb":
        game.no_host_mafia_shot_pending_uid = None
        game.no_host_mafia_shot_awaiting_confirm = False
        await callback.answer("بازگشت به لیست.")
        pick_text = build_no_host_mafia_shot_pick_html(game)
        pick_kb = _shot_pick_keyboard(game, mafia_uid, gm)
        await _sync_mafia_shot_mirror_panel(bot, game, mafia_uid, pick_text, pick_kb)
        return

    if act == "msc":
        pick = game.no_host_mafia_shot_pending_uid
        if pick is None or pick not in game.players or not game.players[pick].is_alive:
            await callback.answer("ابتدا یک بازیکن انتخاب کنید.", show_alert=True)
            return
        claim_key = _mafia_shot_confirm_claim_key(game)
        existing = game.mirror_action_claims.get(claim_key)
        if existing is not None and existing != actor_uid:
            await callback.answer(
                "یکی از اعضای تیم مافیا قبلاً هدف شات را تأیید کرده است.",
                show_alert=True,
            )
            return
        if existing is None:
            game.mirror_action_claims[claim_key] = actor_uid
            if no_host_observer_registered(game):
                await apply_mirror_claim_winner(
                    bot,
                    game,
                    _mafia_shot_mirror_ui_key(game, mafia_uid),
                    actor_uid,
                    mafia_uid,
                )
        if game.no_host_mafia_shot_done:
            await callback.answer("هدف شات قبلاً ثبت شده است.", show_alert=True)
            return
        await callback.answer("تأیید شد.")
        await _finalize_mafia_shot(
            bot,
            game,
            gm,
            mafia_uid=mafia_uid,
            actor_uid=actor_uid,
            target_uid=pick,
        )
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
