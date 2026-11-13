"""Namayande 10-13 expansion regressions: composition, independent NATO,
Soldier + temporary Sniper lifecycle, Hacker->MineLayer immunity.

Reuses the v2 harness classes from tests.test_namayande10_night_v2 with a
module-level ``load_tests`` so only this module's own tests run.
"""

import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/root/mafia-telegram-bot")

from tests.test_namayande10_night_v2 import (  # noqa: E402
    ASSIST_UID,
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    GUIDE_UID,
    GUARD_UID,
    LAW_UID,
    MINE_UID,
    Nam10NightV2Test,
    NATO_UID,
    OBS_UID,
    SHIAD_UID,
    SYN_UID,
)
from bot.models import Phase, Player  # noqa: E402
from bot.nam10.nmnd_narrator import Role  # noqa: E402
from bot.nam10.night2 import PENDING_RESOLVED  # noqa: E402
from tests.test_namayande10_night_v2 import REAL_UIDS  # noqa: E402

AGT_UID = 910   # independent Mafia NATO agent (12/13)
SOL_UID = 911   # Soldier (town, 12/13)
CIT2_UID = 912  # extra Simple Citizen (13)

REAL_12 = [
    BOSS_UID, NATO_UID, SHIAD_UID, AGT_UID, LAW_UID, GUIDE_UID,
    GUARD_UID, DOC_UID, MINE_UID, SOL_UID, CIT1_UID, SYN_UID,
]


def _count_roles(roles):
    out: dict[str, int] = {}
    for r in roles:
        out[r.value] = out.get(r.value, 0) + 1
    return out


class NamExpansionRoomTest(Nam10NightV2Test):
    """12/13-player fork rooms driven through the real dispatcher."""

    def _fork12(self, *, players_13: bool = False, with_observer: bool = True):
        from bot.game_audit_log import init_audit_log

        n = 13 if players_13 else 12
        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=n,
            nam10_no_host=True,
        )
        assert game is not None
        roster = list(REAL_12) + ([CIT2_UID] if players_13 else [])
        seat = 0
        for uid in roster:
            seat += 1
            err = self.manager.add_player(
                game,
                Player(
                    user_id=uid,
                    full_name=f"بازیکن {seat}",
                    username=None,
                    role=None,
                    is_alive=True,
                    seat=seat,
                ),
            )
            assert err is None, err
        team_map = {
            BOSS_UID: Role.MAFIA_BOSS,
            NATO_UID: Role.NATO,
            SHIAD_UID: Role.SHIAD,
            AGT_UID: Role.NATO_AGENT,
            LAW_UID: Role.HUNTER,
            GUIDE_UID: Role.INTERROGATOR,
            GUARD_UID: Role.DETECTIVE,
            DOC_UID: Role.DOCTOR,
            MINE_UID: Role.RUINTAN,
            SOL_UID: Role.SOLDIER,
            CIT1_UID: Role.CITIZEN,
            SYN_UID: Role.CITIZEN,
        }
        if players_13:
            team_map[CIT2_UID] = Role.CITIZEN
        for uid, pl in game.players.items():
            pl.role = team_map[uid]
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nam10_intro_night_started = True
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_night_count = 1
        if with_observer:
            game.observer_user_id = OBS_UID
            game.observer_prompt_status = "registered"
        init_audit_log(game)
        self.game = game
        return game

    async def _walk12(
        self,
        *,
        boss_tid: int = 1,
        shot_target: int = DOC_UID,
        nato_role_tid: int | None = None,
        nato_target: int | None = None,
        doc_pick: int | None = CIT1_UID,
        hack_src: int = DOC_UID,
        hack_dst: int = SYN_UID,
        guide_target: int = NATO_UID,
        guard_target: int = BOSS_UID,
        mine_pick: int = 0,
        law_pick: int = 0,
        soldier_target: int | None = CIT1_UID,
        sniper_target: int | None = None,
        do_extra: bool = True,
        extra_target: int | None = None,
        players_13: bool = False,
    ) -> None:
        g = self.game
        if boss_tid == 3:
            await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
            await self._press(AGT_UID, "nrole", AGT_UID, tid=nato_role_tid)
            await self._press(AGT_UID, "nrok", AGT_UID)
            await self._press(AGT_UID, "npl", AGT_UID, tid=nato_target)
            await self._press(AGT_UID, "npok", AGT_UID)
        else:
            await self._press(BOSS_UID, "bmode", BOSS_UID, tid=boss_tid)
            if boss_tid in (1, 2):
                await self._press(BOSS_UID, "sht", BOSS_UID, tid=shot_target)
                await self._press(BOSS_UID, "shtok", BOSS_UID)
        if soldier_target is not None:
            await self._press(SOL_UID, "sldp", SOL_UID, tid=soldier_target)
            await self._press(SOL_UID, "sldok", SOL_UID)
        else:
            # Tests that do not exercise the Soldier consume the lifetime
            # allowance so the waiting ack is the only obligation.
            g.nmnd_night2_soldier_used = True
            await self._press(SOL_UID, "waitok", SOL_UID)
        if doc_pick is not None:
            await self._press(DOC_UID, "docp", DOC_UID, tid=doc_pick)
            await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=hack_src)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=hack_dst)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=guide_target)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=guard_target)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        await self._press(MINE_UID, "minp", MINE_UID, tid=mine_pick)
        await self._press(MINE_UID, "minok", MINE_UID)
        if mine_pick:
            await self._press(MINE_UID, "waitok", MINE_UID)
        await self._press(LAW_UID, "lawp", LAW_UID, tid=law_pick)
        await self._press(LAW_UID, "lawok", LAW_UID)
        if law_pick:
            await self._press(LAW_UID, "waitok", LAW_UID)
        await self._press(NATO_UID, "waitok", NATO_UID)
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        await self._press(OBS_UID, "waitok", SYN_UID)
        if players_13:
            await self._press(CIT2_UID, "waitok", CIT2_UID)
        await self._press(AGT_UID, "waitok", AGT_UID)
        if (
            do_extra
            and g.nmnd_night2_extra_kind == "extra_sent"
            and g.nmnd_night2_extra_uid is not None
            and g.nmnd_night2_extra_target_uid is None
        ):
            extra_uid = g.nmnd_night2_extra_uid
            actor = OBS_UID if extra_uid < 0 else extra_uid
            if extra_target is None:
                extra_target = DOC_UID if extra_uid != DOC_UID else CIT1_UID
            await self._press(actor, "exin", extra_uid, tid=extra_target)
            await self._press(actor, "exok", extra_uid)
        # Temporary Sniper (recipient may be synthetic -> observer presses)
        if g.nmnd_night2_soldier_grant_status == "delivered":
            sniper_uid = g.nmnd_night2_soldier_uid
            actor = OBS_UID if sniper_uid < 0 else sniper_uid
            if sniper_target is not None:
                await self._press(actor, "tsnp", sniper_uid, tid=sniper_target)
                await self._press(actor, "tsnok", sniper_uid)

    # -- independent NATO: agent waiting ack --------------------------
    async def test_agent_wait_panel_and_ack_key(self):
        from bot.nam10.night2 import night2_required_keys

        self._fork12()
        await self._enter_night()
        self.assertIn("NATO_AGENT", night2_required_keys(self.game))
        self.assertIn("🎭 ناتو", "\n".join(self.bot.texts_to(AGT_UID)))
        await self._press(AGT_UID, "waitok", AGT_UID)
        self.assertNotIn("NATO_AGENT", night2_required_keys(self.game))

    async def test_nato_mode_panels_route_to_agent(self):
        self._fork12()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        # The shooter is forbidden from the NATO stages; the agent owns them
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=1)
        self.assertTrue(
            any(
                "شما مجاز به این عمل نیستید" in (a or "")
                for a in self.bot.acks()
            )
        )
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        await self._press(AGT_UID, "nrok", AGT_UID)
        self.assertEqual(
            self.game.nmnd_night2_nato_role, Role.INTERROGATOR.value
        )
        await self._press(AGT_UID, "npl", AGT_UID, tid=GUIDE_UID)
        await self._press(AGT_UID, "npok", AGT_UID)
        self.assertEqual(self.game.nmnd_night2_nato_target_uid, GUIDE_UID)
        self.assertEqual(self.game.nmnd_night2_boss_phase, "done")

    async def test_nato_via_agent_correct_guess_resolves(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            boss_tid=3,
            nato_role_tid=2,       # INTERROGATOR (راهنما)
            nato_target=GUIDE_UID,
            doc_pick=None,
            soldier_target=None,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertFalse(self.game.players[GUIDE_UID].is_alive)
        self.assertTrue(self.game.nmnd_night2_nato_used)

    async def test_nato_via_agent_wrong_guess_survives(self):
        self._fork12()
        await self._enter_night()
        # Guess DOCTOR but target the Guide -> failure
        await self._walk12(
            boss_tid=3,
            nato_role_tid=1,
            nato_target=GUIDE_UID,
            doc_pick=None,
            soldier_target=None,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(self.game.players[GUIDE_UID].is_alive)

    async def test_dead_agent_rejects_nato_mode(self):
        from bot.nam10.night2 import night2_apply_elimination

        self._fork12()
        await self._enter_night()
        night2_apply_elimination(self.game, AGT_UID, "test")
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertTrue(
            any(
                "این مرحله دیگر فعال نیست" in (a or "")
                for a in self.bot.acks()
            )
        )
        self.assertIsNone(self.game.nmnd_night2_boss_mode)
        # the 10-player room keeps the shooter-owned NATO option
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertEqual(self.game.nmnd_night2_boss_phase, "nato_role")

    async def test_10_room_shooter_owned_nato_regression(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=2)
        await self._press(BOSS_UID, "nrok", BOSS_UID)
        await self._press(BOSS_UID, "npl", BOSS_UID, tid=GUIDE_UID)
        await self._press(BOSS_UID, "npok", BOSS_UID)
        self.assertEqual(self.game.nmnd_night2_nato_target_uid, GUIDE_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=NATO_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=BOSS_UID)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        await self._press(MINE_UID, "minok", MINE_UID)
        await self._press(LAW_UID, "lawp", LAW_UID, tid=0)
        await self._press(LAW_UID, "lawok", LAW_UID)
        await self._press(NATO_UID, "waitok", NATO_UID)
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        await self._press(OBS_UID, "waitok", SYN_UID)
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)

    async def test_13_room_full_walk_resolves(self):
        self._fork12(players_13=True)
        await self._enter_night()
        await self._walk12(
            players_13=True,
            soldier_target=CIT1_UID,
            sniper_target=SHIAD_UID,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertFalse(self.game.players[SHIAD_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)

    async def test_nato_usable_by_rebel_after_boss_death(self):
        self._fork12()
        from bot.nam10.night2 import night2_apply_elimination

        night2_apply_elimination(self.game, BOSS_UID, "test")
        await self._enter_night()
        # Rebel is the shooter now; NATO stages still route to the agent
        await self._press(NATO_UID, "bmode", NATO_UID, tid=3)
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        await self._press(AGT_UID, "nrok", AGT_UID)
        await self._press(AGT_UID, "npl", AGT_UID, tid=GUIDE_UID)
        await self._press(AGT_UID, "npok", AGT_UID)
        self.assertEqual(self.game.nmnd_night2_nato_target_uid, GUIDE_UID)

    async def test_11_room_full_walk_resolves(self):
        """11 players = the 10-player flow plus one extra citizen ack."""
        from bot.game_audit_log import init_audit_log
        from tests.test_namayande10_night_v2 import Nam10NightV2ResolveTest

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=11,
            nam10_no_host=True,
        )
        assert game is not None
        roster = list(REAL_UIDS) + [SYN_UID, CIT2_UID]
        seat = 0
        for uid in roster:
            seat += 1
            err = self.manager.add_player(
                game,
                Player(
                    user_id=uid,
                    full_name=f"بازیکن {seat}",
                    username=None,
                    role=None,
                    is_alive=True,
                    seat=seat,
                ),
            )
            assert err is None, err
        team_map = {
            BOSS_UID: Role.MAFIA_BOSS,
            NATO_UID: Role.NATO,
            SHIAD_UID: Role.SHIAD,
            LAW_UID: Role.HUNTER,
            GUIDE_UID: Role.INTERROGATOR,
            GUARD_UID: Role.DETECTIVE,
            DOC_UID: Role.DOCTOR,
            MINE_UID: Role.RUINTAN,
            CIT1_UID: Role.CITIZEN,
            SYN_UID: Role.CITIZEN,
            CIT2_UID: Role.CITIZEN,
        }
        for uid, pl in game.players.items():
            pl.role = team_map[uid]
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nam10_intro_night_started = True
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_night_count = 1
        game.observer_user_id = OBS_UID
        game.observer_prompt_status = "registered"
        init_audit_log(game)
        self.game = game
        await self._enter_night()
        await Nam10NightV2ResolveTest._walk_v2(self)
        await self._press(CIT2_UID, "waitok", CIT2_UID)
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertEqual(
            self.game.nmnd_night2_outcome["soldier_sniper"]["grant_status"],
            None,
        )

    # -- Hacker->MineLayer immunity (global, all counts) ------------------
    async def test_mine_source_pair_is_global_noop(self):
        self._fork12()
        await self._enter_night()
        # Hacker SOURCE = Mine Layer; the mine stays effective and no
        # special notification is produced.
        await self._walk12(
            doc_pick=CIT1_UID,
            hack_src=MINE_UID,
            hack_dst=CIT1_UID,
            mine_pick=CIT1_UID,
            soldier_target=None,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        mine = self.game.nmnd_night2_outcome["mine"]
        self.assertTrue(mine["placed"])
        self.assertFalse(mine.get("nullified_by_hacker", False))
        self.assertIsNotNone(self.game.nmnd_night2_active_mine_uid)
        self.assertTrue(self.game.nmnd_night2_mine_used)
        self.assertNotIn("ایمنی", "\n".join(self.bot.texts_to(MINE_UID)))

    async def test_mine_layer_destination_pair_is_also_noop(self):
        """§8: the SOURCE-side immunity makes the pair a no-op for every
        destination — a (mine -> X) pair never nullifies the mine."""
        self._fork12()
        await self._enter_night()
        await self._walk12(
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,
            hack_src=MINE_UID,
            hack_dst=GUIDE_UID,
            mine_pick=DOC_UID,
            soldier_target=None,
        )
        mine = self.game.nmnd_night2_outcome["mine"]
        self.assertTrue(mine["placed"])
        self.assertFalse(mine.get("nullified_by_hacker", False))
        self.assertIsNotNone(self.game.nmnd_night2_active_mine_uid)


class NamExpansionCompositionTest(NamExpansionRoomTest):
    # -- §1 exact distributions --------------------------------------
    async def test_roles_for_count_10_11_12_13(self):
        from bot.nam10.lobby import roles_for_count

        self.assertEqual(
            _count_roles(roles_for_count(10)),
            {
                "MAFIA_BOSS": 1, "NATO": 1, "SHIAD": 1, "HUNTER": 1,
                "INTERROGATOR": 1, "DETECTIVE": 1, "DOCTOR": 1,
                "RUINTAN": 1, "CITIZEN": 2,
            },
        )
        self.assertEqual(
            _count_roles(roles_for_count(11)),
            {
                "MAFIA_BOSS": 1, "NATO": 1, "SHIAD": 1, "HUNTER": 1,
                "INTERROGATOR": 1, "DETECTIVE": 1, "DOCTOR": 1,
                "RUINTAN": 1, "CITIZEN": 3,
            },
        )
        self.assertEqual(
            _count_roles(roles_for_count(12)),
            {
                "MAFIA_BOSS": 1, "NATO": 1, "SHIAD": 1, "NATO_AGENT": 1,
                "HUNTER": 1, "INTERROGATOR": 1, "DETECTIVE": 1,
                "DOCTOR": 1, "RUINTAN": 1, "SOLDIER": 1, "CITIZEN": 2,
            },
        )
        self.assertEqual(
            _count_roles(roles_for_count(13)),
            {
                "MAFIA_BOSS": 1, "NATO": 1, "SHIAD": 1, "NATO_AGENT": 1,
                "HUNTER": 1, "INTERROGATOR": 1, "DETECTIVE": 1,
                "DOCTOR": 1, "RUINTAN": 1, "SOLDIER": 1, "CITIZEN": 3,
            },
        )
        for bad in (9, 14):
            with self.assertRaises(ValueError):
                roles_for_count(bad)

    # -- §2 lobby/count gates ----------------------------------------
    async def test_create_game_accepts_10_to_13(self):
        for n in (10, 11, 12, 13):
            game = self.manager.create_game(
                host_id=1,
                scenario_name="namayande",
                max_players=n,
                nam10_no_host=True,
            )
            self.assertIsNotNone(game, n)
            self.assertEqual(game.max_players, n)
        for n in (9, 14):
            game = self.manager.create_game(
                host_id=1,
                scenario_name="namayande",
                max_players=n,
                nam10_no_host=True,
            )
            self.assertIsNone(game, n)

    async def test_faction_membership_expanded(self):
        from bot.game import is_mafia_team
        from bot.nam10.engine import nmnd_counts_as_alive_mafia_for_win

        self.assertTrue(is_mafia_team(Role.NATO_AGENT))
        self.assertFalse(is_mafia_team(Role.SOLDIER))
        game = self._fork12()
        agt = game.players[AGT_UID]
        sol = game.players[SOL_UID]
        self.assertTrue(nmnd_counts_as_alive_mafia_for_win(game, agt))
        self.assertFalse(nmnd_counts_as_alive_mafia_for_win(game, sol))

    async def test_assign_roles_namayande10_counts(self):
        from bot.nam10.lobby import assign_roles_namayande10

        for n in (10, 11, 12, 13):
            game = self.manager.create_game(
                host_id=1,
                scenario_name="namayande",
                max_players=n,
                nam10_no_host=True,
            )
            for i in range(n):
                self.manager.add_player(
                    game,
                    Player(
                        user_id=1000 + i,
                        full_name=f"P{i}",
                        username=None,
                        role=None,
                        is_alive=True,
                        seat=i + 1,
                    ),
                )
            assign_roles_namayande10(game)
            dealt = _count_roles(
                [p.role for p in game.players.values() if p.role]
            )
            self.assertEqual(dealt, _count_roles(_rfc(n)), n)

    async def test_role_labels_and_descriptions_present(self):
        from bot.nam10.role_labels import (
            nam10_role_description_fa,
            nam10_role_label_fa,
        )

        self.assertEqual(nam10_role_label_fa(Role.SOLDIER), "سرباز")
        self.assertEqual(nam10_role_label_fa(Role.NATO_AGENT), "ناتو")
        self.assertTrue(nam10_role_description_fa(Role.SOLDIER))
        self.assertTrue(nam10_role_description_fa(Role.NATO_AGENT))


def _rfc(n):
    from bot.nam10.lobby import roles_for_count

    return roles_for_count(n)


class NamExpansionSoldierTest(NamExpansionRoomTest):
    # -- panels --------------------------------------------------------
    async def test_soldier_panel_no_skip_must_select(self):
        from bot.nam10.night2 import night2_required_keys

        self._fork12()
        await self._enter_night()
        self.assertIn("SOLDIER", night2_required_keys(self.game))
        text = "\n".join(self.bot.texts_to(SOL_UID))
        self.assertIn("🪖 انتخاب اسنایپر", text)
        acts = [
            cb.act for cb in self._panel_buttons("انتخاب اسنایپر", SOL_UID)
        ]
        self.assertIn("sldok", acts)
        self.assertNotIn("waitok", acts)

    async def test_soldier_panel_forbidden_for_others(self):
        self._fork12()
        await self._enter_night()
        await self._press(BOSS_UID, "sldp", BOSS_UID, tid=CIT1_UID)
        self.assertTrue(
            any(
                "شما مجاز به این عمل نیستید" in (a or "")
                for a in self.bot.acks()
            )
        )
        self.assertIsNone(self.game.nmnd_night2_soldier_pending_uid)

    async def test_soldier_panel_shows_night_number(self):
        self._fork12()
        await self._enter_night()
        text = "\n".join(self.bot.texts_to(SOL_UID))
        self.assertIn("🌙 شب:", text)

    async def test_soldier_zero_target_confirm_rejected(self):
        self._fork12()
        await self._enter_night()
        await self._press(SOL_UID, "sldok", SOL_UID)
        self.assertTrue(
            any("ابتدا یک بازیکن" in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(self.game.nmnd_night2_soldier_uid)

    # -- grant lifecycle -----------------------------------------------
    async def test_mafia_target_no_grant_soldier_eliminated(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(soldier_target=NATO_UID)
        self.assertEqual(
            self.game.nmnd_night2_soldier_grant_status, "mafia_target"
        )
        self.assertFalse(self.game.nmnd_night2_soldier_used)
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertFalse(self.game.players[SOL_UID].is_alive)
        self.assertTrue(self.game.players[NATO_UID].is_alive)
        self.assertNotIn(
            "🎯 قابلیت اسنایپر", "\n".join(self.bot.texts_to(NATO_UID))
        )

    async def test_grant_pending_blocks_night_until_hacker(self):
        from bot.nam10.night2 import night2_required_keys

        self._fork12()
        await self._enter_night()
        await self._press(SOL_UID, "sldp", SOL_UID, tid=CIT1_UID)
        await self._press(SOL_UID, "sldok", SOL_UID)
        # Hacker unconfirmed -> the pending grant keeps the night open
        self.assertEqual(self.game.nmnd_night2_soldier_grant_status, "pending")
        self.assertIn("n2grant", night2_required_keys(self.game))
        self.assertNotIn(
            "🎯 قابلیت اسنایپر", "\n".join(self.bot.texts_to(CIT1_UID))
        )

    async def test_grant_intercepted_silent_no_charge(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            soldier_target=CIT1_UID,
            hack_src=SOL_UID,
            hack_dst=CIT1_UID,
            doc_pick=CIT1_UID,
        )
        self.assertEqual(
            self.game.nmnd_night2_soldier_grant_status, "intercepted"
        )
        self.assertFalse(self.game.nmnd_night2_soldier_used)
        self.assertTrue(self.game.players[SOL_UID].is_alive)
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertNotIn(
            "🎯 قابلیت اسنایپر", "\n".join(self.bot.texts_to(CIT1_UID))
        )

    async def test_grant_delivered_consumes_charge_once(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(soldier_target=CIT1_UID, sniper_target=BOSS_UID)
        self.assertEqual(
            self.game.nmnd_night2_soldier_grant_status, "delivered"
        )
        self.assertTrue(self.game.nmnd_night2_soldier_used)
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(self.game.nmnd_night2_sniper_delivered_refs)

    async def test_failed_delivery_keeps_pending_no_charge(self):
        from bot.nam10.night2 import night2_required_keys

        self._fork12()
        await self._enter_night()
        await self._press(SOL_UID, "sldp", SOL_UID, tid=CIT1_UID)
        await self._press(SOL_UID, "sldok", SOL_UID)
        with patch(
            "bot.observer_delivery.safe_send_message_return",
            return_value=None,
        ):
            await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
            await self._press(SHIAD_UID, "hacn", SHIAD_UID)
            await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
            await self._press(SHIAD_UID, "hacok", SHIAD_UID)
            await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=NATO_UID)
            await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
            await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=BOSS_UID)
            await self._press(GUARD_UID, "gdnok", GUARD_UID)
            await self._press(MINE_UID, "minp", MINE_UID, tid=0)
            await self._press(MINE_UID, "minok", MINE_UID)
            await self._press(LAW_UID, "lawp", LAW_UID, tid=0)
            await self._press(LAW_UID, "lawok", LAW_UID)
            await self._press(NATO_UID, "waitok", NATO_UID)
            await self._press(CIT1_UID, "waitok", CIT1_UID)
            await self._press(OBS_UID, "waitok", SYN_UID)
        # delivery failed: grant still pending, charge not consumed, the
        # night cannot finish
        self.assertEqual(self.game.nmnd_night2_soldier_grant_status, "pending")
        self.assertFalse(self.game.nmnd_night2_soldier_used)
        self.assertIn("n2grant", night2_required_keys(self.game))
        self.assertNotEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        # a later successful reconcile tick delivers the panel
        await self._press(AGT_UID, "waitok", AGT_UID)
        self.assertEqual(
            self.game.nmnd_night2_soldier_grant_status, "delivered"
        )

    # -- temporary Sniper outcomes --------------------------------------
    async def test_sniper_shoot_boss_both_survive(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            soldier_target=CIT1_UID,
            sniper_target=BOSS_UID,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(self.game.players[BOSS_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        out = self.game.nmnd_night2_outcome["soldier_sniper"]
        self.assertEqual(out["reason"], "boss_immune")
        self.assertIsNone(out["eliminated_uid"])

    async def test_sniper_shoot_rebel_rebel_dies_sniper_survives(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            soldier_target=CIT1_UID,
            sniper_target=NATO_UID,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertFalse(self.game.players[NATO_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        out = self.game.nmnd_night2_outcome["soldier_sniper"]
        self.assertEqual(out["reason"], "mafia_member_eliminated")

    async def test_sniper_shoot_town_sniper_dies_target_survives(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            soldier_target=CIT1_UID,
            sniper_target=GUIDE_UID,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(self.game.players[GUIDE_UID].is_alive)
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        out = self.game.nmnd_night2_outcome["soldier_sniper"]
        self.assertTrue(out["sniper_eliminated"])

    async def test_sniper_shoot_nato_agent_agent_dies(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            soldier_target=CIT1_UID,
            sniper_target=AGT_UID,
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertFalse(self.game.players[AGT_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)

    async def test_sniper_skip_removed_mandatory_shot(self):
        from bot.nam10.night2 import (
            PENDING_COLLECTING,
            night2_required_keys,
        )

        self._fork12()
        await self._enter_night()
        await self._walk12(soldier_target=CIT1_UID)
        # The delivered panel has no skip/no-shot button and the
        # obligation stays pending until one target is confirmed.
        panel = "\n".join(self.bot.texts_to(CIT1_UID))
        self.assertIn("🎯 قابلیت اسنایپر", panel)
        self.assertNotIn("انتخابی ندارم", panel)
        self.assertIn("n2sniper", night2_required_keys(self.game))
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_COLLECTING)
        # A forged/stale skip callback is rejected without any effect.
        await self._press(CIT1_UID, "tsns", CIT1_UID)
        self.assertFalse(self.game.nmnd_night2_sniper_skipped)
        self.assertFalse(self.game.nmnd_night2_sniper_resolved)
        self.assertIn("n2sniper", night2_required_keys(self.game))
        # Zero-target confirmation is rejected.
        await self._press(CIT1_UID, "tsnok", CIT1_UID)
        self.assertFalse(self.game.nmnd_night2_sniper_resolved)
        # Selecting a player replaces the pending target; confirmation
        # resolves the mandatory obligation exactly once.
        await self._press(CIT1_UID, "tsnp", CIT1_UID, tid=BOSS_UID)
        await self._press(CIT1_UID, "tsnp", CIT1_UID, tid=GUIDE_UID)
        await self._press(CIT1_UID, "tsnp", CIT1_UID, tid=GUIDE_UID)
        self.assertEqual(self.game.nmnd_night2_sniper_pending_uid, None)
        await self._press(CIT1_UID, "tsnp", CIT1_UID, tid=GUIDE_UID)
        await self._press(CIT1_UID, "tsnok", CIT1_UID)
        self.assertTrue(self.game.nmnd_night2_sniper_resolved)
        self.assertEqual(self.game.nmnd_night2_sniper_target_uid, GUIDE_UID)
        self.assertNotIn("n2sniper", night2_required_keys(self.game))
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)

    # -- lifecycle durability -------------------------------------------
    async def test_soldier_spent_ack_panel_later_night(self):
        from bot.nam10.night2 import _dispatch_entry_panels

        self._fork12()
        await self._enter_night()
        await self._walk12(soldier_target=CIT1_UID, sniper_target=BOSS_UID)
        self.assertTrue(self.game.nmnd_night2_soldier_used)
        # simulate the next night's entry dispatch surface
        await _dispatch_entry_panels(self.bot, self.game, self.manager)
        text = "\n".join(self.bot.texts_to(SOL_UID))
        self.assertIn(
            "قبلاً از قابلیت انتخاب اسنایپر استفاده کرده‌اید", text
        )

    async def test_soldier_state_snapshot_roundtrip(self):
        from bot.game_snapshot import (
            game_from_snapshot_dict,
            game_to_snapshot_dict,
        )

        self._fork12()
        await self._enter_night()
        await self._walk12(soldier_target=CIT1_UID, sniper_target=BOSS_UID)
        payload = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(payload)
        for attr in (
            "nmnd_night2_soldier_used",
            "nmnd_night2_soldier_used_night",
            "nmnd_night2_soldier_grant_status",
            "nmnd_night2_sniper_night",
            "nmnd_night2_sniper_result",
        ):
            self.assertEqual(
                getattr(restored, attr), getattr(self.game, attr), attr
            )


class NamExpansionReportTest(NamExpansionRoomTest):
    def _report(self):
        from bot.nam10.night2_publish import night2_night_report_extra_section

        return night2_night_report_extra_section(self.game, self.manager)

    async def test_report_soldier_sniper_lines(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            soldier_target=CIT1_UID,
            sniper_target=NATO_UID,
        )
        report = self._report()
        self.assertIn("🪖 سرباز: قابلیت اسنایپر به بازیکن", report)
        self.assertIn("🎯 اسنایپر:", report)
        self.assertIn("از بازی خارج شد", report)

    async def test_report_soldier_intercepted_line(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            soldier_target=CIT1_UID,
            hack_src=SOL_UID,
            hack_dst=CIT1_UID,
        )
        report = self._report()
        self.assertIn("🪖 سرباز:", report)
        self.assertIn("توسط هکر قطع شد", report)

    async def test_report_10_room_has_no_soldier_section(self):
        from tests.test_namayande10_night_v2 import Nam10NightV2ResolveTest

        self._fork_room()
        await self._enter_night()
        await Nam10NightV2ResolveTest._walk_v2(self)
        self.assertNotIn("🪖 سرباز", self._report())

    async def test_nato_night_report_no_ordinary_shot_line(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(
            boss_tid=3,
            nato_role_tid=2,
            nato_target=GUIDE_UID,
            doc_pick=None,
            soldier_target=None,
        )
        report = self._report()
        self.assertNotIn("🔴 شات مافیا", report)


def load_tests(loader, tests, pattern):
    """Collect only the tests defined in this module."""
    suite = unittest.TestSuite()
    for cls in (
        NamExpansionCompositionTest,
        NamExpansionRoomTest,
        NamExpansionSoldierTest,
        NamExpansionReportTest,
    ):
        for name in sorted(n for n in cls.__dict__ if n.startswith("test_")):
            suite.addTest(cls(name))
    return suite
