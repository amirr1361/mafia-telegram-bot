"""ورود به شب — پنل‌های نقش ماسون (no_host)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.bazpors_narrator import NIGHT_START
from bot.models import Game, Player, Role
from bot.no_host_night_common import (
    no_host_night_wait_phase_active,
    no_host_role_ack_keyboard,
    publish_no_host_night_ack_panel,
)
from bot.observer_delivery import (
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
)
from bot.room_mode import is_mason_scenario
from bot.roles.registry import find_alive_role_holder, get_role_module

if TYPE_CHECKING:
    from bot.game import GameManager

MASON_NIGHT_WAIT_ACT = "mok"
MASON_NIGHT_WAIT_TEXT = "منتظر اتمام شب باشید."


def reset_mason_current_night_selections(game: Game) -> None:
    """انتخاب‌های همین شب — بدون دست زدن به شمارنده‌های دائمی بازی."""
    from bot.roles import mason_doctor as ms_doc
    from bot.roles import mason_fraternity as ms_mf
    from bot.roles import mason_gunner as ms_gn
    from bot.roles import mason_guardian as ms_gd
    from bot.roles import mason_nato as ms_nato
    from bot.roles import mason_natasha as ms_nat
    from bot.roles import mason_priest as ms_pr
    from bot.roles import mason_saboteur as ms_sb
    from bot.roles import mason_sniper as ms_sn

    ms_doc.clear_mason_doctor_night_saves(game)
    ms_sn.clear_mason_sniper_night_state(game)
    ms_gd.clear_mason_guardian_night_pick(game)
    ms_gn.clear_mason_gunner_night_pick(game)
    ms_sb.clear_mason_saboteur_night_pick(game)
    ms_mf.clear_mason_recruit_night_state(game)
    ms_nat.clear_mason_natasha_night_state(game)
    ms_pr.clear_mason_priest_night_state(game)
    ms_nato.clear_mason_nato_night_state(game)


def reset_mason_night_panel_state(game: Game) -> None:
    reset_mason_current_night_selections(game)
    game.mason_night_wait_ok_uids = []
    game.mason_night_doctor_confirmed = False
    game.mason_night_doctor_nato_void_pending = False
    game.mason_night_detective_confirmed = False
    game.mason_night_sniper_confirmed = False
    game.mason_night_commander_confirmed = False
    game.mason_night_commander_panel_sent = False
    game.mason_night_guardian_confirmed = False
    game.mason_night_gunner_confirmed = False
    game.mason_night_saboteur_confirmed = False
    game.mason_night_mason_confirmed = False
    game.mason_night_natasha_confirmed = False
    game.mason_night_priest_confirmed = False
    game.mason_night_force_finished = False


def _role_has_night_action(game: Game, role: Role) -> bool:
    mod = get_role_module(role)
    if mod is None:
        return False
    return bool(getattr(mod, "HAS_NIGHT_ACTION", False))


def mason_night_action_roles_in_room(game: Game) -> set[Role]:
    roles: set[Role] = set()
    for p in game.players.values():
        if p.is_alive and p.role and _role_has_night_action(game, p.role):
            roles.add(p.role)
    if Role.GODFATHER in {p.role for p in game.players.values() if p.role}:
        roles.add(Role.GODFATHER)
    elif any(
        p.is_alive and p.role and p.role in (Role.SABOTEUR, Role.MAFIA_BASIC, Role.NATO)
        for p in game.players.values()
    ):
        pass
    return roles


def _alive_players_for_wait_panels(game: Game) -> list[Player]:
    """همهٔ زنده‌ها — شامل صندلی مصنوعی برای آینهٔ ناظر."""
    return [p for p in game.players.values() if p.is_alive]


def night_action_holder_uids(game: Game) -> set[int]:
    holders: set[int] = set()
    from bot.no_host_mafia_chooser import resolve_mafia_night1_panel_recipients

    for p in resolve_mafia_night1_panel_recipients(game):
        holders.add(p.user_id)
    action_roles = (
        Role.SABOTEUR,
        Role.DOCTOR,
        Role.SNIPER,
        Role.GUNMAN,
        Role.BODYGUARD,
        Role.MASON,
        Role.DETECTIVE,
        Role.NATASHA,
        Role.PRIEST,
    )
    for role in action_roles:
        pl = find_alive_role_holder(game, role)
        if pl is not None:
            if role == Role.GUNMAN and is_mason_scenario(game):
                from bot.roles import mason_gunner as ms_gn

                if not ms_gn.mason_gunner_can_give_gun(game):
                    continue
            if role == Role.SNIPER and is_mason_scenario(game):
                from bot.roles import mason_sniper as ms_sn

                if not ms_sn.mason_sniper_needs_night_pick(game):
                    continue
            holders.add(pl.user_id)
    cmd = find_alive_role_holder(game, Role.COMMANDER)
    sn = find_alive_role_holder(game, Role.SNIPER)
    if cmd is not None and sn is None and is_mason_scenario(game):
        from bot.roles import mason_commander as ms_cmd
        from bot.roles import mason_sniper as ms_sn

        if (
            ms_cmd.mason_commander_inherits_sniper_shooting(game)
            and ms_sn.mason_sniper_bullets_remaining(game) > 0
        ):
            holders.add(cmd.user_id)
    return holders


def _wait_ui_key(game: Game, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "mason_night_wait", uid)


async def _dispatch_mason_wait_panels(bot: Bot, game: Game) -> None:
    from bot.mason_night_ready import (
        _night_wait_ok_holder_uids,
        _player_auto_satisfied_wait_ok,
    )

    holders = _night_wait_ok_holder_uids(game)
    for pl in _alive_players_for_wait_panels(game):
        if pl.user_id in holders:
            continue
        if pl.user_id in game.mason_night_wait_ok_uids:
            continue
        if _player_auto_satisfied_wait_ok(game, pl):
            continue
        text = MASON_NIGHT_WAIT_TEXT
        kb = no_host_role_ack_keyboard(game, pl.user_id, MASON_NIGHT_WAIT_ACT)
        await register_mirror_prompt_pair(
            bot,
            game,
            pl.user_id,
            _wait_ui_key(game, pl.user_id),
            text,
            kb,
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )


async def dispatch_mason_night_entry_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not is_mason_scenario(game) or not no_host_night_wait_phase_active(game):
        return
    nc = game.bazpors_narrator_night_count
    if game.mason_night_entry_dispatched_night == nc:
        return
    from bot.game_state import no_host_night_state

    no_host_night_state(game).mafia_night1.reset()
    no_host_night_state(game).mafia_ops.reset()
    reset_mason_night_panel_state(game)
    from bot.roles import mason_gunner as ms_gn

    ms_gn.refresh_mason_day_gun_holder_if_eliminated(game)
    from bot.mason_night_resolve import reset_mason_night_resolution_state

    reset_mason_night_resolution_state(game)
    game.no_host_night_parallel_collect_active = True

    from bot.mason_night_role import (
        dispatch_mason_detective_panel,
        dispatch_mason_doctor_panel,
        dispatch_mason_gunner_panel,
        dispatch_mason_guardian_panel,
        dispatch_mason_mason_recruit_panel,
        dispatch_mason_natasha_panel,
        dispatch_mason_priest_panel,
        dispatch_mason_saboteur_panel,
        dispatch_mason_sniper_panel,
    )

    async def _mafia() -> None:
        from bot.no_host_mafia_night1 import start_no_host_night1_mafia_flow

        await start_no_host_night1_mafia_flow(bot, game, gm)

    results = await asyncio.gather(
        _mafia(),
        dispatch_mason_saboteur_panel(bot, game, gm),
        dispatch_mason_doctor_panel(bot, game, gm),
        dispatch_mason_sniper_panel(bot, game, gm),
        dispatch_mason_gunner_panel(bot, game, gm),
        dispatch_mason_guardian_panel(bot, game, gm),
        dispatch_mason_mason_recruit_panel(bot, game, gm),
        dispatch_mason_detective_panel(bot, game, gm),
        dispatch_mason_natasha_panel(bot, game, gm),
        dispatch_mason_priest_panel(bot, game, gm),
        _dispatch_mason_wait_panels(bot, game),
        return_exceptions=True,
    )
    dispatch_errors = [r for r in results if isinstance(r, BaseException)]
    if dispatch_errors:
        import logging

        log = logging.getLogger(__name__)
        for err in dispatch_errors:
            log.exception("mason night entry panel dispatch failed", exc_info=err)
        raise dispatch_errors[0]
    game.mason_night_entry_dispatched_night = nc
    from bot.mason_night_reminder import (
        cleanup_mason_night_helper_reminder,
        schedule_mason_night_helper_reminder,
    )

    await cleanup_mason_night_helper_reminder(bot, game)
    schedule_mason_night_helper_reminder(bot, game)


def mason_night_wait_act_active(game: Game, act: str) -> bool:
    return is_mason_scenario(game) and act == MASON_NIGHT_WAIT_ACT


async def dispatch_mason_night_wait_ok(
    callback,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    as_uid: int,
    actor_uid: int,
) -> None:
    from bot.no_host_role_pick_common import actor_may_act_on_role_panel
    from bot.mason_night_ready import maybe_finish_mason_parallel_night
    from bot.mason_night_role import MASON_NO_PICK_ALREADY_ACK_TEXT

    from bot.mason_force_finish_night import (
        MASON_NIGHT_PHASE_ENDED_TEXT,
        mason_night_player_actions_closed,
    )

    if mason_night_player_actions_closed(game):
        await callback.answer(MASON_NIGHT_PHASE_ENDED_TEXT, show_alert=True)
        return
    if not no_host_night_wait_phase_active(game):
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not actor_may_act_on_role_panel(game, actor_uid, as_uid):
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return
    if as_uid in game.mason_night_wait_ok_uids:
        await callback.answer(MASON_NO_PICK_ALREADY_ACK_TEXT, show_alert=True)
        return
    game.mason_night_wait_ok_uids.append(as_uid)
    await callback.answer("ثبت شد.")
    from bot.observer_delivery import update_mirror_prompt_pair

    await update_mirror_prompt_pair(
        bot,
        game,
        _wait_ui_key(game, as_uid),
        "✅ تأیید شما ثبت شد.\n\n⏳ لطفاً منتظر اتمام فاز شب بمانید.",
        None,
        assistant_uid=as_uid,
        parse_mode="HTML",
    )
    await maybe_finish_mason_parallel_night(bot, game, gm)
