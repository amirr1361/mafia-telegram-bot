"""قوانین پزشک — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

MASON_MAX_SELF_SAVES = 2
MASON_DOCTOR_NATO_VOID_TEXT = "به دلیل انجام ناتویی، امشب انتخابی ندارید."


def is_mason_doctor(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.DOCTOR
    )


def find_alive_mason_doctor(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_doctor(game, p):
            return p
    return None


def mason_alive_player_count(game: Game) -> int:
    return sum(1 for p in game.players.values() if p.is_alive)


def mason_doctor_save_capacity(game: Game) -> int:
    """ظرفیت نجات در یک شب بر اساس تعداد بازیکنان زنده."""
    from bot.roles.doctor_alive_save_capacity import (
        doctor_save_capacity_for_alive_count,
    )

    return doctor_save_capacity_for_alive_count(mason_alive_player_count(game))


def mason_doctor_self_saves_used(game: Game) -> int:
    return game.mason_doctor_self_save_count


def build_mason_doctor_self_save_usage_line(game: Game) -> str:
    from bot.game import _digits_fa

    used = mason_doctor_self_saves_used(game)
    return (
        f"🛡️ تعداد دفعات استفاده از نجات خود: "
        f"{_digits_fa(used)} از {_digits_fa(MASON_MAX_SELF_SAVES)}"
    )


def can_mason_doctor_self_save(game: Game) -> bool:
    return mason_doctor_self_saves_used(game) < MASON_MAX_SELF_SAVES


def mason_doctor_night_save_uids(game: Game) -> list[int]:
    return list(game.mason_doctor_night_save_uids)


def mason_doctor_remaining_save_slots(game: Game) -> int:
    return max(0, mason_doctor_save_capacity(game) - len(mason_doctor_night_save_uids(game)))


def can_add_mason_doctor_save(game: Game) -> bool:
    return mason_doctor_remaining_save_slots(game) > 0


def mason_doctor_save_pool(game: Game) -> list[Player]:
    alive = [p for p in game.players.values() if p.is_alive]
    saved = set(mason_doctor_night_save_uids(game))
    doc = find_alive_mason_doctor(game)
    if doc is None:
        return [p for p in alive if p.user_id not in saved]
    if not can_mason_doctor_self_save(game):
        return [
            p for p in alive if p.user_id != doc.user_id and p.user_id not in saved
        ]
    if game.mason_night_pending_doctor_self_save:
        return [
            p for p in alive if p.user_id != doc.user_id and p.user_id not in saved
        ]
    return [p for p in alive if p.user_id not in saved]


def mason_doctor_self_save_in_pool(game: Game, doc_uid: int) -> bool:
    return can_mason_doctor_self_save(game) and not game.mason_night_pending_doctor_self_save


def mason_target_valid_for_save(game: Game, target_uid: int) -> bool:
    p = game.players.get(target_uid)
    if p is None or not p.is_alive:
        return False
    doc = find_alive_mason_doctor(game)
    if doc and target_uid == doc.user_id:
        return mason_doctor_self_save_in_pool(game, doc.user_id)
    return any(pl.user_id == target_uid for pl in mason_doctor_save_pool(game))


def commit_mason_doctor_save(game: Game, target_uid: int) -> bool:
    """ثبت یک هدف نجات شبانه — بدون اعمال تا پایان شب."""
    if not is_mason_scenario(game):
        return False
    if not can_add_mason_doctor_save(game):
        return False
    if not mason_target_valid_for_save(game, target_uid):
        return False
    uids = mason_doctor_night_save_uids(game)
    if target_uid in uids:
        return True
    uids.append(target_uid)
    game.mason_doctor_night_save_uids = uids
    doc = find_alive_mason_doctor(game)
    if doc and target_uid == doc.user_id:
        game.mason_night_pending_doctor_self_save = True
    return True


def clear_mason_doctor_night_saves(game: Game) -> None:
    game.mason_doctor_night_save_uids = []
    game.mason_night_pending_doctor_self_save = False


def snapshot_mason_doctor_night_baseline(game: Game) -> None:
    game.mason_night_baseline_doctor_self_saves = game.mason_doctor_self_save_count
    game.mason_night_pending_doctor_self_save = False


def rollback_mason_doctor_self_save_to_baseline(game: Game) -> None:
    baseline = game.mason_night_baseline_doctor_self_saves
    if game.mason_doctor_self_save_count > baseline:
        game.mason_doctor_self_save_count = baseline


def void_mason_doctor_night_after_nato(game: Game) -> None:
    """ناتویی — پزشک گویی نکرده انتخابی ثبت کرده؛ نجات و مصرف نجات خودی امشب باطل."""
    if not is_mason_scenario(game):
        return
    clear_mason_doctor_night_saves(game)
    rollback_mason_doctor_self_save_to_baseline(game)
    game.mason_night_doctor_confirmed = False
    game.mason_night_doctor_nato_void_pending = True


def commit_mason_doctor_pending_self_save(game: Game) -> None:
    """ثبت قطعی نجات خودی پس از پایان شب."""
    if not game.mason_night_pending_doctor_self_save:
        return
    if can_mason_doctor_self_save(game):
        game.mason_doctor_self_save_count += 1
    game.mason_night_pending_doctor_self_save = False


def mason_mafia_shot_blocked_by_doctor_save(game: Game, tgt_uid: int) -> bool:
    """نجات پزشک فقط در برابر شات مافیا اثر دارد."""
    if not is_mason_scenario(game):
        return False
    return tgt_uid in mason_doctor_night_save_uids(game)


def mason_doctor_does_not_block_sniper(game: Game, tgt_uid: int) -> bool:
    """شلیک تأییدشدهٔ اسنایپر نجات پزشک را نادیده می‌گیرد."""
    if not is_mason_scenario(game):
        return False
    from bot.roles.mason_sniper import mason_commander_approved_shot_uids

    return tgt_uid in mason_commander_approved_shot_uids(game)
