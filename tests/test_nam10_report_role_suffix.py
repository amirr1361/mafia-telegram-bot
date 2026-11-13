"""Namayande report role-suffix — regression tests.

Covers the report-display change: every player-name occurrence in the
Namayande event history (live eliminated-player «گزارش بازی» report AND
final post-game reports) is followed by the player's ORIGINAL role in
parentheses, using Namayande-fork Persian labels, /myname display names,
no duplicate suffixes, and no changes outside the Namayande no-host fork.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from bot.models import Game, Player, Role

NAMES = {
    101: "ابوالفضل",
    102: "امیر لطیفی",
    103: "علی فریدونی",
    104: "شاسی بلند",
    105: "امیر تهرانی",  # /myname override → "Amir T"
    106: "مافیا بوس",
    107: "یاغی بازیکن",
    108: "هکر تاریک",
    109: "شهروند یک",
    110: "شهروند دو",
}


def _p(uid: int, seat: int, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=NAMES[uid],
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def nam10_rows_10() -> list[dict[str, object]]:
    composition = [
        (106, Role.MAFIA_BOSS),
        (107, Role.NATO),
        (108, Role.SHIAD),
        (105, Role.HUNTER),
        (104, Role.INTERROGATOR),
        (103, Role.DETECTIVE),
        (101, Role.DOCTOR),
        (102, Role.RUINTAN),
        (109, Role.CITIZEN),
        (110, Role.CITIZEN),
    ]
    rows: list[dict[str, object]] = []
    for seat, (uid, role) in enumerate(composition, start=1):
        # Row tags resolve exactly like the real snapshot: the /myname
        # display override wins over the Telegram full name.
        tag = NAMES[uid]
        if uid == 105:
            tag = "Amir T"
        rows.append(
            {
                "user_id": uid,
                "seat": seat,
                "tag": tag,
                "role": role.value,
                "original_role": role.value,
                "yakuza_converted": False,
            }
        )
    return rows


NIGHT_REPORT_HTML = """🌙 <b>شب ۱</b>

گزارش کامل شب گذشته
════════════════════
🔴 شات مافیا: بدون خنثی‌سازی — هدف: ابوالفضل
💻 هکر: مبدأ: ابوالفضل — مقصد: ابوالفضل
💉 پزشک: هدف نجات: ابوالفضل — ثبت شد
🧭 راهنما: بازیکن انتخاب‌شده: علی فریدونی — استعلام کارآگاهی اعطا شد
🔎 استعلام: علی فریدونی از Amir T — مثبت
🛡️ محافظ: بازیکن تحت حفاظت: شاسی بلند — زره اعمال شد
⚖️ وکیل: بازیکن انتخاب‌شده: علی فریدونی — مصونیت اعمال شد
"""

ALREADY_SUFFIXED_NIGHT_HTML = (
    "گزارش کامل شب گذشته\n"
    "════════\n"
    "🔴 شات مافیا: بدون خنثی‌سازی — هدف: ابوالفضل (پزشک)\n"
)

AUDIT_RECORDS_10 = [
    {
        "event": "night.resolved",
        "bazpors": {"night_count": 1},
        "night_report_html": NIGHT_REPORT_HTML,
    },
    {
        "event": "no_host.day1_defense_elim_confirmed",
        "eliminated_uid": 109,
        "host_day": 1,
    },
    {
        "event": "player.eliminated",
        "uid": 110,
        "bazpors": {
            "narrator_step": "confirm_day_elim",
            "host_day": 1,
            "night_count": 1,
        },
        "source": "day_vote",
    },
]


def write_audit(records: list[dict[str, object]]) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def timeline(snap: dict[str, object]) -> str:
    from bot.main import _build_bazpors_timeline_html

    return _build_bazpors_timeline_html(snap)


def snap_with(rows: list[dict[str, object]], records: list[dict[str, object]]) -> str:
    return timeline(
        {
            "scenario_name": "namayande",
            "nmnd_host_mode": "no_host",
            "rows": rows,
            "audit_log_path": write_audit(records),
        }
    )


class TaggerUnitTests(unittest.TestCase):
    def test_multi_name_line_suffixes(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = nam10_rows_10()
        out = nam10_tag_event_history_names_with_roles(
            "💻 هکر: مبدأ: ابوالفضل — مقصد: امیر لطیفی", rows
        )
        self.assertIn("ابوالفضل (پزشک)", out)
        self.assertIn("امیر لطیفی (مین‌گذار)", out)

    def test_no_duplicate_suffix(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = nam10_rows_10()
        src = "🔴 شات مافیا — هدف: ابوالفضل (پزشک)"
        out = nam10_tag_event_history_names_with_roles(src, rows)
        self.assertEqual(out, src)
        self.assertNotIn("(پزشک) (پزشک)", out)

    def test_seat_variant_matched(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = [{"user_id": 5, "tag": "میز ۵", "role": Role.CITIZEN.value}]
        out = nam10_tag_event_history_names_with_roles(
            "خط با میز ۵ و صندلی ۵", rows
        )
        self.assertEqual(
            out, "خط با میز ۵ (شهروند ساده) و صندلی ۵ (شهروند ساده)"
        )

    def test_html_escaped_tag_matched(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = [{"user_id": 3, "tag": "Ali & Sons", "role": Role.SHIAD.value}]
        out = nam10_tag_event_history_names_with_roles(
            "بدنه: Ali &amp; Sons — پایان", rows
        )
        self.assertIn("Ali &amp; Sons (هکر)", out)

    def test_converted_player_keeps_original_role(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = [
            {
                "user_id": 7,
                "tag": "تبدیل‌شده",
                "role": Role.CITIZEN.value,  # current (post-Yakuza) role
                "original_role": Role.MAFIA_BOSS.value,
                "yakuza_converted": True,
            }
        ]
        out = nam10_tag_event_history_names_with_roles("تبدیل‌شده را زدند", rows)
        self.assertEqual(out, "تبدیل‌شده (رئیس مافیا) را زدند")

    def test_observer_and_unknown_skipped(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = [
            {"user_id": 1, "tag": "ناظر", "role": Role.OBSERVER.value},
            {"user_id": 2, "tag": "نامعلوم", "role": "NOT_A_ROLE"},
            {"user_id": 3, "tag": "بی‌نقش", "role": None},
        ]
        src = "ناظر و نامعلوم و بی‌نقش"
        self.assertEqual(
            nam10_tag_event_history_names_with_roles(src, rows), src
        )

    def test_prefix_of_longer_name_not_double_suffixed(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = [
            {"user_id": 1, "tag": "امیر", "role": Role.NATO.value},
            {"user_id": 2, "tag": "امیر لطیفی", "role": Role.RUINTAN.value},
        ]
        out = nam10_tag_event_history_names_with_roles("امیر لطیفی حذف شد", rows)
        self.assertEqual(out, "امیر لطیفی (مین‌گذار) حذف شد")
        # separate players listed apart each keep their own suffix
        out2 = nam10_tag_event_history_names_with_roles(
            "امیر رفت؛ امیر لطیفی ماند", rows
        )
        self.assertEqual(
            out2, "امیر (یاغی) رفت؛ امیر لطیفی (مین‌گذار) ماند"
        )

    def test_12_player_role_labels(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = [
            {"user_id": 21, "tag": "ناتو آژانس", "role": Role.NATO_AGENT.value},
            {"user_id": 22, "tag": "سرباز وطن", "role": Role.SOLDIER.value},
        ]
        out = nam10_tag_event_history_names_with_roles(
            "ناتو آژانس دید؛ سرباز وطن محافظت شد", rows
        )
        self.assertIn("ناتو آژانس (ناتو)", out)
        self.assertIn("سرباز وطن (سرباز)", out)

    def test_word_boundary_no_partial_match(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        rows = [{"user_id": 1, "tag": "علی", "role": Role.DOCTOR.value}]
        src = "علیفریدونی بازی کرد"
        self.assertEqual(nam10_tag_event_history_names_with_roles(src, rows), src)

    def test_non_list_rows_unchanged(self) -> None:
        from bot.nam10.role_labels import nam10_tag_event_history_names_with_roles

        src = "ابوالفضل حذف شد"
        self.assertEqual(
            nam10_tag_event_history_names_with_roles(src, None), src
        )


class TimelineIntegrationTests(unittest.TestCase):
    def test_namayande_timeline_all_events_suffixed(self) -> None:
        out = snap_with(nam10_rows_10(), AUDIT_RECORDS_10)
        # night event lines
        self.assertIn("هدف: ابوالفضل (پزشک)", out)
        self.assertIn("مبدأ: ابوالفضل (پزشک) — مقصد: ابوالفضل (پزشک)", out)
        self.assertIn("هدف نجات: ابوالفضل (پزشک) — ثبت شد", out)
        self.assertIn("انتخاب‌شده: علی فریدونی (محافظ) — استعلام", out)
        self.assertIn("علی فریدونی (محافظ) از Amir T (وکیل) — مثبت", out)
        self.assertIn("تحت حفاظت: شاسی بلند (راهنما) — زره اعمال شد", out)
        self.assertIn("⚖️ وکیل: بازیکن انتخاب‌شده: علی فریدونی (محافظ)", out)
        # day eliminations
        self.assertIn("شهروند یک (شهروند ساده) به اتفاق آرا از بازی خارج شد.", out)
        self.assertIn("شهروند دو (شهروند ساده) به اتفاق آرا از بازی خارج شد.", out)
        # generic headings carry no suffix
        self.assertIn("🌙 <b>شب ۱</b>", out)
        self.assertIn("☀️ <b>روز ۱</b>", out)
        self.assertIn("🧭 <b>اتفاقات در طول بازی</b>", out)

    def test_already_suffixed_line_not_duplicated(self) -> None:
        records = [
            {
                "event": "night.resolved",
                "bazpors": {"night_count": 1},
                "night_report_html": ALREADY_SUFFIXED_NIGHT_HTML,
            }
        ]
        out = snap_with(nam10_rows_10(), records)
        self.assertIn("هدف: ابوالفضل (پزشک)", out)
        self.assertNotIn("(پزشک) (پزشک)", out)

    def test_unknown_player_name_untouched(self) -> None:
        records = [
            {
                "event": "night.resolved",
                "bazpors": {"night_count": 1},
                "night_report_html": (
                    "گزارش کامل شب گذشته\n════════\nتماشاگر وارد شد\n"
                ),
            }
        ]
        out = snap_with(nam10_rows_10(), records)
        self.assertIn("تماشاگر وارد شد", out)
        self.assertNotIn("تماشاگر (", out)

    def test_mozakere_timeline_not_tagged(self) -> None:
        rows = nam10_rows_10()
        out = timeline(
            {
                "scenario_name": "mozakere",
                "rows": rows,
                "audit_log_path": write_audit(AUDIT_RECORDS_10),
            }
        )
        self.assertIn("هدف: ابوالفضل\n", out)
        self.assertNotIn("ابوالفضل (پزشک)", out)

    def test_namayande_host_mode_not_tagged(self) -> None:
        rows = nam10_rows_10()
        out = timeline(
            {
                "scenario_name": "namayande",
                "nmnd_host_mode": "host",
                "rows": rows,
                "audit_log_path": write_audit(AUDIT_RECORDS_10),
            }
        )
        self.assertNotIn("ابوالفضل (پزشک)", out)


class Nam10LiveReportTests(unittest.TestCase):
    def setUp(self) -> None:
        from bot.app_state import manager

        self.manager = manager
        self._saved_names = dict(manager.user_display_names)

    def tearDown(self) -> None:
        self.manager.user_display_names.clear()
        self.manager.user_display_names.update(self._saved_names)

    def _game(self) -> Game:
        from bot.game import GameManager

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        game.room_code = "7"
        composition = [
            (106, Role.MAFIA_BOSS, 1),
            (107, Role.NATO, 2),
            (108, Role.SHIAD, 3),
            (105, Role.HUNTER, 4),
            (104, Role.INTERROGATOR, 5),
            (103, Role.DETECTIVE, 6),
            (101, Role.DOCTOR, 7),
            (102, Role.RUINTAN, 8),
            (109, Role.CITIZEN, 9),
            (110, Role.CITIZEN, 10),
        ]
        for uid, role, seat in composition:
            gm.add_player(game, _p(uid, seat, role))
        game.roles_dealt = True
        game.audit_log_path = write_audit(AUDIT_RECORDS_10)
        self.manager.user_display_names[105] = "Amir T"
        return game

    def _assert_live_report(self, html_out: str) -> None:
        self.assertIn("📋 <b>بازیکنان و نقش‌ها</b>", html_out)
        self.assertIn("ابوالفضل — پزشک", html_out)  # roster already shows roles
        # timeline suffixes
        self.assertIn("هدف: ابوالفضل (پزشک)", html_out)
        self.assertIn("مبدأ: ابوالفضل (پزشک) — مقصد: ابوالفضل (پزشک)", html_out)
        self.assertIn("علی فریدونی (محافظ) از Amir T (وکیل) — مثبت", html_out)
        self.assertIn("شهروند یک (شهروند ساده) به اتفاق آرا", html_out)
        self.assertNotIn("(پزشک) (پزشک)", html_out)

    def test_live_elim_report_suffixed_and_myname(self) -> None:
        from bot.nam10.no_host_elim_report import (
            build_nam10_elim_cutoff_report_html,
        )
        from bot.game import GameManager

        gm = GameManager()
        game = self._game()
        html_out = build_nam10_elim_cutoff_report_html(game, gm)
        self._assert_live_report(html_out)
        self.assertIn("📖 سناریو: نماینده", html_out)
        self.assertIn("👥 تعداد بازیکنان: ۱۰ نفر", html_out)

    def test_live_report_rebuilds_after_new_night(self) -> None:
        from bot.nam10.no_host_elim_report import (
            build_nam10_elim_cutoff_report_html,
        )
        from bot.game import GameManager

        gm = GameManager()
        game = self._game()
        first = build_nam10_elim_cutoff_report_html(game, gm)
        self._assert_live_report(first)
        # a second night completes and is logged → next build includes it
        with open(game.audit_log_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "event": "night.resolved",
                        "bazpors": {"night_count": 2},
                        "night_report_html": (
                            "گزارش کامل شب گذشته\n════════\n"
                            "🔴 شات مافیا: هدف: شهروند یک\n"
                        ),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        second = build_nam10_elim_cutoff_report_html(game, gm)
        self.assertIn("🌙 <b>شب ۲</b>", second)
        self.assertIn("هدف: شهروند یک (شهروند ساده)", second)

    def test_final_game_end_report_suffixed(self) -> None:
        from bot.main import build_bazpors_game_end_broadcast_html
        from bot.game import GameManager

        gm = GameManager()
        game = self._game()
        html_out = build_bazpors_game_end_broadcast_html(game, "citizen")
        self._assert_live_report(html_out)
        self.assertIn("تیم شهروند برنده است", html_out)


if __name__ == "__main__":
    unittest.main()
