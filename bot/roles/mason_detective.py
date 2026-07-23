"""کارآگاه — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario
from bot.roles.detective import (
    DetectiveInquiryKind,
    DetectiveInquiryResult,
    find_alive_detective,
)


def is_mason_detective(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.DETECTIVE
    )


def mason_detective_investigation_pool(game: Game) -> list[Player]:
    """همهٔ بازیکنان زنده به‌جز خود کارآگاه."""
    det = find_alive_detective(game)
    if det is None:
        return []
    return [
        p
        for p in game.players.values()
        if p.is_alive and p.user_id != det.user_id
    ]


def mason_detective_panel_button_names(game: Game) -> list[str]:
    return [
        p.full_name or str(p.user_id)
        for p in mason_detective_investigation_pool(game)
    ]


def mason_reads_negative_for_detective(game: Game, target: Player) -> bool:
    """گادفادر برای کارآگاه ماسون همیشه منفی است."""
    if not is_mason_scenario(game):
        return False
    return target.role == Role.GODFATHER


def mason_detective_reads_positive(game: Game, target: Player) -> bool:
    """مافیا به‌جز گادفادر — مثبت."""
    if not is_mason_scenario(game):
        return False
    if mason_reads_negative_for_detective(game, target):
        return False
    return is_mafia_team(target.role)


def evaluate_mason_detective_inquiry(
    game: Game, target_uid: int
) -> DetectiveInquiryResult:
    tgt = game.players.get(target_uid)
    if tgt is None:
        raise ValueError(f"mason detective inquiry target {target_uid} not in game")
    if mason_reads_negative_for_detective(game, tgt):
        return DetectiveInquiryResult(
            DetectiveInquiryKind.NEGATIVE_BOSS, target_uid
        )
    if mason_detective_reads_positive(game, tgt):
        return DetectiveInquiryResult(DetectiveInquiryKind.POSITIVE, target_uid)
    return DetectiveInquiryResult(DetectiveInquiryKind.NEGATIVE_TOWN, target_uid)
