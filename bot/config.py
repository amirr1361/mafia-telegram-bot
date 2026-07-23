from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def get_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Create a .env file from .env.example")
    return token


def get_database_path() -> Path:
    """مسیر SQLite برای بایگانی امتیازها و مدال‌ها (پوشهٔ والد در صورت نیاز ساخته می‌شود)."""
    raw = os.getenv("DATABASE_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "data" / "mafia_bot.sqlite3"


def game_audit_log_enabled() -> bool:
    raw = os.getenv("GAME_AUDIT_LOG_ENABLED", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def get_game_audit_log_dir() -> Path:
    raw = os.getenv("GAME_AUDIT_LOG_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "data" / "game_logs"


def get_panic_trigger_phrase() -> str:
    """عبارت مخفی چت خصوصی برای شروعٔ بازنشانی اضطراری (بات را kill و دوباره بالا نمی‌آورد)."""
    return os.getenv("MAFIA_PANIC_TRIGGER", "ریست ربات").strip()


def get_panic_password() -> str:
    return os.getenv("MAFIA_PANIC_PASSWORD", "1234").strip()


def get_panic_allowed_user_ids() -> frozenset[int]:
    """اگر خالی باشد هر کسی در چت خصوصی که عبارت و پسورد را داند می‌تواند همهٔ اتاق‌ها را ببندد."""
    raw = os.getenv("MAFIA_PANIC_OWNER_IDS", "").strip()
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit() or (p.startswith("-") and p[1:].isdigit()):
            out.add(int(p))
    return frozenset(out)
