"""Namayande-10 fork — independent role display registry.

Presentation-only module: it resolves player-facing role names for the
independent Namayande-10 fork without touching mechanics, internal ``Role``
enum values, faction membership or any label used by Bazpors / classic
Namayande (11+) / other scenarios.

Authoritative mapping (internal Role value -> display name):
    MAFIA_BOSS     رئیس مافیا   Mafia Boss
    NATO           یاغی         Rebel
    SHIAD          هکر          Hacker
    DOCTOR         پزشک         Doctor
    INTERROGATOR   راهنما       Guide
    HUNTER         وکیل         Lawyer
    DETECTIVE      محافظ        Guardian
    RUINTAN        مین‌گذار      Mine Layer
    CITIZEN        شهروند ساده  Citizen

Unknown roles (e.g. SNIPER in the 11–13 player variants that share this
engine) fall back to the global Bazpors formatter so those counts keep
their existing labels.
"""

from __future__ import annotations

import html as html_
import re as re_

from bot.models import Role

NAM10_ROLE_LABELS_FA: dict[Role, str] = {
    Role.MAFIA_BOSS: "رئیس مافیا",
    Role.NATO: "یاغی",
    Role.SHIAD: "هکر",
    Role.DOCTOR: "پزشک",
    Role.INTERROGATOR: "راهنما",
    Role.HUNTER: "وکیل",
    Role.DETECTIVE: "محافظ",
    Role.RUINTAN: "مین‌گذار",
    Role.CITIZEN: "شهروند ساده",
    Role.NATO_AGENT: "ناتو",
    Role.SOLDIER: "سرباز",
}

NAM10_ROLE_LABELS_EN: dict[Role, str] = {
    Role.MAFIA_BOSS: "Mafia Boss",
    Role.NATO: "Rebel",
    Role.SHIAD: "Hacker",
    Role.DOCTOR: "Doctor",
    Role.INTERROGATOR: "Guide",
    Role.HUNTER: "Lawyer",
    Role.DETECTIVE: "Guardian",
    Role.RUINTAN: "Mine Layer",
    Role.CITIZEN: "Citizen",
    Role.NATO_AGENT: "NATO Agent",
    Role.SOLDIER: "Soldier",
}

# Canonical 10-player composition in deal order (CITIZEN x2).
NAM10_FORK_ROLE_COMPOSITION: tuple[Role, ...] = (
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
)


def nam10_role_label_fa(role: Role | None) -> str:
    """Persian display label inside the Namayande-10 fork."""
    if role is None:
        return "—"
    label = NAM10_ROLE_LABELS_FA.get(role)
    if label is not None:
        return label
    from bot.game import role_label_fa

    return role_label_fa(role)


def nam10_role_label_en(role: Role | None) -> str:
    """English display label inside the Namayande-10 fork."""
    if role is None:
        return "-"
    label = NAM10_ROLE_LABELS_EN.get(role)
    if label is not None:
        return label
    return role.value

def _nam10_event_role_label(row: dict) -> str | None:
    """Original assigned-role label for a recap row.

    Converted players (Yakuza) keep their ORIGINAL role; temporary
    abilities are never shown. Returns None for unknown/observer rows.
    """
    from bot.models import Role

    raw = row.get("original_role") or row.get("role")
    try:
        role = Role(str(raw)) if raw else None
    except ValueError:
        return None
    if role is None or role == Role.OBSERVER:
        return None
    return nam10_role_label_fa(role)


_SUFFIX_LABELS_CACHE: set[str] | None = None


def _suffix_labels() -> set[str]:
    """Labels that, when already present in parentheses right after a
    name, mark the occurrence as already role-suffixed (no duplicates)."""
    global _SUFFIX_LABELS_CACHE
    if _SUFFIX_LABELS_CACHE is None:
        labels = set(NAM10_ROLE_LABELS_FA.values())
        try:
            from bot.game import ROLE_LABELS_FA

            labels |= set(ROLE_LABELS_FA.values())
        except Exception:
            pass
        _SUFFIX_LABELS_CACHE = labels
    return _SUFFIX_LABELS_CACHE


_ALREADY_SUFFIXED_RE = re_.compile(r"\s*\(([^()<>\n]{1,40})\)")


def nam10_tag_event_history_names_with_roles(html_text: str, rows: object) -> str:
    """Namayande-only report rendering: append the player's original role
    in parentheses after every display-name occurrence inside the
    event-history HTML (night reports, day eliminations, hacker
    source/destination, ...).

    * Names are matched exactly as rendered (html.escape of the
      /myname-aware display tag) with word boundaries, longest first.
    * Occurrences already followed by a known role label in parentheses
      are left untouched (no duplicate suffixes).
    * Shared by BOTH the live eliminated-player report and the final
      post-game reports via _build_bazpors_timeline_html.
    """
    if not html_text or not isinstance(rows, list):
        return html_text
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        tag = str(row.get("tag") or "").strip()
        if not tag:
            continue
        label = _nam10_event_role_label(row)
        if not label:
            continue
        for variant in dict.fromkeys((tag, tag.replace("میز ", "صندلی "))):
            escaped = html_.escape(variant)
            if escaped and escaped not in seen:
                seen.add(escaped)
                entries.append((escaped, label))
    if not entries:
        return html_text
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    known = _suffix_labels()
    text = html_text
    boundary = r"(?<![\wآ-ی_])"
    all_names = [name for name, _label in entries]
    word_re = re_.compile(r"[\wآ-ی_]")
    for escaped_name, label in entries:
        # Occurrences that are the prefix of a LONGER tracked name
        # (e.g. «امیر» inside «امیر لطیفی») belong to the longer
        # name (processed first, longest-first) and must not receive a
        # second, mid-name suffix.
        continuations = tuple(
            other[len(escaped_name):]
            for other in all_names
            if len(other) > len(escaped_name)
            and other.startswith(escaped_name)
        )

        def _is_inside_longer_name(tail: str) -> bool:
            for cont in continuations:
                if tail.startswith(cont):
                    rest = tail[len(cont):]
                    if not rest or not word_re.match(rest[0]):
                        return True
            return False

        pattern = boundary + re_.escape(escaped_name) + r"(?![\wآ-ی_])"

        def _repl(
            match: "re_.Match[str]",
            _label: str = label,
            _longer=_is_inside_longer_name,
        ) -> str:
            tail = match.string[match.end():]
            if _longer(tail):
                return match.group(0)
            already = _ALREADY_SUFFIXED_RE.match(tail)
            if already and already.group(1).strip() in known:
                return match.group(0)
            return match.group(0) + f" ({_label})"

        text = re_.sub(pattern, _repl, text)
    return text

# Persian one-paragraph capability descriptions for the text-only private
# role notification (no image) inside the Namayande-10 fork.
NAM10_ROLE_DESCRIPTIONS_FA: dict[Role, str] = {
    Role.MAFIA_BOSS: (
        "شما رئیس تیم مافیا هستید. استعلام شما منفی است. در روز اول می‌توانید "
        "با رأی خیانت، یک رأی به یکی از نمایندگان اضافه کنید یا از آن کم کنید؛ "
        "اما اگر خودتان نماینده باشید، نمی‌توانید رأی نمایندگی خود را تغییر "
        "دهید. در شب می‌توانید شات یا قابلیت یک‌بارمصرف ناتویی را انتخاب کنید."
    ),
    Role.NATO: (
        "شما نفر دوم تیم مافیا هستید. اگر رئیس مافیا یا هکر از بازی خارج شوند، "
        "قابلیت ترور شما فعال می‌شود. می‌توانید یک بار در بازی و پیش از شروع "
        "رأی‌گیری روز، یک بازیکن را برای ترور انتخاب کنید. پس از ترور خودتان "
        "از بازی خارج می‌شوید؛ محافظ و بازیکن دارای زره در برابر ترور مصون "
        "هستند."
    ),
    Role.SHIAD: (
        "شما هر شب می‌توانید قابلیت یک بازیکن شهروند را نسبت به بازیکن شهروند "
        "دیگری بی‌اثر کنید. ابتدا صاحب قابلیت و سپس مقصد اثر آن را انتخاب "
        "می‌کنید."
    ),
    Role.DOCTOR: (
        "شما هر شب می‌توانید یک بازیکن، از جمله خودتان، را از شات شبانه نجات "
        "دهید. در طول بازی حداکثر دو بار می‌توانید خودتان را نجات دهید."
    ),
    Role.INTERROGATOR: (
        "شما هر شب یک بازیکن را انتخاب می‌کنید. اگر بازیکن انتخاب‌شده شهروند "
        "باشد، آن شخص می‌تواند مانند کارآگاه از یک نفر استعلام بگیرد. اگر "
        "عضو مافیا باشد، هویت شما برای همان بازیکن فاش می‌شود. نمی‌توانید یک "
        "بازیکن را در دو شب متوالی انتخاب کنید."
    ),
    Role.RUINTAN: (
        "شما یک بار در طول بازی می‌توانید مقابل خانه یک بازیکن مین بگذارید. "
        "مین تا زمان فعال‌شدن یا خنثی‌شدن باقی می‌ماند. اگر مافیا بازیکن "
        "مین‌گذاری‌شده را بدون خنثی‌سازی شات کند و بازیکن نجات پیدا نکند، مین "
        "فعال می‌شود و پیامد آن طبق قوانین بازی محاسبه خواهد شد."
    ),
    Role.HUNTER: (
        "شما یک بار در طول بازی می‌توانید از یک بازیکن حمایت کنید. اگر انتخاب "
        "شما معتبر باشد، آن بازیکن در روز بعد وارد دفاعیه نخواهد شد."
    ),
    Role.DETECTIVE: (
        "شما هر شب می‌توانید یک بازیکن دیگر را انتخاب کنید تا در روز بعد زره "
        "ضدترور داشته باشد. خودتان نیز در برابر ترور مصون هستید."
    ),
    Role.CITIZEN: (
        "شما عضو تیم شهروندان هستید و قابلیت ویژه شبانه ندارید."
    ),
    Role.NATO_AGENT: (
        "شما عضو مستقل تیم مافیا و دارندهٔ قابلیت ناتو هستید. این قابلیت "
        "یک‌بار در طول بازی قابل استفاده است. اگر شوتر تیم مافیا در شب "
        "گزینهٔ «ناتویی» را انتخاب کند، شما نقش یکی از شهروندها را حدس "
        "می‌زنید و سپس بازیکن موردنظر خود را انتخاب می‌کنید. در صورت "
        "درست‌بودن حدس، آن بازیکن از بازی خارج می‌شود."
    ),
    Role.SOLDIER: (
        "شما یک‌بار در طول بازی می‌توانید قابلیت یک شلیک اسنایپری را به "
        "یکی از بازیکنان بدهید. اگر بازیکن انتخاب‌شده عضو تیم شهروند باشد، "
        "پس از تکمیل اقدامات لازم، قابلیت یک شلیک اسنایپری به او داده "
        "می‌شود. اگر بازیکن انتخاب‌شده عضو تیم مافیا باشد، شما از بازی "
        "خارج می‌شوید."
    ),
}


def nam10_role_description_fa(role: Role | None) -> str:
    """Persian capability description inside the Namayande-10 fork."""
    if role is None:
        return ""
    return NAM10_ROLE_DESCRIPTIONS_FA.get(role, "")
