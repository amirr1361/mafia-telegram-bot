"""Mason-only: final day/night outcome blocks in end-of-game history."""

from __future__ import annotations

import html
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot.bazpors_narrator import _compose_full_night_report
from bot.game import GameManager
from bot.game_audit_log import log_night_resolved
from bot.main import (
    _build_bazpors_timeline_html,
    _night_lines_from_report_html,
    build_bazpors_game_end_broadcast_html,
)
from bot.mason_final_outcome import (
    append_mason_outcome_to_timeline_lines,
    find_mason_final_night_outcome,
    format_mason_history_outcome_lines,
    record_mason_final_night_outcome,
)
from bot.mason_night_report import build_mason_night_timeline_lines
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.models import Phase, Player, Role
from bot.post_game_flow import build_post_session_recap_snapshot
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_mf
from bot.roles import mason_sniper as ms_sn
from bot.roles.night_state import mafia_night_state
from bot.no_host_night_resolve import build_no_host_night_results_broadcast_html


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class _IsolatedDbAudit(unittest.TestCase):
    """Keep tests off the live sqlite / game_logs directories."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._db_path = root / "test.sqlite3"
        self._audit_dir = root / "audit"
        self._audit_dir.mkdir()
        self._patches = [
            mock.patch("bot.config.get_database_path", return_value=self._db_path),
            mock.patch(
                "bot.config.get_game_audit_log_dir", return_value=self._audit_dir
            ),
            mock.patch.dict(
                os.environ,
                {
                    "DATABASE_PATH": str(self._db_path),
                    "GAME_AUDIT_LOG_DIR": str(self._audit_dir),
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

    def _base_mason(self, *, night: int = 1, day: int = 1):
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=14,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_host_day = day
        game.bazpors_narrator_night_count = night
        for uid, name, role in [
            (10, "Boss", Role.GODFATHER),
            (11, "Sab", Role.SABOTEUR),
            (20, "Doc", Role.DOCTOR),
            (30, "Det", Role.DETECTIVE),
            (40, "Sn", Role.SNIPER),
            (50, "Cmd", Role.COMMANDER),
            (60, "Mason", Role.MASON),
            (70, "Nat", Role.NATASHA),
            (80, "Citizen", Role.TOWN_SIMPLE),
            (81, "Babak", Role.TOWN_SIMPLE),
            (82, "Ramin", Role.COMMANDER),
        ]:
            # avoid duplicate commander — remap 82
            if uid == 82:
                role = Role.TOWN_SIMPLE
            self.gm.add_player(game, _p(uid, name, role))
        # re-add proper names for Room-16 style
        game.players[81].full_name = "بابک"
        game.players[82].full_name = "رامین"
        game.mafia_ids.update({10, 11})
        return game


class MasonFinalOutcomeUnitTests(_IsolatedDbAudit):
    def test_record_idempotent_single_block(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        mafia_night_state(game).commit_shot(81)
        apply_mason_night_resolution(game, self.gm)
        e1 = record_mason_final_night_outcome(game, self.gm)
        e2 = record_mason_final_night_outcome(game, self.gm)
        self.assertIsNotNone(e1)
        self.assertIs(e1, e2)
        self.assertEqual(len(game.mason_final_night_outcomes), 1)

    def test_unresolved_night_no_invented_result(self) -> None:
        game = self._base_mason()
        game.mason_night_resolution_applied = False
        self.assertIsNone(record_mason_final_night_outcome(game, self.gm))
        self.assertEqual(game.mason_final_night_outcomes, [])

    def test_no_death_wording(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        # doctor saves the only shot
        mafia_night_state(game).commit_shot(80)
        ms_doc.commit_mason_doctor_save(game, 80)
        apply_mason_night_resolution(game, self.gm)
        entry = record_mason_final_night_outcome(game, self.gm)
        assert entry is not None
        lines = format_mason_history_outcome_lines(
            entry, lambda u: game.players[u].full_name
        )
        text = "\n".join(lines)
        self.assertIn("نتیجه نهایی شب و روز ۱", text)
        self.assertIn("در روز ۱ با کسی خداحافظی نکردیم.", text)
        self.assertIn("در شب ۱، با کسی خداحافظی نکردیم.", text)
        self.assertTrue(game.players[80].is_alive)

    def test_doctor_protected_not_listed(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        mafia_night_state(game).commit_shot(80)
        ms_doc.commit_mason_doctor_save(game, 80)
        apply_mason_night_resolution(game, self.gm)
        entry = find_mason_final_night_outcome(game, 1)
        assert entry is not None
        self.assertNotIn(80, entry["night_elim_uids"])

    def test_mafia_shot_survives_not_listed(self) -> None:
        # same as doctor protect — shot alone does not imply death
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        mafia_night_state(game).commit_shot(80)
        ms_doc.commit_mason_doctor_save(game, 80)
        apply_mason_night_resolution(game, self.gm)
        entry = find_mason_final_night_outcome(game, 1)
        assert entry is not None
        self.assertEqual(entry["night_elim_uids"], [])

    def test_sniper_survive_not_listed(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        # sniper shoots mafia saboteur but commander does not approve → no kill
        ms_sn.commit_mason_sniper_night_selection(game, [11])
        apply_mason_night_resolution(game, self.gm)
        entry = find_mason_final_night_outcome(game, 1)
        assert entry is not None
        self.assertNotIn(11, entry["night_elim_uids"])
        self.assertTrue(game.players[11].is_alive)

    def test_recruit_alone_not_death(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        ms_mf.commit_mason_recruit(game, game.players[60], game.players[80])
        apply_mason_night_resolution(game, self.gm)
        entry = find_mason_final_night_outcome(game, 1)
        assert entry is not None
        self.assertNotIn(80, entry["night_elim_uids"])
        self.assertTrue(game.players[80].is_alive)

    def test_multiple_night_elims(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        # kill babak via mafia shot; kill ramin by marking dead after resolution?
        # Better: set two night deaths via resolved state snapshot at record time.
        mafia_night_state(game).commit_shot(81)
        apply_mason_night_resolution(game, self.gm)
        # simulate a second confirmed night death (e.g. sniper) already applied
        if game.players[82].is_alive:
            game.players[82].is_alive = False
        # re-record would be idempotent — clear and re-record for this unit test
        game.mason_final_night_outcomes.clear()
        game.mason_night_resolution_applied = True
        entry = record_mason_final_night_outcome(game, self.gm)
        assert entry is not None
        self.assertIn(81, entry["night_elim_uids"])
        self.assertIn(82, entry["night_elim_uids"])
        lines = format_mason_history_outcome_lines(
            entry, lambda u: game.players[u].full_name
        )
        joined = "\n".join(lines)
        self.assertIn("بابک", joined)
        self.assertIn("رامین", joined)
        self.assertIn(" و ", joined)

    def test_day_elim_names(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        day_start = dict(alive)
        night_start = dict(alive)
        night_start[80] = False  # died during day
        game.players[80].is_alive = False
        game.bazpors_alive_at_day_start = day_start
        game.bazpors_alive_at_night_start = night_start
        game.mason_night_resolution_applied = True
        entry = record_mason_final_night_outcome(game, self.gm)
        assert entry is not None
        self.assertEqual(entry["day_elim_uids"], [80])
        lines = format_mason_history_outcome_lines(
            entry, lambda u: game.players[u].full_name
        )
        self.assertIn("در روز ۱ با Citizen خداحافظی کردیم.", "\n".join(lines))

    def test_special_chars_escaped(self) -> None:
        entry = {
            "night": 1,
            "day": 1,
            "day_elim_uids": [1],
            "night_elim_uids": [],
            "finalized": True,
        }
        lines = format_mason_history_outcome_lines(
            entry, lambda u: html.escape("A<b>&</b>")
        )
        self.assertIn("A&lt;b&gt;&amp;&lt;/b&gt;", "\n".join(lines))

    def test_append_no_duplicate(self) -> None:
        entry = {
            "night": 2,
            "day": 2,
            "day_elim_uids": [],
            "night_elim_uids": [],
            "finalized": True,
        }
        base = ["🔴 شات مافیا: X"]
        once = append_mason_outcome_to_timeline_lines(
            base, entry, lambda u: str(u)
        )
        twice = append_mason_outcome_to_timeline_lines(
            once, entry, lambda u: str(u)
        )
        joined = "\n".join(once)
        self.assertEqual(joined.count("نتیجه نهایی شب و روز ۲"), 1)
        self.assertEqual(twice, once)


class MasonFinalOutcomeTimelineTests(_IsolatedDbAudit):
    def _resolve_night1_with_deaths(self, game):
        alive = {uid: p.is_alive for uid, p in game.players.items()}
        game.bazpors_alive_at_day_start = dict(alive)
        game.bazpors_alive_at_night_start = dict(alive)
        mafia_night_state(game).commit_shot(81)  # بابک
        # second death: sniper+commander on sab is complex; force second death after
        apply_mason_night_resolution(game, self.gm)
        if game.players[82].is_alive:
            game.players[82].is_alive = False
        game.mason_final_night_outcomes.clear()
        game.mason_night_resolution_applied = True
        return record_mason_final_night_outcome(game, self.gm)

    def _write_audit(self, game, report_html: str, outcome: dict, *, day2: bool = True):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            log_path = Path(f.name)
            f.write(
                json.dumps(
                    {
                        "event": "night.resolved",
                        "night_report_html": report_html,
                        "mason_final_outcome": outcome,
                        "bazpors": {"night_count": 1, "host_day": 1},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            if day2:
                f.write(
                    json.dumps(
                        {
                            "event": "no_host.mason_apache_day",
                            "host_day": 2,
                            "target_uid": 30,
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
                        "bazpors": {"host_day": 2, "night_count": 1},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        game.audit_log_path = str(log_path)
        game.phase = Phase.ENDED
        return log_path

    def test_timeline_placement_after_night_before_day2(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        mafia_night_state(game).commit_shot(81)
        apply_mason_night_resolution(game, self.gm)
        entry = find_mason_final_night_outcome(game, 1)
        assert entry is not None
        report_html = _compose_full_night_report(
            game, self.gm, game.bazpors_alive_at_night_start
        )
        # ensure strip still drops public outcome from report html
        stripped = _night_lines_from_report_html(report_html)
        self.assertFalse(any("نتیجه نهایی" in x for x in stripped))
        log_path = self._write_audit(game, report_html, entry)
        try:
            snap = build_post_session_recap_snapshot(game, "citizen")
            html_out = _build_bazpors_timeline_html(snap)
            self.assertIn("نتیجه نهایی شب و روز ۱", html_out)
            night_idx = html_out.index("🌙 <b>شب ۱</b>")
            outcome_idx = html_out.index("نتیجه نهایی شب و روز ۱")
            day2_idx = html_out.index("☀️ <b>روز ۲</b>")
            self.assertLess(night_idx, outcome_idx)
            self.assertLess(outcome_idx, day2_idx)
            # night action still present
            self.assertIn("شات مافیا", html_out)
            # winner/roster path unchanged in full broadcast
            body = build_bazpors_game_end_broadcast_html(game, "citizen")
            self.assertIn("بازیکنان و نقش‌ها", body)
            self.assertIn("اتفاقات در طول بازی", body)
            self.assertIn("نتیجه نهایی شب و روز ۱", body)
            # no duplicate outcome
            self.assertEqual(body.count("نتیجه نهایی شب و روز ۱"), 1)
            # repeat generation identical count
            body2 = build_bazpors_game_end_broadcast_html(game, "citizen")
            self.assertEqual(body.count("نتیجه نهایی"), body2.count("نتیجه نهایی"))
        finally:
            log_path.unlink(missing_ok=True)

    def test_night2_and_night3_outcomes(self) -> None:
        game = self._base_mason(night=1, day=1)
        lines_all = []
        for n in (1, 2, 3):
            game.bazpors_narrator_night_count = n
            game.bazpors_narrator_host_day = n
            alive = {uid: p.is_alive for uid, p in game.players.items()}
            game.bazpors_alive_at_day_start = dict(alive)
            game.bazpors_alive_at_night_start = dict(alive)
            game.mason_night_resolution_applied = False
            apply_mason_night_resolution(game, self.gm)
            entry = find_mason_final_night_outcome(game, n)
            self.assertIsNotNone(entry)
            block = format_mason_history_outcome_lines(
                entry, lambda u: game.players[u].full_name
            )
            lines_all.extend(block)
            # reset resolution flag for next synthetic night without full night cycle
            game.mason_night_resolution_applied = False
            game.mason_night_resolution_applied = False
        text = "\n".join(lines_all)
        self.assertIn("نتیجه نهایی شب و روز ۱", text)
        self.assertIn("نتیجه نهایی شب و روز ۲", text)
        self.assertIn("نتیجه نهایی شب و روز ۳", text)
        self.assertEqual(len(game.mason_final_night_outcomes), 3)

    def test_game_ending_night_includes_result(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        mafia_night_state(game).commit_shot(81)
        apply_mason_night_resolution(game, self.gm)
        game.phase = Phase.ENDED
        tl = build_mason_night_timeline_lines(game, self.gm)
        self.assertTrue(any("نتیجه نهایی شب و روز ۱" in x for x in tl))

    def test_public_broadcast_unchanged(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        mafia_night_state(game).commit_shot(81)
        apply_mason_night_resolution(game, self.gm)
        public = build_no_host_night_results_broadcast_html(game, self.gm)
        self.assertIn("نتیجه نهایی شب و روز گذشته", public)
        self.assertIn("در روز قبل", public)
        self.assertIn("در شبی که گذشت", public)
        # history uses numbered form — different from public
        entry = find_mason_final_night_outcome(game, 1)
        hist = "\n".join(
            format_mason_history_outcome_lines(
                entry, lambda u: game.players[u].full_name
            )
        )
        self.assertIn("نتیجه نهایی شب و روز ۱", hist)
        self.assertNotIn("روز گذشته", hist)

    def test_log_night_resolved_stores_outcome(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        game.bazpors_night_report_html = "<b>گزارش کامل شب گذشته</b>\n🔴 شات"
        mafia_night_state(game).commit_shot(81)
        apply_mason_night_resolution(game, self.gm)
        # ensure audit file under isolated dir
        from bot.game_audit_log import init_audit_log

        init_audit_log(game)
        log_night_resolved(game, self.gm)
        path = Path(game.audit_log_path)
        self.assertTrue(path.is_file())
        # must be under our temp audit dir
        self.assertTrue(str(path).startswith(str(self._audit_dir)))
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        night_rows = [r for r in rows if r.get("event") == "night.resolved"]
        self.assertEqual(len(night_rows), 1)
        self.assertIn("mason_final_outcome", night_rows[0])
        self.assertTrue(night_rows[0]["mason_final_outcome"]["finalized"])

    def test_long_report_html_safe(self) -> None:
        game = self._base_mason()
        chunks = []
        for n in range(1, 8):
            entry = {
                "night": n,
                "day": n,
                "day_elim_uids": [],
                "night_elim_uids": [81, 82] if n % 2 else [],
                "finalized": True,
            }
            chunks.append(f"🌙 <b>شب {n}</b>")
            chunks.append("🔴 شات مافیا: بابک")
            chunks.extend(
                format_mason_history_outcome_lines(
                    entry, lambda u: html.escape(game.players[u].full_name)
                )
            )
        text = "\n".join(chunks)
        # telegram limit 4096 — splitter exists; ensure tags balanced-ish
        self.assertEqual(text.count("<b>"), text.count("</b>"))
        self.assertNotIn("<script", text)

    def test_special_events_still_in_timeline_lines(self) -> None:
        game = self._base_mason()
        alive = {uid: True for uid in game.players}
        game.bazpors_alive_at_night_start = dict(alive)
        game.bazpors_alive_at_day_start = dict(alive)
        mafia_night_state(game).commit_shot(81)
        ms_doc.commit_mason_doctor_save(game, 20)
        ms_mf.commit_mason_recruit(game, game.players[60], game.players[80])
        apply_mason_night_resolution(game, self.gm)
        tl = build_mason_night_timeline_lines(game, self.gm)
        joined = "\n".join(tl)
        self.assertIn("شات مافیا", joined)
        self.assertIn("ماسون", joined)
        self.assertIn("نتیجه نهایی شب و روز ۱", joined)


class CrossScenarioUnchangedSmoke(_IsolatedDbAudit):
    def test_bazpors_log_night_resolved_no_mason_field(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(10, "A", Role.GODFATHER))
        self.gm.add_player(game, _p(20, "B", Role.DOCTOR))
        game.bazpors_narrator_night_count = 1
        game.bazpors_night_report_html = "x"
        from bot.game_audit_log import init_audit_log

        init_audit_log(game)
        log_night_resolved(game, self.gm)
        rows = [
            json.loads(line)
            for line in Path(game.audit_log_path).read_text().splitlines()
            if line.strip()
        ]
        night_rows = [r for r in rows if r.get("event") == "night.resolved"]
        self.assertTrue(night_rows)
        self.assertNotIn("mason_final_outcome", night_rows[0])

    def test_record_noop_for_non_mason(self) -> None:
        for scenario in ("bazpors", "mozakere", "russian_mafia"):
            game = self.gm.create_game(
                host_id=1,
                scenario_name=scenario,
                max_players=10,
                bazpors_host_mode="no_host",
            )
            if game is None:
                # russian may use different create kwargs
                continue
            game.mason_night_resolution_applied = True
            self.assertIsNone(record_mason_final_night_outcome(game, self.gm))


if __name__ == "__main__":
    unittest.main()
