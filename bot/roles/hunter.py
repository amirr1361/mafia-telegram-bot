"""منطق هستهٔ هانتر — مشترک semi_auto و no_host."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.roles.night_state import hunter_night_state

HUNTER_CHAIN_SECRET_ELIM_SOURCES: frozenset[str] = frozenset(
    {"night_resolve", "night_extra", "discipline"}
)


def find_alive_hunter(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.HUNTER:
            return p
    return None


def is_hunter_role(role: Role | None) -> bool:
    return role == Role.HUNTER


def is_hunter(player: Player) -> bool:
    return is_hunter_role(player.role)


def link_pool(game: Game) -> list[Player]:
    """اهداف زنده برای وصل — هانتر خودش در pool نیست."""
    hunter = find_alive_hunter(game)
    return [
        p
        for p in game.players.values()
        if p.is_alive and (not hunter or p.user_id != hunter.user_id)
    ]


def target_valid(game: Game, target_uid: int) -> bool:
    hunter = find_alive_hunter(game)
    p = game.players.get(target_uid)
    if p is None or not p.is_alive:
        return False
    if hunter and target_uid == hunter.user_id:
        return False
    return True


def commit_pick(game: Game, target_uid: int) -> None:
    """ثبت وصل هانتر — semi_auto (hp) و no_host."""
    hunter_night_state(game).commit_pick(target_uid)


def commit_no_link(game: Game) -> None:
    """این شب وصل ندارم — semi_auto (hs) و no_host skip."""
    hunter_night_state(game).commit_no_link()


def apply_pick(game: Game, pick_uid: int | None) -> None:
    """no_host — تأیید نهایی انتخاب هانتر."""
    if pick_uid is None:
        commit_no_link(game)
        return
    commit_pick(game, pick_uid)


def clear_link_state(game: Game) -> None:
    """وضعیت زندهٔ وصل — اسنپ‌شات گزارش شب (`hunter_report_*`) جدا می‌ماند."""
    hunter_night_state(game).clear_link_state()


def effective_link_uid(game: Game) -> int | None:
    """وصل هانتر برای زنجیره — انتخاب شب جاری یا اسنپ‌شات شب گذشته."""
    state = hunter_night_state(game)
    link = state.link_uid
    if link is not None:
        return link
    return state.report_link_uid


def linked_this_night(game: Game) -> bool:
    return hunter_night_state(game).linked_this_night


def chain_eliminates_link(game: Game, link_player: Player) -> bool:
    from bot.roles.mafia_boss import hunter_chain_eliminates_link

    return hunter_chain_eliminates_link(game, link_player)


def chain_companion_uid(
    game: Game,
    eliminated_uid: int,
    *,
    companion_must_be_alive: bool = True,
) -> int | None:
    """اگر با مرگ هانتر، وصل مافیا (غیر رئیس) هم باید خارج شود، uid او را برمی‌گرداند."""
    victim = game.players.get(eliminated_uid)
    if not victim or not is_hunter(victim):
        return None
    link = effective_link_uid(game)
    if not link or link not in game.players:
        return None
    lp = game.players[link]
    if companion_must_be_alive and not lp.is_alive:
        return None
    if not chain_eliminates_link(game, lp):
        return None
    return link


def chain_public_disclosure(elim_source: str | None) -> bool:
    """زنجیره در بازپرسی/رأی روز برای همه؛ در شب فقط هانتر حذف‌شده."""
    return elim_source not in HUNTER_CHAIN_SECRET_ELIM_SOURCES
