"""قوانین کابوی — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = False
HAS_DAY_ACTION = True


def is_mason_cowboy(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.COWBOY
    )


def find_alive_mason_cowboy(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_cowboy(game, p):
            return p
    return None


def mason_cowboy_is_town(game: Game, player: Player) -> bool:
    return is_mason_cowboy(game, player)


def mason_cowboy_day_target_pool(game: Game) -> list[Player]:
    cowboy = find_alive_mason_cowboy(game)
    if cowboy is None:
        return []
    return [p for p in game.players.values() if p.is_alive and p.user_id != cowboy.user_id]


def mason_cowboy_day_target_valid(game: Game, target_uid: int) -> bool:
    return any(p.user_id == target_uid for p in mason_cowboy_day_target_pool(game))


def commit_mason_cowboy_day_pick(game: Game, target_uid: int, *, confirmed: bool) -> bool:
    if not is_mason_scenario(game):
        return False
    if find_alive_mason_cowboy(game) is None:
        return False
    if not mason_cowboy_day_target_valid(game, target_uid):
        return False
    game.mason_cowboy_day_target_uid = target_uid
    game.mason_cowboy_day_pick_confirmed = confirmed
    return True


def clear_mason_cowboy_day_pick(game: Game) -> None:
    game.mason_cowboy_day_target_uid = None
    game.mason_cowboy_day_pick_confirmed = False


def mason_cowboy_day_elimination_would_succeed(game: Game, target_uid: int) -> bool:
    """کابوی بدون بررسی فکشن — محافظ در برابر کابوی محافظت نمی‌کند."""
    if not is_mason_scenario(game):
        return False
    if not game.mason_cowboy_day_pick_confirmed:
        return False
    if game.mason_cowboy_day_target_uid != target_uid:
        return False
    return mason_cowboy_day_target_valid(game, target_uid)
