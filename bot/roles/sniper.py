"""منطق هستهٔ اسنایپر — مشترک semi_auto و no_host."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.game import bazpors_counts_as_mafia_faction, role_label_fa
from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario
from bot.roles.mozakere_sniper import (
    can_mozakere_sniper_shoot,
    mark_mozakere_sniper_shot_used,
    mozakere_sniper_shot_limit,
    mozakere_sniper_shots_remaining,
    mozakere_sniper_shots_used,
)
from bot.roles.night_state import sniper_night_state

if TYPE_CHECKING:
    from bot.game import GameManager


def find_alive_sniper(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.SNIPER:
            return p
    return None


def find_sniper_holder(game: Game) -> Player | None:
    for p in game.players.values():
        if p.role == Role.SNIPER:
            return p
    return None


def is_sniper_role(role: Role | None) -> bool:
    return role == Role.SNIPER


def is_sniper(player: Player) -> bool:
    return is_sniper_role(player.role)


def player_count(game: Game) -> int:
    return len(game.players)


def _game_has_sniper_role(game: Game) -> bool:
    return any(p.role == Role.SNIPER for p in game.players.values())


def shot_limit(game: Game) -> int:
    if is_mozakere_scenario(game):
        return mozakere_sniper_shot_limit(game)
    return 1


def shots_used(game: Game) -> int:
    if is_mozakere_scenario(game):
        return mozakere_sniper_shots_used(game)
    return 1 if bullet_used(game) else 0


def shots_remaining(game: Game) -> int:
    if is_mozakere_scenario(game):
        return mozakere_sniper_shots_remaining(game)
    return 0 if bullet_used(game) else 1


def nights_enabled(game: Game) -> bool:
    """بازپرس: ۱۲/۱۳ نفره؛ مذاکره: همه ظرفیت‌ها با نقش تک‌تیرانداز."""
    if is_mozakere_scenario(game):
        return _game_has_sniper_role(game)
    if game.scenario_name not in ("bazpors", "bazpors_salamat_test"):
        return False
    return player_count(game) in (12, 13)


def bullet_used(game: Game) -> bool:
    if is_mozakere_scenario(game):
        return mozakere_sniper_shots_used(game) >= mozakere_sniper_shot_limit(game)
    return sniper_night_state(game).bullet_used


def mark_bullet_used(game: Game) -> None:
    if is_mozakere_scenario(game):
        mark_mozakere_sniper_shot_used(game)
        return
    sniper_night_state(game).mark_bullet_used()


def can_shoot(game: Game) -> bool:
    if is_mozakere_scenario(game):
        return can_mozakere_sniper_shoot(game)
    return find_alive_sniper(game) is not None and not bullet_used(game)


def night_target_uid(game: Game) -> int | None:
    return sniper_night_state(game).night_target_uid


def shot_pool(game: Game) -> list[Player]:
    sn = find_alive_sniper(game)
    return [
        p
        for p in game.players.values()
        if p.is_alive and (not sn or p.user_id != sn.user_id)
    ]


def target_valid(game: Game, target_uid: int) -> bool:
    sn = find_alive_sniper(game)
    p = game.players.get(target_uid)
    if p is None or not p.is_alive:
        return False
    if sn and target_uid == sn.user_id:
        return False
    return True


def commit_pick(game: Game, target_uid: int | None) -> None:
    if (
        is_mozakere_scenario(game)
        and target_uid is not None
        and not can_mozakere_sniper_shoot(game)
    ):
        return
    sniper_night_state(game).night_target_uid = target_uid
    if is_mozakere_scenario(game) and target_uid is not None:
        mark_mozakere_sniper_shot_used(game)


def clear_pick(game: Game) -> None:
    sniper_night_state(game).night_target_uid = None


def sniper_uid_at_night_start(game: Game) -> int | None:
    snap = game.bazpors_alive_at_night_start or {}
    for uid, pl in game.players.items():
        if pl.role == Role.SNIPER and snap.get(uid, pl.is_alive):
            return uid
    return None


def mafia_kill_blocked_by_doctor(game: Game, tgt_uid: int) -> bool:
    from bot.roles.doctor import mafia_kill_blocked_by_doctor_save

    return mafia_kill_blocked_by_doctor_save(game, tgt_uid)


def boss_immune(target: Player) -> bool:
    from bot.roles.mafia_boss import sniper_boss_immune

    return sniper_boss_immune(target)


def target_is_mafia_faction(game: Game, target: Player) -> bool:
    return bazpors_counts_as_mafia_faction(game, target)


def apply_night_resolution(game: Game, gm: "GameManager") -> None:
    """اعمال شلیک اسنایپر در پایان شب — semi_auto و no_host."""
    tgt_uid = sniper_night_state(game).night_target_uid
    if tgt_uid is None:
        return
    if not is_mozakere_scenario(game) and bullet_used(game):
        return
    sn = find_sniper_holder(game)
    if not sn or tgt_uid not in game.players:
        return
    if not is_mozakere_scenario(game):
        mark_bullet_used(game)
    tgt = game.players[tgt_uid]
    from bot.bazpors_narrator import (
        _append_host_flush_note,
        _eliminate_player,
        _tag_esc,
    )

    sn_tag = _tag_esc(game, gm, sn.user_id)
    tgt_tag = _tag_esc(game, gm, tgt_uid)
    target_is_mafia = target_is_mafia_faction(game, tgt)

    if not tgt.is_alive:
        if boss_immune(tgt):
            game.bazpors_night_announce_lines.append(
                f"تک‌تیرانداز به {tgt_tag} (رئیس مافیا) شلیک کرد؛ "
                "هدف از قبل مرده بود — طبق قانون کسی از بازی خارج نشد."
            )
            _append_host_flush_note(
                game,
                f"🎯 <b>شلیک تک‌تیرانداز</b> روی <b>{tgt_tag}</b> (رئیس مافیا).\n"
                "هدف از قبل از بازی خارج شده بود؛ <b>هیچ‌کس</b> دیگر خارج نشد.",
            )
            return
        if target_is_mafia:
            game.bazpors_night_announce_lines.append(
                f"تک‌تیرانداز به {tgt_tag} شلیک کرد؛ "
                "هدف (مافیا) از قبل مرده بود."
            )
            return
        role_lbl = role_label_fa(tgt.role) if tgt.role else "شهروند"
        _eliminate_player(game, gm, sn.user_id, hunter_chain=False)
        game.bazpors_night_announce_lines.append(
            f"تک‌تیرانداز به {tgt_tag} ({role_lbl}) شلیک کرد؛ "
            "هدف از قبل مرده بود و خود تک‌تیرانداز از بازی خارج شد."
        )
        _append_host_flush_note(
            game,
            f"🎯 تک‌تیرانداز به <b>{tgt_tag}</b> ({role_lbl}) شلیک اشتباه کرد.\n"
            "هدف از قبل مرده بود؛ <b>تک‌تیرانداز</b> از بازی خارج شد.",
        )
        return

    if boss_immune(tgt):
        game.bazpors_night_announce_lines.append(
            f"تک‌تیرانداز به {tgt_tag} (رئیس مافیا) شلیک کرد؛ "
            "طبق قانون کسی از بازی خارج نشد."
        )
        _append_host_flush_note(
            game,
            f"🎯 <b>شلیک تک‌تیرانداز</b> روی <b>{tgt_tag}</b> (رئیس مافیا).\n"
            "طبق قانون <b>هیچ‌کس</b> از بازی خارج نشد.",
        )
        return

    if target_is_mafia:
        if mafia_kill_blocked_by_doctor(game, tgt_uid):
            game.bazpors_night_announce_lines.append(
                f"تک‌تیرانداز به {tgt_tag} شلیک کرد؛ هدف از بازی خارج نشد."
            )
            _append_host_flush_note(
                game,
                f"🎯 تک‌تیرانداز به <b>{tgt_tag}</b> (مافیا) شلیک کرد.\n"
                "نجات پزشک مانع خروج هدف شد؛ <b>تک‌تیرانداز</b> در بازی ماند.",
            )
            return
        note = _eliminate_player(game, gm, tgt_uid)
        from bot.game import mark_bazpors_eliminated_by_sniper

        mark_bazpors_eliminated_by_sniper(game, tgt_uid)
        sniper_night_state(game).hero_mafia_kill = True
        game.bazpors_night_announce_lines.append(
            f"تک‌تیرانداز {tgt_tag} را هدف گرفت و از بازی خارج شد."
        )
        _append_host_flush_note(
            game,
            f"🎯 تک‌تیرانداز به <b>{tgt_tag}</b> (مافیا) شلیک کرد و او از بازی خارج شد."
            + (f"\n{note}" if note else ""),
        )
        return

    _eliminate_player(game, gm, sn.user_id, hunter_chain=False)
    game.bazpors_night_announce_lines.append(
        f"تک‌تیرانداز به {tgt_tag} (شهروند) اشتباه شلیک کرد و خودش از بازی خارج شد."
    )
