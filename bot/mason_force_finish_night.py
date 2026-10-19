"""اتمام اجباری شب — فقط سناریوی ماسون (کمک‌کننده)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.main import no_host_bot_assistant_flow_enabled
from bot.models import Game, Role
from bot.no_host_night_ready import no_host_parallel_night_collect_active
from bot.room_mode import is_mason_scenario
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

MASON_FORCE_FINISH_NIGHT_COMMAND = "اتمام شب"
MASON_FORCE_FINISH_NOT_NIGHT_TEXT = "هنوز تو فاز شب نیستیم."
MASON_FORCE_FINISH_CONFIRM_TEXT = "آیا مطمئن هستید؟"
MASON_FORCE_FINISH_CANCELLED_TEXT = "لغو شد."
MASON_NIGHT_PANEL_LOCKED_TEXT = "فاز شب به پایان رسید."
MASON_NIGHT_PHASE_ENDED_TEXT = "فاز شب به پایان رسیده است."


def mason_night_force_finish_collection_active(game: Game) -> bool:
    """شب ماسون در حال جمع‌آوری اقدامات موازی."""
    if not is_mason_scenario(game):
        return False
    if not no_host_parallel_night_collect_active(game):
        return False
    nc = game.bazpors_narrator_night_count
    return game.mason_night_entry_dispatched_night == nc


def mason_night_player_actions_closed(game: Game) -> bool:
    return is_mason_scenario(game) and game.mason_night_force_finished


def find_mason_bot_assistant_game(
    user_id: int, gm: "GameManager | None" = None
) -> Game | None:
    if gm is None:
        from bot.app_state import manager as gm
    game = gm.find_active_participant_game(user_id)
    if game is None or not is_mason_scenario(game):
        return None
    if not no_host_bot_assistant_flow_enabled(game):
        return None
    if game.bot_assistant_user_id != user_id:
        return None
    return game


def _force_finish_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    from bot.mason_helper_flow import MasonHelperCb

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="بله",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="yes", kind="force_night"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="خیر",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="no", kind="force_night"
                    ).pack(),
                ),
            ]
        ]
    )


def pending_mason_force_finish_labels(game: Game, gm: "GameManager") -> list[str]:
    from bot.mason_responsibilities import collect_mason_night_responsibilities

    return [
        resp.label
        for resp in collect_mason_night_responsibilities(game, gm)
        if resp.required and not resp.done
    ]


def _normalize_pending_mason_mafia_actions(game: Game) -> None:
    from bot.no_host_mafia_night1 import MAFIA_ACTION_NATO, MAFIA_ACTION_SHOT

    if game.no_host_mafia_nato_flow_active and not game.no_host_mafia_nato_done:
        game.no_host_mafia_nato_flow_active = False
        game.no_host_mafia_nato_done = True
        game.no_host_mafia_nato_phase = None
        game.no_host_mafia_nato_pending_role = None
        game.no_host_mafia_nato_pending_target_uid = None

    action = game.no_host_mafia_night1_chosen_action

    if not game.no_host_mafia_night1_done:
        game.no_host_mafia_night1_flow_active = False
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_pending_action = None
        if action is None:
            game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        if game.no_host_mafia_night1_chosen_action == MAFIA_ACTION_NATO:
            if not game.no_host_mafia_nato_done:
                game.no_host_mafia_nato_done = True
            game.no_host_mafia_shot_done = True
        else:
            game.no_host_mafia_shot_done = True
        game.no_host_mafia_shot_flow_active = False
        game.no_host_mafia_shot_pending_uid = None
        game.no_host_mafia_shot_awaiting_confirm = False
        return

    if action == MAFIA_ACTION_NATO:
        if not game.no_host_mafia_nato_done:
            game.no_host_mafia_nato_flow_active = False
            game.no_host_mafia_nato_done = True
            game.no_host_mafia_nato_phase = None
            game.no_host_mafia_nato_pending_role = None
            game.no_host_mafia_nato_pending_target_uid = None
        return

    if action in (MAFIA_ACTION_SHOT, None):
        if not (game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered):
            game.no_host_mafia_shot_done = True
            game.no_host_mafia_shot_flow_active = False
            game.no_host_mafia_shot_pending_uid = None
            game.no_host_mafia_shot_awaiting_confirm = False


def normalize_pending_mason_night_actions(game: Game, gm: "GameManager") -> None:
    """اقدامات ناقص را مثل «انتخابی ندارم» / اوکی بدون اثر ثبت کن."""
    from bot.mason_night_entry import night_action_holder_uids, _wait_ui_key
    from bot.mason_night_ready import (
        _commander_ready,
        _doctor_ready,
        _detective_ready,
        _gunner_ready,
        _guardian_ready,
        _mason_recruit_ready,
        _natasha_ready,
        _priest_ready,
        _player_auto_satisfied_wait_ok,
        _saboteur_ready,
        _sniper_ready,
        _waiters_ready,
    )
    from bot.roles import mason_commander as ms_cmd
    from bot.roles import mason_doctor as ms_doc
    from bot.roles import mason_fraternity as ms_msn
    from bot.roles import mason_gunner as ms_gn
    from bot.roles import mason_guardian as ms_gd
    from bot.roles import mason_natasha as ms_nat
    from bot.roles import mason_priest as ms_pr
    from bot.roles import mason_saboteur as ms_sab
    from bot.roles import mason_sniper as ms_sn

    _normalize_pending_mason_mafia_actions(game)

    if not _saboteur_ready(game):
        sab = ms_sab.find_alive_mason_saboteur(game)
        if sab is not None:
            if ms_sab.mason_saboteur_needs_night_pick(game):
                ms_sab.commit_mason_saboteur_no_sabotage(game)
            game.mason_night_saboteur_confirmed = True

    if not _doctor_ready(game):
        doc = ms_doc.find_alive_mason_doctor(game)
        if doc is not None:
            if not game.mason_night_doctor_nato_void_pending:
                ms_doc.clear_mason_doctor_night_saves(game)
            game.mason_night_doctor_nato_void_pending = False
            game.mason_night_doctor_confirmed = True

    if not _sniper_ready(game):
        sn = ms_sn.find_alive_mason_sniper(game)
        if sn is not None:
            ms_sn.clear_mason_sniper_night_selection(game)
            game.mason_night_sniper_confirmed = True

    if not _commander_ready(game):
        cmd = ms_cmd.find_alive_mason_commander(game)
        if cmd is not None:
            ms_cmd.mason_commander_rejects_all_shots(game)
            game.mason_night_commander_confirmed = True

    if not _gunner_ready(game):
        gun = ms_gn.find_alive_mason_gunner(game)
        if gun is not None:
            if ms_gn.mason_gunner_can_give_gun(game):
                ms_gn.commit_mason_gunner_no_give(game)
            game.mason_night_gunner_confirmed = True

    if not _guardian_ready(game):
        gd = ms_gd.find_alive_mason_guardian(game)
        if gd is not None:
            ms_gd.clear_mason_guardian_night_pick(game)
            game.mason_night_guardian_confirmed = True

    if not _mason_recruit_ready(game):
        mason = ms_msn.find_alive_mason_role_holder(game)
        if mason is not None:
            ms_msn.commit_mason_recruit(game, mason, None)
            game.mason_night_mason_confirmed = True

    if not _detective_ready(game):
        if find_alive_role_holder(game, Role.DETECTIVE) is not None:
            game.mason_night_detective_confirmed = True

    if not _natasha_ready(game):
        nat = ms_nat.find_alive_mason_natasha(game)
        if nat is not None:
            ms_nat.clear_mason_natasha_night_pick(game)
            game.mason_night_natasha_confirmed = True

    if not _priest_ready(game):
        pr = ms_pr.find_alive_mason_priest(game)
        if pr is not None:
            ms_pr.clear_mason_priest_night_pick(game)
            game.mason_night_priest_confirmed = True

    if not _waiters_ready(game):
        holders = night_action_holder_uids(game)
        done = set(game.mason_night_wait_ok_uids)
        for pl in game.players.values():
            if not pl.is_alive or pl.user_id in holders or pl.user_id in done:
                continue
            if _player_auto_satisfied_wait_ok(game, pl):
                continue
            game.mason_night_wait_ok_uids.append(pl.user_id)
            _ = _wait_ui_key(game, pl.user_id)


async def lock_mason_night_mirror_panels(bot: Bot, game: Game) -> None:
    from bot.observer_delivery import update_mirror_prompt_pair

    nc = max(1, game.bazpors_narrator_night_count)
    lockable_kinds = {
        "mason_saboteur",
        "mason_doctor",
        "mason_sniper",
        "mason_commander",
        "mason_gunner",
        "mason_guardian",
        "mason_recruit",
        "mason_detective",
        "mason_natasha",
        "mason_priest",
        "mason_night_wait",
        "night1_mafia",
        "nato",
        f"mafia_shot_n{nc}",
    }
    for key in list(game.mirror_prompt_messages):
        parts = key.split(":", 2)
        if len(parts) != 3:
            continue
        kind, room, uid_s = parts
        if room != game.room_code:
            continue
        if kind not in lockable_kinds and not kind.startswith("mafia_shot_n"):
            continue
        entry = game.mirror_prompt_messages.get(key, {})
        if not (entry.get("player") or entry.get("observer")):
            continue
        try:
            as_uid = int(uid_s)
        except ValueError:
            continue
        await update_mirror_prompt_pair(
            bot,
            game,
            key,
            MASON_NIGHT_PANEL_LOCKED_TEXT,
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )


async def force_finish_mason_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    try:
        from bot.mason_night_reminder import cleanup_mason_night_helper_reminder

        await cleanup_mason_night_helper_reminder(bot, game)
    except Exception:
        pass
    pending = pending_mason_force_finish_labels(game, gm)
    if pending:
        logger.info(
            "Force finishing Mason night room=%s night=%s. Pending: %s",
            game.room_code,
            game.bazpors_narrator_night_count,
            ", ".join(pending),
        )
    game.mason_night_force_finished = True
    normalize_pending_mason_night_actions(game, gm)
    await lock_mason_night_mirror_panels(bot, game)
    from bot.no_host_night_ready import finish_no_host_parallel_night_collect

    await finish_no_host_parallel_night_collect(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "mason.force_finish_night",
            night_count=game.bazpors_narrator_night_count,
            pending=pending,
        )
    except Exception:
        pass


async def reject_mason_night_callback_if_closed(
    callback: CallbackQuery, game: Game
) -> bool:
    if mason_night_player_actions_closed(game):
        await callback.answer(MASON_NIGHT_PHASE_ENDED_TEXT, show_alert=True)
        return True
    return False


async def handle_mason_force_finish_text(
    msg: Message, bot: Bot, user_id: int, gm: "GameManager | None" = None
) -> None:
    game = find_mason_bot_assistant_game(user_id, gm)
    if game is None:
        return
    if not mason_night_force_finish_collection_active(game):
        await msg.answer(MASON_FORCE_FINISH_NOT_NIGHT_TEXT)
        return
    await msg.answer(
        MASON_FORCE_FINISH_CONFIRM_TEXT,
        reply_markup=_force_finish_confirm_keyboard(game),
    )


async def handle_mason_force_finish_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    assistant_uid: int,
    act: str,
) -> None:
    if callback.message is None:
        return
    if not mason_night_force_finish_collection_active(game):
        await callback.answer(MASON_FORCE_FINISH_NOT_NIGHT_TEXT, show_alert=True)
        return
    if act == "no":
        await callback.answer()
        try:
            await callback.message.edit_text(MASON_FORCE_FINISH_CANCELLED_TEXT)
        except Exception:
            pass
        return
    if act != "yes":
        await callback.answer("نامعتبر.", show_alert=True)
        return
    await callback.answer("شب به پایان رسید.")
    try:
        await callback.message.edit_text(
            MASON_FORCE_FINISH_CONFIRM_TEXT + "\n\n✅ شب به پایان رسید."
        )
    except Exception:
        pass
    await force_finish_mason_night(bot, game, gm)
