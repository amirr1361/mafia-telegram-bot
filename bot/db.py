from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from bot.config import get_database_path


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS game_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_code TEXT NOT NULL,
                host_id INTEGER NOT NULL,
                scenario_name TEXT,
                winner TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                players_json TEXT NOT NULL,
                medal_giver_id INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS narrator_ratings (
                session_id INTEGER NOT NULL,
                rater_id INTEGER NOT NULL,
                stars INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (session_id, rater_id),
                FOREIGN KEY (session_id) REFERENCES game_sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rating_invites (
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                invited_at TEXT NOT NULL,
                PRIMARY KEY (session_id, user_id),
                FOREIGN KEY (session_id) REFERENCES game_sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_medals (
                session_id INTEGER NOT NULL,
                slot TEXT NOT NULL,
                recipient_id INTEGER NOT NULL,
                PRIMARY KEY (session_id, slot),
                FOREIGN KEY (session_id) REFERENCES game_sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_display_names (
                user_id INTEGER PRIMARY KEY NOT NULL,
                display_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS host_timer_settings (
                user_id INTEGER PRIMARY KEY NOT NULL,
                lobby_fill_deadline_minutes INTEGER NOT NULL,
                post_deal_timeout_hours INTEGER NOT NULL,
                player_end_approval_minutes INTEGER NOT NULL,
                player_end_broadcast_confirm_minutes INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_game_sessions_medal_giver_column(conn)
        _ensure_game_sessions_recap_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS active_game_snapshots (
                room_code TEXT PRIMARY KEY NOT NULL,
                snapshot_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL,
                roles_dealt INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_game_snapshots_roles "
            "ON active_game_snapshots(roles_dealt)"
        )


def _ensure_game_sessions_medal_giver_column(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(game_sessions)")
    cols = {str(row[1]) for row in cur.fetchall()}
    if "medal_giver_id" not in cols:
        conn.execute("ALTER TABLE game_sessions ADD COLUMN medal_giver_id INTEGER")


def _ensure_game_sessions_recap_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(game_sessions)")
    cols = {str(row[1]) for row in cur.fetchall()}
    if "recap_snapshot_json" not in cols:
        conn.execute("ALTER TABLE game_sessions ADD COLUMN recap_snapshot_json TEXT")
    if "recap_broadcast_at" not in cols:
        conn.execute("ALTER TABLE game_sessions ADD COLUMN recap_broadcast_at TEXT")


MEDAL_SLOTS: tuple[str, ...] = ("gold", "silver", "bronze", "honor1", "honor2")

MEDAL_LABEL_FA: dict[str, str] = {
    "gold": "🥇 مدال طلا",
    "silver": "🥈 مدال نقره",
    "bronze": "🥉 مدال برنز",
    "honor1": "🏅 مدال افتخار (۱)",
    "honor2": "🏅 مدال افتخار (۲)",
}


def insert_game_session(
    room_code: str,
    host_id: int,
    scenario_name: str | None,
    winner: str,
    players: list[dict[str, int | str | None]],
    medal_giver_id: int | None = None,
    recap_snapshot: dict[str, object] | None = None,
) -> int:
    recap_json = (
        json.dumps(recap_snapshot, ensure_ascii=False)
        if recap_snapshot is not None
        else None
    )
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO game_sessions
            (room_code, host_id, scenario_name, winner, ended_at, players_json,
             medal_giver_id, recap_snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room_code,
                host_id,
                scenario_name or "",
                winner,
                _utc_iso(),
                json.dumps(players, ensure_ascii=False),
                medal_giver_id,
                recap_json,
            ),
        )
        return int(cur.lastrowid)


def get_session_recap_snapshot(session_id: int) -> dict[str, object] | None:
    row = get_session(session_id)
    if not row:
        return None
    if row.get("recap_broadcast_at"):
        return None
    raw = row.get("recap_snapshot_json")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def session_recap_already_broadcasted(session_id: int) -> bool:
    row = get_session(session_id)
    if not row:
        return False
    return bool(row.get("recap_broadcast_at"))


def mark_session_recap_broadcasted(session_id: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE game_sessions
            SET recap_broadcast_at = ?
            WHERE id = ?
            """,
            (_utc_iso(), session_id),
        )


def get_session(session_id: int) -> dict[str, object] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM game_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def session_player_entries(session_id: int) -> list[dict[str, object]]:
    row = get_session(session_id)
    if not row:
        return []
    raw = row["players_json"]
    if not isinstance(raw, str):
        return []
    data = json.loads(raw)
    return data if isinstance(data, list) else []


def session_player_ids(session_id: int) -> set[int]:
    out: set[int] = set()
    for p in session_player_entries(session_id):
        for key in ("id", "user_id"):
            if key in p:
                out.add(int(p[key]))
                break
    return out


def record_rating_invite(session_id: int, user_id: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO rating_invites (session_id, user_id, invited_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, user_id) DO NOTHING
            """,
            (session_id, user_id, _utc_iso()),
        )


def user_has_rating_invite(session_id: int, user_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM rating_invites
            WHERE session_id = ? AND user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()
    return row is not None


def user_already_rated_session(session_id: int, user_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM narrator_ratings
            WHERE session_id = ? AND rater_id = ?
            """,
            (session_id, user_id),
        ).fetchone()
    return row is not None


def user_may_rate_session(session_id: int, user_id: int) -> bool:
    if user_id in session_player_ids(session_id):
        return True
    return user_has_rating_invite(session_id, user_id)


def rating_submission_error(session_id: int, user_id: int) -> str | None:
    row = get_session(session_id)
    if not row:
        return "این دست دیگر در بایگانی نیست."
    host_id = int(row["host_id"])
    if user_id == host_id:
        return "گرداننده به خودش امتیاز نمی‌دهد."
    if not user_may_rate_session(session_id, user_id):
        return "شما بازیکن این دست نبودید."
    if user_already_rated_session(session_id, user_id):
        return "قبلاً برای این دست امتیاز داده‌اید."
    return None


def latest_unrated_session_for_user(user_id: int) -> int | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT ri.session_id AS sid
            FROM rating_invites ri
            INNER JOIN game_sessions gs ON gs.id = ri.session_id
            LEFT JOIN narrator_ratings nr
                ON nr.session_id = ri.session_id AND nr.rater_id = ri.user_id
            WHERE ri.user_id = ?
              AND ri.user_id != gs.host_id
              AND nr.rater_id IS NULL
            ORDER BY ri.session_id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return int(row["sid"])


def session_medal_recipient_ids(session_id: int) -> set[int]:
    """بازیکنانی که در این دست حداقل یک مدال گرفته‌اند."""
    return set(get_session_medals(session_id).values())


def session_players_available_for_medal(session_id: int) -> list[dict[str, object]]:
    """فقط کسانی که هنوز هیچ مدالی در این دست نگرفته‌اند."""
    taken = session_medal_recipient_ids(session_id)
    return [
        p
        for p in session_player_entries(session_id)
        if "id" in p and int(p["id"]) not in taken
    ]


def save_narrator_rating(session_id: int, rater_id: int, stars: int) -> bool:
    if stars < 1 or stars > 5:
        return False
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO narrator_ratings (session_id, rater_id, stars, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, rater_id, stars, _utc_iso()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def save_session_medal(session_id: int, slot: str, recipient_id: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO session_medals (session_id, slot, recipient_id)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, slot) DO UPDATE SET
                recipient_id = excluded.recipient_id
            """,
            (session_id, slot, recipient_id),
        )


def get_session_medals(session_id: int) -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT slot, recipient_id FROM session_medals WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        return {str(r["slot"]): int(r["recipient_id"]) for r in rows}


def next_medal_slot(session_id: int) -> str | None:
    done = get_session_medals(session_id)
    for slot in MEDAL_SLOTS:
        if slot not in done:
            return slot
    return None


def narrator_aggregate_for_host(host_id: int) -> tuple[float | None, int]:
    """میانگین ستاره و تعداد رأی برای جلساتی که این کاربر گرداننده بوده."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT AVG(nr.stars) AS av, COUNT(*) AS c
            FROM narrator_ratings nr
            INNER JOIN game_sessions gs ON nr.session_id = gs.id
            WHERE gs.host_id = ?
            """,
            (host_id,),
        ).fetchone()
    if not row or row["c"] == 0:
        return None, 0
    return float(row["av"]), int(row["c"])


def medal_counts_for_recipient(user_id: int) -> dict[str, int]:
    out = {s: 0 for s in MEDAL_SLOTS}
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT slot, COUNT(*) AS n
            FROM session_medals
            WHERE recipient_id = ?
            GROUP BY slot
            """,
            (user_id,),
        ).fetchall()
    for r in rows:
        slot = str(r["slot"])
        if slot in out:
            out[slot] = int(r["n"])
    return out


def ratings_given_count(rater_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM narrator_ratings WHERE rater_id = ?",
            (rater_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def host_game_sessions_count(host_id: int) -> int:
    """تعداد جلساتی که این کاربر گرداننده بوده (شامل جلسهٔ جاری در دیتابیس)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM game_sessions WHERE host_id = ?",
            (host_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def upsert_user_display_name(user_id: int, display_name: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO user_display_names (user_id, display_name, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = excluded.display_name,
                updated_at = excluded.updated_at
            """,
            (user_id, display_name, _utc_iso()),
        )


def delete_user_display_name(user_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM user_display_names WHERE user_id = ?", (user_id,))


def fetch_all_user_display_names() -> dict[int, str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT user_id, display_name FROM user_display_names"
        ).fetchall()
    return {int(r["user_id"]): str(r["display_name"]) for r in rows}


def get_host_timer_settings_row(user_id: int) -> dict[str, int] | None:
    """یک ردیف خام از دیتابیس یا None اگر ذخیره نشده."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM host_timer_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "lobby_fill_deadline_minutes": int(row["lobby_fill_deadline_minutes"]),
        "post_deal_timeout_hours": int(row["post_deal_timeout_hours"]),
        "player_end_approval_minutes": int(row["player_end_approval_minutes"]),
        "player_end_broadcast_confirm_minutes": int(
            row["player_end_broadcast_confirm_minutes"]
        ),
    }


def upsert_host_timer_settings_row(user_id: int, settings: dict[str, int]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO host_timer_settings (
                user_id,
                lobby_fill_deadline_minutes,
                post_deal_timeout_hours,
                player_end_approval_minutes,
                player_end_broadcast_confirm_minutes,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                lobby_fill_deadline_minutes = excluded.lobby_fill_deadline_minutes,
                post_deal_timeout_hours = excluded.post_deal_timeout_hours,
                player_end_approval_minutes = excluded.player_end_approval_minutes,
                player_end_broadcast_confirm_minutes =
                    excluded.player_end_broadcast_confirm_minutes,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                settings["lobby_fill_deadline_minutes"],
                settings["post_deal_timeout_hours"],
                settings["player_end_approval_minutes"],
                settings["player_end_broadcast_confirm_minutes"],
                _utc_iso(),
            ),
        )


def upsert_active_game_snapshot(
    room_code: str,
    snapshot_json: str,
    *,
    reason: str,
    phase: str,
    roles_dealt: int,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO active_game_snapshots (
                room_code, snapshot_json, updated_at, reason, phase, roles_dealt
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_code) DO UPDATE SET
                snapshot_json = excluded.snapshot_json,
                updated_at = excluded.updated_at,
                reason = excluded.reason,
                phase = excluded.phase,
                roles_dealt = excluded.roles_dealt
            """,
            (room_code, snapshot_json, _utc_iso(), reason, phase, roles_dealt),
        )


def delete_active_game_snapshot(room_code: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM active_game_snapshots WHERE room_code = ?",
            (room_code,),
        )


def delete_all_active_game_snapshots() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM active_game_snapshots")


def list_active_game_snapshots() -> list[sqlite3.Row]:
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT room_code, snapshot_json, updated_at, reason, phase, roles_dealt
            FROM active_game_snapshots
            ORDER BY updated_at ASC
            """
        )
        return list(cur.fetchall())


def upsert_active_game_snapshot(
    room_code: str,
    snapshot_json: str,
    *,
    reason: str,
    phase: str,
    roles_dealt: int,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO active_game_snapshots (
                room_code, snapshot_json, updated_at, reason, phase, roles_dealt
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_code) DO UPDATE SET
                snapshot_json = excluded.snapshot_json,
                updated_at = excluded.updated_at,
                reason = excluded.reason,
                phase = excluded.phase,
                roles_dealt = excluded.roles_dealt
            """,
            (room_code, snapshot_json, _utc_iso(), reason, phase, roles_dealt),
        )


def delete_active_game_snapshot(room_code: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM active_game_snapshots WHERE room_code = ?",
            (room_code,),
        )


def delete_all_active_game_snapshots() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM active_game_snapshots")


def list_active_game_snapshots() -> list[sqlite3.Row]:
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT room_code, snapshot_json, updated_at, reason, phase, roles_dealt
            FROM active_game_snapshots
            ORDER BY updated_at ASC
            """
        )
        return list(cur.fetchall())
