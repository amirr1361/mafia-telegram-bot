"""Unified display-name priority tests (/myname > Telegram full_name > id).

Covers: /myname override, restart persistence via DB reload, no @username
suffix, selection-button default labels custom-first with uid-based
callback_data (duplicates stay independent), singleton fallback, HTML
escaping and synthetic-name stripping.
"""

from __future__ import annotations

import html
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot.game import GameManager
from bot.models import Game, Player


def _p(
    uid: int,
    name: str,
    *,
    username: str | None = None,
    seat: int | None = None,
) -> Player:
    return Player(user_id=uid, full_name=name, username=username, seat=seat)


def _game(players: list[Player], scenario: str = "namayande") -> Game:
    game = Game(room_code="R1", host_id=players[0].user_id if players else 1)
    game.scenario_name = scenario
    for p in players:
        game.players[p.user_id] = p
    return game


class IsolatedDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._db = root / "t.sqlite3"
        self._audit = root / "audit"
        self._audit.mkdir()
        self._patches = [
            mock.patch("bot.config.get_database_path", return_value=self._db),
            mock.patch("bot.config.get_game_audit_log_dir", return_value=self._audit),
            mock.patch.dict(
                os.environ,
                {
                    "DATABASE_PATH": str(self._db),
                    "GAME_AUDIT_LOG_DIR": str(self._audit),
                },
                clear=False,
            ),
        ]
        for patch in self._patches:
            patch.start()
        from bot import db

        db.init_db()
        self.gm = GameManager()

    def tearDown(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        self._tmp.cleanup()


class MyNameOverrideTests(IsolatedDbTestCase):
    def test_myname_overrides_telegram_full_name(self) -> None:
        gm = self.gm
        p = _p(101, "Amin", username="kh_ami")
        gm.set_user_display_name(101, "King")
        self.assertEqual(gm.get_user_display_name(101, p.full_name), "King")
        self.assertEqual(gm.format_player_tag(p), "King")
        self.assertEqual(
            gm.format_user_tag(101, "Amin", "kh_ami"), "King"
        )

    def test_without_myname_uses_telegram_full_name(self) -> None:
        gm = self.gm
        p = _p(102, "Amin", username="kh_ami")
        self.assertEqual(gm.format_player_tag(p), "Amin")
        self.assertEqual(
            gm.format_user_tag(102, "Amin", "kh_ami"), "Amin"
        )

    def test_no_username_suffix_anywhere(self) -> None:
        gm = self.gm
        p = _p(103, "Amin", username="kh_ami")
        gm.set_user_display_name(103, "King")
        self.assertNotIn("@", gm.format_player_tag(p))
        self.assertNotIn("(", gm.format_player_tag(p))
        self.assertNotIn("@", gm.format_user_tag(103, "Amin", "kh_ami"))

    def test_custom_name_survives_restart_db_reload(self) -> None:
        gm = self.gm
        gm.set_user_display_name(104, "King")
        # Simulated restart: a fresh manager loads from the database.
        restarted = GameManager()
        restarted.load_user_display_names_from_db()
        self.assertEqual(
            restarted.get_user_display_name(104, "Amin"), "King"
        )

    def test_default_myname_deletes_custom_name(self) -> None:
        gm = self.gm
        gm.set_user_display_name(105, "King")
        gm.set_user_display_name(105, "پیش‌فرض")
        self.assertEqual(gm.get_user_display_name(105, "Amin"), "Amin")

    def test_myname_prompt_constant_imported_in_hub(self) -> None:
        """Bare /myname prompt uses DISPLAY_NAME_MAX_LEN and must not NameError."""
        from bot.game import DISPLAY_NAME_MAX_LEN as from_game
        from bot.handlers.hub import DISPLAY_NAME_MAX_LEN

        self.assertEqual(DISPLAY_NAME_MAX_LEN, from_game)
        self.assertEqual(DISPLAY_NAME_MAX_LEN, 80)


class ButtonLabelTests(IsolatedDbTestCase):
    def test_default_pick_label_custom_first(self) -> None:
        from bot.no_host_role_pick_common import default_pick_label

        p = _p(201, "Amin")
        self.assertEqual(default_pick_label(p, "King"), "King")
        self.assertEqual(default_pick_label(p), "Amin")

    def test_target_button_rows_default_custom_first(self) -> None:
        from bot.no_host_role_pick_common import build_target_button_rows

        game = _game([_p(301, "Amin")])
        rows = build_target_button_rows(
            game,
            as_uid=999,
            pick_act="skt",
            players=list(game.players.values()),
            display_names={301: "King"},
        )
        labels = [btn.text for row in rows for btn in row]
        self.assertEqual(labels, ["King"])

    def test_target_button_rows_fallback_full_name(self) -> None:
        from bot.no_host_role_pick_common import build_target_button_rows

        game = _game([_p(302, "Amin", username="kh_ami")])
        rows = build_target_button_rows(
            game,
            as_uid=999,
            pick_act="skt",
            players=list(game.players.values()),
            display_names=None,
        )
        labels = [btn.text for row in rows for btn in row]
        # No @username suffix in newly rendered labels.
        self.assertEqual(labels, ["Amin"])

    def test_duplicate_names_have_independent_callbacks(self) -> None:
        from bot.no_host_role_pick_common import build_target_button_rows

        game = _game([_p(401, "Ali", seat=1), _p(402, "Ali", seat=2)])
        rows = build_target_button_rows(
            game,
            as_uid=999,
            pick_act="skt",
            players=sort_list(game),
            display_names={401: "Same", 402: "Same"},
        )
        cbs = []
        for row in rows:
            for btn in row:
                cbs.append(btn.callback_data)
        self.assertEqual(len(set(cbs)), 2)
        self.assertIn("401", cbs[0])
        self.assertIn("402", cbs[1])


def sort_list(game: Game) -> list[Player]:
    from bot.no_host_role_pick_common import sort_players_for_pick

    return sort_players_for_pick(list(game.players.values()))


class SingletonFallbackTests(IsolatedDbTestCase):
    def test_singleton_custom_display_name_lookup(self) -> None:
        from bot import app_state
        from bot.no_host_role_pick_common import player_button_name

        app_state.manager.user_display_names[501] = "Boss"
        try:
            self.assertEqual(
                player_button_name(_p(501, "Amin"), 501), "Boss"
            )
        finally:
            app_state.manager.user_display_names.pop(501, None)

    def test_singleton_other_users_unaffected(self) -> None:
        from bot import app_state
        from bot.no_host_role_pick_common import player_button_name

        app_state.manager.user_display_names[601] = "Boss"
        try:
            self.assertEqual(
                player_button_name(_p(602, "Amin"), 602), "Amin"
            )
        finally:
            app_state.manager.user_display_names.pop(601, None)

    def test_explicit_display_name_beats_everything(self) -> None:
        from bot import app_state
        from bot.no_host_role_pick_common import player_button_name

        app_state.manager.user_display_names[701] = "Singleton"
        try:
            self.assertEqual(
                player_button_name(
                    _p(701, "Amin"), 701, display_name="Explicit"
                ),
                "Explicit",
            )
        finally:
            app_state.manager.user_display_names.pop(701, None)


class HtmlAndSyntheticTests(IsolatedDbTestCase):
    def test_custom_name_is_html_escaped_in_default_label(self) -> None:
        gm = self.gm
        gm.set_user_display_name(801, "A<b>&")
        p = _p(801, "Amin")
        # format_player_tag stays raw; escaping happens at render seams.
        self.assertEqual(gm.format_player_tag(p), "A<b>&")
        from bot.no_host_role_pick_common import default_pick_label

        self.assertEqual(default_pick_label(p, "A<b>&"), html.escape("A<b>&"))

    def test_synthetic_display_name_strips_role_suffix(self) -> None:
        from bot.mason_night_reminder import mason_reminder_display_name

        p = _p(-920001, "بازیکن۵ - جاسوس")
        self.assertEqual(mason_reminder_display_name(p), "بازیکن۵")

    def test_night2_button_label_custom_and_seat(self) -> None:
        from bot.nam10.night2 import _button_label

        game = _game([_p(901, "Amin", seat=3)])
        # singleton lookup
        from bot import app_state

        app_state.manager.user_display_names[901] = "King"
        try:
            from bot.nam10.night2 import _seat_fa

            expected = html.escape(
                f"{_seat_fa(game.players[901].seat)} — King"
            )
            self.assertEqual(
                _button_label(game, game.players[901], 901), expected
            )
        finally:
            app_state.manager.user_display_names.pop(901, None)


if __name__ == "__main__":
    unittest.main()
