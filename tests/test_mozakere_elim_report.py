"""Mozakere-only: eliminated-player mid-game report invitation + cutoff."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.mozakere_elim_report import (
    MOZAKERE_ELIM_REPORT_BUTTON_TEXT,
    MOZAKERE_ELIM_REPORT_INVITE_HTML,
    MozakereElimReportCb,
    build_mozakere_elim_cutoff_report_html,
    capture_mozakere_elim_report_cutoff,
    handle_mozakere_elim_report_callback,
    resolve_mozakere_elim_report_html,
    send_mozakere_elim_report_invitation,
    split_html_message_chunks,
)
from bot.observer_delivery import (
    ELIMINATED_PLAYER_MESSAGE_HTML,
    flush_elimination_notifications,
    notify_eliminated_player,
    queue_player_elimination_notify,
)


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


class _Isolated(unittest.IsolatedAsyncioTestCase):
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
        for p in self._patches:
            p.start()
        from bot import db

        db.init_db()
        self.gm = GameManager()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _mozakere(self, *, observer: int | None = 900):
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.observer_user_id = observer
        seats = [
            (10, "Boss", Role.MAFIA_BOSS),
            (11, "Neg", Role.MAFIA_NEGOTIATOR),
            (20, "Doc", Role.DOCTOR),
            (30, "Det", Role.DETECTIVE),
            (40, "Jr", Role.JOURNALIST),
            (50, "Sn", Role.SNIPER),
            (60, "Civ", Role.CITIZEN),
            (70, "Arm", Role.ARMORED),
        ]
        for i, (uid, name, role) in enumerate(seats, start=1):
            err = self.gm.add_player(game, _p(uid, name, role, seat=i))
            assert err is None, err
        game.mafia_ids.update({10, 11})
        game.roles_dealt = True
        game.phase = Phase.DAY_DISCUSSION
        game.bazpors_narrator_host_day = 1
        game.bazpors_narrator_night_count = 0
        from bot.game_audit_log import init_audit_log

        init_audit_log(game)
        return game


class MozakereElimReportCoreTests(_Isolated):
    def test_invite_wording_and_button(self) -> None:
        self.assertEqual(
            MOZAKERE_ELIM_REPORT_INVITE_HTML,
            "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
            "روی دکمه «گزارش بازی» بزنید.",
        )
        self.assertEqual(MOZAKERE_ELIM_REPORT_BUTTON_TEXT, "📋 گزارش بازی")

    async def test_day_elim_sends_invite(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send, patch(
            "bot.mozakere_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send2:
            send.return_value = True
            send2.return_value = True
            await notify_eliminated_player(bot, game, 60)
        # invite captured
        self.assertIn(60, game.mozakere_elim_report_cutoffs)
        invite_calls = [
            c
            for c in send2.await_args_list
            if c.args and MOZAKERE_ELIM_REPORT_INVITE_HTML in str(c.args[2])
        ]
        self.assertTrue(invite_calls)
        # button present
        kb = invite_calls[0].kwargs.get("reply_markup")
        self.assertIsNotNone(kb)
        data = kb.inline_keyboard[0][0].callback_data
        self.assertTrue(data.startswith("mzrep:"))
        self.assertEqual(kb.inline_keyboard[0][0].text, MOZAKERE_ELIM_REPORT_BUTTON_TEXT)

    async def test_duplicate_elim_no_second_invite(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send, patch(
            "bot.mozakere_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send2:
            send.return_value = True
            send2.return_value = True
            await notify_eliminated_player(bot, game, 60)
            n1 = len(send2.await_args_list)
            await notify_eliminated_player(bot, game, 60)
            n2 = len(send2.await_args_list)
        self.assertEqual(n1, n2)

    def test_report_has_roles_and_no_mason_roles(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        html_body = build_mozakere_elim_cutoff_report_html(game, self.gm)
        self.assertIn("بازیکنان و نقش‌ها", html_body)
        from bot.game import mozakere_role_label_fa

        self.assertIn(mozakere_role_label_fa(Role.MAFIA_BOSS), html_body)
        self.assertIn(mozakere_role_label_fa(Role.JOURNALIST), html_body)
        self.assertNotIn("آپاچی", html_body)
        self.assertNotIn("محافظ", html_body)
        self.assertNotIn("ماسون", html_body)

    def test_cutoff_immutable_after_later_events(self) -> None:
        game = self._mozakere()
        from bot.game_audit_log import log_event

        # seed a day-1 elimination event so timeline exists
        log_event(
            game,
            "player.eliminated",
            uid=60,
            source="day_vote",
            bazpors={"host_day": 1, "night_count": 0, "narrator_step": "day_discuss"},
        )
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry is not None
        frozen = entry["report_html"]
        self.assertIn("روز ۱", frozen)
        # later gameplay in audit + role rename would affect live rebuild
        log_event(
            game,
            "night.resolved",
            night_report_html="<b>گزارش کامل شب گذشته</b>\n🔴 شات مافیا: Det",
            bazpors={"night_count": 2, "host_day": 2},
        )
        game.bazpors_narrator_night_count = 2
        game.bazpors_narrator_host_day = 3
        game.players[30].full_name = "CHANGED_LATER"
        again = resolve_mozakere_elim_report_html(
            game, 60, gts=entry["game_created_ts"]
        )
        self.assertEqual(again, frozen)
        self.assertNotIn("شب ۲", frozen)
        self.assertNotIn("CHANGED_LATER", frozen)
        live = build_mozakere_elim_cutoff_report_html(game, self.gm)
        self.assertIn("CHANGED_LATER", live)
        self.assertNotEqual(live, frozen)

    def test_two_players_different_cutoffs(self) -> None:
        game = self._mozakere()
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=60,
            source="day_vote",
            bazpors={"host_day": 1, "night_count": 0, "narrator_step": "day_discuss"},
        )
        game.players[60].is_alive = False
        e1 = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        log_event(
            game,
            "player.eliminated",
            uid=30,
            source="day_vote",
            bazpors={"host_day": 2, "night_count": 1, "narrator_step": "day_discuss"},
        )
        game.players[30].is_alive = False
        e2 = capture_mozakere_elim_report_cutoff(game, self.gm, 30)
        assert e1 and e2
        self.assertNotEqual(e1["report_html"], e2["report_html"])
        self.assertIn("روز ۱", e1["report_html"])
        self.assertIn("روز ۲", e2["report_html"])

    async def test_dead_player_callback_authorized(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        bot = AsyncMock()
        cb = MagicMock()
        cb.from_user = MagicMock(id=60)
        with patch(
            "bot.mozakere_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.mozakere_elim_report.deliver_mozakere_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            deliver.return_value = True
            await handle_mozakere_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            deliver.assert_awaited()
            self.assertEqual(deliver.await_args.args[1], 60)
            self.assertEqual(deliver.await_args.args[2], entry["report_html"])

    async def test_living_player_rejected(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        # attacker is living player 20
        cb = MagicMock()
        cb.from_user = MagicMock(id=20)
        bot = AsyncMock()
        with patch(
            "bot.mozakere_elim_report.safe_callback_answer", new_callable=AsyncMock
        ) as ans, patch(
            "bot.mozakere_elim_report.deliver_mozakere_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            await handle_mozakere_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            deliver.assert_not_awaited()
            ans.assert_awaited()

    async def test_other_uid_rejected(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        cb = MagicMock()
        cb.from_user = MagicMock(id=99999)
        bot = AsyncMock()
        with patch(
            "bot.mozakere_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.mozakere_elim_report.deliver_mozakere_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            await handle_mozakere_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            deliver.assert_not_awaited()

    async def test_helper_no_auto_access(self) -> None:
        game = self._mozakere()
        game.bot_assistant_user_id = 1
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        cb = MagicMock()
        cb.from_user = MagicMock(id=1)  # helper, not elim / not obs
        bot = AsyncMock()
        with patch(
            "bot.mozakere_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.mozakere_elim_report.deliver_mozakere_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            await handle_mozakere_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            deliver.assert_not_awaited()

    async def test_observer_mirror_and_callback(self) -> None:
        game = self._mozakere(observer=900)
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send, patch(
            "bot.mozakere_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send2:
            send.return_value = True
            send2.return_value = True
            await notify_eliminated_player(bot, game, 60)
        obs_invites = [
            c
            for c in send2.await_args_list
            if c.args and c.args[1] == 900 and "گزارش بازی" in str(c.args[2])
        ]
        self.assertTrue(obs_invites)
        entry = game.mozakere_elim_report_cutoffs[60]
        cb = MagicMock()
        cb.from_user = MagicMock(id=900)
        with patch(
            "bot.mozakere_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.mozakere_elim_report.deliver_mozakere_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            deliver.return_value = True
            await handle_mozakere_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            self.assertEqual(deliver.await_args.args[1], 900)

    async def test_synthetic_invite_to_observer_only(self) -> None:
        game = self._mozakere(observer=900)
        syn = -101
        # phase already advanced — insert synthetic seat directly
        game.players[syn] = _p(syn, "SynBot", Role.CITIZEN, seat=9, alive=False)
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send, patch(
            "bot.mozakere_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send2:
            send.return_value = True
            send2.return_value = True
            await send_mozakere_elim_report_invitation(bot, game, self.gm, syn)
        targets = [c.args[1] for c in send2.await_args_list if c.args]
        self.assertIn(900, targets)
        self.assertNotIn(syn, targets)

    async def test_no_observer_real_player_still_works(self) -> None:
        game = self._mozakere(observer=None)
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.mozakere_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send2:
            send2.return_value = True
            ok = await send_mozakere_elim_report_invitation(bot, game, self.gm, 60)
        self.assertTrue(ok)
        self.assertEqual(send2.await_args.args[1], 60)

    def test_stale_gts_rejected(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        self.assertIsNone(
            resolve_mozakere_elim_report_html(game, 60, gts=entry["game_created_ts"] + 99)
        )

    def test_snapshot_roundtrip_keeps_cutoff(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict

        payload = game_to_snapshot_dict(game)
        # ENDED refused — keep phase non-ended
        loaded = game_from_snapshot_dict(payload)
        got = resolve_mozakere_elim_report_html(
            loaded, 60, gts=entry["game_created_ts"]
        )
        self.assertEqual(got, entry["report_html"])

    def test_html_escape_and_chunks(self) -> None:
        game = self._mozakere()
        game.players[60].full_name = "A<b>&x"
        game.players[60].is_alive = False
        html_body = build_mozakere_elim_cutoff_report_html(game, self.gm)
        self.assertIn("A&lt;b&gt;&amp;x", html_body)
        long = ("پاراگراف تست.\n\n" * 400) + html_body
        parts = split_html_message_chunks(long, limit=500)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 500 for part in parts[:-1]))
        self.assertIn("پاراگراف تست", parts[0])
        self.assertIn("بازیکنان و نقش", parts[-1])

    def test_non_mozakere_noop(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(10, "A", Role.CITIZEN))
        game.roles_dealt = True
        game.phase = Phase.DAY_DISCUSSION
        game.players[10].is_alive = False
        self.assertIsNone(capture_mozakere_elim_report_cutoff(game, self.gm, 10))

    async def test_bazpors_notify_unchanged_no_invite_field(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.roles_dealt = True
        self.gm.add_player(game, _p(10, "A", Role.CITIZEN))
        game.players[10].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send:
            send.return_value = True
            await notify_eliminated_player(bot, game, 10)
        # only elim message, no moz cutoff
        self.assertFalse(getattr(game, "mozakere_elim_report_cutoffs", {}))
        bodies = [c.args[2] for c in send.await_args_list if len(c.args) > 2]
        self.assertTrue(any("شما از بازی خارج شدید" in b for b in bodies))
        self.assertFalse(any("گزارش بازی تا این لحظه" in b for b in bodies))

    async def test_repeated_clicks_same_report(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        bot = AsyncMock()
        cb = MagicMock()
        cb.from_user = MagicMock(id=60)
        with patch(
            "bot.mozakere_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.mozakere_elim_report.deliver_mozakere_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            deliver.return_value = True
            await handle_mozakere_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            await handle_mozakere_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            self.assertEqual(deliver.await_count, 2)
            self.assertEqual(
                deliver.await_args_list[0].args[2], deliver.await_args_list[1].args[2]
            )

    async def test_observer_wrong_room_stale(self) -> None:
        game = self._mozakere()
        game.players[60].is_alive = False
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        other = self._mozakere(observer=900)
        other.room_code = "99"
        # gts from first game won't match other
        self.assertIsNone(
            resolve_mozakere_elim_report_html(
                other, 60, gts=entry["game_created_ts"]
            )
        )

    def test_night_outcome_in_cutoff_when_present(self) -> None:
        game = self._mozakere()
        game.bazpors_narrator_night_count = 1
        game.bazpors_narrator_host_day = 1
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        # day1 no death; night kill civ via audit night report style
        from bot.bazpors_narrator import _compose_full_night_report
        from bot.game_audit_log import log_night_resolved
        from bot.roles.night_state import mafia_night_state

        mafia_night_state(game).commit_shot(60)
        game.players[60].is_alive = False
        report = _compose_full_night_report(
            game, self.gm, game.bazpors_alive_at_night_start
        )
        game.bazpors_night_report_html = report
        log_night_resolved(game, self.gm)
        entry = capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry
        self.assertIn("شب ۱", entry["report_html"])
        self.assertIn("شات مافیا", entry["report_html"])


if __name__ == "__main__":
    unittest.main()
