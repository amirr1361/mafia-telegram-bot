"""Mason-only: eliminated-player mid-game report invitation + cutoff."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, role_label_fa
from bot.models import Phase, Player, Role
from bot.mason_elim_report import (
    MASON_ELIM_REPORT_BUTTON_TEXT,
    MASON_ELIM_REPORT_INVITE_HTML,
    MasonElimReportCb,
    build_mason_elim_cutoff_report_html,
    capture_mason_elim_report_cutoff,
    handle_mason_elim_report_callback,
    resolve_mason_elim_report_html,
    send_mason_elim_report_invitation,
    split_html_message_chunks,
)
from bot.bazpors_elim_report import capture_bazpors_elim_report_cutoff
from bot.mozakere_elim_report import capture_mozakere_elim_report_cutoff
from bot.observer_delivery import notify_eliminated_player
from bot.roles import mason_fraternity as ms_mf


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

    def _mason(self, *, observer: int | None = 900):
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=14,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.observer_user_id = observer
        seats = [
            (10, "Boss", Role.GODFATHER),
            (11, "Sab", Role.SABOTEUR),
            (20, "Doc", Role.DOCTOR),
            (30, "Det", Role.DETECTIVE),
            (40, "Sn", Role.SNIPER),
            (50, "Cmd", Role.COMMANDER),
            (60, "Mason", Role.MASON),
            (70, "Civ", Role.TOWN_SIMPLE),
            (80, "Civ2", Role.CITIZEN),
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


class MasonElimReportCoreTests(_Isolated):
    def test_invite_wording_and_msrep_prefix(self) -> None:
        self.assertEqual(
            MASON_ELIM_REPORT_INVITE_HTML,
            "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
            "روی دکمه «گزارش بازی» بزنید.",
        )
        self.assertEqual(MASON_ELIM_REPORT_BUTTON_TEXT, "📋 گزارش بازی")
        self.assertTrue(MasonElimReportCb(code="12", as_uid=70, gts=1).pack().startswith("msrep:"))

    async def test_real_elim_sends_invite_after_elim_message(self) -> None:
        game = self._mason()
        game.players[70].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.mason_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_ms:
            send_od.return_value = True
            send_ms.return_value = True
            await notify_eliminated_player(bot, game, 70)
        self.assertIn(70, game.mason_elim_report_cutoffs)
        self.assertTrue(
            any(
                "شما از بازی خارج شدید" in str(c.args[2])
                for c in send_od.await_args_list
                if len(c.args) > 2
            )
        )
        invites = [
            c
            for c in send_ms.await_args_list
            if c.args and MASON_ELIM_REPORT_INVITE_HTML in str(c.args[2])
        ]
        self.assertTrue(invites)
        kb = invites[0].kwargs.get("reply_markup")
        self.assertEqual(kb.inline_keyboard[0][0].text, MASON_ELIM_REPORT_BUTTON_TEXT)
        self.assertTrue(kb.inline_keyboard[0][0].callback_data.startswith("msrep:"))

    async def test_duplicate_elim_no_second_invite(self) -> None:
        game = self._mason()
        game.players[70].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.mason_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_ms:
            send_od.return_value = True
            send_ms.return_value = True
            await notify_eliminated_player(bot, game, 70)
            n1 = len(send_ms.await_args_list)
            await notify_eliminated_player(bot, game, 70)
            n2 = len(send_ms.await_args_list)
        self.assertEqual(n1, n2)

    def test_report_mason_roles_no_winner(self) -> None:
        game = self._mason()
        game.players[70].is_alive = False
        html_body = build_mason_elim_cutoff_report_html(game, self.gm)
        self.assertIn("ماسون", html_body)
        self.assertIn("بازیکنان و نقش‌ها", html_body)
        self.assertIn(role_label_fa(Role.MASON), html_body)
        self.assertIn(role_label_fa(Role.COMMANDER), html_body)
        self.assertIn(role_label_fa(Role.SABOTEUR), html_body)
        self.assertNotIn("برنده", html_body)
        self.assertNotIn("پایان بازی", html_body)
        self.assertNotIn("مذاکره کننده", html_body)

    def test_recruitment_alone_no_cutoff_or_invite(self) -> None:
        game = self._mason()
        # recruit town into mason team — player stays alive
        welcome = ms_mf.commit_mason_recruit(
            game, game.players[60], game.players[70]
        )
        self.assertIsNotNone(welcome)
        self.assertTrue(game.players[70].is_alive)
        self.assertIsNone(capture_mason_elim_report_cutoff(game, self.gm, 70))
        self.assertFalse(game.mason_elim_report_cutoffs)

    async def test_recruitment_does_not_send_invite_via_notify_if_alive(self) -> None:
        """Even if notify were called while alive, no Mason invite/cutoff."""
        game = self._mason()
        self.assertTrue(game.players[70].is_alive)
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.mason_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_ms:
            send_od.return_value = True
            send_ms.return_value = True
            await notify_eliminated_player(bot, game, 70)
        self.assertFalse(game.mason_elim_report_cutoffs)
        send_ms.assert_not_awaited()

    def test_cutoff_immutable_after_later_events(self) -> None:
        game = self._mason()
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=70,
            source="day_vote",
            bazpors={"host_day": 1, "night_count": 0, "narrator_step": "day_discuss"},
        )
        game.players[70].is_alive = False
        entry = capture_mason_elim_report_cutoff(game, self.gm, 70)
        assert entry is not None
        frozen = entry["report_html"]
        self.assertIn("روز ۱", frozen)
        log_event(
            game,
            "night.resolved",
            night_report_html="<b>گزارش کامل شب گذشته</b>\n🔴 شات مافیا: Det",
            mason_final_outcome={
                "night": 2,
                "day": 2,
                "day_elim_uids": [],
                "night_elim_uids": [30],
                "finalized": True,
            },
            bazpors={"night_count": 2, "host_day": 2},
        )
        game.players[30].full_name = "CHANGED_LATER"
        again = resolve_mason_elim_report_html(
            game, 70, gts=entry["game_created_ts"]
        )
        self.assertEqual(again, frozen)
        self.assertNotIn("شب ۲", frozen)
        self.assertNotIn("CHANGED_LATER", frozen)
        live = build_mason_elim_cutoff_report_html(game, self.gm)
        self.assertIn("CHANGED_LATER", live)

    def test_two_players_different_cutoffs(self) -> None:
        game = self._mason()
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=70,
            source="day_vote",
            bazpors={"host_day": 1, "night_count": 0, "narrator_step": "day_discuss"},
        )
        game.players[70].is_alive = False
        e1 = capture_mason_elim_report_cutoff(game, self.gm, 70)
        log_event(
            game,
            "player.eliminated",
            uid=30,
            source="day_vote",
            bazpors={"host_day": 2, "night_count": 1, "narrator_step": "day_discuss"},
        )
        game.players[30].is_alive = False
        e2 = capture_mason_elim_report_cutoff(game, self.gm, 30)
        assert e1 and e2
        self.assertNotEqual(e1["report_html"], e2["report_html"])

    async def test_dead_player_and_observer_authorized(self) -> None:
        game = self._mason(observer=900)
        game.players[70].is_alive = False
        entry = capture_mason_elim_report_cutoff(game, self.gm, 70)
        assert entry
        bot = AsyncMock()
        for actor in (70, 900):
            cb = MagicMock()
            cb.from_user = MagicMock(id=actor)
            with patch(
                "bot.mason_elim_report.safe_callback_answer", new_callable=AsyncMock
            ), patch(
                "bot.mason_elim_report.deliver_mason_elim_report_chunks",
                new_callable=AsyncMock,
            ) as deliver:
                deliver.return_value = True
                await handle_mason_elim_report_callback(
                    cb, bot, game, as_uid=70, gts=entry["game_created_ts"]
                )
                deliver.assert_awaited()
                self.assertEqual(deliver.await_args.args[1], actor)

    async def test_living_helper_other_rejected(self) -> None:
        game = self._mason()
        game.bot_assistant_user_id = 1
        game.players[70].is_alive = False
        entry = capture_mason_elim_report_cutoff(game, self.gm, 70)
        assert entry
        bot = AsyncMock()
        for actor in (20, 1, 99999):
            cb = MagicMock()
            cb.from_user = MagicMock(id=actor)
            with patch(
                "bot.mason_elim_report.safe_callback_answer", new_callable=AsyncMock
            ), patch(
                "bot.mason_elim_report.deliver_mason_elim_report_chunks",
                new_callable=AsyncMock,
            ) as deliver:
                await handle_mason_elim_report_callback(
                    cb, bot, game, as_uid=70, gts=entry["game_created_ts"]
                )
                deliver.assert_not_awaited()

    async def test_observer_mirror_invite(self) -> None:
        game = self._mason(observer=900)
        game.players[70].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.mason_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_ms:
            send_od.return_value = True
            send_ms.return_value = True
            await notify_eliminated_player(bot, game, 70)
        self.assertTrue(
            any(c.args and c.args[1] == 900 for c in send_ms.await_args_list)
        )

    async def test_synthetic_invite_observer_only(self) -> None:
        game = self._mason(observer=900)
        syn = -101
        game.players[syn] = _p(syn, "Syn", Role.TOWN_SIMPLE, seat=10, alive=False)
        bot = AsyncMock()
        with patch(
            "bot.mason_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_ms:
            send_ms.return_value = True
            await send_mason_elim_report_invitation(bot, game, self.gm, syn)
        targets = [c.args[1] for c in send_ms.await_args_list if c.args]
        self.assertIn(900, targets)
        self.assertNotIn(syn, targets)

    def test_stale_gts_and_snapshot_roundtrip(self) -> None:
        game = self._mason()
        game.players[70].is_alive = False
        entry = capture_mason_elim_report_cutoff(game, self.gm, 70)
        assert entry
        self.assertIsNone(
            resolve_mason_elim_report_html(
                game, 70, gts=entry["game_created_ts"] + 1
            )
        )
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict

        loaded = game_from_snapshot_dict(game_to_snapshot_dict(game))
        self.assertEqual(
            resolve_mason_elim_report_html(
                loaded, 70, gts=entry["game_created_ts"]
            ),
            entry["report_html"],
        )

    def test_night_elim_in_cutoff(self) -> None:
        game = self._mason()
        game.bazpors_narrator_night_count = 1
        game.bazpors_narrator_host_day = 1
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        from bot.bazpors_narrator import _compose_full_night_report
        from bot.game_audit_log import log_night_resolved
        from bot.roles.night_state import mafia_night_state

        mafia_night_state(game).commit_shot(70)
        game.players[70].is_alive = False
        report = _compose_full_night_report(
            game, self.gm, game.bazpors_alive_at_night_start
        )
        game.bazpors_night_report_html = report
        log_night_resolved(game, self.gm)
        entry = capture_mason_elim_report_cutoff(game, self.gm, 70)
        assert entry
        self.assertIn("شب ۱", entry["report_html"])
        self.assertIn("شات مافیا", entry["report_html"])

    async def test_repeated_clicks_same_html(self) -> None:
        game = self._mason()
        game.players[70].is_alive = False
        entry = capture_mason_elim_report_cutoff(game, self.gm, 70)
        assert entry
        bot = AsyncMock()
        cb = MagicMock()
        cb.from_user = MagicMock(id=70)
        with patch(
            "bot.mason_elim_report.safe_callback_answer", new_callable=AsyncMock
        ), patch(
            "bot.mason_elim_report.deliver_mason_elim_report_chunks",
            new_callable=AsyncMock,
        ) as deliver:
            deliver.return_value = True
            await handle_mason_elim_report_callback(
                cb, bot, game, as_uid=70, gts=entry["game_created_ts"]
            )
            await handle_mason_elim_report_callback(
                cb, bot, game, as_uid=70, gts=entry["game_created_ts"]
            )
            self.assertEqual(
                deliver.await_args_list[0].args[2],
                deliver.await_args_list[1].args[2],
            )

    def test_chunks_and_escape(self) -> None:
        game = self._mason()
        game.players[70].full_name = "A<b>&x"
        game.players[70].is_alive = False
        html_body = build_mason_elim_cutoff_report_html(game, self.gm)
        self.assertIn("A&lt;b&gt;&amp;x", html_body)
        parts = split_html_message_chunks(("x\n\n" * 400) + html_body, limit=500)
        self.assertGreater(len(parts), 1)

    async def test_mozakere_bazpors_unchanged_on_mason_notify_path(self) -> None:
        game = self._mason()
        game.players[70].is_alive = False
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message", new_callable=AsyncMock
        ) as send_od, patch(
            "bot.mason_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_ms, patch(
            "bot.mozakere_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_mz, patch(
            "bot.bazpors_elim_report.safe_send_message", new_callable=AsyncMock
        ) as send_bz:
            send_od.return_value = True
            send_ms.return_value = True
            await notify_eliminated_player(bot, game, 70)
        self.assertIn(70, game.mason_elim_report_cutoffs)
        self.assertFalse(game.mozakere_elim_report_cutoffs)
        self.assertFalse(game.bazpors_elim_report_cutoffs)
        send_mz.assert_not_awaited()
        send_bz.assert_not_awaited()

    def test_other_scenarios_noop_for_mason_capture(self) -> None:
        for scenario, mode in (
            ("bazpors", "no_host"),
            ("mozakere", "no_host"),
            ("russian_mafia", "host_helper"),
        ):
            game = self.gm.create_game(
                host_id=1,
                scenario_name=scenario,
                max_players=12,
                bazpors_host_mode=mode,
            )
            if game is None:
                continue
            self.gm.add_player(game, _p(10, "A", Role.CITIZEN, seat=1))
            game.roles_dealt = True
            game.phase = Phase.DAY_DISCUSSION
            game.players[10].is_alive = False
            self.assertIsNone(capture_mason_elim_report_cutoff(game, self.gm, 10))


if __name__ == "__main__":
    unittest.main()
