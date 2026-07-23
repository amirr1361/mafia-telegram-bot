"""قوانین کشیش — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = True
HAS_DAY_ACTION = False
BLOCKS_ONLY_NATASHA_SILENCE = True


def is_mason_priest(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.PRIEST
    )


def find_alive_mason_priest(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_priest(game, p):
            return p
    return None


def mason_priest_is_town(game: Game, player: Player) -> bool:
    return is_mason_priest(game, player) and not is_mafia_team(player.role)


def mason_priest_night_target_pool(game: Game) -> list[Player]:
    if find_alive_mason_priest(game) is None:
        return []
    return [p for p in game.players.values() if p.is_alive]


def mason_priest_can_target(game: Game, priest: Player, target: Player) -> bool:
    if not is_mason_priest(game, priest):
        return False
    if not target.is_alive:
        return False
    return any(p.user_id == target.user_id for p in mason_priest_night_target_pool(game))


def commit_mason_priest_target(
    game: Game, priest: Player, target: Player, *, confirmed: bool = False
) -> bool:
    if not mason_priest_can_target(game, priest, target):
        return False
    game.mason_priest_target_uid = target.user_id
    game.mason_priest_pick_confirmed = confirmed
    return True


def mason_priest_blocks_natasha(game: Game) -> bool:
    """کشیش فقط اثر سکوت ناتاشا را خنثی می‌کند."""
    if not is_mason_scenario(game):
        return False
    nat_uid = game.mason_natasha_target_uid
    priest_uid = game.mason_priest_target_uid
    if nat_uid is None or priest_uid is None:
        return False
    if not game.mason_natasha_pick_confirmed or not game.mason_priest_pick_confirmed:
        return False
    return nat_uid == priest_uid


def mason_priest_blocks_natasha_report(game: Game) -> bool:
    """خنثی‌سازی ناتاشا در گزارش پایان شب (اسنپ‌شات)."""
    if not is_mason_scenario(game):
        return False
    nat_uid = game.mason_night_report_natasha_target_uid
    priest_uid = game.mason_night_report_priest_target_uid
    if nat_uid is None or priest_uid is None:
        return False
    if not game.mason_night_report_natasha_pick_confirmed:
        return False
    if not game.mason_night_report_priest_pick_confirmed:
        return False
    return nat_uid == priest_uid


def clear_mason_priest_night_pick(game: Game) -> None:
    game.mason_priest_target_uid = None
    game.mason_priest_pick_confirmed = False


def clear_mason_priest_night_state(game: Game) -> None:
    clear_mason_priest_night_pick(game)
