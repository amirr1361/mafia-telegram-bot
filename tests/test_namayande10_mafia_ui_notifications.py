"""Namayande 10-13: mafia-team notification + panel restriction regressions.

Focused coverage for the 2026-10 Task E implementation:

- Namayande player-count keyboard restricted to 10/11/12/13 (one row of
  three + one), forged/legacy counts rejected server-side, other
  scenarios' count menus unchanged.
- Redesigned Day-1 Boss betrayal panel (one option per own row, pending
  blue/red selection, single confirm, representative mapping via
  callback tid, commit-once) and the private teammate notification.
- Mafia shot notification (plain + neutralized, successor shooters,
  no premature/disclosing text) after a committed shot.
- NATO notification (10/11 shooter-controlled and 12/13 independent
  agent flow) only after role AND target are confirmed.
- Shot target keyboard colour normalisation (all blue / one selected
  red, no faction-based distinction).

Reuses the established isolated harness classes from
``tests.test_namayande10_night_v2``, ``tests.test_namayande10_day1_betrayal``
and ``tests.test_namayande10_expansion``.
"""

import sys
import unittest

sys.path.insert(0, "/root/mafia-telegram-bot")

import tests.test_namayande10_expansion as _exp  # noqa: E402
from tests.test_namayande10_day1_betrayal import (  # noqa: E402
    Nam10Day1BetrayalTest,
    BOSS_MARK,
    OBS_UID,
)
from tests.test_namayande10_expansion import (  # noqa: E402
    AGT_UID,
    NamExpansionRoomTest,
)
from tests.test_namayande10_night_v2 import (  # noqa: E402
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    GUIDE_UID,
    GUARD_UID,
    LAW_UID,
    MINE_UID,
    Nam10NightV2Test,
    NATO_UID,
    SHIAD_UID,
    SHOT_MARK,
    SYN_UID,
)

from bot.models import Role  # noqa: E402

BETRAYAL_NOTIFY_MARK = "رأی خیانت رئیس مافیا ثبت شد"
SHOT_NOTIFY_MARK = "انتخاب امشب تیم مافیا ثبت شد"
NATO_NOTIFY_MARK = "انتخاب ناتویی امشب تیم مافیا ثبت شد"
PENDING_MARK = "انتخاب موقت شما"


def _texts_containing(texts, mark):
    return [t for t in texts if mark in t]


class NamayandeCountOptionsTest(Nam10NightV2Test):
    """Namayande count keyboard + server-side gate; other scenarios intact."""

    def _counts(self, kb, expected_slug):
        from bot.main import CreatePickPlayers

        counts = []
        for row in kb.inline_keyboard:
            for b in row:
                cb = CreatePickPlayers.unpack(b.callback_data)
                self.assertEqual(cb.slug, expected_slug)
                counts.append(cb.count)
        return counts

    async def test_namayande_keyboard_only_10_to_13(self):
        from bot.main import player_count_keyboard

        counts = self._counts(player_count_keyboard("namayande"), "namayande")
        self.assertEqual(counts, [10, 11, 12, 13])

    async def test_forged_and_legacy_counts_rejected_server_side(self):
        for n in (8, 9, 14, 15, 16, 17, 18):
            game = self.manager.create_game(
                host_id=7700 + n,
                scenario_name="namayande",
                max_players=n,
                nam10_no_host=True,
            )
            self.assertIsNone(game, f"count={n} must be rejected")
        for n in (10, 11, 12, 13):
            game = self.manager.create_game(
                host_id=8000 + n,
                scenario_name="namayande",
                max_players=n,
                nam10_no_host=True,
            )
            self.assertIsNotNone(game, f"count={n} must be accepted")

    async def test_other_scenarios_count_menus_unchanged(self):
        from bot.main import player_count_keyboard

        self.assertEqual(
            self._counts(
                player_count_keyboard("russian_mafia"), "russian_mafia"
            ),
            [8, 9],
        )
        self.assertEqual(
            self._counts(player_count_keyboard("bazpors"), "bazpors"),
            [10, 11, 12, 13],
        )


class NamayandeBetrayalPanelTest(Nam10Day1BetrayalTest):
    """Two-step Boss betrayal panel + private teammate notification."""

    def _option_rows(self, mark=BOSS_MARK):
        kb = None
        for text, k in self.bot.kb_segments():
            if mark in text and k is not None:
                kb = k
        if kb is None:
            return []
        rows = []
        for row in kb.inline_keyboard:
            cells = []
            for btn in row:
                if (btn.callback_data or "").startswith("pmr:"):
                    from bot.observer_delivery import PlayerMirrorCb

                    cb = PlayerMirrorCb.unpack(btn.callback_data)
                    if cb.act in ("d1ba", "d1bs"):
                        cells.append((btn, cb))
            if cells:
                rows.append(cells)
        return rows

    def _confirm_presses(self, mark=BOSS_MARK):
        return [
            b
            for b in self._button_objects(mark)
            if b.text == "✅ تأیید انتخاب"
        ]

    def _notif_sends(self):
        return [
            (chat, t)
            for chat, t in self.bot.sends()
            if BETRAYAL_NOTIFY_MARK in t
        ]

    async def test_panel_two_choices_when_boss_is_representative(self):
        self._fork_room()
        # Boss moves into Representative seat 1; old boss becomes citizen.
        self.game.players[904].role = Role.MAFIA_BOSS
        self.game.players[901].role = Role.CITIZEN
        await self._walk_to_stage_a()
        optical_rows = self._option_rows()
        self.assertEqual(len(optical_rows), 2)
        for row in optical_rows:
            self.assertEqual(len(row), 1)
        acts = {cb.act for _, cb in (c for r in optical_rows for c in r)}
        self.assertEqual(acts, {"d1ba", "d1bs"})
        tids = {cb.tid for _, cb in (c for r in optical_rows for c in r)}
        self.assertEqual(tids, {902})  # only the OTHER representative
        self.assertEqual(len(self._confirm_presses()), 1)
        # Permanent restriction: own-seat pick rejected.
        await self._press(904, "d1ba", 904, tid=904)
        self.assertTrue(
            any("نمی‌توانید به رأی نمایندهٔ خودتان" in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(self.game.nam10_day1_betrayal_pending_op)

    async def test_pending_selection_replace_and_colors(self):
        self._fork_room()
        await self._walk_to_stage_a()
        # No notification for a tentative pick.
        before = len(self._notif_sends())
        await self._press(BOSS_UID, "d1ba", BOSS_UID, tid=904)
        self.assertIsNone(self.game.nam10_day1_betrayal_op)
        self.assertIsNotNone(self.game.nam10_day1_betrayal_pending_op)
        self.assertEqual(len(self._notif_sends()), before)
        kb = None
        for text, kb in self.bot.kb_segments():
            if BOSS_MARK in text and kb is not None:
                pass
        self.assertIsNotNone(kb)
        rows = kb.inline_keyboard
        styles: dict[tuple[str, int], str] = {}
        for r_idx, row in enumerate(rows):
            for b in row:
                if (b.callback_data or "").startswith("pmr:"):
                    from bot.observer_delivery import PlayerMirrorCb

                    cb = PlayerMirrorCb.unpack(b.callback_data)
                    if cb.act in ("d1ba", "d1bs"):
                        styles[(cb.act, cb.tid)] = b.style
        # Blue unselected / red selected; one per row already asserted.
        self.assertEqual(styles[("d1ba", 904)], "danger")
        for key, st in styles.items():
            if key != ("d1ba", 904):
                self.assertEqual(st, "primary", key)
        # Replacement: choosing another option moves the red.
        await self._press(BOSS_UID, "d1bs", BOSS_UID, tid=902)
        kb2 = None
        for text, _kb in self.bot.kb_segments():
            if BOSS_MARK in text and _kb is not None:
                kb2 = _kb
        styles2 = {}
        for row in kb2.inline_keyboard:
            for b in row:
                if (b.callback_data or "").startswith("pmr:"):
                    from bot.observer_delivery import PlayerMirrorCb

                    cb = PlayerMirrorCb.unpack(b.callback_data)
                    if cb.act in ("d1ba", "d1bs"):
                        styles2[(cb.act, cb.tid)] = b.style
        self.assertEqual(styles2[("d1bs", 902)], "danger")
        self.assertEqual(styles2[("d1ba", 904)], "primary")
        # Still nothing applied nor announced.
        self.assertIsNone(self.game.nam10_day1_betrayal_op)
        self.assertEqual(len(self._notif_sends()), before)

    async def test_confirm_requires_pending_selection(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._press(BOSS_UID, "d1bak", BOSS_UID)
        self.assertTrue(
            any(
                "ابتدا یک گزینه را انتخاب کنید" in (a or "")
                for a in self.bot.acks()
            )
        )
        self.assertIsNone(self.game.nam10_day1_betrayal_op)
        # Notification not sent either.
        self.assertEqual(len(self._notif_sends()), 0)

    async def test_confirm_commits_exact_rep_mapping_once(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._press(BOSS_UID, "d1ba", BOSS_UID, tid=904)
        await self._press(BOSS_UID, "d1bak", BOSS_UID)
        self.assertEqual(self.game.nam10_day1_betrayal_op, "add")
        self.assertEqual(self.game.nam10_day1_betrayal_rep_uid, 904)
        # notification text matches the committed mapping (rep 1 = 904 Player 4)
        sends = self._notif_sends()
        texts = {t for _, t in sends}
        expected_add = (
            "🗳️ رأی خیانت رئیس مافیا ثبت شد: "
            "یک رأی به نماینده ۱ (بازیکن 4) اضافه شد."
        )
        # Direct DM copies (no observer prefix) carry the exact text.
        self.assertTrue(expected_add in texts, texts)
        self.assertLessEqual(len(texts), 3)  # 2 players + observer copies
        recipients = {chat for chat, _ in sends}
        # authorised Mafia teammates only (alive, excluding Boss 901)
        self.assertIn(902, recipients)
        self.assertIn(903, recipients)
        self.assertNotIn(BOSS_UID, recipients)
        for uid in (904, 905, 906, 907, 908, 909, SYN_UID):
            self.assertNotIn(uid, recipients)
        # Observer received a mirrored copy; no keyboard anywhere
        obs_texts = [t for chat, t in self.bot.sends() if chat == OBS_UID]
        self.assertTrue(
            any(BETRAYAL_NOTIFY_MARK in t for t in obs_texts)
        )
        # No keyboard on the notification (DMs, mirror copies, edits).
        for text, kb in self.bot.kb_segments():
            if BETRAYAL_NOTIFY_MARK in text:
                self.assertIsNone(kb)
        # Replay: no duplicate notification.
        n_after = len(self._notif_sends())
        await self._press(BOSS_UID, "d1bak", BOSS_UID)
        await self._press(BOSS_UID, "d1ba", BOSS_UID, tid=902)
        self.assertEqual(len(self._notif_sends()), n_after)

    async def test_subtract_commit_notifies_rep2(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._press(BOSS_UID, "d1bs", BOSS_UID, tid=902)
        await self._press(BOSS_UID, "d1bak", BOSS_UID)
        self.assertEqual(self.game.nam10_day1_betrayal_op, "sub")
        self.assertEqual(self.game.nam10_day1_betrayal_rep_uid, 902)
        texts = {t for _, t in self._notif_sends()}
        expected_sub = (
            "🗳️ رأی خیانت رئیس مافیا ثبت شد: "
            "یک رأی از نماینده ۲ (بازیکن 2) کم شد."
        )
        self.assertTrue(expected_sub in texts, texts)
        self.assertLessEqual(len(texts), 3)  # 2 players + observer copies


class NamayandeShotNotifyTest(Nam10NightV2Test):
    """Private notification after a committed Mafia shot."""

    def _notify_texts_to(self, uid):
        return [
            t
            for t in self.bot.texts_to(uid)
            if SHOT_NOTIFY_MARK in t
        ]

    async def test_plain_shot_notify_once_no_disclosure(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        # tentative target: nothing announced yet
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=DOC_UID)
        self.assertEqual(self._notify_texts_to(902), [])
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        expected = (
            "🔴 انتخاب امشب تیم مافیا ثبت شد.\n\n"
            "نوع شلیک: بدون خنثی‌سازی\n\n"
            "🎯 هدف: بازیکن 7"
        )
        self.assertEqual(self._notify_texts_to(902), [expected])
        self.assertEqual(self._notify_texts_to(903), [expected])
        self.assertEqual(self._notify_texts_to(BOSS_UID), [])
        self.assertEqual(self._notify_texts_to(906), [])
        self.assertEqual(self._notify_texts_to(SYN_UID), [])
        self.assertTrue(
            any(SHOT_NOTIFY_MARK in t for t in self.bot.texts_to(OBS_UID))
        )
        for chat, t, kb in self.bot._fullsends():
            if SHOT_NOTIFY_MARK in t:
                self.assertIsNone(kb, chat)
        # replay of the confirmation is rejected -> no duplicate
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        self.assertEqual(len(self._notify_texts_to(902)), 1)

    async def test_neutralized_shot_label(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=2)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=SYN_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        expected = (
            "🔴 انتخاب امشب تیم مافیا ثبت شد.\n\n"
            "نوع شلیک: با خنثی‌سازی\n\n"
            "🎯 هدف: امیر"
        )
        self.assertEqual(self._notify_texts_to(902), [expected])
        self.assertEqual(self._notify_texts_to(903), [expected])

    async def test_successor_shooter_notify(self):
        self._fork_room()
        from bot.nam10.night2 import nam10_night2_entry_dispatch

        await self._enter_night()
        # Boss eliminated mid-game: shooting passes to the next mafia member.
        self.game.players[BOSS_UID].is_alive = False
        self.game.nmnd_night2_entry_dispatched = False
        ok = await nam10_night2_entry_dispatch(self.bot, self.game, self.manager)
        self.assertTrue(ok)
        from bot.nam10.night2 import night2_active_shooter

        self.assertEqual(
            night2_active_shooter(self.game).user_id, NATO_UID
        )
        await self._press(NATO_UID, "bmode", NATO_UID, tid=1)
        await self._press(NATO_UID, "sht", NATO_UID, tid=DOC_UID)
        await self._press(NATO_UID, "shtok", NATO_UID)
        expected = (
            "🔴 انتخاب امشب تیم مافیا ثبت شد.\n\n"
            "نوع شلیک: بدون خنثی‌سازی\n\n"
            "🎯 هدف: بازیکن 7"
        )
        # recipients: alive mafia excluding the shooter (902 is the shooter)
        self.assertEqual(self._notify_texts_to(903), [expected])
        self.assertEqual(self._notify_texts_to(902), [])
        self.assertEqual(self._notify_texts_to(BOSS_UID), [])
        self.assertTrue(
            any(SHOT_NOTIFY_MARK in t for t in self.bot.texts_to(OBS_UID))
        )
        self.assertEqual(self.game.nmnd_night2_shot_target_uid, DOC_UID)


class NamayandeNatoNotifyTest(NamExpansionRoomTest):
    """NATO notification: only after role + target fully confirmed."""

    def _notify_texts_to(self, uid):
        return [
            t
            for t in self.bot.texts_to(uid)
            if NATO_NOTIFY_MARK in t
        ]

    async def test_shooter_controlled_nato_flow_notify_once(self):
        self._fork_room()
        await self._enter_night()
        # activation alone is NOT a committed NATO guess
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertEqual(self._notify_texts_to(902), [])
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=1)  # پزشک
        await self._press(BOSS_UID, "nrok", BOSS_UID)
        self.assertEqual(self._notify_texts_to(902), [])
        await self._press(BOSS_UID, "npl", BOSS_UID, tid=DOC_UID)
        await self._press(BOSS_UID, "npok", BOSS_UID)
        expected = (
            "🎯 انتخاب ناتویی امشب تیم مافیا ثبت شد.\n\n"
            "🎭 نقش حدس‌زده‌شده: پزشک\n\n"
            "👤 بازیکن انتخاب‌شده: بازیکن 7"
        )
        self.assertEqual(self._notify_texts_to(902), [expected])
        self.assertEqual(self._notify_texts_to(903), [expected])
        self.assertEqual(self._notify_texts_to(BOSS_UID), [])
        self.assertTrue(
            any(NATO_NOTIFY_MARK in t for t in self.bot.texts_to(OBS_UID))
        )
        for chat, t, kb in self.bot._fullsends():
            if NATO_NOTIFY_MARK in t:
                self.assertIsNone(kb, chat)
        # exactly once — replay neither re-notifies nor re-commits
        target_uid = self.game.nmnd_night2_nato_target_uid
        await self._press(BOSS_UID, "npok", BOSS_UID)
        self.assertEqual(self.game.nmnd_night2_nato_target_uid, target_uid)
        self.assertEqual(len(self._notify_texts_to(902)), 1)

    async def test_agent_controlled_nato_flow_notify_once(self):
        self._fork12()
        from bot.nam10.night2 import nam10_night2_entry_dispatch

        await self._enter_night()
        self.assertEqual(
            self.game.players[AGT_UID].role, Role.NATO_AGENT
        )
        # Shooter (Boss) activates NATO — no notification on activation.
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertEqual(self._notify_texts_to(903), [])
        # The separate NATO-role player owns the role/target stages.
        self.assertTrue(
            any(
                "ناتویی — انتخاب نقش" in t
                for t in self.bot.texts_to(AGT_UID)
            )
        )
        await self._press(AGT_UID, "nrole", AGT_UID, tid=1)  # پزشک
        await self._press(AGT_UID, "nrok", AGT_UID)
        # role alone is still not a complete NATO action
        self.assertEqual(self._notify_texts_to(901), [])
        await self._press(AGT_UID, "npl", AGT_UID, tid=DOC_UID)
        self.assertEqual(self._notify_texts_to(901), [])
        await self._press(AGT_UID, "npok", AGT_UID)
        expected = (
            "🎯 انتخاب ناتویی امشب تیم مافیا ثبت شد.\n\n"
            "🎭 نقش حدس‌زده‌شده: پزشک\n\n"
            "👤 بازیکن انتخاب‌شده: بازیکن 8"
        )
        # recipients: alive mafia excluding the acting agent (910)
        self.assertEqual(self._notify_texts_to(BOSS_UID), [expected])
        self.assertEqual(self._notify_texts_to(902), [expected])
        self.assertEqual(self._notify_texts_to(903), [expected])
        self.assertEqual(self._notify_texts_to(AGT_UID), [])
        self.assertEqual(self._notify_texts_to(908), [])
        self.assertTrue(
            any(NATO_NOTIFY_MARK in t for t in self.bot.texts_to(OBS_UID))
        )
        for chat, t, kb in self.bot._fullsends():
            if NATO_NOTIFY_MARK in t:
                self.assertIsNone(kb, chat)
        # replay: no duplicate, committed values immutable
        role_before = self.game.nmnd_night2_nato_role
        target_before = self.game.nmnd_night2_nato_target_uid
        await self._press(AGT_UID, "npok", AGT_UID)
        self.assertEqual(self.game.nmnd_night2_nato_role, role_before)
        self.assertEqual(
            self.game.nmnd_night2_nato_target_uid, target_before
        )
        self.assertEqual(len(self._notify_texts_to(BOSS_UID)), 1)


class NamayandeShotPanelColorTest(Nam10NightV2Test):
    """Shot target keyboard: uniform blue, one selected red."""

    def _shot_styles(self):
        out = {}
        for b in self._button_objects(SHOT_MARK):
            if not (b.callback_data or ""):
                continue
            from bot.observer_delivery import PlayerMirrorCb

            cb = PlayerMirrorCb.unpack(b.callback_data)
            if cb is not None and cb.act == "sht":
                out[cb.tid] = b.style
        return out

    async def _open_shot_panel(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        return self.game

    async def test_all_targets_initially_blue_including_mafia(self):
        await self._open_shot_panel()
        styles = self._shot_styles()
        self.assertIn(902, styles)  # mafia teammate (was danger before)
        self.assertIn(907, styles)  # town (was primary before)
        self.assertTrue(
            all(st == "primary" for st in styles.values()), styles
        )

    async def test_selected_target_replacement(self):
        await self._open_shot_panel()
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=DOC_UID)
        styles = self._shot_styles()
        self.assertEqual(styles[DOC_UID], "danger")
        self.assertEqual(
            {k: v for k, v in styles.items() if k != DOC_UID and v == "danger"},
            {},
        )
        # replacement: previously selected returns to blue
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=902)
        styles2 = self._shot_styles()
        self.assertEqual(styles2[902], "danger")
        self.assertEqual(styles2[DOC_UID], "primary")
        self.assertEqual(
            {k: v for k, v in styles2.items() if v == "danger"}, {902: "danger"}
        )
        # still pending — nothing committed
        self.assertIsNone(self.game.nmnd_night2_shot_target_uid)


if __name__ == "__main__":
    unittest.main()
