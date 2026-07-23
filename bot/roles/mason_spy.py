"""قوانین جاسوس — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = False
HAS_DAY_ACTION = False


def is_mason_spy(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.SPY
    )


def find_alive_mason_spy(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_spy(game, p):
            return p
    return None


def mason_spy_is_mafia(game: Game, player: Player) -> bool:
    return is_mason_spy(game, player) and is_mafia_team(player.role)
