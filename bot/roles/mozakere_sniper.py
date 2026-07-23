"""قوانین تک‌تیرانداز — فقط سناریوی مذاکره."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario


def is_mozakere_sniper(game: Game, player: Player) -> bool:
    return (
        is_mozakere_scenario(game)
        and player.is_alive
        and player.role == Role.SNIPER
    )


def mozakere_sniper_shot_limit(game: Game) -> int:
    """۱۰/۱۱ نفره: یک تیر؛ ۱۲/۱۳/۱۵ نفره: دو تیر."""
    n = game.max_players
    if n in (10, 11):
        return 1
    if n in (12, 13, 15):
        return 2
    return 1


def mozakere_sniper_shots_used(game: Game) -> int:
    return game.mozakere_sniper_shots_used


def mozakere_sniper_shots_remaining(game: Game) -> int:
    return max(0, mozakere_sniper_shot_limit(game) - mozakere_sniper_shots_used(game))


def mozakere_sniper_remaining_shots_panel_line(game: Game) -> str:
    limit = mozakere_sniper_shot_limit(game)
    remaining = mozakere_sniper_shots_remaining(game)
    return f"تعداد تیرهای باقی‌مانده شما: {remaining} از {limit}"


def can_mozakere_sniper_shoot(game: Game) -> bool:
    from bot.roles.sniper import find_alive_sniper

    return (
        find_alive_sniper(game) is not None
        and mozakere_sniper_shots_used(game) < mozakere_sniper_shot_limit(game)
    )


def mark_mozakere_sniper_shot_used(game: Game) -> None:
    if mozakere_sniper_shots_used(game) < mozakere_sniper_shot_limit(game):
        game.mozakere_sniper_shots_used += 1
