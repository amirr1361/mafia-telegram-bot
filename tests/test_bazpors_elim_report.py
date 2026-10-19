"""Bazpors-only: eliminated-player mid-game report invitation + cutoff."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, role_label_fa
from bot.models import Phase, Player, Role
from bot.bazpors_elim_report import (
    BAZPORS_ELIM_REPORT_BUTTON_TEXT,
    BAZPORS_ELIM_REPORT_INVITE_HTML,
    BazporsElimReportCb,
    build_bazpors_elim_cutoff_report_html,
    capture_bazpors_elim_report_cutoff,
    handle_bazpors_elim_report_callback,
    resolve_bazpors_elim_report_html,
    send_bazpors_elim_report_invitation,
    split_html_message_chunks,
)
from bot.mozakere_elim_report import (
    capture_mozakere_elim_report_cutoff,
    maybe_send_mozakere_elim_report_invite,
)
from bot.observer_delivery import notify_eliminated_player


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

    def _bazpors(self, *, observer: int | None = 900):
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.observer_user_id = observer
        seats = [
            (10, "Boss", Role.GODFATHER),
            (11, "Nato", Role.NATO),
            (20, "Doc", Role.DOCTOR),
            (30, "Det", Role.DETECTIVE),
            (40, "Int", Role.INTERROGATOR),
            (50, "Sn", Role.SNIPER),
            (60, "Civ", Role.CITIZEN),
            (70, "Hunt", Role.HUNTER),
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


class BazporsElimReportCoreTests(_Isolated):
    def test_invite_wording_and_button(self) -> None:
        self.assertEqual(
            BAZPORS_ELIM_REPORT_INVITE_HTML,
            "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
            "روی دکمه «گزارش بازی» بزنید.",
        )
        self.assertEqual(BAZPORS_ELIM_REPORT_BUTTON_TEXT, "📋 گزارش بازی")
        packed = BazporsElimReportCb(code="12", as_uid=60, gts=1).pack()
        self.assertTrue(packed.startswith("bzrep:"))

    async def test_day_elim_sends_invite_after_elim_message(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.bazpors_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_bz:
            send_od.return_value = True
            send_bz.return_value = True
            await notify_eliminated_player(bot, game, 60)
        self.assertIn(60, game.bazpors_elim_report_cutoffs)
        # elim message first via observer_delivery
        elim_bodies = [
            c.args[2]
            for c in send_od.await_args_list
            if len(c.args) > 2 and "شما از بازی خارج شدید" in str(c.args[2])
        ]
        self.assertTrue(elim_bodies)
        invite_calls = [
            c
            for c in send_bz.await_args_list
            if c.args and BAZPORS_ELIM_REPORT_INVITE_HTML in str(c.args[2])
        ]
        self.assertTrue(invite_calls)
        kb = invite_calls[0].kwargs.get("reply_markup")
        self.assertEqual(kb.inline_keyboard[0][0].text, BAZPORS_ELIM_REPORT_BUTTON_TEXT)
        self.assertTrue(kb.inline_keyboard[0][0].callback_data.startswith("bzrep:"))

    async def test_duplicate_elim_no_second_invite(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.bazpors_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_bz:
            send_od.return_value = True
            send_bz.return_value = True
            await notify_eliminated_player(bot, game, 60)
            n1 = len(send_bz.await_args_list)
            await notify_eliminated_player(bot, game, 60)
            n2 = len(send_bz.await_args_list)
        self.assertEqual(n1, n2)

    def test_report_bazpors_roles_no_winner_no_mozakere(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        html_body = build_bazpors_elim_cutoff_report_html(game, self.gm)
        self.assertIn("بازیکنان و نقش‌ها", html_body)
        self.assertIn("بازپرس", html_body)  # scenario header
        self.assertIn(role_label_fa(Role.GODFATHER), html_body)
        self.assertIn(role_label_fa(Role.INTERROGATOR), html_body)
        self.assertNotIn("برنده", html_body)
        self.assertNotIn("پایان بازی", html_body)
        self.assertNotIn("مذاکره کننده", html_body)
        self.assertNotIn("آپاچی", html_body)

    def test_cutoff_immutable_after_later_events(self) -> None:
        game = self._bazpors()
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=60,
            source="day_vote",
            bazpors={"host_day": 1, "night_count": 0, "narrator_step": "day_discuss"},
        )
        game.players[60].is_alive = False
        entry = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry is not None
        frozen = entry["report_html"]
        self.assertIn("روز ۱", frozen)
        log_event(
            game,
            "night.resolved",
            night_report_html="<b>گزارش کامل شب گذشته</b>\n🔴 شات مافیا: Det",
            bazpors={"night_count": 2, "host_day": 2},
        )
        game.players[30].full_name = "CHANGED_LATER"
        again = resolve_bazpors_elim_report_html(
            game, 60, gts=entry["game_created_ts"]
        )
        self.assertEqual(again, frozen)
        self.assertNotIn("شب ۲", frozen)
        self.assertNotIn("CHANGED_LATER", frozen)
        live = build_bazpors_elim_cutoff_report_html(game, self.gm)
        self.assertIn("CHANGED_LATER", live)
        self.assertNotEqual(live, frozen)

    def test_two_players_different_cutoffs(self) -> None:
        game = self._bazpors()
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=60,
            source="day_vote",
            bazpors={"host_day": 1, "night_count": 0, "narrator_step": "day_discuss"},
        )
        game.players[60].is_alive = False
        e1 = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        log_event(
            game,
            "player.eliminated",
            uid=30,
            source="day_vote",
            bazpors={"host_day": 2, "night_count": 1, "narrator_step": "day_discuss"},
        )
        game.players[30].is_alive = False
        e2 = capture_bazpors_elim_report_cutoff(game, self.gm, 30)
        assert e1 and e2
        self.assertNotEqual(e1["report_html"], e2["report_html"])
        self.assertIn("روز ۱", e1["report_html"])
        self.assertIn("روز ۲", e2["report_html"])

    async def test_dead_player_callback_authorized(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        entry = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry
        bot = AsyncMock()
        cb = MagicMock()
        cb.from_user = MagicMock(id=60)
        with patch(
            "bot.bazpors_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.bazpors_elim_report.deliver_bazpors_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            deliver.return_value = True
            await handle_bazpors_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            deliver.assert_awaited()
            self.assertEqual(deliver.await_args.args[1], 60)
            self.assertEqual(deliver.await_args.args[2], entry["report_html"])

    async def test_living_and_unauthorized_rejected(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        entry = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry
        bot = AsyncMock()
        for actor in (20, 99999, 1):
            game.bot_assistant_user_id = 1
            cb = MagicMock()
            cb.from_user = MagicMock(id=actor)
            with patch(
                "bot.bazpors_elim_report.safe_callback_answer", new_callable=AsyncMock
            ), patch(
                "bot.bazpors_elim_report.deliver_bazpors_elim_report_chunks",
                new_callable=AsyncMock,
            ) as deliver:
                await handle_bazpors_elim_report_callback(
                    cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
                )
                deliver.assert_not_awaited()

    async def test_observer_mirror_and_callback(self) -> None:
        game = self._bazpors(observer=900)
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.bazpors_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_bz:
            send_od.return_value = True
            send_bz.return_value = True
            await notify_eliminated_player(bot, game, 60)
        obs_invites = [
            c
            for c in send_bz.await_args_list
            if c.args and c.args[1] == 900 and "گزارش بازی" in str(c.args[2])
        ]
        self.assertTrue(obs_invites)
        entry = game.bazpors_elim_report_cutoffs[60]
        cb = MagicMock()
        cb.from_user = MagicMock(id=900)
        with patch(
            "bot.bazpors_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.bazpors_elim_report.deliver_bazpors_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            deliver.return_value = True
            await handle_bazpors_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            self.assertEqual(deliver.await_args.args[1], 900)

    async def test_synthetic_invite_to_observer_only(self) -> None:
        game = self._bazpors(observer=900)
        syn = -101
        game.players[syn] = _p(syn, "SynBot", Role.CITIZEN, seat=9, alive=False)
        bot = AsyncMock()
        with patch(
            "bot.bazpors_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_bz:
            send_bz.return_value = True
            await send_bazpors_elim_report_invitation(bot, game, self.gm, syn)
        targets = [c.args[1] for c in send_bz.await_args_list if c.args]
        self.assertIn(900, targets)
        self.assertNotIn(syn, targets)

    async def test_no_observer_real_player_still_works(self) -> None:
        game = self._bazpors(observer=None)
        game.players[60].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.bazpors_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_bz:
            send_bz.return_value = True
            ok = await send_bazpors_elim_report_invitation(bot, game, self.gm, 60)
        self.assertTrue(ok)
        self.assertEqual(send_bz.await_args.args[1], 60)

    def test_stale_gts_rejected(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        entry = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry
        self.assertIsNone(
            resolve_bazpors_elim_report_html(
                game, 60, gts=entry["game_created_ts"] + 99
            )
        )

    def test_snapshot_roundtrip_keeps_cutoff(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        entry = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict

        loaded = game_from_snapshot_dict(game_to_snapshot_dict(game))
        got = resolve_bazpors_elim_report_html(
            loaded, 60, gts=entry["game_created_ts"]
        )
        self.assertEqual(got, entry["report_html"])

    def test_html_escape_and_chunks(self) -> None:
        game = self._bazpors()
        game.players[60].full_name = "A<b>&x"
        game.players[60].is_alive = False
        html_body = build_bazpors_elim_cutoff_report_html(game, self.gm)
        self.assertIn("A&lt;b&gt;&amp;x", html_body)
        long = ("پاراگراف تست.\n\n" * 400) + html_body
        parts = split_html_message_chunks(long, limit=500)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 500 for part in parts[:-1]))

    async def test_repeated_clicks_same_report(self) -> None:
        game = self._bazpors()
        game.players[60].is_alive = False
        entry = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry
        bot = AsyncMock()
        cb = MagicMock()
        cb.from_user = MagicMock(id=60)
        with patch(
            "bot.bazpors_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.bazpors_elim_report.deliver_bazpors_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            deliver.return_value = True
            await handle_bazpors_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            await handle_bazpors_elim_report_callback(
                cb, bot, game, as_uid=60, gts=entry["game_created_ts"]
            )
            self.assertEqual(deliver.await_count, 2)
            self.assertEqual(
                deliver.await_args_list[0].args[2],
                deliver.await_args_list[1].args[2],
            )

    def test_night_outcome_in_cutoff_when_present(self) -> None:
        game = self._bazpors()
        game.bazpors_narrator_night_count = 1
        game.bazpors_narrator_host_day = 1
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
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
        entry = capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry
        self.assertIn("شب ۱", entry["report_html"])
        self.assertIn("شات مافیا", entry["report_html"])

    async def test_mozakere_unchanged_no_bazpors_cutoff(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR, seat=1))
        self.gm.add_player(game, _p(20, "Civ", Role.CITIZEN, seat=2))
        game.roles_dealt = True
        game.phase = Phase.DAY_DISCUSSION
        game.players[20].is_alive = False
        from bot.game_audit_log import init_audit_log

        init_audit_log(game)
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.mozakere_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_mz, patch(
            "bot.bazpors_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_bz:
            send_od.return_value = True
            send_mz.return_value = True
            send_bz.return_value = True
            await notify_eliminated_player(bot, game, 20)
        self.assertIn(20, game.mozakere_elim_report_cutoffs)
        self.assertFalse(game.bazpors_elim_report_cutoffs)
        send_bz.assert_not_awaited()

    def test_mason_and_russian_noop(self) -> None:
        for scenario in ("masoon", "russian_mafia"):
            kwargs = dict(
                host_id=1,
                scenario_name=scenario,
                max_players=12,
                bazpors_host_mode="no_host",
            )
            if scenario == "russian_mafia":
                kwargs["bazpors_host_mode"] = "host_helper"
            game = self.gm.create_game(**kwargs)
            if game is None:
                continue
            self.gm.add_player(game, _p(10, "A", Role.CITIZEN, seat=1))
            game.roles_dealt = True
            game.phase = Phase.DAY_DISCUSSION
            game.players[10].is_alive = False
            self.assertIsNone(capture_bazpors_elim_report_cutoff(game, self.gm, 10))
            self.assertIsNone(capture_mozakere_elim_report_cutoff(game, self.gm, 10))


if __name__ == "__main__":
    unittest.main()
