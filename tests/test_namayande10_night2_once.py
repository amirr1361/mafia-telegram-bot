"""Namayande-10 Night v2 — Mafia Boss once-per-game neutralized shot,
Doctor self-save option omission, and the game-ended publication flow.

Change A: the Mafia Boss's «شات به همراه خنثی‌سازی» (Shot With
Neutralization) is a lifetime once-per-game ability. The allowance is
consumed exactly once at the confirmed-target moment (a mode tap alone
never consumes), persists independently from NATO usage across nights
and snapshots, disappears from every later night's Boss menu, and
replayed callbacks are rejected.

Change B: the Doctor's night selection panel omits the «خودم» option
completely once both lifetime self-save charges are consumed
(mirroring ``roles_doctor.self_save_pool_excludes_doctor``), while the
short usage description stays on the panel; forged selections are
still rejected server-side and a valid NATO rollback restores the
option.

Change C: when the winner is already decided when the Night-v2
publication flow reaches the discipline stage (Room 19 defect), the
established post-night flow must still run: night results broadcast,
night resolution, then winner announcement + game finalization through
the established faction-win path — instead of freezing with the
discipline ask skipped and nothing delivered.
"""

import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

from bot.observer_delivery import PlayerMirrorCb  # noqa: E402
from tests.test_namayande10_night_publish import _SkipInheritedTests  # noqa: E402
import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from tests.test_namayande10_night_v2 import (  # noqa: E402
    ASSIST_UID,
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
    SHOT_MARK,
    SYN_UID,
)

from bot.models import Phase  # noqa: E402
from bot.nam10.night2 import (  # noqa: E402
    ACT_BOSS_MODE,
    ACT_DOC_OK,
    ACT_DOC_PICK,
    ACT_SHOT_TGT,
    ACT_SHOT_TGT_OK,
    BOSS_MODE_SHOT_NEUTRALIZED,
    BOSS_MODE_SHOT_PLAIN,
    BOSS_PHASE_MENU,
    N2_MAX_SELF_SAVES,
)
from bot.nam10 import night2 as night2_mod  # noqa: E402
from bot.nam10 import night2_publish  # noqa: E402

BOSS_MENU_MARK = "قابلیت رئیس مافیا"
DOC_PANEL_MARK = "انتخاب پزشک"
DISCIPLINE_MARK = "انضباطی"
STALE_ALERT = _v2.STALE_ALERT
SELF_QUOTA_ALERT = "سهمیهٔ نجات خود شما تمام شده است."
SELF_RETURN_LABEL = "خودم"
NIGHT_RESULTS_MARK = "خداحافظی"
WIN_BROADCAST_MARK = "برد مافیا"


class Nam10Night2OnceTest(_v2.Nam10NightV2Test, metaclass=_SkipInheritedTests):
    """Once-per-game Boss shot, Doctor self-save UI, game-end hand-off."""

    # ------------------------------------------------------------ helpers

    async def _fork_night(self):
        self._fork_room()
        await self._enter_night()
        return self.game

    def _boss_menu_tids(self):
        return [cb.tid for cb in self._panel_buttons(BOSS_MENU_MARK)]

    def _panel_tids(self, mark):
        return [cb.tid for cb in self._panel_buttons(mark)]

    def _doctor_panel_available(self):
        from bot.nam10.night2 import _send_doctor_pick_panel

        return _send_doctor_pick_panel(self.bot, self.game, DOC_UID)

    def _last_texts(self):
        return self.bot.texts()

    # ------------------------------------------------------- (A) Boss shot

    async def test_neutralized_shot_menu_then_gone_after_confirm(self):
        """Menu offers the neutralized shot once; consumed on confirm."""
        game = await self._fork_night()
        self.assertIn(2, self._boss_menu_tids(), "mode 2 must be offered")
        # Sorting the mode alone must never consume the allowance.
        await self._press(BOSS_UID, ACT_BOSS_MODE, BOSS_UID, tid=2)
        self.assertFalse(game.nmnd_night2_boss_neutral_shot_used)
        self.assertNotIn(
            BOSS_MODE_SHOT_NEUTRALIZED,
            game.nmnd_night2_dispositions.values(),
        )
        # Target panel renders for the selected mode.
        self.assertIn(DOC_UID, self._panel_tids(SHOT_MARK))
        # Confirm the target -> consume exactly once.
        await self._press(BOSS_UID, ACT_SHOT_TGT, BOSS_UID, tid=DOC_UID)
        await self._press(BOSS_UID, ACT_SHOT_TGT_OK, BOSS_UID)
        self.assertTrue(game.nmnd_night2_boss_neutral_shot_used)
        self.assertEqual(game.nmnd_night2_boss_neutral_shot_used_night, 1)
        self.assertEqual(
            game.nmnd_night2_dispositions.get(f"boss_mode:{BOSS_UID}"),
            BOSS_MODE_SHOT_NEUTRALIZED,
        )
        # NATO's independent lifetime flag stays untouched.
        self.assertFalse(game.nmnd_night2_nato_used)

    async def test_neutralized_shot_gone_next_night_forged_rejected(self):
        """Later-night menu omits the used shot and rejects its callback."""
        game = await self._fork_night()
        await self._press(BOSS_UID, ACT_BOSS_MODE, BOSS_UID, tid=2)
        await self._press(BOSS_UID, ACT_SHOT_TGT, BOSS_UID, tid=DOC_UID)
        await self._press(BOSS_UID, ACT_SHOT_TGT_OK, BOSS_UID)

        # A replayed confirm callback must be rejected (stale phase) and
        # never consume twice.
        self.assertTrue(game.nmnd_night2_boss_neutral_shot_used)
        await self._press(BOSS_UID, ACT_SHOT_TGT, BOSS_UID, tid=DOC_UID)
        await self._press(BOSS_UID, ACT_SHOT_TGT_OK, BOSS_UID)
        self.assertEqual(game.nmnd_night2_boss_neutral_shot_used_night, 1)
        self.assertEqual(
            game.nmnd_night2_dispositions.get(f"boss_mode:{BOSS_UID}"),
            BOSS_MODE_SHOT_NEUTRALIZED,
        )

        # Enter the next night: the option must not be offered again.
        game.nmnd_narrator_night_count = 2
        game.nmnd_narrator_host_day = 2
        await night2_mod.nam10_night2_entry_dispatch(
            self.bot, game, self.manager
        )
        tids = self._boss_menu_tids()
        self.assertNotIn(2, tids, "used shot must not be offered again")
        self.assertIn(1, tids, "plain shot must remain available")
        self.assertIn(3, tids, "NATO option must remain available")
        self.assertFalse(game.nmnd_night2_nato_used)

        # Forged/stale tid=2 callback is rejected; no state is changed.
        await self._press(BOSS_UID, ACT_BOSS_MODE, BOSS_UID, tid=2)
        self.assertIn(STALE_ALERT, self.bot.acks())
        self.assertIsNone(game.nmnd_night2_boss_mode)
        self.assertEqual(game.nmnd_night2_boss_phase, BOSS_PHASE_MENU)
        self.assertFalse(game.nmnd_night2_boss_shot_marked)

        # The plain shot still works normally.
        await self._press(BOSS_UID, ACT_BOSS_MODE, BOSS_UID, tid=1)
        self.assertEqual(game.nmnd_night2_boss_mode, BOSS_MODE_SHOT_PLAIN)
        self.assertIn(DOC_UID, self._panel_tids(SHOT_MARK))

    async def test_neutralized_shot_flag_survives_snapshot_roundtrip(self):
        """The lifetime allowance is durable across snapshot restore."""
        game = await self._fork_night()
        await self._press(BOSS_UID, ACT_BOSS_MODE, BOSS_UID, tid=2)
        await self._press(BOSS_UID, ACT_SHOT_TGT, BOSS_UID, tid=DOC_UID)
        await self._press(BOSS_UID, ACT_SHOT_TGT_OK, BOSS_UID)
        self.manager.persist_snapshot(game, reason="test_neutral_shot")

        from bot.game_snapshot import game_from_snapshot_dict

        conn = sqlite3.connect(self._db)
        try:
            row = conn.execute(
                "SELECT snapshot_json FROM active_game_snapshots "
                "WHERE room_code=?",
                (game.room_code,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        restored = game_from_snapshot_dict(json.loads(row[0]))
        self.assertTrue(restored.nmnd_night2_boss_neutral_shot_used)
        self.assertEqual(
            restored.nmnd_night2_boss_neutral_shot_used_night, 1
        )

    async def test_plain_shot_menu_after_neutralized_use_keeps_parity(self):
        """Plain shot is unaffected; no shared usage flag with NATO."""
        game = await self._fork_night()
        await self._press(BOSS_UID, ACT_BOSS_MODE, BOSS_UID, tid=2)
        await self._press(BOSS_UID, ACT_SHOT_TGT, BOSS_UID, tid=DOC_UID)
        await self._press(BOSS_UID, ACT_SHOT_TGT_OK, BOSS_UID)
        # A replayed tid=2 mode pick must be stale (phase already DONE).
        await self._press(BOSS_UID, ACT_BOSS_MODE, BOSS_UID, tid=2)
        self.assertIn(STALE_ALERT, self.bot.acks())
        self.assertEqual(
            game.nmnd_night2_dispositions.get(f"boss_mode:{BOSS_UID}"),
            BOSS_MODE_SHOT_NEUTRALIZED,
        )

    # ----------------------------------------------------- (B) Doctor self

    async def test_doctor_self_option_hidden_at_two_of_two(self):
        """At 2/2 the «خودم» button must not be rendered at all."""
        await self._fork_night()
        game = self.game
        game.nmnd_night2_doctor_self_saves = N2_MAX_SELF_SAVES
        await self._doctor_panel_available()
        tids = self._panel_tids(DOC_PANEL_MARK)
        self.assertNotIn(
            DOC_UID, tids, "exhausted self-save must not be offered"
        )
        self.assertIn(CIT1_UID, tids, "other players must remain listed")
        joined = "\n".join(self._last_texts())
        self.assertIn("از ۲ بار استفاده‌شده", joined)

        # Forged self selection is still rejected server-side and the
        # counter stays intact.
        await self._press(DOC_UID, ACT_DOC_PICK, DOC_UID, tid=DOC_UID)
        await self._press(DOC_UID, ACT_DOC_OK, DOC_UID)
        self.assertIn(SELF_QUOTA_ALERT, self.bot.acks())
        self.assertEqual(
            game.nmnd_night2_doctor_self_saves, N2_MAX_SELF_SAVES
        )
        self.assertFalse(game.nmnd_night2_doctor_confirmed_self)
        self.assertIsNone(game.nmnd_night2_doctor_uid)

    async def test_doctor_self_option_shown_below_limit_and_restored(self):
        """At <2 the option shows; a valid NATO rollback restores it."""
        await self._fork_night()
        game = self.game
        game.nmnd_night2_doctor_self_saves = 1
        await self._doctor_panel_available()
        self.assertIn(DOC_UID, self._panel_tids(DOC_PANEL_MARK))
        joined = "\n".join(self._last_texts())
        self.assertIn("از ۲ بار استفاده‌شده", joined)

        # Simulate a valid NATO rollback: a confirmed self-save earlier
        # in the night with baseline 1 restored by the cancellation.
        game.nmnd_night2_doctor_confirmed_self = True
        game.nmnd_night2_doctor_self_before = 1
        game.nmnd_night2_doctor_self_saves = N2_MAX_SELF_SAVES
        await night2_mod.night2_cancel_doctor_for_nato(
            self.bot, game, self.manager
        )
        self.assertEqual(game.nmnd_night2_doctor_self_saves, 1)
        await self._doctor_panel_available()
        self.assertIn(
            DOC_UID,
            self._panel_tids(DOC_PANEL_MARK),
            "rollback must make the self-save option available again",
        )

    # --------------------------------------------- (C) game-end publication

    def _warp_to_room19_state(self, game):
        """Mirror Room 19: resolved + committed at publication with a
        decided winner (mafia parity) and no discipline ask delivered."""
        nc = int(game.nmnd_night2_night_count or 1)
        for uid in (DOC_UID, GUARD_UID, MINE_UID, CIT1_UID):
            game.players[uid].is_alive = False
        game.nmnd_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.nmnd_night2_phase = "resolved"
        game.nmnd_night2_resolved = True
        game.nmnd_night2_resolved_night = nc
        game.nmnd_night2_night_count = nc
        game.nmnd_night2_outcome_committed = True
        game.nmnd_night2_outcome = {
            "publication": {
                "pending": True,
                "pending_items": ["night_results_publication"],
            },
        }
        game.nmnd_night2_publication_pending = True
        game.nmnd_night2_publication_active = False
        game.nmnd_night2_publication_stage = None
        self.assertIsNone(
            game.nmnd_night2_dispositions.get(f"discipline_asked:{nc}")
        )
        return nc

    async def test_game_ended_publication_resolves_and_finalizes_win(self):
        """Decided winner at publication: no ask panel, full resolve+win."""
        game = await self._fork_night()
        nc = self._warp_to_room19_state(game)
        self.bot.calls.clear()

        advanced = await night2_publish.nam10_night2_publish_tick(
            self.bot, game, self.manager
        )
        self.assertTrue(advanced)
        joined = "\n".join(self._last_texts())
        # The discipline ask must never be delivered (game over).
        self.assertNotIn(DISCIPLINE_MARK, joined)
        # The established post-night flow ran: night results broadcast.
        self.assertIn(NIGHT_RESULTS_MARK, joined)
        # The winner is announced and the game finalized (room released
        # by the manager exactly like any established game end).
        self.assertIn(WIN_BROADCAST_MARK, joined)
        self.assertIsNone(self.manager.get_game(game.room_code))
        self.assertFalse(game.nmnd_night2_publication_pending)
        self.assertIsNone(game.nmnd_night2_publication_stage)
        self.assertEqual(
            game.nmnd_night2_dispositions.get(f"discipline_asked:{nc}"), "1"
        )
        self.assertEqual(
            game.nmnd_night2_dispositions.get(
                f"discipline_game_ended:{nc}"
            ),
            "resolved",
        )

        # Idempotent: re-ticks and replayed stage calls deliver nothing.
        calls_before = len(self.bot.calls)
        self.assertFalse(
            await night2_publish.nam10_night2_publish_tick(
                self.bot, game, self.manager
            )
        )
        self.assertFalse(
            await night2_publish._start_discipline_stage(
                self.bot, game, self.manager
            )
        )
        self.assertEqual(len(self.bot.calls), calls_before)

    async def test_non_ended_publication_still_asks_discipline(self):
        """Regression: a non-decided night still delivers the ask panel."""
        game = await self._fork_night()
        nc = int(game.nmnd_night2_night_count or 1)
        from bot.nam10.night2_publish import N2PUB_DISCIPLINE

        game.nmnd_night2_phase = "resolved"
        game.nmnd_night2_resolved = True
        game.nmnd_night2_resolved_night = nc
        game.nmnd_night2_outcome_committed = True
        game.nmnd_night2_outcome = {"publication": {"pending": True}}
        game.nmnd_night2_publication_pending = True
        game.nmnd_night2_publication_active = False
        game.nmnd_night2_publication_stage = N2PUB_DISCIPLINE
        self.bot.calls.clear()

        advanced = await night2_publish.nam10_night2_publish_tick(
            self.bot, game, self.manager
        )
        self.assertTrue(advanced)
        joined = "\n".join(self._last_texts())
        self.assertIn(DISCIPLINE_MARK, joined)
        self.assertEqual(game.phase, Phase.MANUAL)
        self.assertEqual(
            game.nmnd_night2_dispositions.get(f"discipline_asked:{nc}"), "1"
        )


if __name__ == "__main__":
    unittest.main()
