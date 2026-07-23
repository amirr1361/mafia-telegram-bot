"""قوانین ناتاشا — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = True
HAS_DAY_ACTION = False
HAS_KILL = False


def is_mason_natasha(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.NATASHA
    )


def find_alive_mason_natasha(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_natasha(game, p):
            return p
    return None


def mason_natasha_is_mafia(game: Game, player: Player) -> bool:
    return is_mason_natasha(game, player) and is_mafia_team(player.role)


def mason_natasha_night_target_pool(game: Game) -> list[Player]:
    if find_alive_mason_natasha(game) is None:
        return []
    return [p for p in game.players.values() if p.is_alive]


def mason_natasha_can_target(game: Game, natasha: Player, target: Player) -> bool:
    if not is_mason_natasha(game, natasha):
        return False
    if not target.is_alive:
        return False
    return any(p.user_id == target.user_id for p in mason_natasha_night_target_pool(game))


def commit_mason_natasha_target(
    game: Game, natasha: Player, target: Player, *, confirmed: bool = False
) -> bool:
    if not mason_natasha_can_target(game, natasha, target):
        return False
    game.mason_natasha_target_uid = target.user_id
    game.mason_natasha_pick_confirmed = confirmed
    return True


def _player_display_name(player: Player) -> str:
    return player.full_name or str(player.user_id)


def mason_natasha_silence_public_message(target: Player) -> str:
    name = _player_display_name(target)
    return f"{name} امروز حق صحبت کردن ندارد و فقط در انتهای روز می‌تواند رای بدهد."


def mason_player_silenced_today(game: Game, player: Player) -> bool:
    if not is_mason_scenario(game):
        return False
    silenced_uid = game.mason_silenced_uid_for_day
    return (
        silenced_uid is not None
        and silenced_uid == player.user_id
        and player.is_alive
    )


def clear_mason_silenced_for_day(game: Game) -> None:
    game.mason_silenced_uid_for_day = None


def resolve_mason_natasha_day_effect(game: Game) -> str | None:
    """شروع روز — سکوت هدف ناتاشا مگر اینکه کشیش همان بازیکن را انتخاب کرده باشد."""
    if not is_mason_scenario(game):
        return None
    from bot.roles.mason_priest import mason_priest_blocks_natasha

    nat_uid = game.mason_natasha_target_uid
    if nat_uid is None or not game.mason_natasha_pick_confirmed:
        return None
    target = game.players.get(nat_uid)
    if target is None or not target.is_alive:
        return None
    if mason_priest_blocks_natasha(game):
        clear_mason_silenced_for_day(game)
        return None
    game.mason_silenced_uid_for_day = nat_uid
    return mason_natasha_silence_public_message(target)


def clear_mason_natasha_night_pick(game: Game) -> None:
    game.mason_natasha_target_uid = None
    game.mason_natasha_pick_confirmed = False


def clear_mason_natasha_night_state(game: Game) -> None:
    clear_mason_natasha_night_pick(game)
