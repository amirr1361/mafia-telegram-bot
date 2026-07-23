"""منطق مذاکره‌کننده — فقط سناریوی مذاکره."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario
from bot.roles.night_state import mozakere_negotiation_night_state

VALID_NEGOTIATION_TARGET_ROLES: frozenset[Role] = frozenset(
    {Role.CITIZEN, Role.ARMORED}
)

ORIGINAL_MOZAKERE_MAFIA_ROLES: frozenset[Role] = frozenset(
    {
        Role.MAFIA_BOSS,
        Role.MAFIA_NEGOTIATOR,
        Role.MAFIA_SIMPLE,
        Role.MAFIA_SIMPLE_2,
    }
)


class MozakereNegotiationOutcome(str, Enum):
    SUCCESS = "success"
    INVALID_TARGET = "invalid_target"
    NOT_ALLOWED = "not_allowed"


@dataclass(frozen=True)
class MozakereNegotiationResult:
    outcome: MozakereNegotiationOutcome
    target_uid: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome == MozakereNegotiationOutcome.SUCCESS


def find_alive_negotiator(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.MAFIA_NEGOTIATOR:
            return p
    return None


def is_mozakere_negotiator(game: Game, player: Player) -> bool:
    return (
        is_mozakere_scenario(game)
        and player.is_alive
        and player.role == Role.MAFIA_NEGOTIATOR
    )


def required_eliminated_mafia_count(game: Game) -> int:
    """حداقل تعداد مافیاهای خارج‌شده برای فعال شدن مذاکره."""
    n = game.max_players
    if n in (10, 11):
        return 1
    if n in (12, 13, 15):
        return 2
    return 2


def original_mozakere_mafia_uids(game: Game) -> set[int]:
    """شناسهٔ مافیاهای اصلی اولیه — بدون جذب‌شدگان مذاکره."""
    if not is_mozakere_scenario(game):
        return set()
    from_ids = game.mafia_ids - game.mozakere_mafia_recruit_ids
    if from_ids:
        return from_ids
    out: set[int] = set()
    for p in game.players.values():
        if p.user_id in game.mozakere_mafia_recruit_ids:
            continue
        role = p.mozakere_original_role or p.role
        if role in ORIGINAL_MOZAKERE_MAFIA_ROLES:
            out.add(p.user_id)
    return out


def eliminated_mafia_teammate_count(game: Game) -> int:
    """اعضای اصلی تیم مافیا که از بازی خارج شده‌اند (بدون پیوستگان مذاکره)."""
    if not is_mozakere_scenario(game):
        return 0
    original = original_mozakere_mafia_uids(game)
    return sum(
        1
        for uid in original
        if uid in game.players and not game.players[uid].is_alive
    )


def mafia_elimination_threshold_met(game: Game) -> bool:
    return (
        eliminated_mafia_teammate_count(game)
        >= required_eliminated_mafia_count(game)
    )


def negotiation_used(game: Game) -> bool:
    return mozakere_negotiation_night_state(game).used


def mafia_used_negotiation_tonight(game: Game) -> bool:
    return mozakere_negotiation_night_state(game).tonight


def can_mozakere_negotiate(game: Game, player: Player) -> bool:
    if not is_mozakere_negotiator(game, player):
        return False
    if negotiation_used(game):
        return False
    return mafia_elimination_threshold_met(game)


def negotiation_allowed(game: Game) -> bool:
    """آیا تیم مافیا هنوز می‌تواند (یک‌بار) مذاکره را انتخاب کند؟"""
    neg = find_alive_negotiator(game)
    if neg is None:
        return False
    return can_mozakere_negotiate(game, neg)


def is_valid_mozakere_negotiation_target(game: Game, target: Player) -> bool:
    if not is_mozakere_scenario(game):
        return False
    if not target.is_alive:
        return False
    if target.user_id in game.mozakere_mafia_recruit_ids:
        return False
    if target.role is None:
        return False
    if target.role == Role.ARMORED:
        from bot.roles.mozakere_armored import can_mozakere_negotiate_with_armored

        return can_mozakere_negotiate_with_armored(game, target)
    return target.role in VALID_NEGOTIATION_TARGET_ROLES


def negotiation_panel_target_pool(game: Game) -> list[Player]:
    """همهٔ زنده‌های غیرمافیا برای دکمه‌های پنل — نه فقط هدف‌های قابل جذب."""
    if not is_mozakere_scenario(game):
        return []
    from bot.game import bazpors_counts_as_mafia_faction

    return sorted(
        (
            p
            for p in game.players.values()
            if p.is_alive and not bazpors_counts_as_mafia_faction(game, p)
        ),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def negotiation_target_pool(game: Game) -> list[Player]:
    """هدف‌های قابل جذب — فقط برای commit / اعتبارسنجی نتیجه."""
    return sorted(
        (
            p
            for p in game.players.values()
            if is_valid_mozakere_negotiation_target(game, p)
        ),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def apply_mozakere_negotiation_recruit(game: Game, target: Player) -> None:
    """پیوستن موفق هدف به تیم مافیا."""
    if not is_mozakere_scenario(game):
        return
    if target.mozakere_original_role is None:
        target.mozakere_original_role = target.role
    target.mozakere_converted_by_negotiation = True
    target.role = Role.MAFIA_SIMPLE
    game.mozakere_mafia_recruit_ids.add(target.user_id)
    game.mafia_ids.add(target.user_id)


def mark_mozakere_negotiation_used(game: Game) -> None:
    state = mozakere_negotiation_night_state(game)
    state.used = True
    state.tonight = True


def commit_mozakere_negotiation(
    game: Game,
    negotiator: Player,
    target: Player,
) -> MozakereNegotiationResult:
    """ثبت مذاکره — همیشه شلیک همان شب را می‌بندد؛ تبدیل فقط روی هدف مجاز."""
    if not can_mozakere_negotiate(game, negotiator):
        return MozakereNegotiationResult(
            MozakereNegotiationOutcome.NOT_ALLOWED,
            target_uid=target.user_id,
        )
    state = mozakere_negotiation_night_state(game)
    mark_mozakere_negotiation_used(game)
    state.target_uid = target.user_id
    if not is_valid_mozakere_negotiation_target(game, target):
        state.night_success = False
        return MozakereNegotiationResult(
            MozakereNegotiationOutcome.INVALID_TARGET,
            target_uid=target.user_id,
        )
    apply_mozakere_negotiation_recruit(game, target)
    state.night_success = True
    return MozakereNegotiationResult(
        MozakereNegotiationOutcome.SUCCESS,
        target_uid=target.user_id,
    )


def mozakere_recruit_reads_as_mafia(game: Game, p: Player) -> bool:
    return is_mozakere_scenario(game) and p.user_id in game.mozakere_mafia_recruit_ids
