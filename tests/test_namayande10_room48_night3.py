#!/usr/bin/env python3
"""Namayande — Room 48 Night 3 missing Mafia shooting panel.

Room 48 (12-player): by Night 3 the whole named shooter chain
(Boss/Rebel/Hacker) was dead while the independent NATO agent (the only
living Mafia-team member) was alive. ``night2_active_shooter`` returned
None (the legacy "first living mafia member" fallback was missing), so
no shooting panel was created and the night resolved with no Mafia main
action. These tests pin the restored fallback and the shooter-succession
behaviour across Night-3 configurations.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_expansion as _exp  # noqa: E402
import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from tests.test_namayande10_expansion import (  # noqa: E402
    AGT_UID,
    CIT2_UID,
    SOL_UID,
)
from tests.test_namayande10_night_publish import (  # noqa: E402
    _SkipInheritedTests,
)
from tests.test_namayande10_night_v2 import (  # noqa: E402
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    GUIDE_UID,
    GUARD_UID,
    LAW_UID,
    MINE_UID,
    NATO_UID,
    OBS_UID,
    SHIAD_UID,
    SYN_UID,
)

from bot.nam10.night2 import (  # noqa: E402
    ALERT_STALE,
    night2_active_shooter,
    night2_maybe_finish,
    night2_required_keys,
    nam10_night2_entry_dispatch,
)
from bot.observer_delivery import PlayerMirrorCb, mirror_ui_claim_key  # noqa: E402

BOSS_MENU_MARK = "انتخاب قابلیت رئیس مافیا"
SHOOTER_MENU_MARK = "جانشین رئیس مافیا"


class _SkipAllInherited(_SkipInheritedTests):
    """Shadow inherited test methods across the whole MRO."""

    def __new__(mcls, name, bases, ns):
        cls = super().__new__(mcls, name, bases, ns)
        own = set(ns)
        for k in range(len(cls.__mro__)):
            base = cls.__mro__[k]
            if base is cls or base is object:
                continue
            for attr in [
                a for a in vars(base) if a.startswith("test_") and a not in own
            ]:
                setattr(cls, attr, None)
        return cls


class Room48Night3ShooterTest(
    _exp.NamExpansionRoomTest, metaclass=_SkipAllInherited
):
    """Night-3 shooting panel delivery across succession cases."""

    async def _enter_night3(self, *, dead=(), nato_used=False,
                            neutral_used=False):
        """Simulate opening Night 3 with the given players eliminated."""
        self._fork12()
        await self._enter_night()
        for uid in dead:
            self.game.players[uid].is_alive = False
        g = self.game
        g.nmnd_narrator_night_count = 3
        # nmnd_night2_night_count is advanced by the entry dispatcher
        # itself; leaving it stale is what makes the dispatcher run the
        # per-night reset and render the Night-3 panels.
        if nato_used:
            g.nmnd_night2_nato_used = True
            g.nmnd_night2_nato_used_night = 1
        if neutral_used:
            g.nmnd_night2_boss_neutral_shot_used = True
        ok = await nam10_night2_entry_dispatch(self.bot, g, self.manager)
        self.assertTrue(ok)
        return g

    async def _settle_others(self, g, *, doc=True) -> None:
        """Settle every non-shooter Night-3 obligation (Room 48 shape)."""
        if doc:
            await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
            await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=CIT1_UID)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        await self._press(MINE_UID, "minok", MINE_UID)
        await self._press(LAW_UID, "lawp", LAW_UID, tid=0)
        await self._press(LAW_UID, "lawok", LAW_UID)
        g.nmnd_night2_soldier_used = True
        await self._press(SOL_UID, "waitok", SOL_UID)
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        await self._press(OBS_UID, "waitok", SYN_UID)
        await self._press(CIT1_UID, "exin", CIT1_UID, tid=DOC_UID)
        await self._press(CIT1_UID, "exok", CIT1_UID)

    def _menu_tids(self, mark: str) -> set[int]:
        tids: set[int] = set()
        for text, kb in self.bot.kb_segments():
            if mark in text and kb is not None:
                for row in kb.inline_keyboard:
                    for b in row:
                        cb = PlayerMirrorCb.unpack(b.callback_data or "")
                        if cb is not None:
                            tids.add(cb.tid)
        return tids

    # ------------------------------------------------------------- tests

    async def test_night3_boss_alive_gets_panel(self):
        g = await self._enter_night3()
        self.assertEqual(night2_active_shooter(g).user_id, BOSS_UID)
        self.assertIn("MAFIA_BOSS", night2_required_keys(g))
        # Boss menu with the NATO option still available.
        self.assertEqual(self._menu_tids(BOSS_MENU_MARK), {1, 2, 3})

    async def test_night3_rebel_inherits_after_boss_dead(self):
        g = await self._enter_night3(dead=(BOSS_UID,))
        self.assertEqual(night2_active_shooter(g).user_id, NATO_UID)
        # The shooting obligation replaces the Rebel waiting ack.
        keys = night2_required_keys(g)
        self.assertIn("NATO", keys)
        # Successor menu, NATO still unused.
        self.assertEqual(self._menu_tids(SHOOTER_MENU_MARK), {1, 2, 3})

    async def test_night3_hacker_inherits_and_keeps_hacking(self):
        g = await self._enter_night3(dead=(BOSS_UID, NATO_UID))
        self.assertEqual(night2_active_shooter(g).user_id, SHIAD_UID)
        keys = night2_required_keys(g)
        self.assertIn("SHIAD", keys)
        # The Hacker keeps his own intercept panel AND inherits the shot.
        texts = "\n".join(self.bot.texts_to(SHIAD_UID))
        self.assertIn("هکر", texts)
        self.assertEqual(self._menu_tids(SHOOTER_MENU_MARK), {1, 2, 3})

    async def test_night3_agent_inherits_after_chain_dead(self):
        """The Room 48 case: only the NATO agent is left on the team."""
        from bot.models import Role

        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID),
            nato_used=True,
        )
        self.assertEqual(night2_active_shooter(g).user_id, AGT_UID)
        # The agent receives the successor shooting panel (NATO already
        # used in Night 1: only the two shot modes are offered).
        self.assertEqual(self._menu_tids(SHOOTER_MENU_MARK), {1, 2})
        self.assertIn(
            SHOOTER_MENU_MARK, "\n".join(self.bot.texts_to(AGT_UID))
        )
        # The shooting obligation blocks completion; no chain-role key.
        keys = night2_required_keys(g)
        self.assertIn("NATO_AGENT", keys)
        for k in ("MAFIA_BOSS", "NATO", "SHIAD"):
            self.assertNotIn(k, keys)
        self.assertFalse(night2_maybe_finish(g, self.manager))

    async def test_agent_shooter_end_to_end_shot_resolves(self):
        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID), nato_used=True
        )
        await self._settle_others(g)
        # Only the agent's shooting obligation remains pending.
        self.assertEqual(night2_required_keys(g), ["NATO_AGENT"])
        # The agent shoots: mode + target + confirm.
        await self._press(AGT_UID, "bmode", AGT_UID, tid=1)
        await self._press(AGT_UID, "sht", AGT_UID, tid=GUIDE_UID)
        await self._press(AGT_UID, "shtok", AGT_UID)
        self.assertTrue(g.nmnd_night2_outcome_committed)
        self.assertTrue(g.nmnd_night2_resolved)
        shot = g.nmnd_night2_shot_result or {}
        self.assertTrue(shot.get("eliminated"), shot)
        self.assertEqual(shot.get("target_uid"), GUIDE_UID)
        self.assertTrue(g.players[GUIDE_UID].is_alive is False)

    async def test_agent_shooter_nato_unused_available_end_to_end(self):
        g = await self._enter_night3(dead=(BOSS_UID, NATO_UID, SHIAD_UID))
        # NATO unused → the agent shooter may use it (he is also the
        # NATO actor in 12/13 rooms).
        self.assertEqual(self._menu_tids(SHOOTER_MENU_MARK), {1, 2, 3})
        await self._press(AGT_UID, "bmode", AGT_UID, tid=3)
        self.assertTrue(g.nmnd_night2_nato_used)
        self.assertEqual(g.nmnd_night2_nato_used_night, 3)
        # Handoff: the shooter menu panel is deleted, the stage-1 panel
        # is delivered to the same agent (he owns both obligations).
        agent_key = mirror_ui_claim_key(g.room_code, "n2boss", AGT_UID)
        self.assertNotIn(agent_key, g.mirror_prompt_messages)
        self.assertIn("🎭 ناتو", "\n".join(self.bot.texts_to(AGT_UID)))
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        await self._press(AGT_UID, "nrok", AGT_UID)
        await self._press(AGT_UID, "npl", AGT_UID, tid=GUIDE_UID)
        await self._press(AGT_UID, "npok", AGT_UID)
        # NATO completed (agent = shooter → no extra waiting ack owed);
        # the remaining town obligations still have to be settled before
        # the night resolves.
        self.assertFalse(g.nmnd_night2_outcome_committed)
        await self._settle_others(g, doc=False)
        self.assertTrue(g.nmnd_night2_outcome_committed)
        outcome = g.nmnd_night2_outcome or {}
        nato = outcome.get("nato") or {}
        self.assertTrue(nato.get("activated"))
        self.assertTrue(nato.get("success"))

    async def test_neutralized_allowance_not_reset_on_succession(self):
        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID),
            nato_used=True,
            neutral_used=True,
        )
        self.assertEqual(self._menu_tids(SHOOTER_MENU_MARK), {1})
        await self._press(AGT_UID, "bmode", AGT_UID, tid=2)
        self.assertIn(ALERT_STALE, self.bot.acks())
        self.assertIsNone(g.nmnd_night2_boss_mode)

    async def test_night_specific_callback_validity(self):
        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID), nato_used=True
        )
        # Valid during Night 3 collection...
        await self._press(AGT_UID, "bmode", AGT_UID, tid=1)
        self.assertEqual(g.nmnd_night2_boss_mode, "shot_plain")
        g.nmnd_night2_outcome_committed = False
        g.nmnd_night2_phase = "collected"
        self.bot.acks()
        self.bot.calls.clear()
        # ...and rejected after the collection closed.
        await self._press(AGT_UID, "bmode", AGT_UID, tid=2)
        self.assertIn(ALERT_STALE, self.bot.acks())

    async def test_recovery_redispatch_renders_same_panel(self):
        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID), nato_used=True
        )
        key = mirror_ui_claim_key(g.room_code, "n2boss", AGT_UID)
        self.assertIn(key, g.mirror_prompt_messages)
        # Re-entry (restart recovery / retry) re-renders the same panel
        # registration instead of duplicating it.
        g.nmnd_night2_entry_dispatched = False
        ok = await nam10_night2_entry_dispatch(self.bot, g, self.manager)
        self.assertTrue(ok)
        self.assertIn(key, g.mirror_prompt_messages)

    async def test_agent_panel_mirrored_for_real_and_observer(self):
        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID), nato_used=True
        )
        key = mirror_ui_claim_key(g.room_code, "n2boss", AGT_UID)
        entry = g.mirror_prompt_messages.get(key) or {}
        # Real player: direct player panel; observer mirror registered.
        self.assertTrue(entry.get("player"))
        self.assertTrue(entry.get("observer"))

    async def test_synthetic_agent_shooter_mirrors_to_observer(self):
        from bot.models import Role

        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID), nato_used=True
        )
        # Swap: the synthetic seat holds the NATO agent role.
        g.players[SYN_UID].role = Role.NATO_AGENT
        g.players[AGT_UID].role = Role.CITIZEN
        g.nmnd_night2_entry_dispatched = False
        ok = await nam10_night2_entry_dispatch(self.bot, g, self.manager)
        self.assertTrue(ok)
        self.assertEqual(night2_active_shooter(g).user_id, SYN_UID)
        key = mirror_ui_claim_key(g.room_code, "n2boss", SYN_UID)
        entry = g.mirror_prompt_messages.get(key) or {}
        # Synthetic seat: observer-only delivery.
        self.assertTrue(entry.get("observer"))
        self.assertIn(
            SHOOTER_MENU_MARK, "\n".join(self.bot.texts_to(OBS_UID))
        )
        # The observer operates the synthetic shooter's panel.
        await self._press(OBS_UID, "bmode", SYN_UID, tid=1)
        self.assertEqual(g.nmnd_night2_boss_mode, "shot_plain")
        self.assertNotIn(
            ALERT_STALE, [a or "" for a in self.bot.acks()[-1:]]
        )

    async def test_no_mafia_alive_resolves_without_fictional_action(self):
        """When NO Mafia-team member is alive at all: no fabricated panel."""
        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID, AGT_UID)
        )
        self.assertIsNone(night2_active_shooter(g))
        keys = night2_required_keys(g)
        for k in ("MAFIA_BOSS", "NATO", "SHIAD", "NATO_AGENT"):
            self.assertNotIn(k, keys)

    async def test_night3_state_survives_snapshot_restore(self):
        from bot.game import GameManager
        from bot.game_snapshot import (
            persist_game_snapshot,
            restore_games_into_manager,
        )

        g = await self._enter_night3(
            dead=(BOSS_UID, NATO_UID, SHIAD_UID), nato_used=True
        )
        self.assertEqual(night2_active_shooter(g).user_id, AGT_UID)
        persist_game_snapshot(g, reason="test_room48")
        code = g.room_code
        self.manager.games.pop(code, None)
        self.manager.host_to_room.pop(g.host_id, None)
        m2 = GameManager()
        restore_games_into_manager(m2)
        back = m2.get_game(code)
        self.assertIsNotNone(back)
        # The inherited shooting obligation survives the restart.
        self.assertEqual(night2_active_shooter(back).user_id, AGT_UID)
        self.assertIn("NATO_AGENT", night2_required_keys(back))


if __name__ == "__main__":
    unittest.main()
