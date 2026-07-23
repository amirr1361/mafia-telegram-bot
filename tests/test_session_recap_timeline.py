"""تایم‌لاین «اتفاقات در طول بازی» در پیام پایان دست بازپرس."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bot.main import (
    _build_bazpors_timeline_html,
    _build_session_recap_roster_lines,
    _format_recap_rating_line,
    _timeline_chaos_compact_lines,
    build_bazpors_game_end_broadcast_html,
)
from bot.post_game_flow import build_post_session_recap_snapshot

ROOM_50_LOG = Path(__file__).resolve().parents[1] / "data/game_logs/50_20260519_005230.jsonl"
ROOM_85_LOG = Path(__file__).resolve().parents[1] / "data/game_logs/85_20260521_043803.jsonl"
ROOM_13_LOG = Path(__file__).resolve().parents[1] / "data/game_logs/13_20260524_083255.jsonl"
ROOM_11_LOG = Path(__file__).resolve().parents[1] / "data/game_logs/11_20260524_112535.jsonl"
ROOM_66_LOG = Path(__file__).resolve().parents[1] / "data/game_logs/66_20260525_082555.jsonl"
ROOM_87_LOG = Path(__file__).resolve().parents[1] / "data/game_logs/87_20260525_105312.jsonl"
ROOM_43_LOG = Path(__file__).resolve().parents[1] / "data/game_logs/43_20260526_011004.jsonl"


class SessionRecapTimelineTest(unittest.TestCase):
    def test_chaos_timeline_compact_format(self) -> None:
        def tag(uid: int) -> str:
            names = {
                1: "امین-شهروند ساده",
                2: "عرفان-رییس مافیا",
            }
            return names.get(uid, str(uid))

        lines = _timeline_chaos_compact_lines(
            {
                "winner": "mafia",
                "pair": [1, 2],
                "choices": {"1": 2, "2": 1, "3": 2},
            },
            tag,
        )
        self.assertEqual(
            lines,
            ["دست نهایی: امین ↔ عرفان", "برنده: مافیا 🖤"],
        )

    def test_recap_snapshot_includes_observer(self) -> None:
        from bot.game import GameManager
        from bot.models import Player, Role

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.observer_user_id = 999
        gm.add_player(
            game,
            Player(user_id=2, full_name="P", username=None, role=Role.CITIZEN),
        )
        snap = build_post_session_recap_snapshot(game, "mafia")
        self.assertEqual(snap.get("observer_user_id"), 999)

    def test_recap_rating_line_compact(self) -> None:
        self.assertEqual(
            _format_recap_rating_line(5.0, 10),
            "⭐️ <b>امتیاز:</b> ۵/۵ از ۱۰ بازخورد",
        )
        self.assertIn("ثبت نشده", _format_recap_rating_line(None, 0))

    def test_day_vote_eliminations_from_confirm_day_path(self) -> None:
        if not ROOM_50_LOG.is_file():
            self.skipTest("fixture log missing")
        uids: dict[int, str] = {}
        for line in ROOM_50_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "player.eliminated":
                uids[int(rec["uid"])] = str(rec.get("name") or rec["uid"])
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": str(ROOM_50_LOG),
            "rows": rows,
        }
        html = _build_bazpors_timeline_html(snap)
        self.assertIn("صندلی ۱۱ (تست) به اتفاق آرا از بازی خارج شد.", html)
        self.assertIn("صندلی ۱۲ (تست) به اتفاق آرا از بازی خارج شد.", html)
        self.assertIn("☀️ <b>روز ۲</b> - بدون اتفاق", html)
        self.assertIn("🌙 <b>شب ۳</b> - بدون اتفاق", html)

    def test_night_actions_from_full_report_block(self) -> None:
        if not ROOM_85_LOG.is_file():
            self.skipTest("fixture log missing")
        uids: dict[int, str] = {}
        for line in ROOM_85_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "player.eliminated":
                uids[int(rec["uid"])] = str(rec.get("name") or rec["uid"])
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": str(ROOM_85_LOG),
            "rows": rows,
        }
        html = _build_bazpors_timeline_html(snap)
        night1 = html.split("🌙 <b>شب ۱</b>")[1].split("☀️ <b>روز ۲</b>")[0]
        self.assertIn("شات مافیا: هاکان-بازپرس", night1)
        self.assertIn("استعلام کارآگاه: بابک-ناتو", night1)
        self.assertNotIn("پایان شب اول", night1)
        night2 = html.split("🌙 <b>شب ۲</b>")[1]
        self.assertIn("شات مافیا: فریدونی-هانتر", night2)
        self.assertNotIn("پایان شب دوم", night2)

    def test_room_11_interrog_and_day_vote_days(self) -> None:
        if not ROOM_11_LOG.is_file():
            self.skipTest("fixture log missing")
        uids: dict[int, str] = {}
        for line in ROOM_11_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "player.eliminated":
                uids[int(rec["uid"])] = str(rec.get("name") or rec["uid"])
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": str(ROOM_11_LOG),
            "rows": rows,
        }
        html = _build_bazpors_timeline_html(snap)
        day1 = html.split("☀️ <b>روز ۱</b>")[1].split("🌙 <b>شب ۱</b>")[0]
        day2 = html.split("☀️ <b>روز ۲</b>")[1].split("🌙 <b>شب ۲</b>")[0]
        self.assertIn("بابک-مافیا ساده", day1)
        self.assertNotIn("Amir Latifi", day1)
        self.assertIn("Amir Latifi", day2)
        self.assertIn("رهنما-رییس مافیا", day2)
        self.assertNotIn("رهنما-رییس مافیا", day1)

    def test_no_host_day_eliminations_in_timeline(self) -> None:
        if not ROOM_13_LOG.is_file():
            self.skipTest("fixture log missing")
        uids: dict[int, str] = {}
        for line in ROOM_13_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "player.eliminated":
                uids[int(rec["uid"])] = str(rec.get("name") or rec["uid"])
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": str(ROOM_13_LOG),
            "rows": rows,
        }
        html = _build_bazpors_timeline_html(snap)
        self.assertIn("خسروی-هانتر (شهروند) به اتفاق آرا در رای بازپرسی", html)
        self.assertIn("Amir Latifi به اتفاق آرا از بازی خارج شد.", html)
        self.assertIn("اتفاقات در طول بازی", html)

    def test_game_end_broadcast_includes_timeline(self) -> None:
        from bot.game import GameManager
        from bot.models import Player, Role

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.audit_log_path = str(ROOM_13_LOG) if ROOM_13_LOG.is_file() else ""
        gm.add_player(
            game,
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        if not ROOM_13_LOG.is_file():
            self.skipTest("fixture log missing")
        body = build_bazpors_game_end_broadcast_html(game, "mafia")
        self.assertIn("اتاق شماره", body)
        self.assertIn("تعداد بازیکنان", body)
        self.assertIn("پایان بازی — برد مافیا", body)
        self.assertIn("اتفاقات در طول بازی", body)
        self.assertIn("بازیکنان و نقش‌ها", body)

    def test_game_end_broadcast_header_semi_auto(self) -> None:
        from bot.game import GameManager
        from bot.models import Player, Role

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        body = build_bazpors_game_end_broadcast_html(game, "citizen")
        self.assertIn("اتاق شماره", body)
        self.assertIn("تعداد بازیکنان", body)
        self.assertIn("پایان بازی — برد شهروند", body)

    def test_recap_roster_mafia_then_citizens_grouped(self) -> None:
        rows = [
            {"user_id": 1, "seat": 1, "tag": "احسان-اسنایپر", "role": "SNIPER"},
            {"user_id": 2, "seat": 2, "tag": "فریدونی-هانتر", "role": "HUNTER"},
            {"user_id": 3, "seat": 3, "tag": "بابک-ناتو", "role": "NATO"},
            {"user_id": 7, "seat": 7, "tag": "رایان-مافیا ساده", "role": "MAFIA_BASIC"},
            {"user_id": 8, "seat": 8, "tag": "ابوالفضل-رییس مافیا", "role": "MAFIA_BOSS"},
            {"user_id": 12, "seat": 12, "tag": "امین-شیاد", "role": "SHIAD"},
            {"user_id": 6, "seat": 6, "tag": "فراهانی-شهروند ساده", "role": "CITIZEN"},
        ]
        lines = _build_session_recap_roster_lines(rows)
        joined = "\n".join(lines)
        self.assertLess(joined.index("ابوالفضل-رییس مافیا"), joined.index("بابک-ناتو"))
        self.assertLess(joined.index("بابک-ناتو"), joined.index("امین-شیاد"))
        self.assertLess(joined.index("امین-شیاد"), joined.index("رایان-مافیا ساده"))
        self.assertLess(joined.index("رایان-مافیا ساده"), joined.index("احسان-اسنایپر"))
        self.assertLess(joined.index("احسان-اسنایپر"), joined.index("فراهانی-شهروند ساده"))
        self.assertTrue(all(l.startswith("🔴") for l in lines[:4]))
        self.assertTrue(all(l.startswith("🟢") for l in lines[4:]))

    def test_recap_roster_yakuza_converted_in_mafia_list(self) -> None:
        rows = [
            {"user_id": 8, "seat": 8, "tag": "ابوالفضل-رییس مافیا", "role": "MAFIA_BOSS"},
            {
                "user_id": 6,
                "seat": 5,
                "tag": "علیرضا-رویین تن",
                "role": "RUINTAN",
                "yakuza_converted": True,
                "original_role": "RUINTAN",
            },
            {"user_id": 4, "seat": 4, "tag": "فراهانی-شهروند ساده", "role": "CITIZEN"},
        ]
        lines = _build_session_recap_roster_lines(rows)
        joined = "\n".join(lines)
        self.assertIn("علیرضا-رویین تن (یاکوزایی شده)", joined)
        self.assertIn("رویین", joined)
        self.assertLess(joined.index("🔴"), joined.index("🟢"))
        mafia_lines = [ln for ln in lines if ln.startswith("🔴")]
        self.assertEqual(len(mafia_lines), 2)
        self.assertTrue(any("یاکوزایی شده" in ln for ln in mafia_lines))

    def test_room_43_chaos_day6_handshake_in_timeline(self) -> None:
        if not ROOM_43_LOG.is_file():
            self.skipTest("fixture log missing")
        uids: dict[int, str] = {}
        for line in ROOM_43_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "player.eliminated":
                uids[int(rec["uid"])] = str(rec.get("name") or rec["uid"])
            if rec.get("event") == "game.roles_dealt":
                for pl in rec.get("players") or []:
                    uids[int(pl["uid"])] = str(pl.get("name") or pl["uid"])
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": str(ROOM_43_LOG),
            "rows": rows,
        }
        html_out = _build_bazpors_timeline_html(snap)
        self.assertIn("☀️ <b>روز ۶</b>", html_out)
        day6 = html_out.split("☀️ <b>روز ۶</b>")[1].split("🌙 <b>شب ۶</b>")[0]
        self.assertIn("— فاز آشوب", day6)
        self.assertIn("دست نهایی:", day6)
        self.assertIn("فریدونی", day6)
        self.assertIn("بهنام", day6)
        self.assertIn("برنده:", day6)
        self.assertNotIn("انتخاب‌های بازیکنان", day6)
        self.assertNotIn("انتخاب (دور", day6)

    def test_pre_medal_timeline_includes_chaos_before_game_ended(self) -> None:
        """گزارش پایان بازی (قبل از مدال) — فقط تا chaos_handshake.resolved."""
        if not ROOM_43_LOG.is_file():
            self.skipTest("fixture log missing")
        import tempfile

        uids: dict[int, str] = {}
        partial_lines: list[str] = []
        for line in ROOM_43_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            partial_lines.append(line)
            if rec.get("event") == "game.roles_dealt":
                for pl in rec.get("players") or []:
                    uids[int(pl["uid"])] = str(pl.get("name") or pl["uid"])
            if rec.get("event") == "chaos_handshake.resolved":
                break
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write("\n".join(partial_lines) + "\n")
            partial_path = tmp.name
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": partial_path,
            "rows": rows,
        }
        html = _build_bazpors_timeline_html(snap)
        self.assertIn("☀️ <b>روز ۶</b> — فاز آشوب", html)
        day6 = html.split("☀️ <b>روز ۶</b>")[1].split("🌙 <b>شب ۶</b>")[0]
        self.assertIn("دست نهایی:", day6)
        self.assertIn("برنده:", day6)

    def test_room_87_chaos_day6_in_timeline(self) -> None:
        if not ROOM_87_LOG.is_file():
            self.skipTest("fixture log missing")
        uids: dict[int, str] = {}
        for line in ROOM_87_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "player.eliminated":
                uids[int(rec["uid"])] = str(rec.get("name") or rec["uid"])
            if rec.get("event") == "game.roles_dealt":
                for pl in rec.get("players") or []:
                    uids[int(pl["uid"])] = str(pl.get("name") or pl["uid"])
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": str(ROOM_87_LOG),
            "rows": rows,
        }
        html = _build_bazpors_timeline_html(snap)
        self.assertIn("🌙 <b>شب ۵</b>", html)
        self.assertIn("🌙 <b>شب ۶</b> - بدون اتفاق", html)
        day6 = html.split("☀️ <b>روز ۶</b>")[1].split("🌙 <b>شب ۶</b>")[0]
        self.assertIn("فاز آشوب", day6)
        self.assertIn("پایان بازی", day6)
        self.assertIn("مافیا", day6)

    def test_room_66_incomplete_night4_yaku_in_timeline(self) -> None:
        if not ROOM_66_LOG.is_file():
            self.skipTest("fixture log missing")
        uids: dict[int, str] = {}
        for line in ROOM_66_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "player.eliminated":
                uids[int(rec["uid"])] = str(rec.get("name") or rec["uid"])
            if rec.get("event") == "game.roles_dealt":
                for pl in rec.get("players") or []:
                    uids[int(pl["uid"])] = str(pl.get("name") or pl["uid"])
        rows = [
            {"user_id": uid, "seat": i + 1, "tag": name, "role": None}
            for i, (uid, name) in enumerate(sorted(uids.items()))
        ]
        snap = {
            "scenario_name": "bazpors",
            "audit_log_path": str(ROOM_66_LOG),
            "rows": rows,
        }
        html = _build_bazpors_timeline_html(snap)
        self.assertIn("🌙 <b>شب ۴</b>", html)
        night4 = html.split("🌙 <b>شب ۴</b>")[1]
        self.assertIn("یاکوزایی موفق", night4)
        self.assertIn("حسن-شیاد", night4)
        self.assertIn("کاوه-رویین تن", night4)

    def test_recap_roster_inline_medal(self) -> None:
        rows = [
            {"user_id": 8, "seat": 8, "tag": "ابوالفضل-رییس مافیا", "role": "MAFIA_BOSS"},
            {"user_id": 3, "seat": 3, "tag": "بابک-ناتو", "role": "NATO"},
        ]
        lines = _build_session_recap_roster_lines(
            rows, medal_by_uid={8: "🥇", 3: "🥈"}
        )
        self.assertIn("🔴 <b>۸</b>- ابوالفضل-رییس مافیا — رییس مافیا 🥇", "\n".join(lines))
        self.assertIn("🔴 <b>۳</b>- بابک-ناتو — ناتو 🥈", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
