"""قوانین فرمانده — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario
from bot.roles.mason_sniper import (
    commit_mason_sniper_night_selection,
    find_alive_mason_sniper,
    mason_commander_approved_shot_uids,
    mason_sniper_bullets_remaining,
    mason_sniper_max_targets_this_night,
    mason_sniper_night_selected_uids,
    mason_sniper_shot_pool,
    mason_target_in_shot_pool,
)


def is_mason_commander(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.COMMANDER
    )


def find_alive_mason_commander(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_commander(game, p):
            return p
    return None


def mason_commander_inherits_sniper_shooting(game: Game) -> bool:
    """اگر اسنایپر زنده نیست، فرمانده مستقیماً شلیک می‌کند."""
    if not is_mason_scenario(game):
        return False
    if find_alive_mason_sniper(game) is not None:
        return False
    return find_alive_mason_commander(game) is not None


def mason_commander_bullets_remaining(game: Game) -> int:
    """فرمانده گلولهٔ مستقل ندارد — همان باقی‌ماندهٔ اسنایپر."""
    return mason_sniper_bullets_remaining(game)


def mason_commander_shot_pool(game: Game) -> list[Player]:
    if mason_commander_inherits_sniper_shooting(game):
        cmd = find_alive_mason_commander(game)
        return [
            p
            for p in game.players.values()
            if p.is_alive and (cmd is None or p.user_id != cmd.user_id)
        ]
    return mason_sniper_shot_pool(game)


def validate_mason_commander_approval(game: Game, approved_uids: list[int]) -> bool:
    """تأیید جزئی یا کامل — زیرمجموعهٔ انتخاب اسنایپر."""
    if not is_mason_scenario(game):
        return False
    if len(set(approved_uids)) != len(approved_uids):
        return False
    selected = set(mason_sniper_night_selected_uids(game))
    if not approved_uids:
        return True
    if not selected:
        return False
    if not set(approved_uids).issubset(selected):
        return False
    prev_count = len(game.mason_commander_night_approved_uids)
    new_count = len(approved_uids)
    if new_count - prev_count > mason_sniper_bullets_remaining(game):
        return False
    if new_count > len(selected):
        return False
    return all(mason_target_in_shot_pool(game, uid) for uid in approved_uids)


def validate_mason_commander_direct_selection(game: Game, target_uids: list[int]) -> bool:
    """وقتی اسنایپر نیست — انتخاب مستقیم فرمانده معادل انتخاب+تأیید است."""
    if not mason_commander_inherits_sniper_shooting(game):
        return False
    if len(target_uids) > mason_sniper_max_targets_this_night(game):
        return False
    pool_ids = {p.user_id for p in mason_commander_shot_pool(game)}
    if len(set(target_uids)) != len(target_uids):
        return False
    return all(uid in pool_ids for uid in target_uids)


def commit_mason_commander_approval(game: Game, approved_uids: list[int]) -> bool:
    """ثبت تأیید فرمانده و مصرف گلوله فقط برای اهداف تأییدشده."""
    if not validate_mason_commander_approval(game, approved_uids):
        return False
    prev_count = len(game.mason_commander_night_approved_uids)
    game.mason_commander_night_approved_uids = list(approved_uids)
    game.mason_sniper_bullets_spent += len(approved_uids) - prev_count
    return True


def add_mason_commander_approval(game: Game, target_uid: int) -> bool:
    """افزودن یک هدف به لیست تأیید — بدون انتخاب تکراری."""
    approved = list(mason_commander_approved_shot_uids(game))
    if target_uid in approved:
        return False
    approved.append(target_uid)
    return commit_mason_commander_approval(game, approved)


def commit_mason_commander_direct_shots(game: Game, target_uids: list[int]) -> bool:
    """فرمانده بدون اسنایپر — انتخاب مستقیم همان اهداف تأییدشده است."""
    if not validate_mason_commander_direct_selection(game, target_uids):
        return False
    if not commit_mason_sniper_night_selection(game, target_uids):
        return False
    prev_count = len(game.mason_commander_night_approved_uids)
    game.mason_commander_night_approved_uids = list(target_uids)
    game.mason_sniper_bullets_spent += len(target_uids) - prev_count
    return True


def add_mason_commander_direct_shot(game: Game, target_uid: int) -> bool:
    """افزودن یک هدف به انتخاب مستقیم فرمانده — بدون انتخاب تکراری."""
    selected = list(mason_sniper_night_selected_uids(game))
    if target_uid in selected:
        return False
    selected.append(target_uid)
    return commit_mason_sniper_night_selection(game, selected)


def finalize_mason_commander_direct_shots(game: Game) -> bool:
    """ثبت نهایی شلیک مستقیم فرمانده با اهداف انتخاب‌شده."""
    return commit_mason_commander_direct_shots(
        game, mason_sniper_night_selected_uids(game)
    )


def mason_commander_approval_pool(game: Game) -> list[Player]:
    """اهداف پیشنهادی اسنایپر که هنوز تأیید نشده‌اند."""
    approved = set(mason_commander_approved_shot_uids(game))
    return [
        game.players[u]
        for u in mason_sniper_night_selected_uids(game)
        if u in game.players and u not in approved
    ]


def mason_commander_can_add_approval(game: Game) -> bool:
    selected = mason_sniper_night_selected_uids(game)
    if not selected:
        return False
    approved = mason_commander_approved_shot_uids(game)
    if len(approved) >= len(selected):
        return False
    return mason_sniper_bullets_remaining(game) > 0


def mason_commander_direct_available_pool(game: Game) -> list[Player]:
    """اهداف قابل انتخاب برای شلیک مستقیم فرمانده."""
    selected = set(mason_sniper_night_selected_uids(game))
    return [
        p for p in mason_commander_shot_pool(game) if p.user_id not in selected
    ]


def mason_commander_can_add_direct_shot(game: Game) -> bool:
    if not mason_commander_inherits_sniper_shooting(game):
        return False
    return (
        len(mason_sniper_night_selected_uids(game))
        < mason_sniper_max_targets_this_night(game)
    )


def mason_commander_rejects_all_shots(game: Game) -> bool:
    """فرمانده هیچ شلیکی را تأیید نکرد — گلوله‌ای مصرف نمی‌شود."""
    return commit_mason_commander_approval(game, [])


def mason_commander_needs_no_pick_wait_panel(game: Game) -> bool:
    """فرمانده وقتی اسنایپر نیست و گلولهٔ باقی نمانده — فقط پیام انتظار."""
    return (
        mason_commander_inherits_sniper_shooting(game)
        and mason_sniper_bullets_remaining(game) <= 0
    )


def mason_commander_needs_sniper_no_shot_info_panel(game: Game) -> bool:
    """فرماندهٔ زنده وقتی اسنایپر هدفی ندارد — پیام اطلاع‌رسانی + اوکی."""
    if not is_mason_scenario(game):
        return False
    if find_alive_mason_commander(game) is None:
        return False
    if mason_commander_inherits_sniper_shooting(game):
        return False
    return not mason_sniper_night_selected_uids(game)


def auto_approve_sniper_shots_when_no_commander(game: Game) -> None:
    """بدون فرماندهٔ زنده — انتخاب‌های تأییدشدهٔ اسنایپر مستقیماً مصرف می‌شوند."""
    if not is_mason_scenario(game):
        return
    if find_alive_mason_commander(game) is not None:
        return
    if find_alive_mason_sniper(game) is None:
        return
    if mason_commander_approved_shot_uids(game):
        return
    selected = mason_sniper_night_selected_uids(game)
    if not selected:
        return
    remaining = mason_sniper_bullets_remaining(game)
    if remaining <= 0:
        return
    to_approve = selected[: min(len(selected), remaining)]
    commit_mason_commander_approval(game, to_approve)


def mason_unused_selected_targets_after_partial_approval(game: Game) -> list[int]:
    """اهداف انتخاب‌شدهٔ اسنایپر که فرمانده رد کرده — گلوله برمی‌گردد."""
    selected = set(mason_sniper_night_selected_uids(game))
    approved = set(mason_commander_approved_shot_uids(game))
    return sorted(selected - approved)


def reset_mason_role_counters_for_new_game(game: Game) -> None:
    """صفر کردن state ماسون هنگام پخش نقش."""
    game.mason_doctor_self_save_count = 0
    game.mason_night_baseline_doctor_self_saves = 0
    game.mason_night_pending_doctor_self_save = False
    game.mason_doctor_night_save_uids = []
    game.mason_sniper_bullets_spent = 0
    game.mason_sniper_night_selected_uids = []
    game.mason_commander_night_approved_uids = []
    game.mason_guardian_night_target_uid = None
    game.mason_guardian_day_protection_uid = None
    game.mason_apache_day_target_uid = None
    game.mason_apache_day_pick_confirmed = False
    game.mason_apache_day_action_used = False
    game.mason_cowboy_day_target_uid = None
    game.mason_cowboy_day_pick_confirmed = False
    game.mason_gunner_night_target_uid = None
    game.mason_gunner_night_no_give = False
    game.mason_saboteur_night_target_uid = None
    game.mason_saboteur_night_no_sabotage = False
    game.mason_day_gun_holder_uid = None
    game.mason_day_gun_sabotaged = False
    game.mason_day_gun_used = False
    game.mason_gun_spent = False
    game.mason_day_gun_shot_target_uid = None
    game.mason_team_member_ids = set()
    game.mason_pending_recruit_uid = None
    game.mason_mason_night_no_recruit = False
    game.mason_nato_used = False
    from bot.roles.mason_nato import clear_mason_nato_night_state
    from bot.roles.mason_natasha import clear_mason_natasha_night_state
    from bot.roles.mason_priest import clear_mason_priest_night_state

    clear_mason_nato_night_state(game)
    clear_mason_natasha_night_state(game)
    clear_mason_priest_night_state(game)
    game.mason_silenced_uid_for_day = None
    game.mason_intro_day_ability_open = False
    game.mason_intro_day_ability_locked = False
    game.mason_vote_start_prompt_sent = False
    game.mason_night_start_prompt_sent = False
    game.mason_night_start_pending_night = None
    game.mason_night_wait_ok_uids = []
    game.mason_night_doctor_confirmed = False
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
    game.mason_night_entry_dispatched_night = None
    game.mason_midday_step_prompt_sent = False
    game.mason_midday_step_done = False
    game.mason_night_resolution_applied = False
    game.mason_last_night_had_collapse = False
    game.mason_collapse_night_number = None
    game.mason_team_consultation_retired = False
    game.mason_mafia_consult_prompt_sent = False
    game.mason_mafia_consult_done = False
    game.mason_team_consult_prompt_sent = False
    game.mason_team_consult_done = False
    game.mason_apache_day_flow_active = False
    game.mason_cowboy_day_flow_active = False
    game.mason_apache_day_pending_uid = None
    game.mason_cowboy_day_pending_uid = None
