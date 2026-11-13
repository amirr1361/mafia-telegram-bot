"""Namayande-10 Night v2 — Doctor self-save counter + daytime Rebel
assassination interface regression tests.

Change A: the Doctor's night panel shows the authoritative lifetime
self-save counter («نجات خود: X از ۲ بار استفاده‌شده») computed from the
durable ``nmnd_night2_doctor_self_saves`` field; NATO cancellation rolls
it back, hacker-nullified self-saves still consume their charge.

Change B: the complete daytime Rebel assassination driver
(``bot/nam10/rebel_day.py``):
- unlock when Mafia Boss or Hacker is eliminated (night or day paths);
- one-time activation notice + per-day entry panel after day opening;
- red/blue target selection, one target at a time, town-only pool
  (Rebel + all Mafia-aligned players excluded);
- two-step confirmation with ability-preserving cancellation;
- hard cutoff when the assistant confirms daily defense candidates;
- at-most-once commit, name-only public announcement, Observer mirror
  support for synthetic Rebels.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from bot.observer_delivery import PlayerMirrorCb  # noqa: E402
from tests.test_namayande10_night_publish import _SkipInheritedTests  # noqa: E402
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
    SYN_UID,
)

DOCTOR_CNT_MARK = "نجات خود:"
NOTICE_MARK = "🎯 قابلیت ترور فعال شد"
ENTRY_BUTTON = "🎯 استفاده از قابلیت ترور"
ENTRY_BODY_MARK = "قابلیت ترور شما فعال است."
RESULT_MARK = "📢 نتیجه ترور"


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
                a
                for a in vars(base)
                if a.startswith("test_") and a not in own
            ]:
                setattr(cls, attr, None)
        return cls


class Nam10RebelDayTest(_v2.Nam10NightV2Test, metaclass=_SkipAllInherited):
    """Doctor counter + rebel daytime driver (press-level + state-level)."""

    # ------------------------------------------------------------ helpers

    def _set_day_state(self, *, host_day: int = 2) -> None:
        g = self.game
        from bot.models import Phase
        from bot.nam10.nmnd_narrator import DAY_DISCUSS

        g.nmnd_night2_mode = True
        g.phase = Phase.MANUAL
        g.nmnd_narrator_host_day = host_day
        g.nmnd_narrator_night_count = max(1, host_day - 1)
        g.nmnd_narrator_step = DAY_DISCUSS
        g.nmnd_night2_publication_pending = False
        g.nam10_day1_defense_active = False
        g.nam10_day1_defense_phase = "pick"
        g.nmnd_night2_rebel_cutoff_day = None
        g.nmnd_night2_rebel_stage = None
        g.nmnd_night2_rebel_target_pending = None

    async def _enable_day_flow(self):
        self._fork_room()
        self._set_day_state()
        self.game.nmnd_night2_rebel_unlocked = True
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)

    async def _open_doctor_panel(self):
        from bot.nam10.night2 import _send_doctor_pick_panel

        await _send_doctor_pick_panel(self.bot, self.game, DOC_UID)

    def _rebel_kb(self):
        picked = None
        for text, kb in self.bot.kb_segments():
            if kb is not None and "ترور" in text:
                picked = kb
        return picked

    def _rebel_buttons(self):
        kb = self._rebel_kb()
        if kb is None:
            return []
        out = []
        for row in kb.inline_keyboard:
            for b in row:
                cb = PlayerMirrorCb.unpack(b.callback_data or "")
                if cb is not None:
                    out.append((cb, b.style, b.text))
        return out

    # ------------------------------------------------- doctor counter

    async def test_doctor_panel_counter_zero(self):
        self._fork_room()
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 0)
        await self._enter_night()
        await self._open_doctor_panel()
        joined = "\n".join(self.bot.texts_to(DOC_UID))
        self.assertIn(DOCTOR_CNT_MARK, joined)
        self.assertIn("۰ از ۲ بار استفاده\u200cشده", joined)
        # The old generic sentence is replaced by the counter line.
        self.assertNotIn(
            "پزشک در طول بازی حداکثر دو بار",
            joined,
        )

    async def test_doctor_panel_counter_one_and_two(self):
        self._fork_room()
        self.game.nmnd_night2_doctor_self_saves = 1
        await self._enter_night()
        await self._open_doctor_panel()
        joined = "\n".join(self.bot.texts_to(DOC_UID))
        self.assertIn("۱ از ۲ بار استفاده\u200cشده", joined)
        self.game.nmnd_night2_doctor_self_saves = 2
        await self._open_doctor_panel()
        joined = "\n".join(self.bot.texts_to(DOC_UID))
        self.assertIn("۲ از ۲ بار استفاده\u200cشده", joined)

    async def test_doctor_counter_rollback_after_nato_cancel(self):
        self._fork_room()
        await self._enter_night()
        await self._press(DOC_UID, "docp", DOC_UID, tid=DOC_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 1)
        from bot.nam10.night2 import night2_cancel_doctor_for_nato

        changed = await night2_cancel_doctor_for_nato(
            self.bot, self.game, self.manager
        )
        self.assertTrue(changed)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 0)
        await self._open_doctor_panel()
        joined = "\n".join(self.bot.texts_to(DOC_UID))
        self.assertIn("۰ از ۲ بار استفاده\u200cشده", joined)

    async def test_nullified_self_save_still_consumes_charge(self):
        self._fork_room()
        await self._enter_night()
        # Doctor saves himself; Hacker's confirmed pair (doc -> doc)
        # nullifies the save, but the charge stays consumed.
        await self._press(DOC_UID, "docp", DOC_UID, tid=DOC_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        # Boss plain shot at a citizen; the other roles act/skip.
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
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
        from bot.nam10.night2 import night2_run_resolution

        night2_run_resolution(self.game)
        doc = (self.game.nmnd_night2_outcome or {}).get("doctor") or {}
        self.assertTrue(
            doc.get("nullified_by_hacker"), self.game.nmnd_night2_outcome
        )
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 1)
        # The next night's panel keeps showing the consumed charge.
        await self._open_doctor_panel()
        joined = "\n".join(self.bot.texts_to(DOC_UID))
        self.assertIn("۱ از ۲ بار استفاده\u200cشده", joined)

    # ------------------------------------------------- rebel unlock

    async def test_rebel_unlock_boss_via_night_engine(self):
        self._fork_room()
        from bot.nam10.night2 import night2_apply_elimination

        rec = night2_apply_elimination(self.game, BOSS_UID, "mine_mafia")
        self.assertIsNotNone(rec)
        self.assertTrue(self.game.nmnd_night2_rebel_unlocked)

    async def test_rebel_unlock_hacker_via_night_engine(self):
        self._fork_room()
        from bot.nam10.night2 import night2_apply_elimination

        rec = night2_apply_elimination(self.game, SHIAD_UID, "shot_target")
        self.assertIsNotNone(rec)
        self.assertTrue(self.game.nmnd_night2_rebel_unlocked)

    async def test_rebel_unlock_day_elimination_path(self):
        self._fork_room()
        self._set_day_state()
        from bot.nam10.nmnd_narrator import eliminate_player_from_game

        eliminate_player_from_game(
            self.game, self.manager, SHIAD_UID, elim_source="day_vote"
        )
        self.assertFalse(self.game.players[SHIAD_UID].is_alive)
        self.assertTrue(self.game.nmnd_night2_rebel_unlocked)

    async def test_rebel_no_unlock_from_town_elimination(self):
        self._fork_room()
        self._set_day_state()
        from bot.nam10.nmnd_narrator import eliminate_player_from_game

        eliminate_player_from_game(
            self.game, self.manager, CIT1_UID, elim_source="day_vote"
        )
        self.assertFalse(self.game.nmnd_night2_rebel_unlocked)

    # ------------------------------------------------- day opening

    async def test_day_opening_notice_and_entry_once(self):
        await self._enable_day_flow()
        joined = "\n".join(self.bot.texts_to(NATO_UID))
        self.assertIn(NOTICE_MARK, joined)
        self.assertIn("<b>\u200e</b>".replace("\u200e", ""), joined) if False else None
        self.assertIn("<b>🎯 قابلیت ترور</b>", joined)
        self.assertTrue(self.game.nmnd_night2_rebel_notice_sent)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "entry")
        entry_styles = [
            (text, style)
            for cb, style, text in self._rebel_buttons()
            if cb.act == "rebben"
        ]
        self.assertEqual(entry_styles, [(ENTRY_BUTTON, "danger")])
        # duplicate / repeated dispatch cannot double-send
        count_notice = joined.count(NOTICE_MARK)
        count_entry = joined.count("<b>🎯 قابلیت ترور</b>")
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening, dispatch_nam10_rebel_activation

        await send_nam10_rebel_day_opening(self.bot, self.game)
        await dispatch_nam10_rebel_activation(self.bot, self.game)
        joined2 = "\n".join(self.bot.texts_to(NATO_UID))
        self.assertEqual(joined2.count(NOTICE_MARK), count_notice)
        self.assertEqual(joined2.count("<b>🎯 قابلیت ترور</b>"), count_entry)

    async def test_day_opening_without_unlock_silent(self):
        self._fork_room()
        self._set_day_state()
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)
        self.assertEqual("\n".join(self.bot.texts_to(NATO_UID)), "")

    async def test_synthetic_rebel_uses_observer_mirror(self):
        self._fork_room()
        self._set_day_state()
        # Swap: the synthetic seat is the Rebel (NATO), 902 is a citizen.
        from bot.models import Role

        self.game.players[SYN_UID].role = Role.NATO
        self.game.players[NATO_UID].role = Role.CITIZEN
        self.game.nmnd_night2_rebel_unlocked = True
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)
        joined_obs = "\n".join(self.bot.texts_to(OBS_UID))
        self.assertIn(NOTICE_MARK, joined_obs)
        self.assertIn(ENTRY_BODY_MARK, joined_obs)
        obs_acts = [cb.act for cb, _s, _t in self._rebel_buttons()]
        self.assertIn("rebben", obs_acts)
        self.assertEqual(
            [t for t in self.bot.texts_to(SYN_UID) if "ترور" in t], []
        )

    # ------------------------------------------------- press flow

    async def test_target_pool_excludes_mafia_and_rebel(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        self.assertTrue(
            any("🎯 انتخاب هدف ترور" in t for t in self.bot.texts_to(NATO_UID))
        )
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "target")
        pool_uids = set()
        for cb, _style, _text in self._rebel_buttons():
            if cb.act == "rebpick" and cb.tid:
                pool_uids.add(cb.tid)
        self.assertIn(CIT1_UID, pool_uids)
        self.assertIn(GUARD_UID, pool_uids)
        self.assertNotIn(NATO_UID, pool_uids)  # Rebel excluded
        self.assertNotIn(BOSS_UID, pool_uids)  # Mafia boss
        self.assertNotIn(SHIAD_UID, pool_uids)  # Hacker

    async def test_red_blue_style_and_switch(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=CIT1_UID)
        styles = {cb.tid: st for cb, st, _t in self._rebel_buttons()}
        self.assertEqual(styles.get(CIT1_UID), "danger")
        self.assertEqual(styles.get(GUARD_UID), "primary")
        # switching: previous back to blue, new one red
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=GUARD_UID)
        styles = {cb.tid: st for cb, st, _t in self._rebel_buttons()}
        self.assertEqual(styles.get(CIT1_UID), "primary")
        self.assertEqual(styles.get(GUARD_UID), "danger")
        # tapping the selected target again deselects it
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=GUARD_UID)
        styles = {cb.tid: st for cb, st, _t in self._rebel_buttons()}
        self.assertEqual(styles.get(GUARD_UID), "primary")
        self.assertIsNone(self.game.nmnd_night2_rebel_target_pending)

    async def test_zero_target_confirm_rejected(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "target")
        await self._press(NATO_UID, "rebok", NATO_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "target")
        self.assertFalse(
            any("تأیید نهایی ترور" in t for t in self.bot.texts_to(NATO_UID))
        )
        self.assertFalse(self.game.nmnd_night2_rebel_assassin_used)

    async def test_cancel_preserves_ability(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=CIT1_UID)
        await self._press(NATO_UID, "rebok", NATO_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "final")
        joined = "\n".join(self.bot.texts_to(NATO_UID))
        self.assertIn("⚠️ تأیید نهایی ترور", joined)
        self.assertIn("انتخاب کرده\u200cاید", joined)
        await self._press(NATO_UID, "rebcancel", NATO_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "entry")
        self.assertIsNone(self.game.nmnd_night2_rebel_target_pending)
        self.assertFalse(self.game.nmnd_night2_rebel_assassin_used)
        self.assertTrue(self.game.players[NATO_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        self.assertTrue(
            any(ENTRY_BODY_MARK in t for t in self.bot.texts_to(NATO_UID))
        )

    async def test_final_commit_unprotected_target(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=CIT1_UID)
        await self._press(NATO_UID, "rebok", NATO_UID)
        await self._press(NATO_UID, "rebgo", NATO_UID)
        self.assertTrue(self.game.nmnd_night2_rebel_assassin_used)
        self.assertFalse(self.game.players[NATO_UID].is_alive)
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        joined = "\n".join(self.bot.texts_to(GUARD_UID))
        self.assertIn(RESULT_MARK, joined)
        self.assertIn("بازیکن 9", joined)  # CIT1 seat-9 name
        self.assertIn("بازیکن 2", joined)  # Rebel seat-2 name
        # Repeated confirm cannot duplicate eliminations/announcements.
        used = self.game.nmnd_night2_rebel_assassin_used
        result = dict(self.game.nmnd_night2_rebel_assassin_result or {})
        await self._press(NATO_UID, "rebgo", NATO_UID)
        self.assertEqual(used, self.game.nmnd_night2_rebel_assassin_used)
        self.assertEqual(result, self.game.nmnd_night2_rebel_assassin_result)

    async def test_final_commit_guardian_immune(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=GUARD_UID)
        await self._press(NATO_UID, "rebok", NATO_UID)
        await self._press(NATO_UID, "rebgo", NATO_UID)
        self.assertTrue(self.game.nmnd_night2_rebel_assassin_used)
        self.assertFalse(self.game.players[NATO_UID].is_alive)
        self.assertTrue(self.game.players[GUARD_UID].is_alive)
        result = self.game.nmnd_night2_rebel_assassin_result or {}
        self.assertEqual(result.get("reason"), "guardian_immune")

    async def test_final_commit_armor_absorbed(self):
        await self._enable_day_flow()
        # Guardian armor granted for the current day on CIT1.
        self.game.nmnd_night2_armor_uid = CIT1_UID
        self.game.nmnd_night2_armor_day = self.game.nmnd_narrator_night_count
        await self._press(NATO_UID, "rebben", NATO_UID)
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=CIT1_UID)
        await self._press(NATO_UID, "rebok", NATO_UID)
        await self._press(NATO_UID, "rebgo", NATO_UID)
        self.assertTrue(self.game.nmnd_night2_rebel_assassin_used)
        self.assertFalse(self.game.players[NATO_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        result = self.game.nmnd_night2_rebel_assassin_result or {}
        self.assertEqual(result.get("reason"), "armor_absorbed")
        self.assertTrue(result.get("armor_consumed"))

    # ------------------------------------------------- cutoff rules

    async def test_defense_confirm_cutoff_closes_window(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=CIT1_UID)
        await self._press(NATO_UID, "rebok", NATO_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "final")
        # The assistant confirms the defense candidates: the window
        # closes immediately; nothing is consumed.
        self.game.nam10_day1_defense_active = True
        self.game.nam10_day1_defense_phase = "pick"
        from bot.nam10.dayflow import (
            _no_host_day1_defense_confirm,
            set_day_vote_defender_uids,
            set_day_vote_pick_uids,
        )

        set_day_vote_pick_uids(self.game, {CIT1_UID, GUARD_UID})
        set_day_vote_defender_uids(self.game, set())
        cb = _fake_callback(ASSIST_UID)
        await _no_host_day1_defense_confirm(
            cb, self.bot, self.game, ASSIST_UID, ASSIST_UID
        )
        self.assertEqual(self.game.nam10_day1_defense_phase, "outcome")
        self.assertEqual(
            self.game.nmnd_night2_rebel_cutoff_day,
            self.game.nmnd_narrator_host_day,
        )
        self.assertIsNone(self.game.nmnd_night2_rebel_stage)
        self.assertIsNone(self.game.nmnd_night2_rebel_target_pending)
        from bot.nam10.rebel_day import nam10_rebel_window_open

        self.assertFalse(nam10_rebel_window_open(self.game))
        # Forged final confirmation after the cutoff: rejected.
        await self._press(NATO_UID, "rebgo", NATO_UID)
        self.assertFalse(self.game.nmnd_night2_rebel_assassin_used)
        self.assertTrue(self.game.players[NATO_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)

    async def test_unused_ability_survives_to_next_day(self):
        await self._enable_day_flow()
        # Nothing pressed; the next day opens (fresh panel stage).
        self.game.nmnd_narrator_host_day = 3
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)
        self.assertFalse(self.game.nmnd_night2_rebel_assassin_used)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "entry")
        self.assertIsNone(self.game.nmnd_night2_rebel_target_pending)
        self.assertTrue(
            any(ENTRY_BODY_MARK in t for t in self.bot.texts_to(NATO_UID))
        )

    async def test_previous_day_buttons_invalid_after_day_advances(self):
        await self._enable_day_flow()
        await self._press(NATO_UID, "rebben", NATO_UID)
        await self._press(NATO_UID, "rebpick", NATO_UID, tid=CIT1_UID)
        await self._press(NATO_UID, "rebok", NATO_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "final")
        # A new day begins before the commit; the stale final-confirm
        # button can no longer execute anything.
        self.game.nmnd_narrator_host_day = 3
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "entry")
        await self._press(NATO_UID, "rebgo", NATO_UID)
        self.assertFalse(self.game.nmnd_night2_rebel_assassin_used)
        self.assertTrue(self.game.players[NATO_UID].is_alive)
        self.assertTrue(self.game.players[CIT1_UID].is_alive)

    async def test_forbidden_actor_rejected(self):
        await self._enable_day_flow()
        # A non-Rebel actor can never open the flow as itself.
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "entry")
        await self._press(CIT1_UID, "rebben", CIT1_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "entry")
        # The Observer cannot operate a real player's private action.
        await self._press(OBS_UID, "rebben", NATO_UID)
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "entry")
        self.assertFalse(self.game.nmnd_night2_rebel_assassin_used)


# ---------------------------------------------------------------- helpers


def _fake_callback(actor_uid):
    from unittest.mock import AsyncMock, MagicMock

    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = actor_uid
    cb.message = MagicMock()
    cb.message.html_text = "panel"
    cb.message.text = "panel"
    cb.message.message_id = 55
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.answer = AsyncMock()
    return cb


if __name__ == "__main__":
    unittest.main()
