"""قوانین پزشک — فقط سناریوی مذاکره."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario

MOZAKERE_MAX_SELF_SAVES = 2


def is_mozakere_doctor(game: Game, player: Player) -> bool:
    return (
        is_mozakere_scenario(game)
        and player.is_alive
        and player.role == Role.DOCTOR
    )


def mozakere_alive_player_count(game: Game) -> int:
    return sum(1 for p in game.players.values() if p.is_alive)


def mozakere_doctor_save_capacity(game: Game) -> int:
    """ظرفیت نجات در یک شب بر اساس تعداد بازیکنان زنده."""
    from bot.roles.doctor_alive_save_capacity import (
        doctor_save_capacity_for_alive_count,
    )

    return doctor_save_capacity_for_alive_count(mozakere_alive_player_count(game))


def mozakere_doctor_self_saves_used(game: Game) -> int:
    return game.mozakere_doctor_self_save_count


def can_mozakere_doctor_self_save(game: Game) -> bool:
    return mozakere_doctor_self_saves_used(game) < MOZAKERE_MAX_SELF_SAVES


def mark_mozakere_doctor_self_save_used(game: Game) -> None:
    """پس از اعمال قطعی نجات خودی در پایان شب."""
    if can_mozakere_doctor_self_save(game):
        game.mozakere_doctor_self_save_count += 1
