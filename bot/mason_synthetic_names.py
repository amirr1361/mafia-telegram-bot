"""نام نمایشی بازیکنان ساختگی ماسون — فقط تست/دیباگ."""

from __future__ import annotations

from bot.game import (
    is_synthetic_player_uid,
    scenario_role_label_fa,
    synthetic_player_base_name,
)
from bot.models import Game
from bot.room_mode import is_mason_scenario

MASON_SYNTHETIC_NAME_SEP = " - "


def append_mason_role_labels_to_synthetic_players(game: Game) -> None:
    """پس از پخش نقش: «امیر - آپاچی» فقط برای بازیکن ساختگی ماسون."""
    if not is_mason_scenario(game):
        return
    for p in game.players.values():
        if not is_synthetic_player_uid(p.user_id) or p.role is None:
            continue
        base = synthetic_player_base_name(p.full_name)
        role_txt = scenario_role_label_fa(game, p.role)
        p.full_name = f"{base}{MASON_SYNTHETIC_NAME_SEP}{role_txt}"
