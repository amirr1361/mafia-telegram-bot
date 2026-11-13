"""Namayande immediate game-end report must use the fork role labels.

Root cause regression: ``bot/nam10/dayflow.build_bazpors_game_end_broadcast_html``
rendered the roster through the shared renderer but without ``nam10=True``,
so internal Role values shared with Bazpors (SHIAD/NATO/DETECTIVE/HUNTER/
INTERROGATOR/RUINTAN) displayed legacy Bazpors names (شیاد/ناتو/کاراگاه/
هانتر/بازپرس/رویین‌تن) instead of the Namayande labels (هکر/یاغی/محافظ/
وکیل/راهنما/مین‌گذار).

Each player's rendered label is verified against the actual internal role
identifier (never a global forbidden-word scan), label parity between the
immediate report and the post-medal recap path is asserted, and the shared
renderer is guarded so Bazpors labels stay untouched there.

Tests use isolated temporary SQLite/audit storage only.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

from bot.game import GameManager, role_label_fa
from bot.models import Game, Player, Role
from bot.nam10.dayflow import build_bazpors_game_end_broadcast_html
from bot.nam10.lobby import roles_for_count
from bot.nam10.role_labels import NAM10_ROLE_LABELS_FA, nam10_role_label_fa
from bot.main import (
    _build_session_recap_roster_lines,
    _recap_roster_name_and_role,
    _snap_is_nam10_fork,
)
from bot.post_game_flow import build_post_session_recap_snapshot

# Internal Role -> required Namayande display label (per task contract).
EXPECTED_NAM10_LABELS: dict[Role, str] = {
    Role.SHIAD: "هکر",
    Role.NATO: "یاغی",
    Role.DETECTIVE: "محافظ",
    Role.HUNTER: "وکیل",
    Role.INTERROGATOR: "راهنما",
    Role.RUINTAN: "مین‌گذار",
    Role.NATO_AGENT: "ناتو",
    Role.SOLDIER: "سرباز",
    Role.MAFIA_BOSS: "رئیس مافیا",
    Role.DOCTOR: "پزشک",
    Role.CITIZEN: "شهروند ساده",
}


class _Isolated(unittest.TestCase):
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


def _build_fork_room(gm: GameManager, n: int) -> Game:
    """Namayande fork room with the canonical composition for n players."""
    game = gm.create_game(
        host_id=7100 + n,
        host_full_name="سازنده",
        host_username=None,
        scenario_name="namayande",
        max_players=n,
        nam10_no_host=True,
    )
    roles = roles_for_count(n)
    assert len(roles) == n
    for idx, role in enumerate(roles, start=1):
        uid = 72000 + n * 100 + idx
        gm.add_player(game, Player(user_id=uid, full_name=f"بازیکن {idx}", username=None))
        p = game.players[uid]
        p.role = role
        p.seat = idx
    return game


def _line_for_player(report: str, tag: str) -> str:
    for line in report.splitlines():
        if tag in line:
            return line
    raise AssertionError(f"no roster line for tag {tag!r}\n{report}")


class Nam10ImmediateEndReportTests(_Isolated):
    def test_all_counts_use_namayande_labels_per_player(self) -> None:
        for n in (10, 11, 12, 13):
            with self.subTest(count=n):
                game = _build_fork_room(self.gm, n)
                report = build_bazpors_game_end_broadcast_html(game, "mafia")
                for p in game.players.values():
                    if p.role is None or p.role == Role.OBSERVER:
                        continue
                    line = _line_for_player(report, p.full_name)
                    expected = EXPECTED_NAM10_LABELS[p.role]
                    legacy = role_label_fa(p.role)
                    self.assertIn(expected, line, (n, p.role))
                    # Same internal Role value must NOT show the legacy
                    # Bazpors label on that player's own roster line.
                    if legacy != expected:
                        self.assertNotIn(legacy, line, (n, p.role))

    def test_12_and_13_include_nato_agent_and_soldier_rows(self) -> None:
        for n in (12, 13):
            with self.subTest(count=n):
                game = _build_fork_room(self.gm, n)
                report = build_bazpors_game_end_broadcast_html(game, "mafia")
                # NATO_AGENT (legitimate Namayande mafia role) and SOLDIER.
                self.assertIn("ناتو", report)
                self.assertIn("سرباز", report)
                # The rebel (NATO) label یاغی must exist alongside «ناتو».
                self.assertIn("یاغی", report)
                agent_uid = next(
                    uid
                    for uid, p in game.players.items()
                    if p.role == Role.NATO_AGENT
                )
                soldier_uid = next(
                    uid
                    for uid, p in game.players.items()
                    if p.role == Role.SOLDIER
                )
                agent_line = _line_for_player(
                    report, game.players[agent_uid].full_name
                )
                soldier_line = _line_for_player(
                    report, game.players[soldier_uid].full_name
                )
                self.assertIn("ناتو", agent_line)
                self.assertIn("سرباز", soldier_line)
                # Rebel's own line keeps یاغی, never the ambiguous fallback.
                rebel_line = _line_for_player(
                    report,
                    next(
                        p.full_name
                        for p in game.players.values()
                        if p.role == Role.NATO
                    ),
                )
                self.assertIn("یاغی", rebel_line)

    def test_10_and_11_have_no_12plus_roles(self) -> None:
        for n in (10, 11):
            with self.subTest(count=n):
                game = _build_fork_room(self.gm, n)
                build_bazpors_game_end_broadcast_html(game, "citizen")
                internal_roles = {
                    p.role.value for p in game.players.values() if p.role
                }
                self.assertNotIn("NATO_AGENT", internal_roles)
                self.assertNotIn("SOLDIER", internal_roles)

    def test_labels_match_internal_role_registry(self) -> None:
        for role, label in EXPECTED_NAM10_LABELS.items():
            self.assertEqual(nam10_role_label_fa(role), label)
            self.assertEqual(NAM10_ROLE_LABELS_FA[role], label)


class ImmediateVsPostMedalParityTests(_Isolated):
    """Immediate report labels == post-medal recap labels for the same room."""

    def _texts(self, n: int) -> tuple[str, dict[str, str]]:
        game = _build_fork_room(self.gm, n)
        immediate = build_bazpors_game_end_broadcast_html(game, "mafia")
        snap = build_post_session_recap_snapshot(game, "mafia")
        # The snapshot must mark the fork so the post-medal renderer
        # (build_session_recap_html) resolves nam10=True.
        self.assertTrue(_snap_is_nam10_fork(snap))
        rows = snap["rows"]
        assert isinstance(rows, list)
        post_lines = _build_session_recap_roster_lines(
            rows,
            scenario_name=str(snap["scenario_name"]),
            nam10=_snap_is_nam10_fork(snap),
        )
        post_by_uid: dict[int, str] = {}
        for row in rows:
            uid = int(row["user_id"])
            tag, role_txt = _recap_roster_name_and_role(
                row,
                scenario_name=str(snap["scenario_name"]),
                nam10=_snap_is_nam10_fork(snap),
            )
            post_by_uid[uid] = f"{tag} — {role_txt}"
        return immediate, post_by_uid

    def test_parity_per_player_10_and_13(self) -> None:
        for n in (10, 13):
            with self.subTest(count=n):
                game = _build_fork_room(self.gm, n)
                immediate, post_by_uid = self._texts(n)
                for uid, expected in post_by_uid.items():
                    p = game.players[uid]
                    if p.role is None or p.role == Role.OBSERVER:
                        continue
                    line = _line_for_player(immediate, p.full_name)
                    self.assertIn(expected, line, (n, uid))

    def test_post_medal_flag_resolution(self) -> None:
        n = 11
        game = _build_fork_room(self.gm, n)
        snap = build_post_session_recap_snapshot(game, "mafia")
        rows = snap["rows"]
        assert isinstance(rows, list)
        # nam10=True flag → هکر (NOT شیاد) for internal SHIAD rows.
        shiad_rows = [r for r in rows if r["role"] == "SHIAD"]
        self.assertTrue(shiad_rows)
        texts = [
            _recap_roster_name_and_role(
                r, scenario_name="namayande", nam10=_snap_is_nam10_fork(snap)
            )[1]
            for r in shiad_rows
        ]
        self.assertTrue(all(t == "هکر" for t in texts), texts)


class BazporsUnchangedGuardTests(_Isolated):
    def test_shared_renderer_keeps_bazpors_labels(self) -> None:
        players = [
            (1, Role.SHIAD),
            (2, Role.NATO),
            (3, Role.DETECTIVE),
            (4, Role.HUNTER),
        ]
        rows = [
            {
                "user_id": uid,
                "seat": uid,
                "tag": f"بزپرس‌کار {uid}",
                "role": role.value,
            }
            for uid, role in players
        ]
        lines = _build_session_recap_roster_lines(
            rows, scenario_name="bazpors"
        )
        joined = "\n".join(lines)
        self.assertIn("شیاد", joined)
        self.assertNotEqual("شیاد", nam10_role_label_fa(Role.SHIAD))
        self.assertIn("ناتو", joined)
        self.assertNotEqual("ناتو", nam10_role_label_fa(Role.NATO))
        self.assertIn("کاراگاه", joined)
        self.assertNotEqual("کاراگاه", nam10_role_label_fa(Role.DETECTIVE))
        self.assertIn("هانتر (شهروند)", joined)
        self.assertNotEqual(
            "هانتر (شهروند)", nam10_role_label_fa(Role.HUNTER)
        )

    def test_nam10_flag_is_call_site_scoped(self) -> None:
        # Identical rows must render differently only when nam10=True —
        # the shared default must stay False for other scenarios.
        rows = [{"user_id": 1, "seat": 1, "tag": "x", "role": "SHIAD"}]
        base = _build_session_recap_roster_lines(rows, scenario_name="bazpors")
        fork = _build_session_recap_roster_lines(
            rows, scenario_name="bazpors", nam10=True
        )
        self.assertIn("شیاد", "\n".join(base))
        self.assertIn("هکر", "\n".join(fork))
        self.assertNotEqual("\n".join(base), "\n".join(fork))


if __name__ == "__main__":
    unittest.main()
