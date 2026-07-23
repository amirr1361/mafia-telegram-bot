"""منطق هستهٔ ناتویی — مشترک semi_auto و no_host."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.roles.night_state import nato_night_state

if TYPE_CHECKING:
    from bot.game import GameManager

GUESS_ROLES: tuple[Role, ...] = (
    Role.DETECTIVE,
    Role.DOCTOR,
    Role.INTERROGATOR,
    Role.HUNTER,
    Role.RUINTAN,
    Role.SNIPER,
)


def find_alive_nato(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.NATO:
            return p
    return None


def can_register(game: Game) -> bool:
    if nato_night_state(game).used:
        return False
    return find_alive_nato(game) is not None


def denied_message(game: Game) -> str:
    """پیام رد ناتویی — تفکیک «قبلاً انجام شده» از «بازیکن ناتو خارج شده»."""
    if nato_night_state(game).used:
        return (
            "ناتویی قبلاً انجام شده است. به مرحله قبل برگردید و "
            "گزینه دیگری انتخاب کنید."
        )
    if find_alive_nato(game) is None:
        return (
            "بازیکن ناتو از بازی خارج شده است؛ ناتویی امکان‌پذیر نیست. "
            "به مرحله قبل برگردید و گزینه دیگری انتخاب کنید."
        )
    return "ناتویی در حال حاضر مجاز نیست."


def visually_mafia(game: Game, p: Player) -> bool:
    if p.user_id in game.bazpors_sniper_eliminated_uids:
        return False
    if p.user_id in game.bazpors_mafia_recruit_ids:
        return True
    if getattr(p, "bazpors_converted_by_yakuza", False):
        return True
    if not p.role:
        return False
    return is_mafia_team(p.role)


def alive_players(game: Game) -> list[Player]:
    return [p for p in game.players.values() if p.is_alive]


def target_pool(game: Game) -> list[Player]:
    """اهداف زندهٔ غیرمافیا — همان pool یاکوزایی/ناتویی no_host."""
    return [p for p in alive_players(game) if not visually_mafia(game, p)]


def non_mafia_roles_in_room(game: Game) -> list[Role]:
    found: set[Role] = set()
    for p in game.players.values():
        if p.role is None:
            continue
        if p.role == Role.OBSERVER:
            continue
        if is_mafia_team(p.role):
            continue
        found.add(p.role)
    from bot.bazpors_narrator import role_label_fa

    return sorted(found, key=lambda r: role_label_fa(r))


def guess_roles_in_room(game: Game) -> list[Role]:
    """همان فهرست semi_auto — بدون شهروند ساده."""
    present = set(non_mafia_roles_in_room(game))
    return [r for r in GUESS_ROLES if r in present]


def role_guessable_in_room(game: Game, role: Role) -> bool:
    return role in guess_roles_in_room(game)


def target_valid(game: Game, target_uid: int) -> bool:
    p = game.players.get(target_uid)
    if p is None or not p.is_alive:
        return False
    return not visually_mafia(game, p)


def evaluate_guess(game: Game, guess_role: Role, target_uid: int) -> bool:
    target = game.players.get(target_uid)
    if target is None:
        return False
    return target.is_alive and target.role == guess_role


def _void_doctor_after_nato(game: Game) -> None:
    from bot.roles.doctor import void_night_pick

    void_night_pick(game)


def commit_guess(
    game: Game,
    guess_role: Role,
    target_uid: int,
    *,
    gm: "GameManager | None" = None,
    announce: bool = False,
) -> bool:
    """ثبت ناتویی — state مشترک semi_auto (npick) و no_host."""
    success = evaluate_guess(game, guess_role, target_uid)
    nato_night_state(game).commit_guess(
        guess_role, target_uid, success=success
    )
    _void_doctor_after_nato(game)
    if announce and gm is not None:
        import html

        from bot.bazpors_narrator import role_label_fa

        target = game.players[target_uid]
        role_txt = html.escape(role_label_fa(guess_role))
        tgt_txt = html.escape(gm.format_player_tag(target))
        game.bazpors_night_announce_lines.append(
            f"ناتویی: حدس نقش {role_txt} — هدف {tgt_txt} (ثبت شد)."
        )
        gm.check_winner(game)
    return success


def commit_confirm_result(
    game: Game,
    target_uid: int,
    *,
    success: bool,
) -> None:
    """semi_auto — nok/nwr پس از انتخاب هدف در NS_NATO_CONFIRM."""
    nato_night_state(game).commit_confirm_result(target_uid, success=success)
    _void_doctor_after_nato(game)


def commit_multi_pick_fail(game: Game) -> None:
    """semi_auto — nm_no."""
    nato_night_state(game).commit_multi_pick_fail()
    _void_doctor_after_nato(game)


def commit_multi_pick_success(game: Game, target_uid: int) -> None:
    """semi_auto — nm_pick."""
    nato_night_state(game).commit_multi_pick_success(target_uid)
    _void_doctor_after_nato(game)


def clear_pending_role(game: Game) -> None:
    nato_night_state(game).clear_pending_role()


def action_registered(game: Game) -> bool:
    return nato_night_state(game).action_registered


def already_used(game: Game) -> bool:
    return nato_night_state(game).used
