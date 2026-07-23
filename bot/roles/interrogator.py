"""منطق هستهٔ بازپرس — مشترک semi_auto و no_host."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.roles.night_state import interrogator_night_state


def find_alive_interrogator(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.INTERROGATOR:
            return p
    return None


def is_interrogator_role(role: Role | None) -> bool:
    return role == Role.INTERROGATOR


def is_interrogator(player: Player) -> bool:
    return is_interrogator_role(player.role)


def ability_used(game: Game) -> bool:
    return interrogator_night_state(game).once_done


def mark_ability_used(game: Game) -> None:
    """یک‌بار در بازی بازپرسی روز انجام/تصمیم شد (ادامه یا انحلال)."""
    interrogator_night_state(game).once_done = True


def first_nominee_uid(game: Game) -> int | None:
    return interrogator_night_state(game).first_uid


def second_nominee_uid(game: Game) -> int | None:
    return interrogator_night_state(game).second_uid


def pending_pick_uid(game: Game) -> int | None:
    return interrogator_night_state(game).pick_uid


def night_finished(game: Game) -> bool:
    return interrogator_night_state(game).night_finished


def ready_for_day(game: Game) -> bool:
    return interrogator_night_state(game).ready_for_day


def cancel_next_day(game: Game) -> bool:
    return interrogator_night_state(game).cancel_next_day


def int1_pool(game: Game) -> list[Player]:
    return [p for p in game.players.values() if p.is_alive]


def int2_pool(game: Game) -> list[Player]:
    state = interrogator_night_state(game)
    fu = state.pick_uid or state.first_uid
    return [p for p in game.players.values() if p.is_alive and p.user_id != fu]


def first_target_valid(game: Game, target_uid: int) -> bool:
    p = game.players.get(target_uid)
    return p is not None and p.is_alive


def second_target_valid(game: Game, target_uid: int) -> bool:
    state = interrogator_night_state(game)
    fu = state.pick_uid or state.first_uid
    if target_uid == fu:
        return False
    return first_target_valid(game, target_uid)


def commit_first_nominee(game: Game, target_uid: int) -> None:
    interrogator_night_state(game).commit_first_nominee(target_uid)


def commit_second_nominee(game: Game, target_uid: int) -> None:
    interrogator_night_state(game).commit_second_nominee(target_uid)


def clear_night_pick(game: Game) -> None:
    interrogator_night_state(game).clear_night_pick()


def nominees_both_alive(game: Game) -> bool:
    state = interrogator_night_state(game)
    for uid in (state.first_uid, state.second_uid):
        if uid is None or uid not in game.players:
            return False
        if not game.players[uid].is_alive:
            return False
    return (
        state.first_uid is not None
        and state.second_uid is not None
    )


def nominees_died_uids(
    game: Game, alive_before: dict[int, bool] | None = None
) -> list[int]:
    """نامزدهای بازپرسی که از شروع شب زنده بودند و الان مرده‌اند."""
    snap = alive_before if alive_before is not None else game.bazpors_alive_at_night_start
    out: list[int] = []
    state = interrogator_night_state(game)
    for uid in (state.first_uid, state.second_uid):
        if uid is None or uid not in game.players:
            continue
        p = game.players[uid]
        if snap is not None:
            if snap.get(uid, True) and not p.is_alive:
                out.append(uid)
        elif not p.is_alive:
            out.append(uid)
    return out


def sync_day_state(game: Game) -> None:
    """اگر هر نامزد بازپرسی در همین شب (یا قبل از شروع روز) مرده باشد، بازپرسی منتفی می‌شود."""
    state = interrogator_night_state(game)
    if not state.night_finished:
        return
    if state.first_uid is None or state.second_uid is None:
        return
    if nominees_died_uids(game) or not nominees_both_alive(game):
        state.cancel_next_day = True
        state.ready_for_day = False


def refresh_ready_for_day(game: Game) -> None:
    """نامزدهای شب قبل زنده باشند؛ مرگ خود بازپرس مانع بازپرسی روز نیست."""
    sync_day_state(game)
    state = interrogator_night_state(game)
    state.ready_for_day = bool(
        state.night_finished
        and not state.cancel_next_day
        and nominees_both_alive(game)
    )


def apply_cancel_if_nominee_died(
    game: Game, alive_before: dict[int, bool] | None = None
) -> None:
    sync_day_state(game)


def day_vote_pool(game: Game) -> list[Player]:
    """نامزدهای زندهٔ بازپرسی برای ثبت خروج با رأی همان جلسه."""
    out: list[Player] = []
    state = interrogator_night_state(game)
    for uid in (state.first_uid, state.second_uid):
        if uid is None or uid not in game.players:
            continue
        p = game.players[uid]
        if p.is_alive:
            out.append(p)
    return out


def clear_day_targets(game: Game) -> None:
    interrogator_night_state(game).clear_day_targets()
