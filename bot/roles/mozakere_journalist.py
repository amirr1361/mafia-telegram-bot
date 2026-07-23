"""منطق خبرنگار — فقط سناریوی مذاکره."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario
from bot.roles.mozakere_negotiator import negotiation_used
from bot.roles.night_state import mozakere_journalist_night_state


class MozakereJournalistCheckKind(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


@dataclass(frozen=True)
class MozakereJournalistCheckResult:
    kind: MozakereJournalistCheckKind
    target_uid: int

    @property
    def is_positive(self) -> bool:
        return self.kind == MozakereJournalistCheckKind.POSITIVE

    def label_fa(self) -> str:
        return "مثبت" if self.is_positive else "منفی"

    def detail_fa(self) -> str:
        if self.is_positive:
            return "✅ این بازیکن با مذاکره به تیم مافیا پیوسته است."
        return "❌ این بازیکن با مذاکره به تیم مافیا نپیوسته است."

    def private_line_fa(self, target_name_html: str) -> str:
        return f"استعلام شما از {target_name_html} {self.label_fa()} است."


def find_alive_journalist(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.JOURNALIST:
            return p
    return None


def is_mozakere_journalist(game: Game, player: Player) -> bool:
    return (
        is_mozakere_scenario(game)
        and player.is_alive
        and player.role == Role.JOURNALIST
    )


def mozakere_journalist_active(game: Game) -> bool:
    """خبرنگار فقط پس از انجام مذاکره در بازی فعال می‌شود."""
    if not is_mozakere_scenario(game):
        return False
    return negotiation_used(game)


def investigation_pool(game: Game) -> list[Player]:
    """همهٔ بازیکنان زنده — به‌جز خود خبرنگار."""
    j = find_alive_journalist(game)
    return sorted(
        (
            p
            for p in game.players.values()
            if p.is_alive and (not j or p.user_id != j.user_id)
        ),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def target_joined_mafia_by_negotiation(game: Game, target: Player) -> bool:
    """آیا target با مذاکره به تیم مافیا پیوسته است؟"""
    if not is_mozakere_scenario(game):
        return False
    return target.user_id in game.mozakere_mafia_recruit_ids


def evaluate_check(game: Game, target_uid: int) -> MozakereJournalistCheckResult:
    tgt = game.players.get(target_uid)
    if tgt is None:
        raise ValueError(f"journalist check target {target_uid} not in game")
    if target_joined_mafia_by_negotiation(game, tgt):
        return MozakereJournalistCheckResult(
            MozakereJournalistCheckKind.POSITIVE,
            target_uid,
        )
    return MozakereJournalistCheckResult(
        MozakereJournalistCheckKind.NEGATIVE,
        target_uid,
    )


def commit_check(game: Game, target_uid: int) -> MozakereJournalistCheckResult:
    result = evaluate_check(game, target_uid)
    state = mozakere_journalist_night_state(game)
    state.target_uid = target_uid
    state.ack_positive = result.is_positive
    return result


def load_result(game: Game) -> MozakereJournalistCheckResult | None:
    state = mozakere_journalist_night_state(game)
    if state.target_uid is None:
        return None
    if state.ack_positive:
        return MozakereJournalistCheckResult(
            MozakereJournalistCheckKind.POSITIVE,
            state.target_uid,
        )
    return MozakereJournalistCheckResult(
        MozakereJournalistCheckKind.NEGATIVE,
        state.target_uid,
    )
