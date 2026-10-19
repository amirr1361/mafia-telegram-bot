"""Russian Mafia immutable eliminated-player report."""

from __future__ import annotations

import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, SEMI_AUTO_SYNTHETIC_UID_BASE
from bot.models import Phase, Player, Role
from bot.observer_delivery import flush_elimination_notifications, notify_eliminated_player
from bot.russian_mafia import (
    HOST_HELPER_MODE,
    ROLE_GODFATHER,
    ROLE_SIMPLE_MAFIA,
    ROLE_TERROR,
    apply_night_resolution,
    record_russian_elimination,
    russian_roles_for_count,
)
from bot.russian_mafia_elim_report import (
    RUSSIAN_MAFIA_ELIM_REPORT_BUTTON_TEXT,
    RUSSIAN_MAFIA_ELIM_REPORT_INVITE_HTML,
    RussianMafiaElimReportCb,
    build_russian_mafia_elim_cutoff_report_html,
    capture_russian_mafia_elim_report_cutoff,
    handle_russian_mafia_elim_report_callback,
    resolve_russian_mafia_elim_report_html,
    send_russian_mafia_elim_report_invitation,
)
from bot.russian_mafia_flow import apply_terror_eliminations


def _p(uid: int, name: str, *, seat: int) -> Player:
    return Player(user_id=uid, full_name=name, username=None, seat=seat)


class RussianMafiaElimReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._random_state = random.getstate()
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._db = root / "isolated.sqlite3"
        self._audit = root / "isolated-audit"
        self._audit.mkdir()
        self._patches = [
            mock.patch("bot.config.get_database_path", return_value=self._db),
            mock.patch(
                "bot.config.get_game_audit_log_dir", return_value=self._audit
            ),
            mock.patch.dict(
                os.environ,
                {
                    "DATABASE_PATH": str(self._db),
                    "GAME_AUDIT_LOG_DIR": str(self._audit),
                },
                clear=False,
            ),
        ]
        for item in self._patches:
            item.start()
        from bot import db

        db.init_db()
        self.gm = GameManager()

    def tearDown(self) -> None:
        for item in reversed(self._patches):
            item.stop()
        self._tmp.cleanup()
        random.setstate(self._random_state)

    def _game(
        self, count: int = 8, *, observer: int | None = 900, synthetic: bool = False
    ):
        game = self.gm.create_game(
            host_id=1,
            scenario_name="russian_mafia",
            max_players=count,
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        assert game is not None
        ids = (
            [SEMI_AUTO_SYNTHETIC_UID_BASE - i for i in range(count)]
            if synthetic
            else [100 + i for i in range(count)]
        )
        for seat, uid in enumerate(ids, start=1):
            assert self.gm.add_player(game, _p(uid, f"P{seat}", seat=seat)) is None
        mapping = dict(zip(ids, russian_roles_for_count(count)))
        self.gm.assign_russian_mafia_roles_by_player(game, mapping)
        game.roles_dealt = True
        game.phase = Phase.DAY_DISCUSSION
        game.russian_mafia_day_index = 1
        game.observer_user_id = observer
        game.observer_prompt_status = "registered" if observer else None
        game.bot_assistant_user_id = ids[-1]
        from bot.game_audit_log import init_audit_log

        init_audit_log(game)
        return game

    @staticmethod
    def _uid(game, role: Role) -> int:
        return next(p.user_id for p in game.players.values() if p.role == role)

    def test_invite_wording_button_and_namespace(self) -> None:
        self.assertEqual(
            RUSSIAN_MAFIA_ELIM_REPORT_INVITE_HTML,
            "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
            "روی دکمه «گزارش بازی» بزنید.",
        )
        self.assertEqual(
            RUSSIAN_MAFIA_ELIM_REPORT_BUTTON_TEXT, "📋 گزارش بازی"
        )
        self.assertTrue(
            RussianMafiaElimReportCb(code="12", as_uid=100, gts=1)
            .pack()
            .startswith("rmrep:")
        )

    async def test_normal_message_precedes_invitation(self) -> None:
        game = self._game()
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        order: list[str] = []

        async def normal(*args, **kwargs):
            order.append("normal")
            return True

        async def invite(*args, **kwargs):
            order.append("invite")
            return True

        with patch("bot.observer_delivery.safe_send_message", new=normal), patch(
            "bot.russian_mafia_elim_report.safe_send_message", new=invite
        ):
            await flush_elimination_notifications(AsyncMock(), game)
        self.assertEqual(order[0], "normal")
        self.assertIn("invite", order)
        self.assertIn(uid, game.russian_mafia_elim_report_cutoffs)

    async def test_day_vote_elimination_triggers_invitation(self) -> None:
        game = self._game()
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        with patch(
            "bot.russian_mafia_elim_report.safe_send_message",
            new=AsyncMock(return_value=True),
        ):
            await flush_elimination_notifications(AsyncMock(), game)
        report = game.russian_mafia_elim_report_cutoffs[uid]["report_html"]
        self.assertIn("خروج روز", report)
        self.assertIn("روز ۱", report)

    async def test_night_shot_triggers_but_doctor_save_does_not(self) -> None:
        game = self._game()
        victim = self._uid(game, Role.CITIZEN)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        game.russian_mafia_mafia_target = victim
        game.russian_mafia_mafia_confirmed = True
        game.russian_mafia_doctor_confirmed = True
        game.russian_mafia_doctor_targets = [self._uid(game, Role.DOCTOR)]
        apply_night_resolution(game)
        self.assertFalse(game.players[victim].is_alive)
        with patch(
            "bot.russian_mafia_elim_report.safe_send_message",
            new=AsyncMock(return_value=True),
        ):
            await flush_elimination_notifications(AsyncMock(), game)
        self.assertIn(victim, game.russian_mafia_elim_report_cutoffs)
        self.assertIn(
            "نتیجه نهایی شب",
            game.russian_mafia_elim_report_cutoffs[victim]["report_html"],
        )

        saved = self._game()
        protected = self._uid(saved, Role.CITIZEN)
        saved.phase = Phase.NIGHT
        saved.russian_mafia_night_index = 1
        saved.russian_mafia_mafia_target = protected
        saved.russian_mafia_doctor_confirmed = True
        saved.russian_mafia_doctor_targets = [protected]
        apply_night_resolution(saved)
        self.assertTrue(saved.players[protected].is_alive)
        self.assertNotIn(protected, saved.eliminated_notify_uids)

    async def test_discipline_elimination_triggers_and_is_in_cutoff(self) -> None:
        game = self._game()
        uid = self._uid(game, Role.CITIZEN)
        game.russian_mafia_night_index = 1
        record_russian_elimination(game, uid, source="discipline")
        with patch(
            "bot.russian_mafia_elim_report.safe_send_message",
            new=AsyncMock(return_value=True),
        ):
            await flush_elimination_notifications(AsyncMock(), game)
        report = game.russian_mafia_elim_report_cutoffs[uid]["report_html"]
        self.assertIn("اخراج انضباطی", report)

    async def test_terror_atomic_double_elimination_has_two_cutoffs(self) -> None:
        game = self._game()
        terror = self._uid(game, ROLE_TERROR)
        victim = self._uid(game, Role.CITIZEN)
        game.russian_mafia_terror_target = victim
        apply_terror_eliminations(game)
        self.assertEqual(
            set(game.eliminated_notify_uids), {terror, victim}
        )
        with patch(
            "bot.russian_mafia_elim_report.safe_send_message",
            new=AsyncMock(return_value=True),
        ):
            await flush_elimination_notifications(AsyncMock(), game)
        self.assertIn(terror, game.russian_mafia_elim_report_cutoffs)
        self.assertIn(victim, game.russian_mafia_elim_report_cutoffs)
        for uid in (terror, victim):
            report = game.russian_mafia_elim_report_cutoffs[uid]["report_html"]
            self.assertIn("نتیجه اقدام ترور", report)
            self.assertIn(game.players[terror].full_name, report)
            self.assertIn(game.players[victim].full_name, report)

    def test_eight_player_roster_roles_and_markers(self) -> None:
        game = self._game(8)
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        report = build_russian_mafia_elim_cutoff_report_html(game, self.gm)
        for label in (
            "گادفادر",
            "ترور",
            "پزشک",
            "کارآگاه",
            "شهروند ساده",
        ):
            self.assertIn(label, report)
        self.assertIn("🔴", report)
        self.assertIn("🟢", report)
        self.assertIn("تعداد بازیکنان: ۸ نفر", report)

    def test_nine_player_roster_has_two_simple_mafia_no_terror(self) -> None:
        game = self._game(9)
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        report = build_russian_mafia_elim_cutoff_report_html(game, self.gm)
        self.assertEqual(report.count("مافیای ساده"), 2)
        self.assertNotIn("— ترور", report)
        self.assertIn("تعداد بازیکنان: ۹ نفر", report)

    def test_names_seats_timeline_and_no_winner(self) -> None:
        game = self._game()
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        report = build_russian_mafia_elim_cutoff_report_html(game, self.gm)
        for seat in range(1, 9):
            self.assertIn(f"<b>{str(seat).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))}</b>", report)
            self.assertIn(f"P{seat}", report)
        self.assertIn("اتفاقات در طول بازی", report)
        self.assertNotIn("برنده", report)
        self.assertNotIn("پایان بازی", report)

    def test_cutoff_is_immutable_and_players_are_independent(self) -> None:
        game = self._game()
        citizens = [
            p.user_id for p in game.players.values() if p.role == Role.CITIZEN
        ]
        record_russian_elimination(game, citizens[0], source="day_vote")
        first = capture_russian_mafia_elim_report_cutoff(
            game, self.gm, citizens[0]
        )
        assert first is not None
        frozen = first["report_html"]
        game.russian_mafia_day_index = 2
        record_russian_elimination(game, citizens[1], source="day_vote")
        second = capture_russian_mafia_elim_report_cutoff(
            game, self.gm, citizens[1]
        )
        assert second is not None
        self.assertEqual(first["report_html"], frozen)
        self.assertNotEqual(first["report_html"], second["report_html"])
        self.assertNotIn(game.players[citizens[1]].full_name + " از بازی", frozen)

    def test_snapshot_roundtrip_and_old_snapshot_compatibility(self) -> None:
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict

        game = self._game()
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        entry = capture_russian_mafia_elim_report_cutoff(game, self.gm, uid)
        assert entry
        loaded = game_from_snapshot_dict(game_to_snapshot_dict(game))
        self.assertEqual(
            resolve_russian_mafia_elim_report_html(
                loaded, uid, gts=entry["game_created_ts"]
            ),
            entry["report_html"],
        )
        raw = game_to_snapshot_dict(game)
        raw["game"]["fields"].pop("russian_mafia_elim_report_cutoffs")
        old = game_from_snapshot_dict(raw)
        self.assertEqual(old.russian_mafia_elim_report_cutoffs, {})

    async def test_duplicate_processing_sends_one_invitation(self) -> None:
        game = self._game()
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        send = AsyncMock(return_value=True)
        with patch("bot.russian_mafia_elim_report.safe_send_message", new=send):
            await send_russian_mafia_elim_report_invitation(
                AsyncMock(), game, self.gm, uid
            )
            count = send.await_count
            await send_russian_mafia_elim_report_invitation(
                AsyncMock(), game, self.gm, uid
            )
        self.assertEqual(send.await_count, count)

    async def test_real_and_synthetic_observer_delivery(self) -> None:
        real = self._game(observer=900)
        uid = self._uid(real, Role.CITIZEN)
        record_russian_elimination(real, uid, source="day_vote")
        send = AsyncMock(return_value=True)
        with patch("bot.russian_mafia_elim_report.safe_send_message", new=send):
            await send_russian_mafia_elim_report_invitation(
                AsyncMock(), real, self.gm, uid
            )
        targets = [call.args[1] for call in send.await_args_list]
        self.assertIn(uid, targets)
        self.assertIn(900, targets)

        synthetic = self._game(observer=901, synthetic=True)
        syn = self._uid(synthetic, Role.CITIZEN)
        record_russian_elimination(synthetic, syn, source="day_vote")
        send_syn = AsyncMock(return_value=True)
        with patch(
            "bot.russian_mafia_elim_report.safe_send_message", new=send_syn
        ):
            await send_russian_mafia_elim_report_invitation(
                AsyncMock(), synthetic, self.gm, syn
            )
        syn_targets = [call.args[1] for call in send_syn.await_args_list]
        self.assertEqual(syn_targets, [901])

    async def test_owner_and_registered_observer_authorized(self) -> None:
        game = self._game(observer=900)
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        entry = capture_russian_mafia_elim_report_cutoff(game, self.gm, uid)
        assert entry
        for actor in (uid, 900):
            callback = MagicMock()
            callback.from_user = MagicMock(id=actor)
            with patch(
                "bot.russian_mafia_elim_report.safe_callback_answer",
                new=AsyncMock(),
            ), patch(
                "bot.russian_mafia_elim_report.deliver_russian_mafia_elim_report_chunks",
                new=AsyncMock(return_value=True),
            ) as deliver:
                await handle_russian_mafia_elim_report_callback(
                    callback,
                    AsyncMock(),
                    game,
                    as_uid=uid,
                    gts=entry["game_created_ts"],
                )
                deliver.assert_awaited_once()
                self.assertEqual(deliver.await_args.args[1], actor)

    async def test_living_other_helper_and_unregistered_observer_rejected(self) -> None:
        game = self._game(observer=900)
        uid = self._uid(game, Role.CITIZEN)
        record_russian_elimination(game, uid, source="day_vote")
        entry = capture_russian_mafia_elim_report_cutoff(game, self.gm, uid)
        assert entry
        helper = int(game.bot_assistant_user_id)
        living = next(p.user_id for p in game.players.values() if p.is_alive)
        for actor in (helper, living, 99999):
            callback = MagicMock()
            callback.from_user = MagicMock(id=actor)
            with patch(
                "bot.russian_mafia_elim_report.safe_callback_answer",
                new=AsyncMock(),
            ), patch(
                "bot.russian_mafia_elim_report.deliver_russian_mafia_elim_report_chunks",
                new=AsyncMock(),
            ) as deliver:
                await handle_russian_mafia_elim_report_callback(
                    callback,
                    AsyncMock(),
                    game,
                    as_uid=uid,
                    gts=entry["game_created_ts"],
                )
                deliver.assert_not_awaited()
        game.observer_prompt_status = "skipped"
        callback = MagicMock()
        callback.from_user = MagicMock(id=900)
        with patch(
            "bot.russian_mafia_elim_report.safe_callback_answer", new=AsyncMock()
        ), patch(
            "bot.russian_mafia_elim_report.deliver_russian_mafia_elim_report_chunks",
            new=AsyncMock(),
        ) as deliver:
            await handle_russian_mafia_elim_report_callback(
                callback,
                AsyncMock(),
                game,
                as_uid=uid,
                gts=entry["game_created_ts"],
            )
            deliver.assert_not_awaited()

    async def test_living_owner_and_stale_game_token_rejected(self) -> None:
        game = self._game()
        uid = self._uid(game, Role.CITIZEN)
        callback = MagicMock()
        callback.from_user = MagicMock(id=uid)
        with patch(
            "bot.russian_mafia_elim_report.safe_callback_answer", new=AsyncMock()
        ), patch(
            "bot.russian_mafia_elim_report.deliver_russian_mafia_elim_report_chunks",
            new=AsyncMock(),
        ) as deliver:
            await handle_russian_mafia_elim_report_callback(
                callback, AsyncMock(), game, as_uid=uid, gts=1
            )
            deliver.assert_not_awaited()

        record_russian_elimination(game, uid, source="day_vote")
        entry = capture_russian_mafia_elim_report_cutoff(game, self.gm, uid)
        assert entry
        self.assertIsNone(
            resolve_russian_mafia_elim_report_html(
                game, uid, gts=entry["game_created_ts"] + 1
            )
        )

    def test_other_scenario_capture_is_noop(self) -> None:
        game = self.gm.create_game(
            host_id=77,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(700, "Other", seat=1))
        game.players[700].role = Role.CITIZEN
        game.players[700].is_alive = False
        game.roles_dealt = True
        game.phase = Phase.DAY_DISCUSSION
        self.assertIsNone(
            capture_russian_mafia_elim_report_cutoff(game, self.gm, 700)
        )
        self.assertFalse(game.russian_mafia_elim_report_cutoffs)


if __name__ == "__main__":
    unittest.main()
