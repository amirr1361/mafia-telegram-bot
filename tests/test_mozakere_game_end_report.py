"""گزارش نهایی بازی — سناریوی مذاکره."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import _compose_full_night_report
from bot.game import GameManager, mozakere_role_label_fa
from bot.main import (
    _build_bazpors_timeline_html,
    _build_session_recap_roster_lines,
    build_bazpors_game_end_broadcast_html,
)
from bot.models import Phase, Player, Role
from bot.post_game_flow import (
    broadcast_bazpors_game_end_to_players,
    build_post_session_recap_snapshot,
)
from bot.roles.mozakere_journalist import commit_check as commit_journalist_check


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class MozakereGameEndReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_recap_uses_mozakere_role_labels(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        self.gm.add_player(game, _p(20, "Jr", Role.JOURNALIST))
        self.gm.add_player(game, _p(30, "Arm", Role.ARMORED))
        game.phase = Phase.ENDED
        snap = build_post_session_recap_snapshot(game, "citizen")
        rows = snap["rows"]
        assert isinstance(rows, list)
        lines = _build_session_recap_roster_lines(
            rows, scenario_name="mozakere"
        )
        joined = "\n".join(lines)
        self.assertIn(mozakere_role_label_fa(Role.MAFIA_NEGOTIATOR), joined)
        self.assertIn(mozakere_role_label_fa(Role.JOURNALIST), joined)
        self.assertIn(mozakere_role_label_fa(Role.ARMORED), joined)
        self.assertNotIn("بازپرس", joined)

    def test_recruited_player_shown_with_mozakere_note(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        civ = _p(40, "Recruit", Role.MAFIA_SIMPLE)
        civ.mozakere_original_role = Role.CITIZEN
        civ.mozakere_converted_by_negotiation = True
        self.gm.add_player(game, civ)
        snap = build_post_session_recap_snapshot(game, "mafia")
        rows = snap["rows"]
        assert isinstance(rows, list)
        lines = _build_session_recap_roster_lines(
            rows, scenario_name="mozakere"
        )
        joined = "\n".join(lines)
        self.assertIn("(مذاکره)", joined)
        self.assertIn(mozakere_role_label_fa(Role.CITIZEN), joined)

    def test_game_end_broadcast_html_includes_mozakere_labels(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        self.gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        self.gm.add_player(game, _p(20, "Doc", Role.DOCTOR))
        body = build_bazpors_game_end_broadcast_html(game, "citizen")
        self.assertIn("پایان بازی", body)
        self.assertIn(mozakere_role_label_fa(Role.MAFIA_NEGOTIATOR), body)
        self.assertIn(mozakere_role_label_fa(Role.DOCTOR), body)


class MozakereGameEndTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _mozakere_game_with_audit(self) -> tuple["Game", Path]:
        from bot.models import Game

        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_host_day = 1
        game.bazpors_narrator_night_count = 1
        game.bazpors_alive_at_night_start = {}

        self.gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS))
        self.gm.add_player(game, _p(11, "Neg", Role.MAFIA_NEGOTIATOR))
        self.gm.add_player(game, _p(20, "Doc", Role.DOCTOR))
        self.gm.add_player(game, _p(30, "Det", Role.DETECTIVE))
        self.gm.add_player(game, _p(40, "Jr", Role.JOURNALIST))
        self.gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        self.gm.add_player(game, _p(60, "C", Role.CITIZEN))
        game.mafia_ids.update({10, 11})

        game.mozakere_negotiation_tonight = True
        game.mozakere_negotiation_used = True
        game.mozakere_negotiation_target_uid = 60
        game.mozakere_negotiation_success = True
        game.mozakere_mafia_recruit_ids.add(60)
        recruit = game.players[60]
        recruit.mozakere_original_role = Role.CITIZEN
        recruit.mozakere_converted_by_negotiation = True
        recruit.role = Role.MAFIA_SIMPLE

        commit_journalist_check(game, 60)
        game.no_host_journalist_pick_confirmed = True

        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = 20
        game.actions.detective_check = 60
        game.bazpors_det_no_inquiry = False
        game.bazpors_sniper_night_target_uid = 11

        alive_snap = {uid: p.is_alive for uid, p in game.players.items()}
        game.bazpors_alive_at_night_start = alive_snap
        report_html = _compose_full_night_report(game, self.gm, alive_snap)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            log_path = Path(f.name)
            f.write(
                json.dumps(
                    {
                        "event": "night.resolved",
                        "night_report_html": report_html,
                        "bazpors": {"night_count": 1, "host_day": 1},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "event": "no_host.mozakere_negotiation_committed",
                        "night_count": 1,
                        "target_uid": 60,
                        "success": True,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "event": "no_host.journalist_pick_confirmed",
                        "night_count": 1,
                        "target_uid": 60,
                        "journalist_positive": True,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "event": "game.ended",
                        "winner": "citizen",
                        "bazpors": {"host_day": 1, "night_count": 1},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        game.audit_log_path = str(log_path)
        game.phase = Phase.ENDED
        return game, log_path

    def test_timeline_html_includes_mozakere_events(self) -> None:
        game, log_path = self._mozakere_game_with_audit()
        try:
            snap = build_post_session_recap_snapshot(game, "citizen")
            html = _build_bazpors_timeline_html(snap)
            self.assertIn("اتفاقات در طول بازی", html)
            self.assertIn("شات مافیا", html)
            self.assertIn("مذاکره", html)
            self.assertIn("خبرنگار", html)
            self.assertIn("استعلام کارآگاه", html)
            self.assertIn("تک‌تیرانداز", html)
        finally:
            log_path.unlink(missing_ok=True)

    def test_game_end_broadcast_includes_full_timeline(self) -> None:
        game, log_path = self._mozakere_game_with_audit()
        try:
            body = build_bazpors_game_end_broadcast_html(game, "citizen")
            self.assertIn("اتاق شماره", body)
            self.assertIn("بازیکنان و نقش‌ها", body)
            self.assertIn("اتفاقات در طول بازی", body)
            self.assertIn("مذاکره", body)
            self.assertIn(mozakere_role_label_fa(Role.JOURNALIST), body)
        finally:
            log_path.unlink(missing_ok=True)


class MozakereGameEndBroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_mozakere_broadcast_sends_to_players(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        gm.add_player(game, _p(10, "A", Role.CITIZEN))
        gm.add_player(game, _p(20, "B", Role.MAFIA_BOSS))
        bot = MagicMock()
        sent: list[int] = []

        async def _capture(bot_, g, uid, text, **kwargs):
            sent.append(uid)

        with patch(
            "bot.post_game_flow.deliver_no_host_player_game_copy",
            new=AsyncMock(side_effect=_capture),
        ), patch(
            "bot.post_game_flow.safe_send_message",
            new=AsyncMock(),
        ), patch(
            "bot.post_game_flow.mirror_per_player_to_observer",
            new=AsyncMock(),
        ):
            await broadcast_bazpors_game_end_to_players(bot, game, "citizen")

        self.assertIn(10, sent)
        self.assertIn(20, sent)

    async def test_bazpors_broadcast_still_works(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        gm.add_player(game, _p(10, "A", Role.CITIZEN))
        bot = MagicMock()
        sent: list[int] = []

        async def _capture(bot_, g, uid, text, **kwargs):
            sent.append(uid)

        with patch(
            "bot.post_game_flow.deliver_no_host_player_game_copy",
            new=AsyncMock(side_effect=_capture),
        ), patch(
            "bot.post_game_flow.safe_send_message",
            new=AsyncMock(),
        ), patch(
            "bot.post_game_flow.mirror_per_player_to_observer",
            new=AsyncMock(),
        ):
            await broadcast_bazpors_game_end_to_players(bot, game, "citizen")

        self.assertEqual(sent, [10])
