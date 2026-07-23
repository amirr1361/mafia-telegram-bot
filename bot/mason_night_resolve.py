"""محاسبهٔ شب — فقط سناریوی ماسون."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.models import Game
from bot.room_mode import is_mason_scenario
from bot.roles.night_state import mafia_night_state

if TYPE_CHECKING:
    from bot.game import GameManager


def reset_mason_night_resolution_state(game: Game) -> None:
    from bot.mason_night_report import clear_mason_night_report_snapshot

    game.mason_night_resolution_applied = False
    game.mason_last_night_had_collapse = False
    clear_mason_night_report_snapshot(game)


def apply_mason_night_resolution(game: Game, gm: "GameManager") -> None:
    """اعمال مرگ‌ها و اثرات شب ماسون — بدون پیام میانی."""
    if not is_mason_scenario(game):
        return
    if game.mason_night_resolution_applied:
        return

    from bot.bazpors_narrator import _eliminate_player
    from bot.roles import mason_doctor as ms_doc
    from bot.roles import mason_fraternity as ms_mf
    from bot.roles import mason_sniper as ms_sn
    from bot.roles.mason_nato import resolve_mason_nato_elimination_uid

    game.bazpors_host_flush_note = None
    game.bazpors_night_announce_lines.clear()
    game.mason_last_night_had_collapse = False

    from bot.mason_night_report import freeze_mason_night_report_snapshot
    from bot.roles.mason_armored import mason_armored_mafia_shot_immune

    freeze_mason_night_report_snapshot(game)

    recruit = ms_mf.resolve_mason_recruitment_result(game)
    collapse_victim_uids: tuple[int, ...] = ()
    if recruit.collapsed:
        game.mason_last_night_had_collapse = True
        if game.mason_collapse_night_number is None:
            game.mason_collapse_night_number = max(
                1, game.bazpors_narrator_night_count
            )
        collapse_victim_uids = recruit.eliminated_uids

    mafia = mafia_night_state(game)
    if mafia.shot_registered:
        shot_target = mafia.target_uid
        if shot_target is not None and game.players.get(shot_target) is not None:
            pl = game.players[shot_target]
            if (
                pl.is_alive
                and not ms_doc.mason_mafia_shot_blocked_by_doctor_save(
                    game, shot_target
                )
                and not mason_armored_mafia_shot_immune(game, pl)
            ):
                _eliminate_player(game, gm, shot_target, elim_source="night_resolve")

    nato_uid = resolve_mason_nato_elimination_uid(game)
    if nato_uid is not None:
        pl = game.players.get(nato_uid)
        if pl is not None and pl.is_alive:
            _eliminate_player(game, gm, nato_uid, elim_source="night_resolve")

    for uid in ms_sn.mason_approved_shots_that_kill(game):
        pl = game.players.get(uid)
        if pl is not None and pl.is_alive:
            _eliminate_player(game, gm, uid, elim_source="night_resolve")

    for uid in collapse_victim_uids:
        pl = game.players.get(uid)
        if pl is not None and pl.is_alive:
            _eliminate_player(game, gm, uid, elim_source="night_resolve")

    ms_doc.commit_mason_doctor_pending_self_save(game)
    ms_doc.clear_mason_doctor_night_saves(game)

    from bot.roles import mason_gunner as ms_gn

    ms_gn.prepare_mason_day_gun_from_night_choices(game)

    gm.check_winner(game)
    game.mason_night_resolution_applied = True
