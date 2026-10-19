"""فاز ۴ — snapshot/recovery بازی‌های فعال در SQLite."""

from __future__ import annotations

import json
import logging
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from bot import db
from bot.models import Game, NightActions, Phase, Player, Role

logger = logging.getLogger(__name__)

_SNAPSHOT_VERSION = 1
_TUPLE_VALUE_FIELDS = frozenset(
    {
        "bazpors_assistant_panel_refs",
        "bazpors_observer_narrator_mirror_refs",
        "no_host_mafia_night1_refs",
        "russian_mafia_role_pick_panel_messages",
    }
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return {"__dt__": value.isoformat()}
    if isinstance(value, set):
        return {"__set__": [_encode(v) for v in value]}
    if isinstance(value, tuple):
        return {"__tuple__": [_encode(v) for v in value]}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if is_dataclass(value):
        return {
            "__dc__": type(value).__name__,
            "fields": {f.name: _encode(getattr(value, f.name)) for f in fields(value)},
        }
    return str(value)


def _decode(value: Any) -> Any:
    if not isinstance(value, dict):
        if isinstance(value, list):
            return [_decode(v) for v in value]
        return value
    if "__dt__" in value:
        raw = value["__dt__"]
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if "__set__" in value:
        return {_decode(v) for v in value["__set__"]}
    if "__tuple__" in value:
        return tuple(_decode(v) for v in value["__tuple__"])
    if "__dc__" in value:
        return _decode_dataclass(value["__dc__"], value["fields"])
    return {_decode_key(k): _decode(v) for k, v in value.items()}


def _decode_key(key: str) -> int | str:
    if key.lstrip("-").isdigit():
        return int(key)
    return key


def _decode_dataclass(name: str, data: dict[str, Any]) -> Any:
    if name == "Player":
        role = data.get("role")
        baz_orig = data.get("bazpors_original_role")
        return Player(
            user_id=int(data["user_id"]),
            full_name=str(data.get("full_name") or ""),
            username=data.get("username"),
            role=Role(role) if role else None,
            is_alive=bool(data.get("is_alive", True)),
            seat=data.get("seat"),
            bazpors_original_role=Role(baz_orig) if baz_orig else None,
            bazpors_converted_by_yakuza=bool(data.get("bazpors_converted_by_yakuza", False)),
        )
    if name == "NightActions":
        return NightActions(
            mafia_target=data.get("mafia_target"),
            doctor_save=data.get("doctor_save"),
            detective_check=data.get("detective_check"),
        )
    if name == "Game":
        game_fields = {f.name: _decode(data[f.name]) for f in fields(Game) if f.name in data}
        phase = game_fields.get("phase")
        if isinstance(phase, str):
            game_fields["phase"] = Phase(phase)
        players_raw = game_fields.get("players")
        if isinstance(players_raw, dict):
            game_fields["players"] = {
                int(k) if str(k).lstrip("-").isdigit() else k: v
                for k, v in players_raw.items()
            }
        for fname in _TUPLE_VALUE_FIELDS:
            refs = game_fields.get(fname)
            if isinstance(refs, dict):
                game_fields[fname] = {
                    k: tuple(v) if isinstance(v, list) else v for k, v in refs.items()
                }
        return Game(**game_fields)
    raise ValueError(f"unknown dataclass in snapshot: {name}")


def game_to_snapshot_dict(game: Game) -> dict[str, Any]:
    return {
        "version": _SNAPSHOT_VERSION,
        "saved_at": _utc_iso(),
        "game": _encode(game),
    }


def game_from_snapshot_dict(data: dict[str, Any]) -> Game:
    if data.get("version") != _SNAPSHOT_VERSION:
        raise ValueError(f"unsupported snapshot version: {data.get('version')}")
    game = _decode(data["game"])
    if not isinstance(game, Game):
        raise TypeError("snapshot game payload is not a Game")
    if game.phase == Phase.ENDED:
        raise ValueError("refusing to restore ENDED game")
    return game


def persist_game_snapshot(game: Game, *, reason: str = "") -> None:
    """ذخیرهٔ وضعیت اتاق در SQLite."""
    if game.phase == Phase.ENDED:
        delete_game_snapshot(game.room_code)
        return
    payload = game_to_snapshot_dict(game)
    db.upsert_active_game_snapshot(
        game.room_code,
        json.dumps(payload, ensure_ascii=False),
        reason=reason,
        phase=game.phase.value,
        roles_dealt=1 if game.roles_dealt else 0,
    )


def delete_game_snapshot(room_code: str) -> None:
    db.delete_active_game_snapshot(room_code)


def restore_games_into_manager(manager: Any) -> list[str]:
    """بازیابی اتاق‌های فعال پس از ری‌استارت — برمی‌گرداند لیست room_code."""
    restored: list[str] = []
    for row in db.list_active_game_snapshots():
        code = str(row["room_code"])
        if manager.get_game(code) is not None:
            continue
        try:
            payload = json.loads(row["snapshot_json"])
            game = game_from_snapshot_dict(payload)
        except Exception:
            logger.exception("skip corrupt game snapshot room=%s", code)
            db.delete_active_game_snapshot(code)
            continue
        manager.games[code] = game
        manager._rebuild_room_indexes(game)
        restored.append(code)
        logger.info(
            "restored game snapshot room=%s phase=%s roles_dealt=%s reason=%s",
            code,
            game.phase.value,
            game.roles_dealt,
            row["reason"],
        )
    return restored
