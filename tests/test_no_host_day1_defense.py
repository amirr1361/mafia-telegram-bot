"""پنل دفاعیهٔ روز اول — حالت بدون گرداننده."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import (
    begin_no_host_day1_defense_pick,
    day_vote_defender_uids,
    day_vote_participation_count,
    day_vote_pick_uids,
    record_day_vote_participants,
    set_day_vote_defender_uids,
    set_day_vote_pick_uids,
)
from bot.game import GameManager
from bot.game_audit_log import (
    init_audit_log,
    normalize_day1_defense_act,
)
from bot.main import (
    NoHostDay1DefenseCb,
    _dispatch_no_host_day1_defense_act,
    _no_host_day1_defense_outcome_keyboard,
    build_no_host_day1_defense_no_exit_broadcast_html,
    build_no_host_day1_defense_outcome_html,
    build_no_host_day1_defense_pick_html,
    build_no_host_day1_elim_broadcast_html,
    build_no_host_day1_no_defense_votes_broadcast_html,
)
from bot.models import Phase, Player, Role


def _read_audit_lines(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _no_exit_events(lines: list[dict]) -> list[dict]:
    return [
        row
        for row in lines
        if row.get("event") == "no_host.day1_defense_callback"
        and row.get("act") == "no_exit"
    ]


class NoHostDay1DefenseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _game_with_players(self) -> tuple:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        for uid, name in ((10, "A"), (20, "B"), (30, "C")):
            self.gm.add_player(
                game, Player(user_id=uid, full_name=name, username=None)
            )
        game.phase = Phase.MANUAL
        game.roles_dealt = True
        game.bot_assistant_user_id = 10
        return game

    def test_begin_pick_clears_state(self) -> None:
        game = self._game_with_players()
        game.bazpors_day_vote_participations[20] = 2
        begin_no_host_day1_defense_pick(game)
        self.assertTrue(game.no_host_day1_defense_active)
        self.assertEqual(game.no_host_day1_defense_phase, "pick")
        self.assertEqual(day_vote_pick_uids(game), set())

    def test_outcome_html_shows_prior_participation_before_increment(self) -> None:
        game = self._game_with_players()
        begin_no_host_day1_defense_pick(game)
        set_day_vote_pick_uids(game, {20, 30})
        game.bazpors_day_vote_defender_uids = "20,30"
        game.bazpors_day_vote_participations[20] = 1
        html = build_no_host_day1_defense_outcome_html(game)
        self.assertIn("B", html)
        self.assertIn("سابقه حضور در رأی‌گیری‌های قبلی: ۱", html)
        self.assertIn("سابقه حضور در رأی‌گیری‌های قبلی: ۰", html)
        record_day_vote_participants(game, day_vote_defender_uids(game))
        self.assertEqual(day_vote_participation_count(game, 20), 2)
        self.assertEqual(day_vote_participation_count(game, 30), 1)

    def test_elim_broadcast_html(self) -> None:
        game = self._game_with_players()
        html = build_no_host_day1_elim_broadcast_html(game, 10, 20)
        self.assertIn("پایان روز اول", html)
        self.assertIn("اجماع رأی", html)
        self.assertIn("B", html)
        self.assertIn("فاز شب", html)

    def test_no_defense_votes_broadcast_html(self) -> None:
        game = self._game_with_players()
        html = build_no_host_day1_no_defense_votes_broadcast_html(game, 10)
        self.assertIn("پایان روز اول", html)
        self.assertIn("آرای لازم برای دفاعیه", html)
        self.assertIn("شب یک", html)
        self.assertIn("A", html)

    def test_defense_no_exit_broadcast_html(self) -> None:
        game = self._game_with_players()
        html = build_no_host_day1_defense_no_exit_broadcast_html(game, 10)
        self.assertIn("پایان روز اول", html)
        self.assertIn("پس از دفاعیه", html)
        self.assertIn("شب یک", html)
        self.assertIn("A", html)

    def test_pick_html_new_day_vote_copy(self) -> None:
        game = self._game_with_players()
        begin_no_host_day1_defense_pick(game)
        text = build_no_host_day1_defense_pick_html(game)
        self.assertIn("🌅 روز شروع شد", text)
        self.assertIn("برو به مرحله بعد", text)
        self.assertIn("دفاعیه نداریم", text)


class NoHostDay1DefenseNoExitDispatchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _outcome_game(self):
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        for uid, name in ((10, "A"), (20, "B")):
            self.gm.add_player(
                game, Player(user_id=uid, full_name=name, username=None)
            )
        game.phase = Phase.MANUAL
        game.roles_dealt = True
        game.bot_assistant_user_id = 10
        game.no_host_intro_night_started = True
        game.no_host_assistant_narrator_active = True
        begin_no_host_day1_defense_pick(game)
        game.no_host_day1_defense_phase = "outcome"
        set_day_vote_defender_uids(game, {20})
        return game

    async def test_outcome_no_exit_enters_night(self) -> None:
        game = self._outcome_game()

        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "outcome"
        cb.message.text = "outcome"
        cb.answer = AsyncMock()
        bot = AsyncMock()

        with patch(
            "bot.main.broadcast_to_alive_players", new_callable=AsyncMock
        ), patch(
            "bot.main.on_no_host_entered_night1", new_callable=AsyncMock
        ) as night:
            await _dispatch_no_host_day1_defense_act(
                cb, bot, game, 10, 10, "no_exit"
            )

        self.assertFalse(game.no_host_day1_defense_active)
        self.assertIsNone(game.no_host_day1_defense_phase)
        self.assertEqual(day_vote_participation_count(game, 20), 1)
        cb.answer.assert_awaited_once_with("ثبت شد.")
        night.assert_awaited_once()

    async def test_outcome_keyboard_includes_no_exit_callback(self) -> None:
        game = self._outcome_game()
        kb = _no_host_day1_defense_outcome_keyboard(game, 10, mirror=False)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertTrue(any("خروجی نداشتیم" in t for t in labels))
        packed = NoHostDay1DefenseCb.unpack(
            next(cb for cb in callbacks if "no_exit" in cb)
        )
        self.assertEqual(packed.act, "no_exit")
        self.assertEqual(normalize_day1_defense_act("d1d0"), "no_exit")

    async def test_no_exit_success_writes_audit_callback_and_outcome(self) -> None:
        game = self._outcome_game()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("bot.config.game_audit_log_enabled", return_value=True), patch(
                "bot.config.get_game_audit_log_dir", return_value=Path(tmp)
            ):
                init_audit_log(game)
                assert game.audit_log_path

                cb = MagicMock()
                cb.message = MagicMock()
                cb.message.html_text = "outcome"
                cb.message.text = "outcome"
                cb.answer = AsyncMock()
                bot = AsyncMock()

                with patch(
                    "bot.main.broadcast_to_alive_players", new_callable=AsyncMock
                ), patch("bot.main.on_no_host_entered_night1", new_callable=AsyncMock):
                    await _dispatch_no_host_day1_defense_act(
                        cb, bot, game, 10, 10, "no_exit", source="nhd"
                    )

                lines = _read_audit_lines(game.audit_log_path)
                no_exit_rows = _no_exit_events(lines)
                self.assertGreaterEqual(len(no_exit_rows), 1)
                received = [r for r in no_exit_rows if r.get("outcome") == "received"]
                completed = [r for r in no_exit_rows if r.get("outcome") == "completed"]
                self.assertEqual(len(received), 1)
                self.assertEqual(len(completed), 1)
                self.assertEqual(received[0]["source"], "nhd")
                self.assertEqual(received[0]["phase"], "outcome")
                outcomes = [
                    r for r in lines if r.get("event") == "no_host.day1_defense_outcome"
                ]
                self.assertEqual(len(outcomes), 1)
                self.assertFalse(outcomes[0]["had_exit"])

    async def test_each_no_exit_click_is_logged_separately(self) -> None:
        game = self._outcome_game()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("bot.config.game_audit_log_enabled", return_value=True), patch(
                "bot.config.get_game_audit_log_dir", return_value=Path(tmp)
            ):
                init_audit_log(game)
                assert game.audit_log_path

                cb = MagicMock()
                cb.message = None
                cb.answer = AsyncMock()
                bot = AsyncMock()

                for _ in range(3):
                    game.no_host_day1_defense_phase = "pick"
                    await _dispatch_no_host_day1_defense_act(
                        cb, bot, game, 10, 10, "no_exit", source="nhd"
                    )

                lines = _read_audit_lines(game.audit_log_path)
                no_exit_rows = _no_exit_events(lines)
                received = [r for r in no_exit_rows if r.get("outcome") == "received"]
                rejected = [
                    r
                    for r in no_exit_rows
                    if r.get("outcome") == "rejected"
                    and r.get("reject_reason") == "wrong_phase"
                ]
                self.assertEqual(len(received), 3)
                self.assertEqual(len(rejected), 3)

    async def test_no_exit_wrong_phase_rejected_without_entering_night(self) -> None:
        game = self._outcome_game()
        game.no_host_day1_defense_phase = "pick"
        cb = MagicMock()
        cb.message = None
        cb.answer = AsyncMock()
        bot = AsyncMock()

        with patch("bot.main.on_no_host_entered_night1", new_callable=AsyncMock) as night:
            await _dispatch_no_host_day1_defense_act(
                cb, bot, game, 10, 10, "no_exit", source="nhd"
            )

        self.assertTrue(game.no_host_day1_defense_active)
        self.assertEqual(game.no_host_day1_defense_phase, "pick")
        night.assert_not_awaited()
        cb.answer.assert_awaited_once()
        self.assertIn("فعال نیست", cb.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
