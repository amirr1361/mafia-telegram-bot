"""مسیر کارت‌های تصویری نقش — پس از پخش نقش خصوصی."""

from __future__ import annotations

from pathlib import Path

from bot.models import Role

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROLE_CARDS_DIR = _REPO_ROOT / "assets" / "role_cards"

_ROLE_CARD_FILES: dict[Role, str] = {
    Role.MAFIA_BOSS: "mafia_boss.png",
    Role.DETECTIVE: "detective.png",
    Role.INTERROGATOR: "interrogator.png",
    Role.NATO: "nato.png",
    Role.SHIAD: "shiad.png",
    Role.MAFIA_BASIC: "mafia_basic.png",
    Role.MAFIA_SIMPLE: "mafia_basic.png",
    Role.MAFIA_SIMPLE_2: "mafia_basic.png",
    Role.SNIPER: "sniper.png",
    Role.DOCTOR: "doctor.png",
    Role.RUINTAN: "ruintan.png",
    Role.HUNTER: "hunter.png",
    Role.CITIZEN: "citizen.png",
}


def role_card_image_path(role: Role) -> Path | None:
    """فایل کارت نقش اگر در assets/role_cards موجود باشد."""
    filename = _ROLE_CARD_FILES.get(role)
    if not filename:
        return None
    path = _ROLE_CARDS_DIR / filename
    return path if path.is_file() else None
