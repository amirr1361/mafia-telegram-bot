"""منطق زره‌پوش — فقط سناریوی مذاکره."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario

if TYPE_CHECKING:
    from bot.game import GameManager


def is_mozakere_armored(game: Game, player: Player) -> bool:
    return (
        is_mozakere_scenario(game)
        and player.is_alive
        and player.role == Role.ARMORED
    )


def find_alive_armored(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.ARMORED:
            return p
    return None


def mozakere_armored_armor_used(game: Game, player: Player) -> bool:
    if not is_mozakere_armored(game, player):
        return False
    return bool(player.mozakere_armored_armor_used)


def mozakere_armored_armor_active(game: Game, player: Player) -> bool:
    return is_mozakere_armored(game, player) and not player.mozakere_armored_armor_used


def consume_mozakere_armored_armor(game: Game, player: Player) -> None:
    if not is_mozakere_armored(game, player):
        return
    player.mozakere_armored_armor_used = True


def can_mozakere_negotiate_with_armored(game: Game, player: Player) -> bool:
    return mozakere_armored_armor_active(game, player)


def mafia_shot_blocked_by_armor(game: Game, target: Player) -> bool:
    """شات شب مافیا روی زره‌پوش با زره فعال نمی‌نشیند."""
    return mozakere_armored_armor_active(game, target)


def mozakere_day_elimination_blocked_by_armor(game: Game, target: Player) -> bool:
    """رأی روز — یک‌بار از حذف نجات می‌یابد اگر زره فعال باشد."""
    return mozakere_armored_armor_active(game, target)


def mafia_shot_armor_survival_note(game: Game, gm: "GameManager", uid: int) -> str:
    tag = html.escape(gm.format_player_tag(game.players[uid]))
    return (
        f"<b>شات روی زره‌پوش ({tag}) بود.</b> زره هنوز فعال است؛ "
        "این بازیکن از این شات از بازی خارج نمی‌شود."
    )


def mafia_shot_armor_survival_announce_line(game: Game, gm: "GameManager", uid: int) -> str:
    tag = gm.format_player_tag(game.players[uid])
    return (
        f"شات روی زره‌پوش ({tag})؛ زره فعال بود و او از شات شب مافیا خارج نشد."
    )


def try_survive_mozakere_day_vote_elimination(
    game: Game, gm: "GameManager", uid: int
) -> str | None:
    """اگر زره فعال است، مصرف زره و برگرداندن یادداشت؛ وگرنه None."""
    if not is_mozakere_scenario(game):
        return None
    pl = game.players.get(uid)
    if pl is None or not pl.is_alive:
        return None
    if not mozakere_day_elimination_blocked_by_armor(game, pl):
        return None
    consume_mozakere_armored_armor(game, pl)
    tag = html.escape(gm.format_player_tag(pl))
    return (
        f"<b>{tag}</b> (زره‌پوش) با رأی روز قرار بود خارج شود؛ "
        "زره مصرف شد و در بازی ماند."
    )


def day_vote_armor_consumed_announce_line(game: Game, gm: "GameManager", uid: int) -> str:
    tag = gm.format_player_tag(game.players[uid])
    return (
        f"🛡️ {tag} با نقش زره‌پوش در بازی می‌ماند؛ اما از این پس در برابر شات مافیا "
        "محافظت نمی‌شود و قابل مذاکره شدن هم نخواهد بود."
    )
