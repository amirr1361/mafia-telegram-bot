"""شبیه‌سازی نقش‌های ماسون — doctor، sniper، gunner، mason، detective، …"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import (
    begin_no_host_day1_defense_pick,
    record_day_vote_participants,
    set_day_vote_defender_uids,
)
from bot.game import GameManager
from bot.mason_day_defense import build_mason_defense_candidates_announcement_html
from bot.bazpors_narrator import _compose_full_night_report
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_mf
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_saboteur as ms_sb
from bot.roles import mason_sniper as ms_sn
from bot.roles import detective as det
from bot.roles.night_state import mafia_night_state

from tests.mason_simulation_harness import MasonSimHarness


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class MasonSimulationDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.h = MasonSimHarness.build(self.gm, max_players=16)

    def test_save_capacity_by_alive_count(self) -> None:
        for alive, expected in ((18, 4), (16, 4), (15, 3), (12, 3), (11, 2), (8, 2), (7, 1)):
            with self.subTest(alive=alive, expected=expected):
                h = MasonSimHarness.build(self.gm, max_players=max(alive, 18))
                for i, p in enumerate(h.game.players.values()):
                    p.is_alive = i < alive
                cap = ms_doc.mason_doctor_save_capacity(h.game)
                self.assertEqual(cap, expected)

    def test_self_save_line_format(self) -> None:
        line = ms_doc.build_mason_doctor_self_save_usage_line(self.h.game)
        self.assertIn("🛡️ تعداد دفعات استفاده از نجات خود:", line)
        self.assertIn("از", line)

    def test_self_save_counter_persists_across_night_reset(self) -> None:
        from bot.mason_night_entry import reset_mason_current_night_selections

        self.h.game.mason_doctor_self_save_count = 1
        reset_mason_current_night_selections(self.h.game)
        self.assertEqual(self.h.game.mason_doctor_self_save_count, 1)

    def test_night_saves_cleared_between_nights(self) -> None:
        from bot.mason_night_entry import reset_mason_current_night_selections

        doc_uid = self.h.holder_uid(Role.DOCTOR)
        assert doc_uid is not None
        ms_doc.commit_mason_doctor_save(self.h.game, doc_uid)
        reset_mason_current_night_selections(self.h.game)
        self.assertEqual(ms_doc.mason_doctor_night_save_uids(self.h.game), [])


class MasonSimulationSniperCommanderTests(unittest.TestCase):
    def test_bullet_limit_room_16_is_three(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        self.assertEqual(ms_sn.mason_sniper_total_bullets(h.game), 3)

    def test_rejected_shots_free_bullets(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        t1, t2 = h.alive_uids_except()[:2]
        ms_sn.commit_mason_sniper_night_selection(h.game, [t1, t2])
        ms_cmd.mason_commander_rejects_all_shots(h.game)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(h.game), 0)

    def test_partial_approval_consumes_one(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        sn_uid = h.holder_uid(Role.SNIPER)
        pool = [
            uid
            for uid in h.alive_uids_except(sn_uid)
            if ms_sn.mason_target_in_shot_pool(h.game, uid)
        ]
        t1, t2 = pool[:2]
        self.assertTrue(ms_sn.commit_mason_sniper_night_selection(h.game, [t1, t2]))
        self.assertTrue(ms_cmd.commit_mason_commander_approval(h.game, [t1]))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(h.game), 1)

    def test_ruintan_and_godfather_not_killed(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        gf = h.holder_uid(Role.GODFATHER)
        rt = h.holder_uid(Role.RUINTAN)
        assert gf is not None and rt is not None
        ms_sn.commit_mason_sniper_night_selection(h.game, [gf, rt])
        ms_cmd.commit_mason_commander_approval(h.game, [gf, rt])
        apply_mason_night_resolution(h.game, h.gm)
        self.assertTrue(h.game.players[gf].is_alive)
        self.assertTrue(h.game.players[rt].is_alive)

    def test_doctor_save_does_not_block_sniper(self) -> None:
        from bot.roles.mason_sniper import mason_sniper_shot_immune

        h = MasonSimHarness.build(GameManager(), max_players=16)
        doc_uid = h.holder_uid(Role.DOCTOR)
        tgt = next(
            uid
            for uid in h.alive_uids_except(doc_uid)
            if not mason_sniper_shot_immune(h.game, h.game.players[uid])
        )
        if doc_uid is not None:
            ms_doc.commit_mason_doctor_save(h.game, tgt)
        ms_sn.commit_mason_sniper_night_selection(h.game, [tgt])
        ms_cmd.commit_mason_commander_approval(h.game, [tgt])
        apply_mason_night_resolution(h.game, h.gm)
        self.assertFalse(h.game.players[tgt].is_alive)


class MasonSimulationGunnerSaboteurTests(unittest.TestCase):
    def test_full_gun_lifecycle(self) -> None:
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
        gn = game.players[10]
        holder = game.players[20]
        victim = game.players[30]
        ms_gn.commit_mason_gunner_target(game, gn, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        result = ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        self.assertIsNotNone(result)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))
        self.assertFalse(ms_sb.mason_saboteur_needs_night_pick(game))

    def test_gunner_no_give_does_not_spend(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        self.assertTrue(ms_gn.commit_mason_gunner_no_give(h.game))
        ms_gn.prepare_mason_day_gun_from_night_choices(h.game)
        self.assertIsNone(ms_gn.mason_day_gun_holder_uid(h.game))
        self.assertTrue(ms_gn.mason_gunner_can_give_gun(h.game))

    def test_holder_death_after_delivery_keeps_gun_spent(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        gn = h.holder(Role.GUNMAN)
        holder_uid = h.first_town_target()
        assert gn is not None
        ms_gn.commit_mason_gunner_target(h.game, gn, h.game.players[holder_uid])
        ms_gn.prepare_mason_day_gun_from_night_choices(h.game)
        ms_gn.mark_mason_gun_delivered_to_holder(h.game)
        h.game.players[holder_uid].is_alive = False
        ms_gn.refresh_mason_day_gun_holder_if_eliminated(h.game)
        self.assertTrue(ms_gn.mason_gun_is_spent(h.game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(h.game))


class MasonSimulationMasonRecruitTests(unittest.TestCase):
    def test_town_recruit_adds_to_team(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        mason = h.holder(Role.MASON)
        target_uid = h.first_town_target()
        assert mason is not None
        ms_mf.commit_mason_recruit(h.game, mason, h.game.players[target_uid])
        self.assertIn(target_uid, h.game.mason_team_member_ids)

    def test_no_recruit_flag(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        mason = h.holder(Role.MASON)
        assert mason is not None
        ms_mf.commit_mason_recruit(h.game, mason, None)
        self.assertTrue(h.game.mason_mason_night_no_recruit)

    def test_selection_reset_between_nights(self) -> None:
        from bot.mason_night_entry import reset_mason_current_night_selections

        h = MasonSimHarness.build(GameManager(), max_players=16)
        h.game.mason_pending_recruit_uid = 123
        reset_mason_current_night_selections(h.game)
        self.assertIsNone(h.game.mason_pending_recruit_uid)


class MasonSimulationDetectiveTests(unittest.TestCase):
    def test_godfather_negative_town_negative(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        det_uid = h.holder_uid(Role.DETECTIVE)
        gf_uid = h.holder_uid(Role.GODFATHER)
        town_uid = h.first_town_target()
        assert det_uid is not None and gf_uid is not None
        r_gf = det.commit_pick(h.game, gf_uid)
        self.assertFalse(r_gf.is_positive)
        r_town = det.commit_pick(h.game, town_uid)
        self.assertFalse(r_town.is_positive)

    def test_saboteur_positive(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        sb_uid = h.holder_uid(Role.SABOTEUR)
        assert sb_uid is not None
        r = det.commit_pick(h.game, sb_uid)
        self.assertTrue(r.is_positive)


class MasonSimulationDefenseTests(unittest.TestCase):
    def test_numbered_defense_format(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(20, "امیر", Role.TOWN_SIMPLE))
        set_day_vote_defender_uids(game, {20})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("1. امیر | سابقه رأی‌گیری: ۰ بار", html)

    def test_defense_history_single_increment(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(20, "امیر", Role.TOWN_SIMPLE))
        game.bazpors_day_vote_participations[20] = 0
        set_day_vote_defender_uids(game, {20})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("۰ بار", html)
        record_day_vote_participants(game, {20})
        self.assertEqual(game.bazpors_day_vote_participations[20], 1)
        set_day_vote_defender_uids(game, {20})
        html2 = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("۱ بار", html2)
        self.assertNotIn("۲ بار", html2)


class MasonSimulationNightReportTests(unittest.TestCase):
    def test_full_report_includes_core_actions(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        doc_uid = h.holder_uid(Role.DOCTOR)
        sn_uid = h.holder_uid(Role.SNIPER)
        gn_uid = h.holder_uid(Role.GUNMAN)
        tgt = h.first_town_target()
        if doc_uid is not None:
            ms_doc.commit_mason_doctor_save(h.game, tgt)
        if sn_uid is not None:
            ms_sn.commit_mason_sniper_night_selection(h.game, [tgt])
            ms_cmd.commit_mason_commander_approval(h.game, [tgt])
        if gn_uid is not None:
            gn = h.game.players[gn_uid]
            other = h.first_town_target(exclude_uids=[gn_uid, tgt])
            ms_gn.commit_mason_gunner_target(h.game, gn, h.game.players[other])
        sb = h.holder(Role.SABOTEUR)
        if sb is not None:
            ms_sb.commit_mason_saboteur_target(h.game, sb, h.game.players[tgt])
        mafia_night_state(h.game).commit_shot(tgt)
        alive_before = {uid: True for uid in h.game.players}
        apply_mason_night_resolution(h.game, h.gm)
        report = _compose_full_night_report(h.game, h.gm, alive_before)
        if doc_uid is not None:
            self.assertIn("نجات پزشک", report)
        if sn_uid is not None:
            self.assertIn("اسنایپر", report)
        self.assertIn("شات مافیا", report)


class MasonSimulationCallbackSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_sniper_click_safe(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        h.setup_night(night_count=1)
        sn_uid = h.holder_uid(Role.SNIPER)
        assert sn_uid is not None
        h.game.mason_night_sniper_confirmed = True
        await h.click_role(as_uid=sn_uid, act="mssp", tid=h.first_town_target())

    async def test_dead_player_wait_ok_does_not_crash(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        h.setup_night(night_count=1)
        uid = h.first_town_target()
        h.game.players[uid].is_alive = False
        with patch(
            "bot.observer_delivery.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new_callable=AsyncMock,
        ):
            await h.press_wait_ok(uid)

    async def test_observer_can_press_wait_ok_for_synthetic(self) -> None:
        h = MasonSimHarness.build(GameManager(), max_players=16)
        syn = next(
            p.user_id for p in MasonSimHarness.synthetic_players(h.game)
        )
        h.setup_night(night_count=1)
        with patch(
            "bot.observer_delivery.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new_callable=AsyncMock,
        ):
            await h.press_wait_ok(syn, actor_uid=h.observer_uid)
        self.assertIn(syn, h.game.mason_night_wait_ok_uids)
