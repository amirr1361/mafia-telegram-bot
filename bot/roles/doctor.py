"""منطق هستهٔ شب پزشک — مشترک semi_auto و no_host."""

from __future__ import annotations

from bot.game import bazpors_counts_as_mafia_faction
from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario
from bot.roles.mozakere_doctor import (
    MOZAKERE_MAX_SELF_SAVES,
    mozakere_doctor_save_capacity,
)
from bot.roles.night_state import doctor_night_state, yaku_night_state

MAX_SELF_SAVES = 2


def find_alive_doctor(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.DOCTOR:
            return p
    return None


def alive_players(game: Game) -> list[Player]:
    return [p for p in game.players.values() if p.is_alive]


def doctor_save_capacity(game: Game) -> int:
    """ظرفیت نجات در یک شب — بازپرس: ۱؛ مذاکره: بر اساس تعداد زنده."""
    if is_mozakere_scenario(game):
        return mozakere_doctor_save_capacity(game)
    return 1


def remaining_save_slots(game: Game) -> int:
    return max(0, doctor_save_capacity(game) - len(save_uid_set_raw(game)))


def can_add_doctor_save(game: Game) -> bool:
    return remaining_save_slots(game) > 0


def nato_yaku_rules_active(game: Game) -> bool:
    """قوانین باطل‌کردن نجات پزشک پس از ناتو/یاکوزا — semi_auto و no_host."""
    if game.scenario_name == "bazpors_salamat_test":
        return True
    if game.scenario_name != "bazpors":
        return False
    from bot.bazpors_narrator import no_host_assistant_narrator_active

    return game.bazpors_host_mode == "semi_auto" or no_host_assistant_narrator_active(
        game
    )


def self_save_pool_excludes_doctor(game: Game) -> bool:
    doc = find_alive_doctor(game)
    if not doc:
        return False
    state = doctor_night_state(game)
    if state.self_save_count >= MAX_SELF_SAVES:
        return True
    if state.pending_self_save:
        return True
    return False


def blocked_this_night(game: Game) -> bool:
    """پزشک پس از ناتویی یا یاکوزایی همان شب انتخاب ندارد."""
    return bool(
        game.bazpors_nato_action_registered
        or yaku_night_state(game).civilian_picked_this_night
    )


def skip_after_yaku_this_night(game: Game) -> bool:
    """پزشک در همان شبی که یاکوزایی (موفق یا ناموفق) انجام شده انتخاب ندارد."""
    return (
        nato_yaku_rules_active(game)
        and yaku_night_state(game).civilian_picked_this_night
    )


def night_pick_allowed(game: Game) -> bool:
    return not blocked_this_night(game)


def save_uid_set_raw(game: Game) -> set[int]:
    return doctor_night_state(game).save_uid_set_raw()


def save_uid_set(game: Game) -> set[int]:
    if nato_yaku_rules_active(game) and blocked_this_night(game):
        return set()
    return save_uid_set_raw(game)


def save_pool(game: Game) -> list[Player]:
    alive = alive_players(game)
    doc = find_alive_doctor(game)
    if doc and self_save_pool_excludes_doctor(game):
        return [p for p in alive if p.user_id != doc.user_id]
    return alive


def commit_pick(game: Game, target_uid: int | None) -> None:
    """ثبت انتخاب نجات (no_host confirm و منطق مشترک state)."""
    state = doctor_night_state(game)
    if target_uid is None:
        state.clear_save()
        return
    doc = find_alive_doctor(game)
    if doc and doc.user_id == target_uid and self_save_limit_reached(game):
        return
    had_self_pending = bool(
        state.pending_self_save
        and doc is not None
        and doc.user_id in state.save_uid_set_raw()
    )
    cap = doctor_save_capacity(game)
    if cap <= 1:
        state.set_save_target(target_uid)
    elif not state.add_save_target(target_uid):
        return
    if doc and doc.user_id == target_uid:
        state.mark_pending_self_save()
    elif had_self_pending:
        state.pending_self_save = True
    else:
        state.clear_pending_self_save()


def clear_pick(game: Game) -> None:
    doctor_night_state(game).clear_save()


def void_night_pick(game: Game) -> None:
    """انتخاب پزشک قبل از ناتو/یاکوزا را باطل کن؛ شمارندهٔ نجات خودی را برگردان."""
    if not nato_yaku_rules_active(game):
        return
    if not blocked_this_night(game):
        return
    doc = find_alive_doctor(game)
    state = doctor_night_state(game)
    saves = state.save_uid_set_raw()
    had_pending_self = state.pending_self_save
    was_self = had_pending_self or (doc is not None and doc.user_id in saves)
    state.clear_save()
    from bot.bazpors_narrator import no_host_assistant_narrator_active

    if no_host_assistant_narrator_active(game):
        state.clear_no_host_pending_save_uids()
    if was_self:
        state.rollback_self_save_count_to_baseline()


def commit_pending_self_save(game: Game) -> None:
    """ثبت قطعی نجات خودی پزشک — فقط پس از «اعمال پایان شب»."""
    state = doctor_night_state(game)
    if not state.pending_self_save:
        return
    if nato_yaku_rules_active(game) and blocked_this_night(game):
        state.clear_pending_self_save()
        return
    state.commit_pending_self_save()


def mafia_kill_blocked_by_doctor_save(game: Game, tgt_uid: int) -> bool:
    """نجات پزشک مانع اثر کشندهٔ شلیک اسنایپر روی مافیا غیر رئیس می‌شود."""
    if tgt_uid not in save_uid_set(game):
        return False
    tgt = game.players.get(tgt_uid)
    if tgt is None or not tgt.is_alive or tgt.role == Role.MAFIA_BOSS:
        return False
    return bazpors_counts_as_mafia_faction(game, tgt)


def self_save_limit_reached(game: Game) -> bool:
    limit = MOZAKERE_MAX_SELF_SAVES if is_mozakere_scenario(game) else MAX_SELF_SAVES
    return doctor_night_state(game).self_save_count >= limit


def can_register_self_save_this_night(game: Game) -> bool:
    return not doctor_night_state(game).pending_self_save
