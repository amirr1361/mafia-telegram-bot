"""رویین‌تن ماسون — مصونیت در برابر شلیک تک‌تیرانداز."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario


def is_mason_armored(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.RUINTAN
    )


def find_alive_mason_armored(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_armored(game, p):
            return p
    return None


def mason_armored_sniper_immune(game: Game, player: Player) -> bool:
    """شلیک تأییدشدهٔ اسنایپر روی رویین‌تن ماسون اثر ندارد."""
    return is_mason_armored(game, player)


def mason_armored_mafia_shot_immune(game: Game, player: Player) -> bool:
    """شات شب مافیا روی رویین‌تن ماسون اثر ندارد — نجات پزشک لازم نیست."""
    return is_mason_armored(game, player)
