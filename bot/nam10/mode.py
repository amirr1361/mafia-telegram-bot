"""Fork room-mode gates — bot.nam10 non-shared identity helpers."""

from __future__ import annotations

from bot.models import Game
from bot.room_mode import (
    is_mason_scenario,  # noqa: F401  (shared-neutral)
    is_mozakere_scenario,  # noqa: F401  (shared-neutral)
    mozakere_no_host_uses_parallel_night_ui,  # noqa: F401
    is_no_host_player_room as _shared_is_no_host_player_room,
)


def is_nam10_fork_room(game: Game) -> bool:
    """Namayande 10-player fork identity (independent of Bazpors)."""
    return (
        game.scenario_name == "namayande"
        and game.nmnd_host_mode == "no_host"
    )


def is_no_host_player_room(game: Game) -> bool:
    if is_nam10_fork_room(game):
        return True
    return _shared_is_no_host_player_room(game)
