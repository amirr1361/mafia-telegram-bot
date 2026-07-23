"""رگرسیون باگ‌های اتاق‌های قبلی — سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START, _night_report_outcome_section
from bot.bazpors_narrator import (
    record_day_vote_participants,
    set_day_vote_defender_uids,
)
from bot.game import GameManager, is_mafia_team
from bot.mason_day_defense import build_mason_defense_candidates_announcement_html
from bot.mason_night_entry import (
    MASON_NIGHT_WAIT_TEXT,
    reset_mason_current_night_selections,
)
from bot.mason_night_role import (
    MASON_SABOTEUR_GUN_SPENT_TEXT,
    MSS_NONE,
    dispatch_mason_saboteur_panel,
    dispatch_mason_sniper_panel,
)
from bot.models import Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_sniper as ms_sn
from bot.roles import mason_guardian as ms_gd
from bot.roles.mason_armored import mason_armored_mafia_shot_immune

from tests.mason_simulation_harness import MasonSimHarness


class Room22RegressionTests(unittest.IsolatedAsyncioTestCase):
    """Room 22 — گلولهٔ اسنایپر، چرخهٔ تفنگ."""

    async def test_night3_no_sniper_panel_after_three_bullets(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.game.mason_sniper_bullets_spent = 3
        h.setup_night(night_count=3)
        with patch(
            "bot.mason_night_role._show_mason_sniper_panel",
            new_callable=AsyncMock,
        ) as show_sn:
            await dispatch_mason_sniper_panel(h.bot, h.game, h.gm)
        show_sn.assert_not_awaited()
        self.assertFalse(h.game.mason_night_sniper_confirmed)

    def test_gun_spent_gunner_no_panel_next_night(self) -> None:
        from bot.models import Player

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, Player(user_id=10, full_name="Gn", username=None, role=Role.GUNMAN))
        gm.add_player(game, Player(user_id=20, full_name="Holder", username=None, role=Role.TOWN_SIMPLE))
        gm.add_player(game, Player(user_id=30, full_name="Victim", username=None, role=Role.TOWN_SIMPLE))
        gunner = game.players[10]
        holder = game.players[20]
        victim = game.players[30]
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        result = ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        self.assertIsNotNone(result)
        reset_mason_current_night_selections(game)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))


class Room46RegressionTests(unittest.IsolatedAsyncioTestCase):
    """Room 46 — readiness و زنجیرهٔ فرمانده."""

    async def test_sniper_no_shot_commander_auto_confirms(self) -> None:
        from bot.mason_night_role import dispatch_mason_night_role

        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        h.game.no_host_night_parallel_collect_active = True
        h.game.bazpors_narrator_step = NIGHT_START
        sn_uid = h.holder_uid(Role.SNIPER)
        assert sn_uid is not None
        cb = MagicMock()
        cb.answer = AsyncMock()
        with (
            patch(
                "bot.mason_night_role.finalize_no_host_role_pick_message",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_role.dispatch_mason_commander_panel",
                new_callable=AsyncMock,
            ) as cmd,
        ):
            await dispatch_mason_night_role(
                cb,
                h.bot,
                h.game,
                h.gm,
                as_uid=sn_uid,
                actor_uid=sn_uid,
                act=MSS_NONE,
                tid=0,
            )
        cmd.assert_awaited()


class Room94RegressionTests(unittest.TestCase):
    """Room 94 — رویین‌تن، گزارش شب، ریست انتخاب."""

    def test_ruintan_mafia_shot_immune(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        rt = h.holder(Role.RUINTAN)
        assert rt is not None
        self.assertTrue(mason_armored_mafia_shot_immune(h.game, rt))

    def test_night_selection_reset_preserves_bullets(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        h.game.mason_sniper_bullets_spent = 2
        h.game.mason_sniper_night_selected_uids = [20, 30]
        reset_mason_current_night_selections(h.game)
        self.assertEqual(h.game.mason_sniper_bullets_spent, 2)
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(h.game), [])

    def test_mason_collapse_line(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        mason_uid = h.holder_uid(Role.MASON)
        assert mason_uid is not None
        h.game.mason_last_night_had_collapse = True
        snap = {mason_uid: True}
        lines = _night_report_outcome_section(h.game, h.gm, snap)
        self.assertIn("مرگ ماسونی", "\n".join(lines))


class Room39GunnerSaboteurRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_saboteur_no_panel_after_gun_spent(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.game.mason_gun_spent = True
        captured: list[str] = []

        async def _capture(_bot, _game, _uid, _ui, text, _kb, **kw):
            captured.append(text)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_saboteur_panel(h.bot, h.game, h.gm)
        self.assertEqual(len(captured), 1)
        self.assertIn(MASON_SABOTEUR_GUN_SPENT_TEXT, captured[0])


class Room53DefenseRegressionTests(unittest.TestCase):
    def test_single_defense_increment(self) -> None:
        from bot.models import Player

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, Player(user_id=20, full_name="امیر", username=None))
        set_day_vote_defender_uids(game, {20})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("۰ بار", html)
        record_day_vote_participants(game, {20})
        set_day_vote_defender_uids(game, {20})
        html2 = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("۱ بار", html2)


class Room79ConsultRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_team_consult_only_from_night_two(self) -> None:
        from bot.mason_helper_flow import mason_team_consult_required

        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.game.bazpors_narrator_night_count = 1
        self.assertFalse(mason_team_consult_required(h.game))
        h.game.bazpors_narrator_night_count = 2
        self.assertTrue(mason_team_consult_required(h.game))


class BazporsMozakereIsolationTests(unittest.TestCase):
    def test_bazpors_sniper_limit_still_one(self) -> None:
        from bot.roles import sniper as sn

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertEqual(sn.shot_limit(game), 1)

    def test_mozakere_saboteur_inert(self) -> None:
        from bot.roles import mason_saboteur as ms_sb

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertFalse(ms_sb.mason_saboteur_needs_night_pick(game))


class Room22BulletSimulationRegressionTests(unittest.TestCase):
    def test_three_night_bullet_accounting(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        sn_uid = h.holder_uid(Role.SNIPER)
        assert sn_uid is not None
        targets = [
            uid
            for uid in h.alive_uids_except(sn_uid)
            if not is_mafia_team(h.game.players[uid].role)
        ][:3]
        ms_sn.commit_mason_sniper_night_selection(h.game, targets[:2])
        ms_cmd.commit_mason_commander_approval(h.game, targets[:2])
        reset_mason_current_night_selections(h.game)
        ms_sn.commit_mason_sniper_night_selection(h.game, [targets[2]])
        ms_cmd.commit_mason_commander_approval(h.game, [targets[2]])
        self.assertEqual(ms_sn.mason_sniper_bullets_remaining(h.game), 0)
        self.assertFalse(ms_sn.mason_sniper_needs_night_pick(h.game))


def _build_room57_night5_game(gm: GameManager):
    """وضعیت اتاق ۵۷ — شب ۵، پنج نفر زنده (از audit log)."""
    import json
    from pathlib import Path

    from bot.bazpors_narrator import NIGHT_START
    from bot.models import Player
    from bot.roles.night_state import mafia_night_state

    path = Path(__file__).resolve().parents[1] / "data/game_logs/57_20260623_071131.jsonl"
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    game = gm.create_game(
        host_id=108214166,
        scenario_name="masoon",
        max_players=16,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "57"
    game.bot_assistant_user_id = 108214166
    game.observer_user_id = 8620239861
    game.observer_prompt_status = "registered"
    game.no_host_assistant_narrator_active = True
    for r in records:
        if r.get("event") == "game.roles_dealt":
            for p in r["players"]:
                gm.add_player(
                    game,
                    Player(
                        user_id=p["uid"],
                        full_name=p["name"],
                        username=p.get("username"),
                        role=Role(p["role"]),
                        is_alive=True,
                        seat=p.get("seat"),
                    ),
                )
    for r in records:
        if r.get("event") == "player.eliminated" and r["uid"] in game.players:
            game.players[r["uid"]].is_alive = False
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 5
    game.no_host_night_parallel_collect_active = True
    game.mason_sniper_bullets_spent = 3
    game.mason_apache_day_action_used = False
    game.mason_gun_spent = True
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True
    mafia_night_state(game).commit_shot(-920001)
    return game


class Room57Night5RegressionTests(unittest.IsolatedAsyncioTestCase):
    """اتاق ۵۷ — شب ۵ گیر کرده بود."""

    async def test_guardian_gets_ok_not_pick_when_apache_dead(self) -> None:
        gm = GameManager()
        game = _build_room57_night5_game(gm)
        gd_uid = next(p.user_id for p in game.players.values() if p.role == Role.BODYGUARD)
        self.assertFalse(ms_gd.mason_guardian_needs_night_pick(game))
        bot = MagicMock()
        captured: list[str] = []

        async def _cap(_b, _g, uid, _ui, text, kb, **kw):
            if uid == gd_uid:
                captured.append(text)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_cap,
        ):
            from bot.mason_night_role import (
                MASON_GUARDIAN_APACHE_GONE_TEXT,
                dispatch_mason_guardian_panel,
            )

            await dispatch_mason_guardian_panel(bot, game, gm)
        self.assertEqual(len(captured), 1)
        self.assertIn(MASON_GUARDIAN_APACHE_GONE_TEXT, captured[0])

    def test_spent_gunner_blocks_until_guardian_ok(self) -> None:
        from bot.mason_night_ready import all_mason_parallel_night_ready

        gm = GameManager()
        game = _build_room57_night5_game(gm)
        sn_uid = next(p.user_id for p in game.players.values() if p.role == Role.SNIPER)
        game.mason_night_saboteur_confirmed = True
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_wait_ok_uids = [sn_uid]
        game.mason_night_commander_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_guardian_confirmed = False
        game.mason_night_mason_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_natasha_confirmed = True
        game.mason_night_priest_confirmed = True
        self.assertFalse(all_mason_parallel_night_ready(game))

    def test_night5_readiness_report_before_actions(self) -> None:
        from bot.mason_night_ready import format_mason_night_readiness_report

        gm = GameManager()
        game = _build_room57_night5_game(gm)
        from bot.mason_night_entry import reset_mason_night_panel_state

        reset_mason_night_panel_state(game)
        report = format_mason_night_readiness_report(game, gm)
        self.assertIn("guardian: waiting", report)
        self.assertIn("sniper: waiting", report)
        self.assertIn("commander: complete", report)
        self.assertIn("doctor: waiting", report)
