from __future__ import annotations

import logging
import random
import secrets
import string
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from bot import db
from bot.mason_roles import masoon_roles_for_count
from bot.models import Game, NightActions, Phase, Player, Role


CODE_LENGTH = 2
CODE_ALPHABET = string.digits

# ارقام فارسی (۰–۹) و عربی-هندی (٠–٩) → لاتین برای کد اتاق و /join
_JOIN_DIGIT_TRANSLATE = str.maketrans(
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669",
    "0123456789" * 2,
)


def join_code_to_ascii_digits(raw: str) -> str:
    """فاصله‌های ابتدا/انتها حذف می‌شود؛ ارقام فارسی/عربی به لاتین تبدیل می‌شوند."""
    return raw.strip().translate(_JOIN_DIGIT_TRANSLATE)


def is_synthetic_player_uid(user_id: int) -> bool:
    """بازیکنان تست اتاق سلامت با شناسهٔ منفی ساخته می‌شوند (بدون تلگرام)."""
    return user_id < 0


# لابی موقت نیمه‌خودکار (پر کردن تصادفی برای تست گرداننده)
SEMI_AUTO_SYNTHETIC_UID_BASE = -920000

# نام‌های نمایشی بازیکنان ساختگی — بدون تکرار در هر پر کردن لابی
SYNTHETIC_PLAYER_NAME_POOL: tuple[str, ...] = (
    "امیر",
    "حسن",
    "رضا",
    "عرفان",
    "بهنام",
    "احسان",
    "بابک",
    "فریدونی",
    "خسروی",
    "رهنما",
    "امین",
    "علیرضا",
    "قاسم",
    "رایان",
    "کاوه",
    "فراهانی",
    "ابوالفضل",
    "هاکان",
    "رامین",
)


def draw_unique_synthetic_player_names(count: int) -> list[str]:
    """تعداد نام یکتا از لیست ثابت (به‌صورت تصادفی)."""
    if count < 0:
        raise ValueError("count must be non-negative")
    pool = list(SYNTHETIC_PLAYER_NAME_POOL)
    if count > len(pool):
        raise ValueError(
            f"need {count} unique synthetic names but pool has {len(pool)}"
        )
    random.shuffle(pool)
    return pool[:count]


def synthetic_player_base_name(full_name: str) -> str:
    """نام پایهٔ ساختگی قبل از الحاق نقش (مثلاً «امیر - آپاچی» → «امیر»)."""
    if full_name in SYNTHETIC_PLAYER_NAME_POOL:
        return full_name
    for base in SYNTHETIC_PLAYER_NAME_POOL:
        if full_name.startswith(f"{base} - "):
            return base
        if full_name.startswith(f"{base}-"):
            return base
    return full_name
# اگر تا این مدت لابی به حد نصاب نرسد، اتاق بسته می‌شود و کد آزاد می‌گردد.
LOBBY_FILL_DEADLINE_MINUTES = 20
# بعد از پخش موفق نقش‌ها؛ بدون پایان رسمی، اتاق بسته می‌شود.
POST_DEAL_TIMEOUT_HOURS = 12
# جمع‌آوری تأیید بازیکنان برای پایان بدون گرداننده.
PLAYER_END_APPROVAL_MINUTES = 10
# مهلت تأیید دوم درخواست‌دهنده قبل از فرستادن رأی برای همه.
PLAYER_END_BROADCAST_CONFIRM_MINUTES = 10

# محدودهٔ مجاز تنظیمات گرداننده (ذخیره در دیتابیس؛ روی هر اتاق جدید اعمال می‌شود)
HOST_TIMER_LOBBY_MIN = 10
HOST_TIMER_LOBBY_MAX = 60
HOST_TIMER_POST_DEAL_MIN_HOURS = 6
HOST_TIMER_POST_DEAL_MAX_HOURS = 48
HOST_TIMER_PLAYER_END_APPROVAL_MIN = 5
HOST_TIMER_PLAYER_END_APPROVAL_MAX = 30
HOST_TIMER_BROADCAST_CONFIRM_MIN = 5
HOST_TIMER_BROADCAST_CONFIRM_MAX = 20


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def normalize_host_timer_settings(
    lobby: int | None = None,
    post: int | None = None,
    appr: int | None = None,
    brdc: int | None = None,
) -> dict[str, int]:
    """یک ردیف تنظیمات گرداننده را در محدودهٔ مجاز قرار می‌دهد."""
    return {
        "lobby_fill_deadline_minutes": _clamp_int(
            lobby if lobby is not None else LOBBY_FILL_DEADLINE_MINUTES,
            HOST_TIMER_LOBBY_MIN,
            HOST_TIMER_LOBBY_MAX,
        ),
        "post_deal_timeout_hours": _clamp_int(
            post if post is not None else POST_DEAL_TIMEOUT_HOURS,
            HOST_TIMER_POST_DEAL_MIN_HOURS,
            HOST_TIMER_POST_DEAL_MAX_HOURS,
        ),
        "player_end_approval_minutes": _clamp_int(
            appr if appr is not None else PLAYER_END_APPROVAL_MINUTES,
            HOST_TIMER_PLAYER_END_APPROVAL_MIN,
            HOST_TIMER_PLAYER_END_APPROVAL_MAX,
        ),
        "player_end_broadcast_confirm_minutes": _clamp_int(
            brdc if brdc is not None else PLAYER_END_BROADCAST_CONFIRM_MINUTES,
            HOST_TIMER_BROADCAST_CONFIRM_MIN,
            HOST_TIMER_BROADCAST_CONFIRM_MAX,
        ),
    }


# Persian menu scenario keys
SCENARIO_LABELS_FA: dict[str, str] = {
    "bazpors": "بازپرس",
    "bazpors_salamat_test": "بازپرس شبکه سلامت (تست ۱۲ نفره)",
    "namayande": "نماینده",
    "takavar": "تکاور",
    "masoon": "ماسون",
    # موقت برای تست؛ بعد از تست حذف شود
    "masoon2": "ماسون ۲نفره (تست)",
    "mozakere": "مذاکره",
    "russian_mafia": "مافیای روسی",
}

DEFAULT_SCENARIO_KEY = "namayande"

MOZAKERE_PLAYER_COUNTS = frozenset({10, 11, 12, 13, 15})
BAZPORS_PLAYER_COUNTS = frozenset({10, 11, 12, 13})
BAZPORS_SALAMAT_TEST_PLAYER_COUNTS = frozenset({12})
TAKAVAR_PLAYER_COUNTS = frozenset({10, 11, 12, 13, 15})
# سناریوی موقت: ۱ مافیا + ۱ شهروند — فقط ۲ نفر
MASOON2_PLAYER_COUNTS = frozenset({2})
# ماسون رسمی: ۱۲ تا ۱۸ نفر
MASOON_PLAYER_COUNTS = frozenset(range(12, 19))
# نماینده: فقط این ظرفیت‌ها (۱۵ نفره تعریف نشده)
NAMAYANDEH_PLAYER_COUNTS = frozenset({10, 11, 12, 13, 14, 16})

ROLE_LABELS_FA: dict[Role, str] = {
    Role.MAFIA: "مافیا",
    Role.MAFIA_BOSS: "رییس مافیا",
    Role.MAFIA_NEGOTIATOR: "مذاکره‌کننده",
    Role.MAFIA_SIMPLE: "مافیا اول ساده",
    Role.MAFIA_SIMPLE_2: "مافیا دوم ساده",
    Role.DOCTOR: "پزشک",
    Role.DETECTIVE: "کاراگاه",
    Role.ARMORED: "زره‌پوش",
    Role.SNIPER: "اسنایپر",
    Role.JOURNALIST: "خبرنگار",
    Role.CITIZEN: "شهروند ساده",
    Role.NATO: "ناتو",
    Role.SHIAD: "شیاد",
    Role.HUNTER: "هانتر (شهروند)",
    Role.INTERROGATOR: "بازپرس",
    Role.RUINTAN: "رویین تن",
    Role.MAFIA_BASIC: "مافیا ساده",
    Role.KIDNAPPER: "گروگانگیر",
    Role.GUARD: "نگهبان",
    Role.GUNMAN: "تفنگدار",
    Role.COMMANDO: "تکاور",
    Role.GODFATHER: "گادفادر",
    Role.SABOTEUR: "خرابکار",
    Role.SPY: "جاسوس",
    Role.APACHE: "آپاچی",
    Role.NATASHA: "ناتاشا",
    Role.COWBOY: "کابوی",
    Role.COMMANDER: "فرمانده",
    Role.BODYGUARD: "محافظ",
    Role.MASON: "ماسون",
    Role.TAILOR: "تایلر",
    Role.PRIEST: "کشیش",
    Role.TOWN_SIMPLE: "شهر ساده",
    Role.DON_MAFIA: "دان مافیا",
    Role.YAGHI: "یاغی",
    Role.HACKER_MAFIA: "هکر مافیا",
    Role.GUIDE: "راهنما",
    Role.MINELAYER: "مین‌گذار",
    Role.TOWN_LAWYER: "وکیل شهروند",
    Role.SOLDIER: "سرباز",
    Role.OBSERVER: "ناظر بازی",
    Role.RUSSIAN_GODFATHER: "گادفادر",
    Role.TERROR: "ترور",
}

MOZAKERE_ROLE_LABELS_FA: dict[Role, str] = {
    Role.MAFIA_BOSS: "رئیس مافیا",
    Role.MAFIA_NEGOTIATOR: "مذاکره کننده",
    Role.MAFIA_SIMPLE: "مافیا ساده اول",
    Role.MAFIA_SIMPLE_2: "مافیا ساده دوم",
    Role.DOCTOR: "پزشک",
    Role.DETECTIVE: "کارآگاه",
    Role.ARMORED: "زره پوش",
    Role.SNIPER: "تک تیرانداز",
    Role.JOURNALIST: "خبرنگار",
    Role.CITIZEN: "شهروند ساده",
}


def role_label_fa(role: Role) -> str:
    return ROLE_LABELS_FA.get(role, role.value)


def scenario_role_label_fa(game: Game, role: Role | None) -> str:
    """برچسب نقش برای نمایش — بر اساس سناریوی اتاق."""
    if role is None:
        return "—"
    if game.scenario_name == "mozakere":
        return mozakere_role_label_fa(role)
    if game.scenario_name == "russian_mafia":
        from bot.russian_mafia import russian_role_label_fa

        return russian_role_label_fa(role)
    return role_label_fa(role)


def is_mafia_team(role: Role | None) -> bool:
    if role is None:
        return False
    return role in (
        Role.MAFIA,
        Role.MAFIA_BOSS,
        Role.MAFIA_NEGOTIATOR,
        Role.MAFIA_SIMPLE,
        Role.MAFIA_SIMPLE_2,
        Role.NATO,
        Role.SHIAD,
        Role.KIDNAPPER,
        Role.MAFIA_BASIC,
        Role.GODFATHER,
        Role.SABOTEUR,
        Role.SPY,
        Role.APACHE,
        Role.NATASHA,
        Role.DON_MAFIA,
        Role.YAGHI,
        Role.HACKER_MAFIA,
        Role.RUSSIAN_GODFATHER,
        Role.TERROR,
    )


def bazpors_counts_as_mafia_faction(game: Game, p: Player) -> bool:
    """هویت فکشن مافیا (گزارش مردگان، استعلام میز، شلیک اسنایپر)."""
    if game.scenario_name == "mozakere":
        if p.user_id in game.mozakere_mafia_recruit_ids:
            return True
        return is_mafia_team(p.role)
    if game.scenario_name not in ("bazpors", "bazpors_salamat_test"):
        return is_mafia_team(p.role)
    if p.user_id in game.bazpors_mafia_recruit_ids:
        return True
    return is_mafia_team(p.role)


def bazpors_counts_as_alive_mafia_for_win(game: Game, p: Player) -> bool:
    """مافیا یا یاکوزا‌شدهٔ زنده برای شرط برد — قربانی اسنایپر هرگز شمار نمی‌شود."""
    if not p.is_alive:
        return False
    if p.user_id in game.bazpors_sniper_eliminated_uids:
        return False
    return bazpors_counts_as_mafia_faction(game, p)


def mark_bazpors_eliminated_by_sniper(game: Game, uid: int) -> None:
    """پس از حذف موفق توسط اسنایپر؛ از لیست‌های فکشن مافیا هم خارج شود."""
    if game.scenario_name not in ("bazpors", "bazpors_salamat_test"):
        return
    game.bazpors_sniper_eliminated_uids.add(uid)
    game.mafia_ids.discard(uid)
    game.bazpors_mafia_recruit_ids.discard(uid)


def apply_bazpors_yakuzai_recruit(game: Game, p: Player) -> None:
    """یاکوزایی موفق — نقش به مافیا ساده؛ نقش قبلی برای گزارش‌ها نگه داشته می‌شود."""
    if p.user_id in game.bazpors_sniper_eliminated_uids:
        return
    if p.bazpors_original_role is None:
        p.bazpors_original_role = p.role
    p.bazpors_converted_by_yakuza = True
    game.bazpors_mafia_recruit_ids.add(p.user_id)
    p.role = Role.MAFIA_BASIC
    game.mafia_ids.add(p.user_id)


def namayande_roles_for_count(n: int) -> list[Role]:
    """سناریوی نماینده — ترکیب رسمی ۱۰ تا ۱۴ و ۱۶ نفره (بدون ۱۵)."""
    base_town_10 = [
        Role.DOCTOR,
        Role.GUIDE,
        Role.MINELAYER,
        Role.TOWN_LAWYER,
        Role.BODYGUARD,
    ]
    mafia_3 = [Role.DON_MAFIA, Role.YAGHI, Role.HACKER_MAFIA]
    if n == 10:
        return mafia_3 + base_town_10 + [Role.CITIZEN, Role.CITIZEN]
    if n == 11:
        return mafia_3 + base_town_10 + [Role.CITIZEN, Role.CITIZEN, Role.CITIZEN]
    mafia_4 = mafia_3 + [Role.NATO]
    town_12 = base_town_10 + [Role.SOLDIER, Role.CITIZEN, Role.CITIZEN]
    if n == 12:
        return mafia_4 + town_12
    if n == 13:
        return mafia_4 + town_12 + [Role.CITIZEN]
    if n == 14:
        return mafia_4 + town_12 + [Role.CITIZEN, Role.CITIZEN]
    if n == 16:
        return mafia_4 + [Role.MAFIA_BASIC] + town_12 + [
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    raise ValueError(f"نماینده فقط ۱۰، ۱۱، ۱۲، ۱۳، ۱۴ یا ۱۶ بازیکن؛ الان {n}")


def mozakere_role_label_fa(role: Role) -> str:
    """برچسب نقش‌ها در پنل لابی سناریوی مذاکره (فقط نمایش)."""
    return MOZAKERE_ROLE_LABELS_FA.get(role, role_label_fa(role))


def mozakere_roles_for_count(n: int) -> list[Role]:
    if n == 10:
        return [
            Role.MAFIA_BOSS,
            Role.MAFIA_NEGOTIATOR,
            Role.MAFIA_SIMPLE,
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.ARMORED,
            Role.SNIPER,
            Role.JOURNALIST,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 11:
        return [
            Role.MAFIA_BOSS,
            Role.MAFIA_NEGOTIATOR,
            Role.MAFIA_SIMPLE,
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.ARMORED,
            Role.SNIPER,
            Role.JOURNALIST,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 12:
        return [
            Role.MAFIA_BOSS,
            Role.MAFIA_NEGOTIATOR,
            Role.MAFIA_SIMPLE,
            Role.MAFIA_SIMPLE_2,
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.ARMORED,
            Role.SNIPER,
            Role.JOURNALIST,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 13:
        return [
            Role.MAFIA_BOSS,
            Role.MAFIA_NEGOTIATOR,
            Role.MAFIA_SIMPLE,
            Role.MAFIA_SIMPLE_2,
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.ARMORED,
            Role.SNIPER,
            Role.JOURNALIST,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 15:
        return [
            Role.MAFIA_BOSS,
            Role.MAFIA_NEGOTIATOR,
            Role.MAFIA_SIMPLE,
            Role.MAFIA_SIMPLE_2,
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.ARMORED,
            Role.SNIPER,
            Role.JOURNALIST,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    raise ValueError(f"مذاکره فقط برای ۱۰ تا ۱۲ یا ۱۳ یا ۱۵ بازیکن؛ الان {n}")


def bazpors_roles_for_count(n: int) -> list[Role]:
    if n == 10:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.SHIAD,
            Role.HUNTER,
            Role.INTERROGATOR,
            Role.DETECTIVE,
            Role.DOCTOR,
            Role.RUINTAN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 11:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.SHIAD,
            Role.HUNTER,
            Role.INTERROGATOR,
            Role.DETECTIVE,
            Role.DOCTOR,
            Role.RUINTAN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 12:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.SHIAD,
            Role.MAFIA_BASIC,
            Role.HUNTER,
            Role.INTERROGATOR,
            Role.DETECTIVE,
            Role.DOCTOR,
            Role.RUINTAN,
            Role.SNIPER,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 13:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.SHIAD,
            Role.MAFIA_BASIC,
            Role.HUNTER,
            Role.INTERROGATOR,
            Role.DETECTIVE,
            Role.DOCTOR,
            Role.RUINTAN,
            Role.SNIPER,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    raise ValueError(f"بازپرس فقط ۱۰ تا ۱۳ بازیکن؛ الان {n}")


def takavar_roles_for_count(n: int) -> list[Role]:
    # تکاور ۱۰ نفره: مافیا ۳ (رییس، ناتو، گروگانگیر) + شهر ۷ (پزشک، نگهبان، کارآگاه، تفنگدار، تکاور، ۲× شهروند)
    if n == 10:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.KIDNAPPER,
            Role.DOCTOR,
            Role.GUARD,
            Role.DETECTIVE,
            Role.GUNMAN,
            Role.COMMANDO,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    # تکاور ۱۱ نفره — ترکیب رسمی:
    # مافیا: رییس، ناتو، گروگانگیر
    # شهر: پزشک، نگهبان، کارآگاه، تفنگدار، تکاور، ۳× شهروند ساده
    if n == 11:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.KIDNAPPER,
            Role.DOCTOR,
            Role.GUARD,
            Role.DETECTIVE,
            Role.GUNMAN,
            Role.COMMANDO,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 12:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.KIDNAPPER,
            Role.MAFIA_BASIC,
            Role.DOCTOR,
            Role.GUARD,
            Role.DETECTIVE,
            Role.GUNMAN,
            Role.COMMANDO,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 13:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.KIDNAPPER,
            Role.MAFIA_BASIC,
            Role.DOCTOR,
            Role.GUARD,
            Role.DETECTIVE,
            Role.GUNMAN,
            Role.COMMANDO,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    if n == 15:
        return [
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.KIDNAPPER,
            Role.MAFIA_BASIC,
            Role.MAFIA_BASIC,
            Role.DOCTOR,
            Role.GUARD,
            Role.DETECTIVE,
            Role.GUNMAN,
            Role.COMMANDO,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
            Role.CITIZEN,
        ]
    raise ValueError(f"تکاور فقط ۱۰، ۱۱، ۱۲، ۱۳ یا ۱۵ بازیکن؛ الان {n}")


def _digits_fa(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _rtl(s: str) -> str:
    return f"\u200f{s}"


def _grouped_roster_block(
    title_line: str,
    mafia_roles: list[Role],
    town_roles: list[Role],
    *,
    label_fn: Callable[[Role], str] | None = None,
) -> str:
    role_label = label_fn or role_label_fa
    nm, nt = len(mafia_roles), len(town_roles)
    lines = [
        _rtl(title_line),
        "",
        _rtl(f"گروه مافیا: ({_digits_fa(nm)} نفر)"),
        *[_rtl(f"🔴 {role_label(r)}") for r in mafia_roles],
        "",
        _rtl(f"گروه شهروندها: ({_digits_fa(nt)} نفر)"),
        *[_rtl(f"🟢 {role_label(r)}") for r in town_roles],
    ]
    return "\n".join(lines)


def role_roster_banner_text(scenario_name: str, max_players: int, gm: "GameManager") -> str:
    roles = gm.intended_roles_for_room(scenario_name, max_players)
    if scenario_name == "mozakere":
        mafia_roles = [r for r in roles if is_mafia_team(r)]
        town_roles = [r for r in roles if not is_mafia_team(r)]
        return _grouped_roster_block(
            f"نقش‌ها — سناریو مذاکره ({_digits_fa(max_players)} نفره):",
            mafia_roles,
            town_roles,
            label_fn=mozakere_role_label_fa,
        )

    if scenario_name == "bazpors":
        mafia_roles = [r for r in roles if is_mafia_team(r)]
        town_roles = [r for r in roles if not is_mafia_team(r)]
        return _grouped_roster_block(
            f"نقش‌ها — سناریو بازپرس ({_digits_fa(max_players)} نفره):",
            mafia_roles,
            town_roles,
        )

    if scenario_name == "bazpors_salamat_test":
        mafia_roles = [r for r in roles if is_mafia_team(r)]
        town_roles = [r for r in roles if not is_mafia_team(r)]
        return _grouped_roster_block(
            f"نقش‌ها — سناریو بازپرس ({_digits_fa(max_players)} نفره):",
            mafia_roles,
            town_roles,
        )

    if scenario_name == "takavar":
        mafia_roles = [r for r in roles if is_mafia_team(r)]
        town_roles = [r for r in roles if not is_mafia_team(r)]
        return _grouped_roster_block(
            f"نقش‌ها — سناریو تکاور ({_digits_fa(max_players)} نفره):",
            mafia_roles,
            town_roles,
        )

    if scenario_name == "masoon":
        mafia_roles = [r for r in roles if is_mafia_team(r)]
        town_roles = [r for r in roles if not is_mafia_team(r)]
        return _grouped_roster_block(
            f"نقش‌ها — سناریو ماسون ({_digits_fa(max_players)} نفره):",
            mafia_roles,
            town_roles,
        )

    if scenario_name == "namayande":
        mafia_roles = [r for r in roles if is_mafia_team(r)]
        town_roles = [r for r in roles if not is_mafia_team(r)]
        return _grouped_roster_block(
            f"نقش‌ها — سناریو نماینده ({_digits_fa(max_players)} نفره):",
            mafia_roles,
            town_roles,
        )

    if scenario_name == "russian_mafia":
        from bot.russian_mafia import russian_role_label_fa

        mafia_roles = [r for r in roles if is_mafia_team(r)]
        town_roles = [r for r in roles if not is_mafia_team(r)]
        return _grouped_roster_block(
            f"نقش‌ها — سناریو مافیای روسی ({_digits_fa(max_players)} نفره):",
            mafia_roles,
            town_roles,
            label_fn=russian_role_label_fa,
        )

    mafia_n = sum(1 for r in roles if is_mafia_team(r))
    town_n = len(roles) - mafia_n
    lines = [
        _rtl(
            f"نقش‌ها — {gm.scenario_display_name(scenario_name)} (ظرفیت {_digits_fa(max_players)} نفر):"
        ),
        _rtl(
            f"گروه مافیا: ({_digits_fa(mafia_n)} نفر) — گروه شهروندها: ({_digits_fa(town_n)} نفر)"
        ),
        "",
    ]
    for r in roles:
        mark = "🔴" if is_mafia_team(r) else "🟢"
        lines.append(_rtl(f"{mark} {role_label_fa(r)}"))
    return "\n".join(lines)


DISPLAY_NAME_MAX_LEN = 80

LOBBY_LEAVE_BLOCKED_AFTER_ROLES_MSG = (
    "⛔ بعد از تقسیم نقش‌ها امکان خروج از اتاق وجود ندارد."
)
LOBBY_LEAVE_SUCCESS_MSG = "✅ شما از اتاق خارج شدید."
LOBBY_LEAVE_BROADCAST_MSG = (
    "⚠️ یک بازیکن از اتاق خارج شد. "
    "اتاق تا زمان ورود بازیکن جدید منتظر می‌ماند."
)
LOBBY_NOT_FULL_FOR_ROLES_MSG = (
    "⏳ اتاق هنوز کامل نیست. لطفاً منتظر بمانید تا بازیکن جدید وارد شود."
)
LOBBY_FULL_READY_FOR_ROLES_MSG = (
    "✅ ظرفیت اتاق کامل شد. "
    "گرداننده اکنون می‌تواند نقش‌ها را به‌صورت تصادفی تقسیم کند."
)


def reset_lobby_seats_after_roster_change(game: Game) -> None:
    game.seats_finalized = False
    game.pending_seat_order = None
    game.bazpors_seat_shuffle_count = 0
    for p in game.players.values():
        p.seat = None


class GameManager:
    def __init__(self) -> None:
        self.games: dict[str, Game] = {}
        self.player_to_room: dict[int, str] = {}
        self.host_to_room: dict[int, str] = {}
        self.observer_to_room: dict[int, str] = {}
        """نام نمایشی اختیاری فقط در پیام‌های ربات (user_id → متن)؛ پایدار با دیتابیس."""
        self.user_display_names: dict[int, str] = {}
        self.scenarios: dict[str, list[Role]] = {
            "bazpors": [],
            "bazpors_salamat_test": [],
            "namayande": [],
            "takavar": [],
            "masoon": [],
            "masoon2": [Role.MAFIA, Role.CITIZEN],
            "mozakere": [],
            "russian_mafia": [],
        }

    def _rebuild_room_indexes(self, game: Game) -> None:
        """پس از restore snapshot — نگاشت host/player/observer."""
        code = game.room_code
        self.host_to_room[game.host_id] = code
        for uid in game.players:
            self.player_to_room[uid] = code
        if game.observer_user_id is not None:
            self.observer_to_room[game.observer_user_id] = code

    def persist_snapshot(self, game: Game, *, reason: str = "") -> None:
        try:
            from bot.game_snapshot import persist_game_snapshot

            persist_game_snapshot(game, reason=reason)
        except Exception:
            logging.getLogger(__name__).exception(
                "persist game snapshot failed room=%s reason=%s",
                game.room_code,
                reason,
            )

    def restore_active_games_from_db(self) -> list[str]:
        try:
            from bot.game_snapshot import restore_games_into_manager

            return restore_games_into_manager(self)
        except Exception:
            logging.getLogger(__name__).exception("restore active games failed")
            return []

    def load_user_display_names_from_db(self) -> None:
        self.user_display_names = db.fetch_all_user_display_names()

    def scenario_display_name(self, scenario_key: str) -> str:
        return SCENARIO_LABELS_FA.get(scenario_key, scenario_key)

    def get_user_display_name(self, user_id: int, telegram_full_name: str) -> str:
        return self.user_display_names.get(user_id, telegram_full_name)

    def set_user_display_name(self, user_id: int, raw: str) -> None:
        name = raw.strip()
        if not name:
            raise ValueError("نام نمی‌تواند خالی باشد.")
        if name in ("-", "پیشفرض", "پیش‌فرض"):
            self.user_display_names.pop(user_id, None)
            db.delete_user_display_name(user_id)
            return
        if len(name) > DISPLAY_NAME_MAX_LEN:
            raise ValueError(f"نام حداکثر {DISPLAY_NAME_MAX_LEN} نویسه باشد.")
        self.user_display_names[user_id] = name
        db.upsert_user_display_name(user_id, name)

    def format_player_tag(self, player: Player) -> str:
        custom = self.user_display_names.get(player.user_id)
        if custom is not None:
            label = custom
            if player.username:
                return f"{label} (@{player.username})"
            return label
        label = player.full_name
        if player.username:
            return f"{label} (@{player.username})"
        return label

    def format_user_tag(self, user_id: int, telegram_full_name: str, username: str | None) -> str:
        custom = self.user_display_names.get(user_id)
        if custom is not None:
            label = custom
            if username:
                return f"{label} (@{username})"
            return label
        label = telegram_full_name
        if username:
            return f"{label} (@{username})"
        return label

    def intended_roles_for_room(self, scenario_name: str, max_players: int) -> list[Role]:
        if scenario_name == "mozakere":
            return mozakere_roles_for_count(max_players)
        if scenario_name == "bazpors":
            return bazpors_roles_for_count(max_players)
        if scenario_name == "bazpors_salamat_test":
            return bazpors_roles_for_count(max_players)
        if scenario_name == "takavar":
            return takavar_roles_for_count(max_players)
        if scenario_name == "masoon":
            return masoon_roles_for_count(max_players)
        if scenario_name == "namayande":
            return namayande_roles_for_count(max_players)
        if scenario_name == "russian_mafia":
            from bot.russian_mafia import russian_roles_for_count

            return russian_roles_for_count(max_players)
        roles = list(self._scenario_roles(scenario_name))
        while len(roles) < max_players:
            roles.append(Role.CITIZEN)
        return roles

    def _scenario_roles(self, scenario_name: str) -> list[Role]:
        if scenario_name in (
            "mozakere",
            "bazpors",
            "bazpors_salamat_test",
            "takavar",
            "masoon",
            "namayande",
            "russian_mafia",
        ):
            return []
        roles = self.scenarios.get(scenario_name)
        if roles is None:
            roles = self.scenarios[DEFAULT_SCENARIO_KEY]
        return roles

    def _new_room_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.games:
                return code

    def create_game(
        self,
        host_id: int,
        scenario_name: str,
        max_players: int,
        *,
        host_full_name: str = "",
        host_username: str | None = None,
        bazpors_host_mode: str | None = None,
    ) -> Game | None:
        scenario_key = scenario_name.strip().lower()
        if scenario_key not in self.scenarios:
            return None

        if scenario_key == "mozakere":
            if max_players not in MOZAKERE_PLAYER_COUNTS:
                return None
        elif scenario_key == "bazpors":
            if max_players not in BAZPORS_PLAYER_COUNTS:
                return None
        elif scenario_key == "bazpors_salamat_test":
            if max_players not in BAZPORS_SALAMAT_TEST_PLAYER_COUNTS:
                return None
        elif scenario_key == "takavar":
            if max_players not in TAKAVAR_PLAYER_COUNTS:
                return None
        elif scenario_key == "masoon2":
            if max_players not in MASOON2_PLAYER_COUNTS:
                return None
        elif scenario_key == "masoon":
            if max_players not in MASOON_PLAYER_COUNTS:
                return None
        elif scenario_key == "namayande":
            if max_players not in NAMAYANDEH_PLAYER_COUNTS:
                return None
        elif scenario_key == "russian_mafia":
            from bot.russian_mafia import HOST_HELPER_MODE, PLAYER_COUNTS

            if max_players not in PLAYER_COUNTS:
                return None
            if bazpors_host_mode not in (None, HOST_HELPER_MODE):
                return None
        else:
            need = self.required_players_for_scenario(scenario_key)
            if max_players < need or max_players > 50:
                return None

        code = self._new_room_code()
        raw_timers = db.get_host_timer_settings_row(host_id)
        if raw_timers:
            tm = normalize_host_timer_settings(
                lobby=raw_timers["lobby_fill_deadline_minutes"],
                post=raw_timers["post_deal_timeout_hours"],
                appr=raw_timers["player_end_approval_minutes"],
                brdc=raw_timers["player_end_broadcast_confirm_minutes"],
            )
        else:
            tm = normalize_host_timer_settings()
        game = Game(
            room_code=code,
            host_id=host_id,
            scenario_name=scenario_key,
            max_players=max_players,
            host_full_name=(host_full_name or "").strip(),
            host_username=host_username,
            lobby_fill_deadline_minutes=tm["lobby_fill_deadline_minutes"],
            post_deal_timeout_hours=tm["post_deal_timeout_hours"],
            player_end_approval_minutes=tm["player_end_approval_minutes"],
            player_end_broadcast_confirm_minutes=tm[
                "player_end_broadcast_confirm_minutes"
            ],
        )
        if scenario_key == "bazpors":
            game.bazpors_host_mode = bazpors_host_mode or "manual"
        elif scenario_key == "mozakere" and bazpors_host_mode:
            game.bazpors_host_mode = bazpors_host_mode
        elif scenario_key == "masoon" and bazpors_host_mode:
            game.bazpors_host_mode = bazpors_host_mode
        elif scenario_key == "russian_mafia" and bazpors_host_mode:
            game.bazpors_host_mode = bazpors_host_mode
        self.games[code] = game
        self.host_to_room[host_id] = code
        self.persist_snapshot(game, reason="create")
        return game

    def normalize_join_code(self, raw: str) -> str | None:
        s = join_code_to_ascii_digits(raw)
        if not s.isdigit():
            return None
        if not 1 <= len(s) <= CODE_LENGTH:
            return None
        return s.zfill(CODE_LENGTH)

    def get_game(self, room_code: str) -> Game | None:
        key = self.normalize_join_code(room_code)
        if key is not None:
            return self.games.get(key)
        return self.games.get(room_code.strip())

    def setup_bazpors_salamat_test_room(self, game: Game) -> None:
        """
        اتاق تست شبکه سلامت: ۱۲ بازیکن ساختگی با صندلی ثابت، بدون ثبت در player_to_room.
        گرداننده واقعی است؛ بقیه شناسهٔ منفی دارند تا ربات به آن‌ها پیام نفرستد.
        """
        if game.scenario_name != "bazpors_salamat_test":
            return
        game.players.clear()
        for seat in range(1, game.max_players + 1):
            uid = -910000 - seat
            game.players[uid] = Player(
                user_id=uid,
                full_name=f"صندلی {_digits_fa(seat)} (تست شبکه سلامت)",
                username=None,
                seat=seat,
            )
        game.seats_finalized = True
        game.pending_seat_order = None
        game.lobby_full_notice_sent = True

    def _fill_bazpors_synthetic_preserving_real_players(
        self, game: Game
    ) -> str | None:
        """بازیکن واقعی حفظ می‌شود؛ ساختگی‌های قبلی حذف و ظرفیت باقی پر می‌شود."""
        for uid in list(game.players):
            if is_synthetic_player_uid(uid):
                game.players.pop(uid)
                self.player_to_room.pop(uid, None)
        needed = game.max_players - len(game.players)
        if needed < 0:
            return "over_capacity"
        if needed == 0:
            game.lobby_full_notice_sent = False
            self.persist_snapshot(game, reason="lobby_fill")
            return None
        try:
            names = draw_unique_synthetic_player_names(needed)
        except ValueError:
            return "name_pool_exhausted"
        used_uids = set(game.players)
        synth_idx = 1
        added = 0
        while added < needed:
            uid = SEMI_AUTO_SYNTHETIC_UID_BASE - synth_idx
            synth_idx += 1
            if uid in used_uids:
                continue
            used_uids.add(uid)
            game.players[uid] = Player(
                user_id=uid,
                full_name=names[added],
                username=None,
                seat=None,
            )
            added += 1
        game.lobby_full_notice_sent = False
        self.persist_snapshot(game, reason="lobby_fill")
        return None

    def fill_bazpors_semi_auto_synthetic_lobby(self, game: Game) -> str | None:
        """
        موقت: پر کردن لابی بازپرس نیمه‌خودکار با بازیکن ساختگی (بدون تلگرام).
        اگر بازیکن واقعی در لابی باشد، مثل no_host فقط جای خالی پر می‌شود.
        """
        if game.scenario_name != "bazpors" or game.bazpors_host_mode != "semi_auto":
            return "not_semi_auto"
        if game.phase != Phase.LOBBY:
            return "not_lobby"
        if game.seats_finalized or game.roles_dealt:
            return "past_lobby"
        has_real = any(
            not is_synthetic_player_uid(uid) for uid in game.players
        )
        if has_real:
            return self._fill_bazpors_synthetic_preserving_real_players(game)
        game.players.clear()
        names = draw_unique_synthetic_player_names(game.max_players)
        for seat in range(1, game.max_players + 1):
            uid = SEMI_AUTO_SYNTHETIC_UID_BASE - seat
            game.players[uid] = Player(
                user_id=uid,
                full_name=names[seat - 1],
                username=None,
                seat=None,
            )
        game.lobby_full_notice_sent = False
        self.persist_snapshot(game, reason="lobby_fill")
        return None

    def fill_no_host_synthetic_lobby(self, game: Game) -> str | None:
        """
        پر کردن ظرفیت باقی‌مانده در «بازیکن گرداننده» (بازپرس یا مذاکره).
        سازندهٔ اتاق (و هر بازیکن واقعی دیگر) حفظ می‌شود.
        """
        if game.bazpors_host_mode != "no_host":
            return "not_no_host"
        if game.scenario_name not in ("bazpors", "mozakere", "masoon"):
            return "not_no_host"
        if game.phase != Phase.LOBBY:
            return "not_lobby"
        if game.seats_finalized or game.roles_dealt:
            return "past_lobby"
        if game.host_id not in game.players:
            return "creator_not_player"
        return self._fill_bazpors_synthetic_preserving_real_players(game)

    def fill_russian_mafia_synthetic_lobby(self, game: Game) -> str | None:
        """جای خالی مافیای روسی را با همان بازیکن ساختگی لابی پر می‌کند."""
        if game.scenario_name != "russian_mafia" or game.bazpors_host_mode != "host_helper":
            return "not_russian_host_helper"
        if game.phase != Phase.LOBBY:
            return "not_lobby"
        if game.seats_finalized or game.roles_dealt:
            return "past_lobby"
        return self._fill_bazpors_synthetic_preserving_real_players(game)

    def fill_bazpors_no_host_synthetic_lobby(self, game: Game) -> str | None:
        """سازگاری با نام قبلی — فقط بازپرس."""
        if game.scenario_name != "bazpors" or game.bazpors_host_mode != "no_host":
            return "not_no_host"
        return self.fill_no_host_synthetic_lobby(game)

    def _sync_synthetic_player_display_names_to_roles(self, game: Game) -> None:
        """
        پس از پخش نقش: نام نمایشی بازیکن ساختگی را با نقش هم‌خوان می‌کند.
        - بازپرس معمولی (لابی تست): «امیر-شیاد»
        - تست شبکه سلامت: فقط نام نقش (+ شماره اگر تکراری)
        """
        if game.scenario_name not in ("bazpors", "bazpors_salamat_test"):
            return
        players = sorted(
            game.players.values(),
            key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
        )
        if game.scenario_name == "bazpors_salamat_test":
            tot: Counter[Role] = Counter()
            for p in players:
                if not is_synthetic_player_uid(p.user_id) or p.role is None:
                    continue
                tot[p.role] += 1
            seen: Counter[Role] = Counter()
            for p in players:
                if not is_synthetic_player_uid(p.user_id) or p.role is None:
                    continue
                lab = role_label_fa(p.role)
                seen[p.role] += 1
                if tot[p.role] > 1:
                    p.full_name = f"{lab} ({_digits_fa(seen[p.role])})"
                else:
                    p.full_name = lab
            return
        for p in players:
            if not is_synthetic_player_uid(p.user_id) or p.role is None:
                continue
            base = synthetic_player_base_name(p.full_name)
            p.full_name = f"{base}-{role_label_fa(p.role)}"

    def _sync_mozakere_synthetic_player_display_names(self, game: Game) -> None:
        if game.scenario_name != "mozakere":
            return
        for p in sorted(
            game.players.values(),
            key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
        ):
            if not is_synthetic_player_uid(p.user_id) or p.role is None:
                continue
            base = synthetic_player_base_name(p.full_name)
            p.full_name = f"{base}-{mozakere_role_label_fa(p.role)}"

    def lobby_ready_for_deal(self, game: Game) -> tuple[bool, str | None]:
        """برای شافل و پخش نقش: لابی پر مطابق سناریو."""
        if game.phase != Phase.LOBBY:
            return False, "بازی در لابی نیست."
        n = len(game.players)
        if game.scenario_name in (
            "mozakere",
            "bazpors",
            "bazpors_salamat_test",
            "takavar",
            "masoon2",
            "masoon",
            "namayande",
            "russian_mafia",
        ):
            if n != game.max_players:
                label = self.scenario_display_name(game.scenario_name)
                return (
                    False,
                    f"سناریوی {label}: باید دقیقاً {game.max_players} بازیکن باشد. الان: {n}",
                )
        else:
            need = self.required_players_for_scenario(game.scenario_name)
            if n < max(5, need):
                return (
                    False,
                    f"حداقل {max(5, need)} بازیکن لازم است. الان: {n}",
                )
            if n > game.max_players:
                return False, "خطای ظرفیت."
        return True, None

    def is_lobby_past_fill_deadline(
        self, game: Game, max_age_minutes: int | None = None
    ) -> bool:
        """لابی باز، هنوز به حد نصاب نرسیده، و از زمان ساخت اتاق بیش از max_age_minutes گذشته."""
        minutes = (
            max_age_minutes
            if max_age_minutes is not None
            else game.lobby_fill_deadline_minutes
        )
        if game.phase != Phase.LOBBY:
            return False
        full, _ = self.lobby_ready_for_deal(game)
        if full:
            return False
        created = game.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return created <= cutoff

    def collect_stale_unfilled_lobbies(
        self, max_age_minutes: int | None = None
    ) -> list[Game]:
        return [
            g
            for g in list(self.games.values())
            if self.is_lobby_past_fill_deadline(g, max_age_minutes)
        ]

    def prepare_shuffle(self, game: Game) -> list[tuple[int, Player]]:
        ok, err = self.lobby_ready_for_deal(game)
        if not ok:
            raise ValueError(err or "لابی آماده نیست.")
        if game.roles_dealt:
            raise ValueError("نقش‌ها پخش شده؛ نمی‌توان دوباره شافل کرد.")
        ids = list(game.players.keys())
        random.shuffle(ids)
        game.pending_seat_order = ids
        return [(i + 1, game.players[uid]) for i, uid in enumerate(ids)]

    def confirm_shuffle(self, game: Game) -> list[tuple[int, Player]]:
        if game.phase != Phase.LOBBY:
            raise ValueError("فقط در لابی می‌توان صندلی را ثبت کرد.")
        if not game.pending_seat_order:
            raise ValueError("اول /shuffle بزنید.")
        if game.roles_dealt:
            raise ValueError("نقش‌ها قبلاً پخش شده.")
        out: list[tuple[int, Player]] = []
        for seat_idx, uid in enumerate(game.pending_seat_order, start=1):
            p = game.players[uid]
            p.seat = seat_idx
            out.append((seat_idx, p))
        game.pending_seat_order = None
        game.seats_finalized = True
        game.bazpors_seat_shuffle_count = 0
        return out

    def assert_can_deal_roles(self, game: Game) -> None:
        """قبل از assign_roles و ارسال پیام؛ فاز هنوز لابی می‌ماند تا همهٔ DMها برود."""
        if game.phase != Phase.LOBBY:
            raise ValueError("فقط از لابی می‌توان نقش پخش کرد.")
        if game.roles_dealt:
            raise ValueError(LOBBY_LEAVE_BLOCKED_AFTER_ROLES_MSG)
        ready, _ = self.lobby_ready_for_deal(game)
        if not ready:
            raise ValueError(LOBBY_NOT_FULL_FOR_ROLES_MSG)
        if not game.seats_finalized:
            raise ValueError("اول صندلی‌ها را با /shuffle و /confirmshuffle مشخص کنید.")

    def finalize_deal_roles_phase(self, game: Game) -> None:
        """بعد از ارسال موفق نقش‌ها به همه."""
        game.roles_dealt = True
        game.roles_dealt_at = datetime.now(timezone.utc)
        if (
            game.scenario_name in ("bazpors", "mozakere")
            and game.bazpors_host_mode == "semi_auto"
        ):
            game.narration_mode = "semi_auto"
        else:
            game.narration_mode = "manual"
        game.phase = Phase.MANUAL
        game.host_may_pick_winner = False
        try:
            from bot.game_audit_log import log_game_started

            log_game_started(game, self)
        except Exception:
            logging.getLogger(__name__).exception("audit log game start failed")
        self.persist_snapshot(game, reason="roles_dealt")

    def is_post_deal_past_timeout(self, game: Game) -> bool:
        if game.phase != Phase.MANUAL or not game.roles_dealt or game.roles_dealt_at is None:
            return False
        ra = game.roles_dealt_at
        if ra.tzinfo is None:
            ra = ra.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=game.post_deal_timeout_hours)
        return ra <= cutoff

    def collect_post_deal_timeout_games(self) -> list[Game]:
        return [g for g in list(self.games.values()) if self.is_post_deal_past_timeout(g)]

    def player_end_vote_active(self, game: Game) -> bool:
        if game.player_end_initiator_id is None or game.player_end_deadline is None:
            return False
        dl = game.player_end_deadline
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < dl

    def player_end_vote_expired(self, game: Game) -> bool:
        if game.player_end_initiator_id is None or game.player_end_deadline is None:
            return False
        dl = game.player_end_deadline
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= dl

    def clear_player_end_broadcast_pending(self, game: Game) -> None:
        game.player_end_broadcast_pending_uid = None
        game.player_end_broadcast_pending_at = None

    def set_player_end_broadcast_pending(self, game: Game, uid: int) -> None:
        game.player_end_broadcast_pending_uid = uid
        game.player_end_broadcast_pending_at = datetime.now(timezone.utc)

    def player_end_broadcast_confirm_expired(self, game: Game) -> bool:
        if game.player_end_broadcast_pending_uid is None:
            return False
        at = game.player_end_broadcast_pending_at
        if at is None:
            return True
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        deadline = at + timedelta(
            minutes=game.player_end_broadcast_confirm_minutes
        )
        return datetime.now(timezone.utc) >= deadline

    def collect_expired_player_end_broadcast_pending(self) -> list[Game]:
        return [
            g
            for g in list(self.games.values())
            if g.player_end_broadcast_pending_uid is not None
            and self.player_end_broadcast_confirm_expired(g)
        ]

    def clear_player_end_vote(self, game: Game) -> None:
        game.player_end_initiator_id = None
        game.player_end_deadline = None
        game.player_end_approvals = set()
        game.player_end_required_ids = None

    def player_end_all_approved(self, game: Game) -> bool:
        req = game.player_end_required_ids
        if not req:
            return False
        return req <= game.player_end_approvals

    def start_player_end_vote(self, game: Game, initiator_id: int) -> str | None:
        """
        شروع درخواست پایان با رأی بازیکنان.
        برمی‌گرداند: None = موفق، یا کلید خطا برای پیام.
        """
        if game.phase != Phase.MANUAL or not game.roles_dealt:
            return "phase"
        if initiator_id == game.host_id:
            return "host"
        if initiator_id not in game.players:
            return "not_player"
        if game.scenario_name == "bazpors_salamat_test":
            return "sandbox"
        if game.player_end_winner_picker_id is not None:
            return "picker_pending"
        if game.player_end_broadcast_pending_uid is not None:
            if self.player_end_broadcast_confirm_expired(game):
                self.clear_player_end_broadcast_pending(game)
            elif game.player_end_broadcast_pending_uid != initiator_id:
                return "pending_confirm_other"
            else:
                return "await_first_confirm"
        if game.player_end_initiator_id is not None:
            if self.player_end_vote_active(game):
                return "already"
            self.clear_player_end_vote(game)
        game.player_end_initiator_id = initiator_id
        game.player_end_deadline = datetime.now(timezone.utc) + timedelta(
            minutes=game.player_end_approval_minutes
        )
        game.player_end_approvals = set()
        game.player_end_required_ids = set(game.players.keys())
        self.clear_player_end_broadcast_pending(game)
        return None

    def approve_player_end_vote(self, game: Game, voter_id: int) -> str | None:
        """None = ثبت شد؛ در غیر این صورت کلید خطا."""
        if not self.player_end_vote_active(game):
            return "inactive"
        if voter_id == game.host_id:
            return "host"
        req = game.player_end_required_ids
        if not req or voter_id not in req:
            return "not_voter"
        if voter_id in game.player_end_approvals:
            return "dup"
        game.player_end_approvals.add(voter_id)
        return None

    def try_finalize_player_end_vote(self, game: Game) -> int | None:
        """
        اگر همهٔ بازیکنان مقصد تا مهلت تأیید کرده باشند، وضعیت رأی را می‌بندد و
        شناسهٔ انتخاب‌کنندهٔ برنده را برمی‌گرداند؛ وگرنه None.
        """
        if not self.player_end_vote_active(game):
            return None
        if not self.player_end_all_approved(game):
            return None
        initiator = game.player_end_initiator_id
        if initiator is None:
            return None
        game.player_end_winner_picker_id = initiator
        self.clear_player_end_vote(game)
        return initiator

    def collect_expired_player_end_votes(self) -> list[Game]:
        out: list[Game] = []
        for g in list(self.games.values()):
            if g.player_end_initiator_id is None or g.player_end_deadline is None:
                continue
            if not self.player_end_vote_expired(g):
                continue
            if self.player_end_all_approved(g):
                continue
            out.append(g)
        return out

    def remove_player_from_manual_game(
        self, game: Game, user_id: int
    ) -> tuple[str | None, int | None]:
        """
        خروج اضطراری بازیکن بعد از پخش نقش.
        برمی‌گرداند (وضعیت, شناسهٔ انتخاب‌کنندهٔ برنده در صورت تکمیل خودکار رأی).
        وضعیت «no» = ناموفق؛ «vote_cancelled» = لغو درخواست جمعی؛ None = موفق بدون لغو.
        """
        if game.phase != Phase.MANUAL or not game.roles_dealt:
            return ("no", None)
        if user_id == game.host_id:
            return ("no", None)
        if user_id not in game.players:
            return ("no", None)
        cancel_notice: str | None = None
        if game.player_end_initiator_id == user_id:
            self.clear_player_end_vote(game)
            cancel_notice = "vote_cancelled"
        if game.player_end_broadcast_pending_uid == user_id:
            self.clear_player_end_broadcast_pending(game)
        if game.player_end_required_ids is not None:
            game.player_end_required_ids.discard(user_id)
            game.player_end_approvals.discard(user_id)
        if game.player_end_winner_picker_id == user_id:
            game.player_end_winner_picker_id = None
        elected = self.try_finalize_player_end_vote(game)
        game.players.pop(user_id)
        self.player_to_room.pop(user_id, None)
        if not game.players:
            self.end_game(game.room_code)
        return (cancel_notice, elected)

    def get_room_for_user(self, user_id: int) -> str | None:
        return self.player_to_room.get(user_id)

    def get_room_for_host(self, user_id: int) -> str | None:
        return self.host_to_room.get(user_id)

    def get_room_for_observer(self, user_id: int) -> str | None:
        return self.observer_to_room.get(user_id)

    def find_active_participant_game(self, user_id: int) -> Game | None:
        """اتاق فعال مرتبط با کاربر — حتی اگر نگاشت player_to_room از دست رفته باشد."""
        for game in self.games.values():
            if game.phase == Phase.ENDED:
                continue
            if user_id in game.players:
                self.player_to_room[user_id] = game.room_code
                return game
        room = (
            self.get_room_for_host(user_id)
            or self.get_room_for_observer(user_id)
            or self.get_room_for_user(user_id)
        )
        if room:
            game = self.get_game(room)
            if game is not None and game.phase != Phase.ENDED:
                return game
        for game in self.games.values():
            if (
                game.phase != Phase.ENDED
                and game.bot_assistant_user_id == user_id
            ):
                return game
        return None

    def ensure_observer_code(self, game: Game) -> str:
        if game.observer_code:
            return game.observer_code
        while True:
            code = f"{secrets.randbelow(10000):04d}"
            if not any(
                g.observer_code == code
                for g in self.games.values()
                if g is not game
            ):
                game.observer_code = code
                return code

    def find_no_host_game_by_observer_code(self, code: str) -> Game | None:
        key = code.strip()
        if len(key) != 4 or not key.isdigit():
            return None
        for game in self.games.values():
            allowed = game.bazpors_host_mode == "no_host" or (
                game.scenario_name == "russian_mafia"
                and game.bazpors_host_mode == "host_helper"
            )
            if (
                allowed
                and game.observer_code == key
                and game.phase != Phase.ENDED
            ):
                return game
        return None

    def register_game_observer(
        self,
        game: Game,
        user_id: int,
        *,
        full_name: str,
        username: str | None,
    ) -> str | None:
        allowed_observer_room = game.bazpors_host_mode == "no_host" or (
            game.scenario_name == "russian_mafia"
            and game.bazpors_host_mode == "host_helper"
        )
        if not allowed_observer_room:
            return "not_no_host"
        if game.observer_prompt_status == "skipped":
            return "skipped"
        if game.observer_user_id is not None:
            return "already_registered"
        if user_id == game.host_id:
            return "creator_is_player"
        if user_id in game.players:
            return "is_player"
        if self.get_room_for_user(user_id):
            return "in_other_room"
        if self.get_room_for_host(user_id):
            return "hosts_other_room"
        if self.get_room_for_observer(user_id):
            return "observer_elsewhere"
        game.observer_user_id = user_id
        game.observer_full_name = (full_name or "").strip() or "ناظر"
        game.observer_username = username
        game.observer_prompt_status = "registered"
        self.observer_to_room[user_id] = game.room_code
        return None

    def end_game(self, room_code: str) -> None:
        try:
            from bot.mason_night_reminder import cancel_mason_night_reminder_task

            cancel_mason_night_reminder_task(room_code)
        except Exception:
            pass
        game = self.games.get(room_code)
        if not game:
            return
        for player_id in game.players:
            self.player_to_room.pop(player_id, None)
        self.host_to_room.pop(game.host_id, None)
        if game.observer_user_id is not None:
            self.observer_to_room.pop(game.observer_user_id, None)
        self.games.pop(room_code, None)
        try:
            from bot.game_snapshot import delete_game_snapshot

            delete_game_snapshot(room_code)
        except Exception:
            logging.getLogger(__name__).exception(
                "delete game snapshot failed room=%s", room_code
            )

    def force_release_ended_session(
        self,
        room_code: str,
        host_id: int,
        player_ids: set[int],
        *,
        observer_user_id: int | None = None,
    ) -> None:
        """پس از پایان دست — اگر end_game قبلاً نخورده یا نگاشت‌ها مانده باشند."""
        key = self.normalize_join_code(room_code) or room_code.strip()
        game = self.games.get(key)
        if game is not None:
            self.end_game(key)
            return
        self.host_to_room.pop(host_id, None)
        for pid in player_ids:
            self.player_to_room.pop(pid, None)
        if observer_user_id is not None:
            self.observer_to_room.pop(observer_user_id, None)
        self.games.pop(key, None)

    def reset_all_games(self) -> int:
        """پاک کردن همهٔ اتاق‌های فعال از حافظه و آزاد کردن نگاشت بازیکن/گرداننده/ناظر."""
        n = len(self.games)
        self.games.clear()
        self.player_to_room.clear()
        self.host_to_room.clear()
        self.observer_to_room.clear()
        try:
            from bot import db

            db.delete_all_active_game_snapshots()
        except Exception:
            logging.getLogger(__name__).exception("clear active game snapshots failed")
        return n

    def add_player(self, game: Game, player: Player) -> str | None:
        """Returns None on success, or error code string."""
        if game.phase != Phase.LOBBY:
            return "not_lobby"
        if player.user_id in game.players:
            return "already_in_room"
        if len(game.players) >= game.max_players:
            return "full"
        game.players[player.user_id] = player
        self.player_to_room[player.user_id] = game.room_code
        self.persist_snapshot(game, reason="join")
        return None

    def remove_player_from_lobby(self, game: Game, user_id: int) -> bool:
        """Leave lobby before roles are dealt; preserves room and join order."""
        if game.phase != Phase.LOBBY or game.roles_dealt:
            return False
        if user_id not in game.players:
            return False
        if user_id == game.host_id:
            return False
        game.players.pop(user_id)
        self.player_to_room.pop(user_id, None)
        if game.seats_finalized or game.pending_seat_order is not None:
            reset_lobby_seats_after_roster_change(game)
        ready, _ = self.lobby_ready_for_deal(game)
        if not ready:
            game.lobby_full_notice_sent = False
        self.persist_snapshot(game, reason="leave")
        return True

    def host_leave_cancel_game(self, game: Game) -> None:
        self.end_game(game.room_code)

    def set_scenario(self, game: Game, scenario_name: str) -> bool:
        if game.phase != Phase.LOBBY:
            return False
        if game.seats_finalized:
            return False
        key = scenario_name.strip().lower()
        if key not in self.scenarios:
            return False
        if key == "mozakere":
            if game.max_players not in MOZAKERE_PLAYER_COUNTS:
                return False
        elif key == "bazpors":
            if game.max_players not in BAZPORS_PLAYER_COUNTS:
                return False
        elif key == "bazpors_salamat_test":
            if game.max_players not in BAZPORS_SALAMAT_TEST_PLAYER_COUNTS:
                return False
        elif key == "takavar":
            if game.max_players not in TAKAVAR_PLAYER_COUNTS:
                return False
        elif key == "masoon2":
            if game.max_players not in MASOON2_PLAYER_COUNTS:
                return False
        elif key == "masoon":
            if game.max_players not in MASOON_PLAYER_COUNTS:
                return False
        elif key == "namayande":
            if game.max_players not in NAMAYANDEH_PLAYER_COUNTS:
                return False
        else:
            need = self.required_players_for_scenario(key)
            if game.max_players < need:
                return False
        game.scenario_name = key
        return True

    def scenario_names(self) -> list[str]:
        return sorted(self.scenarios.keys())

    def required_players_for_scenario(self, scenario_name: str) -> int:
        if scenario_name == "mozakere":
            return 10
        if scenario_name == "bazpors":
            return 10
        if scenario_name == "bazpors_salamat_test":
            return 12
        if scenario_name == "takavar":
            return 10
        if scenario_name == "masoon2":
            return 2
        if scenario_name == "masoon":
            return 12
        if scenario_name == "namayande":
            return 10
        base = self._scenario_roles(scenario_name)
        return len(base) + 1

    def assign_roles(self, game: Game) -> None:
        if game.scenario_name == "mozakere":
            self._assign_roles_mozakere(game)
            self._sync_mozakere_synthetic_player_display_names(game)
            return
        if game.scenario_name == "bazpors":
            self._assign_roles_bazpors(game)
            self._sync_synthetic_player_display_names_to_roles(game)
            return
        if game.scenario_name == "bazpors_salamat_test":
            self._assign_roles_bazpors(game)
            self._sync_synthetic_player_display_names_to_roles(game)
            return
        if game.scenario_name == "takavar":
            self._assign_roles_takavar(game)
            return
        if game.scenario_name == "masoon":
            self._assign_roles_masoon(game)
            from bot.mason_synthetic_names import (
                append_mason_role_labels_to_synthetic_players,
            )

            append_mason_role_labels_to_synthetic_players(game)
            return
        if game.scenario_name == "namayande":
            self._assign_roles_namayande(game)
            return
        if game.scenario_name == "russian_mafia":
            from bot.russian_mafia_flow import assign_roles_on_game

            assign_roles_on_game(game)
            return

        player_ids = list(game.players.keys())
        random.shuffle(player_ids)
        count = len(player_ids)
        roles = list(self._scenario_roles(game.scenario_name))
        while len(roles) < count:
            roles.append(Role.CITIZEN)
        random.shuffle(roles)

        game.mafia_ids.clear()
        for idx, player_id in enumerate(player_ids):
            role = roles[idx]
            game.players[player_id].role = role
            if is_mafia_team(role):
                game.mafia_ids.add(player_id)

    def _assign_roles_mozakere(self, game: Game) -> None:
        n = len(game.players)
        roles = mozakere_roles_for_count(n)

        player_ids = list(game.players.keys())
        random.shuffle(player_ids)
        game.mafia_ids.clear()
        game.mozakere_mafia_recruit_ids.clear()
        game.mozakere_negotiation_used = False
        game.mozakere_negotiation_tonight = False
        game.mozakere_negotiation_target_uid = None
        game.mozakere_negotiation_success = None
        game.mozakere_doctor_self_save_count = 0
        game.mozakere_night_baseline_doctor_self_saves = 0
        game.mozakere_sniper_shots_used = 0
        game.mozakere_journalist_target_uid = None
        game.mozakere_journalist_ack_positive = False
        for pid, role in zip(player_ids, roles):
            pl = game.players[pid]
            pl.role = role
            pl.mozakere_original_role = None
            pl.mozakere_converted_by_negotiation = False
            pl.mozakere_armored_armor_used = False
            if is_mafia_team(role):
                game.mafia_ids.add(pid)

    def _assign_roles_bazpors(self, game: Game) -> None:
        n = len(game.players)
        roles = bazpors_roles_for_count(n)
        player_ids = list(game.players.keys())
        random.shuffle(player_ids)
        game.mafia_ids.clear()
        game.bazpors_mafia_recruit_ids.clear()
        for pid, role in zip(player_ids, roles):
            pl = game.players[pid]
            pl.role = role
            pl.bazpors_original_role = None
            pl.bazpors_converted_by_yakuza = False
            if is_mafia_team(role):
                game.mafia_ids.add(pid)

    def assign_bazpors_roles_by_player(self, game: Game, role_by_player: dict[int, Role]) -> None:
        """اعمال نقش‌های از‌پیش‌تعیین‌شدهٔ بازپرس (انتخاب شماره توسط بازیکن‌ها)."""
        game.mafia_ids.clear()
        game.bazpors_mafia_recruit_ids.clear()
        for pid, pl in game.players.items():
            role = role_by_player.get(pid)
            if role is None:
                raise ValueError("همهٔ بازیکن‌ها باید نقش داشته باشند.")
            pl.role = role
            pl.bazpors_original_role = None
            pl.bazpors_converted_by_yakuza = False
            if is_mafia_team(role):
                game.mafia_ids.add(pid)
        self._sync_synthetic_player_display_names_to_roles(game)

    def assign_mozakere_roles_by_player(
        self, game: Game, role_by_player: dict[int, Role]
    ) -> None:
        """اعمال نقش‌های از‌پیش‌تعیین‌شدهٔ مذاکره (انتخاب شماره توسط بازیکن‌ها)."""
        game.mafia_ids.clear()
        game.mozakere_mafia_recruit_ids.clear()
        game.mozakere_negotiation_used = False
        game.mozakere_negotiation_tonight = False
        game.mozakere_negotiation_target_uid = None
        game.mozakere_negotiation_success = None
        game.mozakere_doctor_self_save_count = 0
        game.mozakere_night_baseline_doctor_self_saves = 0
        game.mozakere_sniper_shots_used = 0
        game.mozakere_journalist_target_uid = None
        game.mozakere_journalist_ack_positive = False
        for pid, pl in game.players.items():
            role = role_by_player.get(pid)
            if role is None:
                raise ValueError("همهٔ بازیکن‌ها باید نقش داشته باشند.")
            pl.role = role
            pl.mozakere_original_role = None
            pl.mozakere_converted_by_negotiation = False
            pl.mozakere_armored_armor_used = False
            if is_mafia_team(role):
                game.mafia_ids.add(pid)
        self._sync_mozakere_synthetic_player_display_names(game)

    def assign_russian_mafia_roles_by_player(
        self, game: Game, role_by_player: dict[int, Role]
    ) -> None:
        from bot.russian_mafia_flow import assign_roles_on_game

        assign_roles_on_game(game, role_by_player)

    def assign_mason_roles_by_player(
        self, game: Game, role_by_player: dict[int, Role]
    ) -> None:
        """اعمال نقش‌های از‌پیش‌تعیین‌شدهٔ ماسون (انتخاب شماره توسط بازیکن‌ها)."""
        from bot.roles.mason_commander import reset_mason_role_counters_for_new_game
        from bot.roles.mason_fraternity import initialize_mason_team_for_new_game
        from bot.mason_synthetic_names import (
            append_mason_role_labels_to_synthetic_players,
        )

        game.mafia_ids.clear()
        reset_mason_role_counters_for_new_game(game)
        for pid, pl in game.players.items():
            role = role_by_player.get(pid)
            if role is None:
                raise ValueError("همهٔ بازیکن‌ها باید نقش داشته باشند.")
            pl.role = role
            if is_mafia_team(role):
                game.mafia_ids.add(pid)
        initialize_mason_team_for_new_game(game)
        append_mason_role_labels_to_synthetic_players(game)

    def _assign_roles_takavar(self, game: Game) -> None:
        n = len(game.players)
        roles = takavar_roles_for_count(n)
        player_ids = list(game.players.keys())
        random.shuffle(player_ids)
        game.mafia_ids.clear()
        for pid, role in zip(player_ids, roles):
            game.players[pid].role = role
            if is_mafia_team(role):
                game.mafia_ids.add(pid)

    def _assign_roles_masoon(self, game: Game) -> None:
        from bot.roles.mason_commander import reset_mason_role_counters_for_new_game

        n = len(game.players)
        roles = masoon_roles_for_count(n)
        player_ids = list(game.players.keys())
        random.shuffle(player_ids)
        game.mafia_ids.clear()
        reset_mason_role_counters_for_new_game(game)
        for pid, role in zip(player_ids, roles):
            game.players[pid].role = role
            if is_mafia_team(role):
                game.mafia_ids.add(pid)
        from bot.roles.mason_fraternity import initialize_mason_team_for_new_game

        initialize_mason_team_for_new_game(game)

    def _assign_roles_namayande(self, game: Game) -> None:
        n = len(game.players)
        roles = namayande_roles_for_count(n)
        player_ids = list(game.players.keys())
        random.shuffle(player_ids)
        game.mafia_ids.clear()
        for pid, role in zip(player_ids, roles):
            game.players[pid].role = role
            if is_mafia_team(role):
                game.mafia_ids.add(pid)

    def resolve_night(self, game: Game) -> tuple[list[str], int | None]:
        logs: list[str] = []
        killed_id: int | None = None

        target = game.actions.mafia_target
        saved = game.actions.doctor_save
        if target and target != saved and game.players[target].is_alive:
            game.players[target].is_alive = False
            killed_id = target
            logs.append(
                f"🌙 شب گذشته {self.format_player_tag(game.players[target])} کشته شد."
            )
        else:
            logs.append("🌙 شب گذشته کسی کشته نشد.")

        game.actions = NightActions()
        return logs, killed_id

    def alive_players(self, game: Game) -> list[Player]:
        return [p for p in game.players.values() if p.is_alive]

    def is_alive(self, game: Game, user_id: int) -> bool:
        player = game.players.get(user_id)
        return bool(player and player.is_alive)

    def check_winner(self, game: Game) -> str | None:
        alive = self.alive_players(game)
        if not alive:
            return None
        mafia_alive = sum(
            1 for p in alive if bazpors_counts_as_alive_mafia_for_win(game, p)
        )
        citizens_alive = len(alive) - mafia_alive
        if mafia_alive == 0:
            return "شهروندها برنده شدند! 🎉"
        # سناریوی موقت masoon2: ۱ مافیا و ۱ شهروند؛ شروع ۱–۱ نباید فوراً پایان بازی شود
        if (
            game.scenario_name == "masoon2"
            and len(alive) == 2
            and mafia_alive == 1
            and citizens_alive == 1
        ):
            return None
        if game.scenario_name == "bazpors_salamat_test":
            if mafia_alive > citizens_alive:
                return "مافیا برنده شد! 😈"
            if mafia_alive == citizens_alive and mafia_alive > 0:
                return (
                    "بازی تمام شد: تعداد مافیا و شهروند برابر شد — "
                    "<b>مافیا برنده است</b>! 😈"
                )
            return None
        if mafia_alive >= citizens_alive:
            return "مافیا برنده شد! 😈"
        return None

    def register_vote(self, game: Game, voter_id: int, target_id: int) -> None:
        game.votes[voter_id] = target_id

    def resolve_votes(self, game: Game) -> tuple[int | None, str]:
        if not game.votes:
            return None, "هیچ رایی ثبت نشد."

        counts = Counter(game.votes.values())
        top_target, top_votes = counts.most_common(1)[0]
        tied = [target for target, c in counts.items() if c == top_votes]
        if len(tied) > 1:
            return None, "رای‌گیری مساوی شد و کسی حذف نشد."

        target = game.players.get(top_target)
        if target and target.is_alive:
            target.is_alive = False
            return (
                top_target,
                f"🗳 {self.format_player_tag(target)} با رای گروه حذف شد.",
            )
        return None, "هدف رای‌گیری معتبر نبود."
