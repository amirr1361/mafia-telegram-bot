"""Room 99 — Night 2 stuck with Godfather dead, Saboteur mafia chooser (Mason only).

Reconstructed from audit log 99_20260624_094741.jsonl:
- 12-player masoon, Night 2, 8 alive after Day 2 (Apache day gun + self-elim)
- Mafia shot (Saboteur → Bodyguard) completed; parallel collect never finished
- Commander must not receive generic wait panel while Sniper is alive
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_entry import (
    MASON_NIGHT_WAIT_ACT,
    _dispatch_mason_wait_panels,
    dispatch_mason_night_entry_panels,
)
from bot.mason_night_ready import (
    all_mason_parallel_night_ready,
    explain_mason_night_stuck,
    maybe_finish_mason_parallel_night,
)
from bot.mason_responsibilities import (
    collect_mason_night_responsibilities,
    format_mason_responsibilities_report,
)
from bot.models import Player, Role
from bot.no_host_mafia_shot import _finalize_mafia_shot


def _p(
    uid: int,
    name: str,
    role: Role,
    *,
    alive: bool = True,
    seat: int = 0,
) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _room99_night2_game(gm: GameManager, *, after_mafia_shot: bool = True):
    """Eight alive at Night 2 — matches Room 99 end-of-log state."""
    game = gm.create_game(
        host_id=108214166,
        scenario_name="masoon",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "99"
    game.bot_assistant_user_id = 108214166
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 2
    game.no_host_night_parallel_collect_active = True
    game.mason_night_entry_dispatched_night = 2

    roster = [
        (30006146, "Ehsan Pilzoor", Role.COWBOY, 1, True),
        (504542027, "Ghasem", Role.SABOTEUR, 2, True),
        (8553283735, "Cyber Seq", Role.SNIPER, 3, True),
        (479369026, "Behnam", Role.RUINTAN, 4, True),
        (126512798, "Hassan", Role.MASON, 5, True),
        (108214166, "Amir Latifi", Role.APACHE, 6, False),
        (313243161, "Hassan Khosravi", Role.GUNMAN, 7, True),
        (344288807, "Ram Moe", Role.GODFATHER, 8, False),
        (106882355, "Ehsan Goroohi", Role.DOCTOR, 9, False),
        (91576703, "R Rah", Role.SPY, 10, False),
        (73526314, "Abolfazl Alizadeh", Role.BODYGUARD, 11, True),
        (131662695, "Hamed", Role.COMMANDER, 12, True),
    ]
    for uid, name, role, seat, alive in roster:
        gm.add_player(game, _p(uid, name, role, alive=alive, seat=seat))

    if after_mafia_shot:
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_night1_chooser_uid = 504542027
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_shot_target_uid = 73526314
    return game


def _arm_all_night2_actions(game) -> None:
    game.mason_night_saboteur_confirmed = True
    game.mason_night_sniper_confirmed = True
    game.mason_night_commander_confirmed = True
    game.mason_night_gunner_confirmed = True
    game.mason_night_guardian_confirmed = True
    game.mason_night_mason_confirmed = True
    game.mason_night_wait_ok_uids = [30006146, 479369026]


class Room99Night2DiagnosticTests(unittest.TestCase):
    def test_diagnostic_identifies_saboteur_role_blocker(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm)
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("night 2", report.lower())
        self.assertIn("Mafia action complete", report)
        self.assertIn("Waiting for Saboteur", report)
        self.assertIn("mason_night_saboteur_confirmed=False", report)
        self.assertIn("Ghasem", report)
        self.assertFalse(all_mason_parallel_night_ready(game))

    def test_responsibilities_registry_matches_stuck_state(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm)
        resps = collect_mason_night_responsibilities(game, gm)
        pending_ids = {r.responsibility_id for r in resps if not r.done and r.required}
        self.assertIn("saboteur_role", pending_ids)
        self.assertIn("sniper_role", pending_ids)
        self.assertIn("commander_role", pending_ids)
        self.assertNotIn("doctor_role", pending_ids)
        wait_ok = [r for r in resps if r.responsibility_id.startswith("wait_ok_")]
        wait_uids = {r.holder_uid for r in wait_ok}
        self.assertEqual(wait_uids, {30006146, 479369026})
        self.assertNotIn(131662695, wait_uids, "Commander must not be a wait-OK waiter")

    def test_dead_players_do_not_block(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm)
        _arm_all_night2_actions(game)
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Night readiness complete", report)
        self.assertTrue(all_mason_parallel_night_ready(game))

    def test_independent_mafia_shot_vs_saboteur_role(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm)
        report = format_mason_responsibilities_report(game, gm)
        self.assertIn("Mafia shot (Saboteur)", report)
        self.assertIn("done=True", report.split("Mafia shot")[1].split("\n")[0])
        self.assertIn("Saboteur role", report)
        self.assertIn("done=False", report.split("Saboteur role")[1].split("\n")[0])


class Room99CommanderWaitPanelFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_commander_not_sent_generic_wait_when_sniper_alive(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm, after_mafia_shot=False)
        bot = MagicMock()
        sent: list[tuple[int, str]] = []

        async def capture(_bot, _game, uid, ui_key, _text, _kb, **kw):
            sent.append((uid, ui_key))

        with patch(
            "bot.mason_night_entry.register_mirror_prompt_pair",
            side_effect=capture,
        ):
            await _dispatch_mason_wait_panels(bot, game)

        commander_uid = 131662695
        commander_keys = [k for u, k in sent if u == commander_uid]
        self.assertEqual(
            commander_keys,
            [],
            "Commander must not get mason_night_wait while Sniper is alive",
        )
        cowboy_keys = [k for u, k in sent if u == 30006146]
        self.assertTrue(
            any(k.startswith("mason_night_wait:99:") for k in cowboy_keys),
            "Cowboy should still receive generic wait panel",
        )

    async def test_night_entry_does_not_trap_commander_with_wait_panel(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm, after_mafia_shot=False)
        bot = MagicMock()
        sent: list[tuple[int, str]] = []

        async def capture(_bot, _game, uid, ui_key, _text, _kb, **kw):
            sent.append((uid, ui_key))

        patches = (
            patch("bot.no_host_mafia_night1.start_no_host_night1_mafia_flow", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_saboteur_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_doctor_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_sniper_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_gunner_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_guardian_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_mason_recruit_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_detective_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_natasha_panel", new=AsyncMock()),
            patch("bot.mason_night_role.dispatch_mason_priest_panel", new=AsyncMock()),
            patch(
                "bot.mason_night_entry.register_mirror_prompt_pair",
                side_effect=capture,
            ),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10]:
            await dispatch_mason_night_entry_panels(bot, game, gm)

        commander_wait = [
            k
            for u, k in sent
            if u == 131662695 and k.startswith("mason_night_wait:")
        ]
        self.assertEqual(commander_wait, [])

    def test_commander_wait_ok_does_not_satisfy_commander_role(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm)
        game.mason_night_wait_ok_uids = [131662695]
        game.mason_night_commander_confirmed = False
        self.assertFalse(all_mason_parallel_night_ready(game))
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("mason_night_commander_confirmed", report)
        self.assertIn("Commander", report)


class Room99Night2ResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_mafia_shot_redispatches_saboteur_role_panel(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm, after_mafia_shot=False)
        game.no_host_mafia_shot_flow_active = True
        game.no_host_mafia_night1_panel_uids = [504542027]
        bot = MagicMock()
        sab_dispatch = AsyncMock()
        with patch(
            "bot.no_host_mafia_shot.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_mafia_shot.notify_mafia_team_shot_result",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.dispatch_mason_saboteur_panel",
            sab_dispatch,
        ):
            await _finalize_mafia_shot(
                bot,
                game,
                gm,
                mafia_uid=504542027,
                actor_uid=504542027,
                target_uid=73526314,
            )
        sab_dispatch.assert_awaited_once()
        self.assertTrue(game.no_host_mafia_shot_done)

    async def test_night_resolves_when_all_actions_complete(self) -> None:
        gm = GameManager()
        game = _room99_night2_game(gm)
        _arm_all_night2_actions(game)
        bot = MagicMock()
        finish = AsyncMock()
        with patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            finish,
        ):
            await maybe_finish_mason_parallel_night(bot, game, gm)
        self.assertTrue(all_mason_parallel_night_ready(game))
        finish.assert_awaited_once()


class Room99RegressionIsolationTests(unittest.TestCase):
    def test_bazpors_unchanged(self) -> None:
        from bot.roles.doctor import doctor_save_capacity

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertEqual(doctor_save_capacity(game), 1)

    def test_mozakere_unchanged(self) -> None:
        from bot.no_host_mafia_night1 import build_mozakere_mafia_operation_menu_html

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertIn("مذاکره", build_mozakere_mafia_operation_menu_html(game))

    def test_wait_panel_act_unchanged(self) -> None:
        self.assertEqual(MASON_NIGHT_WAIT_ACT, "mok")


if __name__ == "__main__":
    unittest.main()
