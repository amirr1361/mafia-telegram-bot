"""گیت عملیات مافیا در شب مذاکره (تأیید شات/مذاکره)."""

from __future__ import annotations

from bot.models import Game
from bot.nam10.engine import is_mafia_team
from bot.nam10.mode import is_mozakere_scenario


def mozakere_mafia_night_action_finalized(game: Game) -> bool:
    """شات تأیید شده یا مذاکره commit شده."""
    if not is_mozakere_scenario(game):
        return True
    has_mafia = any(
        p.is_alive and p.role and is_mafia_team(p.role)
        for p in game.players.values()
    )
    if not has_mafia:
        return True
    if not game.nam10_mafia_night1_done:
        return False
    from bot.nam10.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE, MAFIA_ACTION_SHOT

    action = game.nam10_mafia_night1_chosen_action
    if action == MAFIA_ACTION_SHOT:
        return bool(
            game.nam10_mafia_shot_done or game.nmnd_mafia_shot_registered
        )
    if action == MAFIA_ACTION_NEGOTIATE:
        return game.nam10_negotiator_pick_confirmed
    return False
