"""منطق هستهٔ شب شیاد — مشترک semi_auto و no_host."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.models import Game, Player, Role
from bot.roles.detective import block_inquiry_by_shiad, find_alive_detective
from bot.roles.night_state import detective_night_state, shiad_night_state

if TYPE_CHECKING:
    from bot.game import GameManager


def find_alive_shiad(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.SHIAD:
            return p
    return None


def guess_pool(game: Game) -> list[Player]:
    """اهداف زندهٔ غیرمافیا — شیاد خودش در pool نیست."""
    from bot.bazpors_narrator import _alive, _visually_mafia

    sh = find_alive_shiad(game)
    return [
        p
        for p in _alive(game)
        if (not sh or p.user_id != sh.user_id) and not _visually_mafia(game, p)
    ]


def target_valid(game: Game, target_uid: int) -> bool:
    p = game.players.get(target_uid)
    if p is None or not p.is_alive:
        return False
    sh = find_alive_shiad(game)
    if sh and target_uid == sh.user_id:
        return False
    from bot.bazpors_narrator import _visually_mafia

    return not _visually_mafia(game, p)


def commit_pick(
    game: Game,
    target_uid: int,
    *,
    gm: "GameManager | None" = None,
    semi_auto: bool = False,
) -> bool:
    """ثبت هدف شیاد؛ True یعنی کارآگاه درست حدس زده شد."""
    shiad_night_state(game).target_uid = target_uid
    det = find_alive_detective(game)
    if det and target_uid == det.user_id:
        block_inquiry_by_shiad(game)
        return True
    detective_night_state(game).blocked = False
    tgt = game.players.get(target_uid)
    if tgt:
        if semi_auto and gm is not None:
            tag_plain = gm.format_player_tag(tgt)
            detective_night_state(game).last_answer = (
                f"هدف شیاد «{tag_plain}» است. به کارآگاه بگو استعلام را "
                "منفی (شهروندی) نشان بده."
            )
        else:
            detective_night_state(game).last_answer = (
                f"هدف شیاد «{tgt.full_name or target_uid}» است."
            )
    return False


def clear_pick(game: Game) -> None:
    shiad_night_state(game).clear_pick()


def committed_target_uid(game: Game) -> int | None:
    return shiad_night_state(game).target_uid
