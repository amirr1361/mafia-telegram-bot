"""گزارش نهایی بازی — سناریوی ماسون."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bot.bazpors_narrator import _compose_full_night_report
from bot.game import GameManager
from bot.main import (
    _build_bazpors_timeline_html,
    build_bazpors_game_end_broadcast_html,
)
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.models import Phase, Player, Role
from bot.post_game_flow import build_post_session_recap_snapshot
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_mf
from bot.roles import mason_natasha as ms_nat
from bot.roles import mason_nato as ms_nato
from bot.roles import mason_sniper as ms_sn
from bot.roles.night_state import mafia_night_state


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class MasonGameEndTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _mason_game_with_audit(self) -> tuple[object, Path]:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=14,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_host_day = 1
        game.bazpors_narrator_night_count = 1
        game.bazpors_alive_at_night_start = {}

        self.gm.add_player(game, _p(10, "Boss", Role.GODFATHER))
        self.gm.add_player(game, _p(11, "Sab", Role.SABOTEUR))
        self.gm.add_player(game, _p(20, "Doc", Role.DOCTOR))
        self.gm.add_player(game, _p(30, "Det", Role.DETECTIVE))
        self.gm.add_player(game, _p(40, "Sn", Role.SNIPER))
        self.gm.add_player(game, _p(50, "Cmd", Role.COMMANDER))
        self.gm.add_player(game, _p(60, "Mason", Role.MASON))
        self.gm.add_player(game, _p(70, "Nat", Role.NATASHA))
        self.gm.add_player(game, _p(80, "C", Role.TOWN_SIMPLE))
        game.mafia_ids.update({10, 11})

        mafia_night_state(game).commit_shot(80)
        ms_doc.commit_mason_doctor_save(game, 80)
        ms_sn.commit_mason_sniper_night_selection(game, [11])
        ms_cmd.commit_mason_commander_approval(game, [11])
        game.actions.detective_check = 60
        game.bazpors_det_no_inquiry = False
        ms_nat.commit_mason_natasha_target(
            game, game.players[70], game.players[50], confirmed=True
        )
        game.mason_nato_tonight = True
        ms_nato.commit_mason_nato_guess(game, Role.DOCTOR, 20)
        ms_mf.commit_mason_recruit(game, game.players[60], game.players[80])

        alive_snap = {uid: p.is_alive for uid, p in game.players.items()}
        game.bazpors_alive_at_night_start = alive_snap
        apply_mason_night_resolution(game, self.gm)
        report_html = _compose_full_night_report(game, self.gm, alive_snap)
        from bot.mason_final_outcome import find_mason_final_night_outcome

        mason_outcome = find_mason_final_night_outcome(game, 1)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            log_path = Path(f.name)
            payload = {
                "event": "night.resolved",
                "night_report_html": report_html,
                "bazpors": {"night_count": 1, "host_day": 1},
            }
            if mason_outcome is not None:
                payload["mason_final_outcome"] = dict(mason_outcome)
            f.write(
                json.dumps(payload, ensure_ascii=False)
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "event": "no_host.mason_apache_day",
                        "host_day": 1,
                        "target_uid": 80,
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

    def test_timeline_html_includes_mason_events(self) -> None:
        game, log_path = self._mason_game_with_audit()
        try:
            snap = build_post_session_recap_snapshot(game, "citizen")
            html = _build_bazpors_timeline_html(snap)
            self.assertIn("اتفاقات در طول بازی", html)
            self.assertIn("شات مافیا", html)
            self.assertIn("ناتاشا", html)
            self.assertIn("ناتو", html)
            self.assertIn("ماسون", html)
            self.assertIn("نجات پزشک", html)
            self.assertIn("اسنایپر", html)
            self.assertIn("فرمانده", html)
            self.assertIn("استعلام کارآگاه", html)
            self.assertIn("آپاچی", html)
        finally:
            log_path.unlink(missing_ok=True)

    def test_game_end_broadcast_includes_full_timeline(self) -> None:
        game, log_path = self._mason_game_with_audit()
        try:
            body = build_bazpors_game_end_broadcast_html(game, "citizen")
            self.assertIn("اتاق شماره", body)
            self.assertIn("بازیکنان و نقش‌ها", body)
            self.assertIn("اتفاقات در طول بازی", body)
            self.assertIn("ناتاشا", body)
            self.assertIn("ناتو", body)
            self.assertIn("ماسون", body)
        finally:
            log_path.unlink(missing_ok=True)

