"""Namayande (nam10) night-panel synthetic labels + live night reminder.

Regression coverage for the Room 13 findings:

1. Every nam10 night2 target panel (Sniper, Soldier, Mafia shot, Doctor,
   Hacker, mine/lawyer/Guard defaults, selection echoes) keeps the
   synthetic role suffix (``رضا-هکر``) — previously ``_button_label``
   stripped it for the shared ``_danger_pick_rows`` path.
2. The Observer roster uses nam10 role labels, and Bazpors keeps its own.
3. The helper ``🌙 اتمام شب`` reminder count updates LIVE on the same
   message after each confirmed action, and is deleted when count hits
   zero, when the collection stage leaves PENDING_COLLECTING (e.g. the
   disciplinary elimination panel), or via cleanup.
4. After a service restart the reminder lifecycle recovers: a persisted
   binding keeps being edited/deleted; a pending timer is re-created with
   the remaining delay (or, when its original time has already passed, it
   sends exactly once).

Tentative (unconfirmed) selections never shrink the count. Real players
never see role annotations. Storage isolation per AGENTS.md §5.8.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

from bot.game import (
    GameManager,
    is_synthetic_player_uid,
    SYNTHETIC_PLAYER_NAME_POOL,
)
from bot.models import Game, Phase, Player, Role
from bot.nam10.lobby import roles_for_count
from bot.nam10.night2 import (
    ACT_SOLDIER_PICK,
    BOSS_PHASE_DONE,
    PENDING_COLLECTED,
    PENDING_COLLECTING,
    _button_label,
    _danger_pick_rows,
    _holder,
    _send_boss_shot_panel,
    _send_doctor_pick_panel,
    _send_sniper_panel,
    _send_soldier_panel,
    night2_required_keys,
)
from bot.nam10.night_force_finish import (
    nam10_night_force_finish_collection_active,
)
from bot.nam10.role_labels import nam10_role_label_fa
from bot.night_helper_reminder import (
    REMINDER_DELAY_SEC,
    _REMINDER_TASKS,
    _send_reminder_if_needed,
    cancel_night_helper_reminder_task,
    cleanup_night_helper_reminder,
    recover_night_helper_reminders_after_restart,
    refresh_night_helper_reminder,
)
from bot.observer_delivery import build_observer_players_roster_html
from bot.room_mode import is_namayande10_no_host_room
from bot.text_fa import fa_digits
from bot.nam10.lobby import sync_synthetic_player_display_names_nam10

HELPER_CHAT_UID = 900


class _Isolated(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._db = root / "t.sqlite3"
        self._audit = root / "audit"
        self._audit.mkdir()
        self._patches = [
            patch("bot.config.get_database_path", return_value=self._db),
            patch("bot.config.get_game_audit_log_dir", return_value=self._audit),
            patch.dict(
                os.environ,
                {
                    "DATABASE_PATH": str(self._db),
                    "GAME_AUDIT_LOG_DIR": str(self._audit),
                },
                clear=False,
            ),
        ]
        for p in self._patches:
            p.start()
        from bot import db

        db.init_db()
        self.gm = GameManager()

    def tearDown(self) -> None:
        for code in list(_REMINDER_TASKS):
            cancel_night_helper_reminder_task(code)
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    # game builders
    # ------------------------------------------------------------------
    def _build_fork_room(
        self, n: int, *, roster_ready: bool = True, room_code: str = "RNL"
    ) -> Game:
        game = self.gm.create_game(
            host_id=7100 + n,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="namayande",
            max_players=n,
            nam10_no_host=True,
        )
        assert game is not None
        game.room_code = room_code
        self.gm.games[room_code] = game
        roles = roles_for_count(n)
        assert len(roles) == n
        seen_bases: dict[str, int] = {}
        for idx, role in enumerate(roles, start=1):
            base = SYNTHETIC_PLAYER_NAME_POOL[(idx - 1) % len(SYNTHETIC_PLAYER_NAME_POOL)]
            seen_bases[base] = seen_bases.get(base, 0) + 1
            count = seen_bases[base]
            unique_base = base if count == 1 else f"{base}{count}"
            uid = -(72000 + n * 100 + idx)
            self.gm.add_player(
                game,
                Player(
                    user_id=uid,
                    full_name=f"{unique_base}-{nam10_role_label_fa(role)}",
                    username=None,
                ),
            )
            p = game.players[uid]
            p.role = role
            p.seat = idx
        if roster_ready:
            game.bot_assistant_user_id = HELPER_CHAT_UID
            game.no_host_assistant_narrator_active = True
            game.nmnd_narrator_night_count = 2
            game.nmnd_night2_night_count = 2
            game.nmnd_night2_entry_dispatched = True
            game.nmnd_night2_mode = True
            game.nmnd_night2_phase = PENDING_COLLECTING
            game.phase = Phase.NIGHT
        return game

    def holder(self, game: Game, role: Role) -> Player:
        p = _holder(game, role)
        assert p is not None, role
        return p

    def all_pending_levers(self, game: Game) -> None:
        game.nmnd_night2_boss_phase = BOSS_PHASE_DONE
        game.nmnd_night2_dispositions.update(
            {
                "hacker_none": True,
                "guide_none": True,
                "guardian_none": True,
                "mine_none": True,
                "lawyer_none": True,
            }
        )
        game.nmnd_night2_doctor_uid = next(iter(game.players))
        game.nmnd_night2_soldier_uid = next(iter(game.players))
        for key in ("CITIZEN", "NATO", "NATO_AGENT"):
            game.nmnd_night2_waiting_acked[key] = [
                p.user_id
                for p in game.players.values()
                if p.role == getattr(Role, key)
            ]
        # Independent NATO stages are 12/13-only and must not be pending here.
        game.nmnd_night2_extra_kind = None
        game.nmnd_night2_soldier_grant_status = None

    def _bot(self) -> MagicMock:
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=4242))
        bot.edit_message_text = AsyncMock()
        bot.delete_message = AsyncMock()
        return bot


# ======================================================================
# 1. Night-panel synthetic labels
# ======================================================================


def _labels(rows) -> list[str]:
    return [btn.text for row in rows for btn in row]


class NightPanelLabelTests(_Isolated):
    async def test_danger_pick_rows_keep_suffix(self) -> None:
        game = self._build_fork_room(13)
        soldier = self.holder(game, Role.SOLDIER)
        pool = [p for p in game.players.values() if p.user_id != soldier.user_id]
        rows = _danger_pick_rows(
            game, soldier.user_id, ACT_SOLDIER_PICK, pool, None
        )
        labels = _labels(rows)
        for p in pool:
            if not is_synthetic_player_uid(p.user_id):
                continue
            expected = f"{fa_digits(p.seat)} — {p.full_name}"[:40]
            self.assertIn(expected, labels, p.full_name)
            self.assertEqual(labels.count(expected), 1, p.full_name)

    async def test_soldier_sniper_doctor_boss_shoot_panels(self) -> None:
        game = self._build_fork_room(13)
        pub = AsyncMock()
        synthetic_suffixes = [
            p.full_name for p in game.players.values() if is_synthetic_player_uid(p.user_id)
        ]
        uid_to_name = {
            p.user_id: p.full_name
            for p in game.players.values()
        }
        checks = (
            (_send_soldier_panel, self.holder(game, Role.SOLDIER)),
            (_send_sniper_panel, self.holder(game, Role.NATO_AGENT)),
        )
        for fn, owner in checks:
            pub.reset_mock()
            with patch("bot.nam10.night2._publish_panel", pub):
                await fn(MagicMock(), game, owner.user_id)
            kb = pub.await_args.args[5]
            labels = [
                btn.text for row in kb.inline_keyboard for btn in row
            ]
            for uid, suffix_name in uid_to_name.items():
                if uid == owner.user_id:
                    # The owner's seat is removed from its own panel pool.
                    continue
                matching = [
                    line for line in labels if line.split(" — ", 1)[-1] == suffix_name
                ]
                self.assertTrue(matching, suffix_name)

        # Doctor target panel: custom label closure also goes through
        # _button_label — suffix preserved except for «خودم».
        doc = self.holder(game, Role.DOCTOR)
        game.nmnd_night2_doctor_self_saves = 0
        pub.reset_mock()
        with patch("bot.nam10.night2._publish_panel", pub):
            await _send_doctor_pick_panel(MagicMock(), game, doc.user_id)
        kb = pub.await_args.args[5]
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("خودم", labels)
        for uid, suffix_name in uid_to_name.items():
            if uid == doc.user_id:
                # Self-target renders as «خودم», never as the annotated name.
                continue
            matching = [
                line for line in labels if line.split(" — ", 1)[-1] == suffix_name
            ]
            self.assertTrue(matching, suffix_name)

        # Mafia shot target selection (Boss mode menu was already chosen).
        boss = self.holder(game, Role.MAFIA_BOSS)
        game.nmnd_night2_boss_mode = "shot"
        pub.reset_mock()
        with patch("bot.nam10.night2._publish_panel", pub):
            await _send_boss_shot_panel(MagicMock(), game, boss.user_id)
        kb = pub.await_args.args[5]
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        for suffix_name in synthetic_suffixes:
            matching = [
                line for line in labels if line.split(" — ", 1)[-1] == suffix_name
            ]
            self.assertTrue(matching, suffix_name)

    def test_real_player_labels_stay_role_free(self) -> None:
        game = self._build_fork_room(10, roster_ready=False)
        real = Player(user_id=555, full_name="علی رضایی", username="alir", seat=6)
        self.gm.add_player(game, real)
        label = _button_label(game, real, 555)
        self.assertNotIn("-", label.replace(" — ", ""))
        self.assertIn("علی رضایی", label)

    def test_myname_priority_beats_suffix(self) -> None:
        game = self._build_fork_room(10, roster_ready=False)
        p = next(iter(game.players.values()))
        with patch("bot.nam10.night2._custom_display_name", return_value="امیرم"):
            label = _button_label(game, p, p.user_id)
        self.assertIn("امیرم", label)
        self.assertNotIn(nam10_role_label_fa(p.role), label)

    def test_suffix_never_duplicated_after_resync(self) -> None:
        game = self._build_fork_room(10, roster_ready=False)
        p = next(iter(game.players.values()))
        before = p.full_name
        sync_synthetic_player_display_names_nam10(game)
        self.assertEqual(p.full_name, before)
        label = _button_label(game, p, p.user_id)
        role_txt = nam10_role_label_fa(p.role)
        self.assertEqual(
            label.count(f"-{role_txt}"),
            max(1, 0) if f"-{role_txt}" in label else 0,
        )
        self.assertIn(f"-{role_txt}", label)

    def test_echo_texts_keep_suffix(self) -> None:
        game = self._build_fork_room(10, roster_ready=False)
        p = next(iter(game.players.values()))
        echo = _button_label(game, p, p.user_id)
        self.assertIn(f"-{nam10_role_label_fa(p.role)}", echo)


# ======================================================================
# 2. Observer roster labels
# ======================================================================


class ObserverRosterLabelTests(_Isolated):
    def test_nam10_roster_uses_fork_labels(self) -> None:
        game = self._build_fork_room(10, roster_ready=False)
        game.observer_user_id = 9001
        html = build_observer_players_roster_html(game, self.gm)
        self.assertIn("هکر", html)
        self.assertIn("یاغی", html)
        self.assertNotIn("شیاد", html)
        self.assertNotIn("کاراگاه", html)

    def test_bazpors_roster_unchanged(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        for idx, (uid, role) in enumerate(
            [(-11, Role.SHIAD), (-12, Role.NATO), (-13, Role.DETECTIVE)], start=1
        ):
            self.gm.add_player(
                game,
                Player(
                    user_id=uid,
                    full_name=f"بازیکن {idx}",
                    username=None,
                    role=role,
                    seat=idx,
                ),
            )
        html = build_observer_players_roster_html(game, self.gm)
        self.assertIn("شیاد", html)
        self.assertIn("ناتو", html)
        self.assertIn("کاراگاه", html)


# ======================================================================
# 3. Live reminder counter + removal
# ======================================================================


class LiveReminderCountTests(_Isolated):
    async def test_count_counts_actions_and_edits_live(self) -> None:
        game = self._build_fork_room(13)
        bot = self._bot()
        game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(
            bot, game, self.gm, generation=1, night_count=2
        )
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(game.night_helper_reminder_message_id, 4242)

        c0 = len(night2_required_keys(game))
        self.assertGreater(c0, 0)
        sent_text = bot.send_message.await_args.kwargs.get("text") or str(
            bot.send_message.await_args
        )
        self.assertIn(fa_digits(c0), sent_text)

        # Tentative selection must NOT shrink the counter (unconfirmed).
        game.nmnd_night2_mine_pending_uid = next(iter(game.players))
        self.assertEqual(len(night2_required_keys(game)), c0)
        await refresh_night_helper_reminder(bot, game)
        self.assertEqual(bot.edit_message_text.await_count, 0)

        # Confirmed dispositions shrink it — the SAME message is edited.
        game.nmnd_night2_dispositions["mine_none"] = True
        c1 = len(night2_required_keys(game))
        self.assertLess(c1, c0)
        await refresh_night_helper_reminder(bot, game)
        self.assertEqual(bot.edit_message_text.await_count, 1)
        self.assertEqual(
            bot.edit_message_text.await_args.kwargs["message_id"], 4242
        )
        self.assertIn(fa_digits(c1), bot.edit_message_text.await_args.kwargs["text"])

        # Each further confirmed lever keeps editing live.
        game.nmnd_night2_dispositions["lawyer_none"] = True
        c2 = len(night2_required_keys(game))
        self.assertLess(c2, c1)
        await refresh_night_helper_reminder(bot, game)
        self.assertEqual(bot.edit_message_text.await_count, 2)
        self.assertEqual(
            game.night_helper_reminder_last_count, c2
        )
        # No duplicate reminder messages were ever sent.
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_deleted_when_count_reaches_zero(self) -> None:
        game = self._build_fork_room(13)
        bot = self._bot()
        game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, self.gm, generation=1, night_count=2)
        self.assertGreater(len(night2_required_keys(game)), 0)
        self.all_pending_levers(game)
        self.assertEqual(night2_required_keys(game), [])
        await refresh_night_helper_reminder(bot, game)
        self.assertEqual(bot.delete_message.await_count, 1)
        self.assertIsNone(game.night_helper_reminder_message_id)
        self.assertEqual(bot.edit_message_text.await_count, 0)

    async def test_deleted_when_collection_leaves_pending(self) -> None:
        game = self._build_fork_room(13)
        bot = self._bot()
        game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, self.gm, generation=1, night_count=2)
        # Disciplinary elimination stage: collection left PENDING_COLLECTING.
        game.nmnd_night2_phase = PENDING_COLLECTED
        await refresh_night_helper_reminder(bot, game)
        self.assertEqual(bot.delete_message.await_count, 1)
        self.assertIsNone(game.night_helper_reminder_message_id)
        # Force-finish callbacks are invalidated by the phase gate.
        self.assertFalse(nam10_night_force_finish_collection_active(game))

    async def test_cleanup_deletes_bound_message_once(self) -> None:
        game = self._build_fork_room(13)
        bot = self._bot()
        game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, self.gm, generation=1, night_count=2)
        await cleanup_night_helper_reminder(bot, game)
        self.assertEqual(bot.delete_message.await_count, 1)
        self.assertIsNone(game.night_helper_reminder_message_id)
        await cleanup_night_helper_reminder(bot, game)
        self.assertEqual(bot.delete_message.await_count, 1)

    async def test_reminder_text_stays_helper_only(self) -> None:
        from bot.night_helper_reminder import build_counted_night_reminder_text

        game = self._build_fork_room(13)
        c0 = len(night2_required_keys(game))
        text = build_counted_night_reminder_text(game, c0)
        self.assertIn(fa_digits(c0), text)
        # No player identities in the reminder (generic rule warnings may
        # mention role words like «سرباز» by design — those name no one).
        for p in game.players.values():
            self.assertNotIn(p.full_name, text)
            self.assertNotIn(str(p.user_id), text)

    def test_120s_delay_constant_unchanged(self) -> None:
        self.assertEqual(REMINDER_DELAY_SEC, 120.0)


# ======================================================================
# 4. Restart recovery
# ======================================================================


class RestartRecoveryTests(_Isolated):
    async def _prepare(self, game: Game) -> None:
        game.night_helper_reminder_generation = 3
        game.night_helper_reminder_night_count = 2

    async def test_immediate_send_when_original_timer_elapsed(self) -> None:
        game = self._build_fork_room(13)
        await self._prepare(game)
        game.night_helper_reminder_scheduled_at = time.time() - (REMINDER_DELAY_SEC + 10)
        bot = self._bot()
        with patch("bot.app_state.manager", self.gm):
            await recover_night_helper_reminders_after_restart(bot)
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(game.night_helper_reminder_message_id, 4242)
        self.assertEqual(game.night_helper_reminder_night_count, 2)
        # Second recovery is a no-op (binding intact).
        await recover_night_helper_reminders_after_restart(bot)
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_pending_timer_recreated_with_remaining_delay(self) -> None:
        game = self._build_fork_room(13)
        await self._prepare(game)
        game.night_helper_reminder_scheduled_at = time.time() - 10
        bot = self._bot()
        try:
            with patch("bot.app_state.manager", self.gm):
                await recover_night_helper_reminders_after_restart(bot)
            task = _REMINDER_TASKS.get(game.room_code)
            self.assertIsNotNone(task)
            self.assertFalse(task.done())
            bot.send_message.assert_not_called()
        finally:
            cancel_night_helper_reminder_task(game.room_code)

    async def test_live_binding_kept_no_resend(self) -> None:
        game = self._build_fork_room(13)
        await self._prepare(game)
        game.night_helper_reminder_scheduled_at = time.time() - 300
        game.night_helper_reminder_chat_id = HELPER_CHAT_UID
        game.night_helper_reminder_message_id = 777
        game.night_helper_reminder_last_count = 9
        bot = self._bot()
        with patch("bot.app_state.manager", self.gm):
            await recover_night_helper_reminders_after_restart(bot)
        bot.send_message.assert_not_called()
        bot.edit_message_text.assert_not_called()
        bot.delete_message.assert_not_called()
        self.assertEqual(game.night_helper_reminder_message_id, 777)

    async def test_no_recovery_without_scheduling_stamp(self) -> None:
        game = self._build_fork_room(13)
        await self._prepare(game)
        game.night_helper_reminder_scheduled_at = 0.0
        bot = self._bot()
        with patch("bot.app_state.manager", self.gm):
            await recover_night_helper_reminders_after_restart(bot)
        bot.send_message.assert_not_called()

    async def test_no_recovery_across_nights(self) -> None:
        game = self._build_fork_room(13)
        game.night_helper_reminder_generation = 3
        game.night_helper_reminder_night_count = 1  # older night stamp
        game.night_helper_reminder_scheduled_at = time.time() - 300
        bot = self._bot()
        with patch("bot.app_state.manager", self.gm):
            await recover_night_helper_reminders_after_restart(bot)
        bot.send_message.assert_not_called()

    async def test_no_recovery_after_collection_finished(self) -> None:
        game = self._build_fork_room(13)
        await self._prepare(game)
        game.nmnd_night2_phase = PENDING_COLLECTED
        game.night_helper_reminder_scheduled_at = time.time() - 300
        bot = self._bot()
        with patch("bot.app_state.manager", self.gm):
            await recover_night_helper_reminders_after_restart(bot)
        bot.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
