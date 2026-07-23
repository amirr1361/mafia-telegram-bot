"""قوانین محافظ (BODYGUARD) — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = True
HAS_DAY_ACTION = False
PROTECTS_ONLY_AGAINST_APACHE = True


def is_mason_guardian(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.BODYGUARD
    )


def find_alive_mason_guardian(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_guardian(game, p):
            return p
    return None


def is_mason_town_role(game: Game, player: Player) -> bool:
    from bot.game import is_mafia_team

    if not is_mason_scenario(game):
        return False
    return player.is_alive and not is_mafia_team(player.role)


def mason_guardian_needs_night_pick(game: Game) -> bool:
    """محافظ فقط وقتی باید هدف انتخاب کند که آپاچی زنده و هنوز از قابلیت روزانه‌اش استفاده نکرده باشد."""
    if not is_mason_scenario(game):
        return False
    if find_alive_mason_guardian(game) is None:
        return False
    from bot.roles.mason_apache import find_alive_mason_apache

    if find_alive_mason_apache(game) is None:
        return False
    return not game.mason_apache_day_action_used


def mason_guardian_night_target_pool(game: Game) -> list[Player]:
    guardian = find_alive_mason_guardian(game)
    if guardian is None:
        return []
    return [
        p
        for p in game.players.values()
        if p.is_alive and p.user_id != guardian.user_id
    ]


def mason_guardian_night_target_valid(game: Game, target_uid: int) -> bool:
    return any(p.user_id == target_uid for p in mason_guardian_night_target_pool(game))


def commit_mason_guardian_night_pick(game: Game, target_uid: int) -> bool:
    """انتخاب شبانه — دقیقاً یک هدف غیر از خود."""
    if not is_mason_scenario(game):
        return False
    if not mason_guardian_needs_night_pick(game):
        return False
    if find_alive_mason_guardian(game) is None:
        return False
    if not mason_guardian_night_target_valid(game, target_uid):
        return False
    game.mason_guardian_night_target_uid = target_uid
    return True


def guardian_current_target(game: Game) -> int | None:
    """محافظت فعال روز جاری (از انتخاب شب قبل)."""
    if not is_mason_scenario(game):
        return None
    return game.mason_guardian_day_protection_uid


def guardian_blocks_apache(game: Game, target_uid: int) -> bool:
    """محافظت فقط در برابر حذف روزانهٔ آپاچی.

    محافظ همیشه در برابر آپاچی محافظت‌شده تلقی می‌شود؛ اگر آپاچی خودِ محافظ را
    هدف بگیرد، دقیقاً همان مسیر محافظت شب قبل اجرا می‌شود.
    """
    if not is_mason_scenario(game):
        return False
    guardian = find_alive_mason_guardian(game)
    if guardian is not None and guardian.user_id == target_uid:
        return True
    protected = guardian_current_target(game)
    return protected is not None and protected == target_uid


def activate_mason_guardian_day_protection(game: Game) -> None:
    """شروع روز — انتخاب شب قبل فعال می‌شود."""
    if not is_mason_scenario(game):
        return
    game.mason_guardian_day_protection_uid = game.mason_guardian_night_target_uid


def clear_mason_guardian_day_protection(game: Game) -> None:
    """پایان روز — محافظت منقضی می‌شود."""
    game.mason_guardian_day_protection_uid = None


def clear_mason_guardian_night_pick(game: Game) -> None:
    game.mason_guardian_night_target_uid = None
