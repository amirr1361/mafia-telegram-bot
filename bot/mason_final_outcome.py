"""نتیجهٔ نهایی روز/شب در تاریخچهٔ پایان بازی — فقط ماسون."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any, Callable

from bot.models import Game, Role
from bot.room_mode import is_mason_scenario
from bot.text_fa import fa_digits

if TYPE_CHECKING:
    from bot.game import GameManager

MasonOutcomeEntry = dict[str, Any]


def _join_farewell_names(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} و {names[1]}"
    return "، ".join(names[:-1]) + f" و {names[-1]}"


def compute_mason_final_night_elim_uids(
    game: Game,
) -> tuple[list[int], list[int]]:
    """uidهای حذف‌شدهٔ قطعی روز قبل و شب جاری — همان منبع نتیجهٔ عمومی."""
    from bot.bazpors_narrator import (
        _discipline_kick_uids,
        _night_report_day_farewell_uids,
    )

    alive_before = game.bazpors_alive_at_night_start
    if not alive_before:
        alive_before = {uid: p.is_alive for uid, p in game.players.items()}

    day_died = [
        uid
        for uid in _night_report_day_farewell_uids(game, alive_before)
        if uid in game.players and game.players[uid].role != Role.OBSERVER
    ]
    discipline_uids = set(_discipline_kick_uids(game))
    night_died = [
        uid
        for uid, p in game.players.items()
        if p.role != Role.OBSERVER
        and alive_before.get(uid, True)
        and not p.is_alive
        and uid not in discipline_uids
    ]
    return day_died, night_died


def find_mason_final_night_outcome(
    game: Game, night: int
) -> MasonOutcomeEntry | None:
    for entry in game.mason_final_night_outcomes:
        if int(entry.get("night") or 0) == night and entry.get("finalized"):
            return entry
    return None


def record_mason_final_night_outcome(
    game: Game, gm: "GameManager | None" = None
) -> MasonOutcomeEntry | None:
    """ثبت یک‌بارهٔ نتیجهٔ نهایی شب حل‌شده — idempotent."""
    del gm  # reserved for future name helpers; uids only
    if not is_mason_scenario(game):
        return None
    if not game.mason_night_resolution_applied:
        return None
    night = max(1, int(game.bazpors_narrator_night_count or 1))
    existing = find_mason_final_night_outcome(game, night)
    if existing is not None:
        return existing
    day_uids, night_uids = compute_mason_final_night_elim_uids(game)
    # روز متناظر با شب N همان N است (روز N → شب N).
    day = night
    entry: MasonOutcomeEntry = {
        "night": night,
        "day": day,
        "day_elim_uids": list(day_uids),
        "night_elim_uids": list(night_uids),
        "finalized": True,
    }
    game.mason_final_night_outcomes.append(entry)
    return entry


def format_mason_history_outcome_lines(
    entry: MasonOutcomeEntry,
    tag_for_uid: Callable[[int], str],
) -> list[str]:
    """خطوط تاریخچهٔ پایان بازی — با شمارهٔ روز/شب."""
    if not entry.get("finalized"):
        return []
    try:
        day = int(entry.get("day") or entry.get("night") or 0)
        night = int(entry.get("night") or 0)
    except (TypeError, ValueError):
        return []
    if night <= 0:
        return []
    if day <= 0:
        day = night
    day_fa = fa_digits(day)
    night_fa = fa_digits(night)

    day_uids = entry.get("day_elim_uids") or []
    night_uids = entry.get("night_elim_uids") or []
    if not isinstance(day_uids, list):
        day_uids = []
    if not isinstance(night_uids, list):
        night_uids = []

    day_names = _join_farewell_names(
        [tag_for_uid(int(u)) for u in day_uids]
    )
    night_names = _join_farewell_names(
        [tag_for_uid(int(u)) for u in night_uids]
    )

    if day_names:
        day_line = f"در روز {day_fa} با {day_names} خداحافظی کردیم."
    else:
        day_line = f"در روز {day_fa} با کسی خداحافظی نکردیم."

    if night_names:
        night_line = f"در شب {night_fa}، با {night_names} خداحافظی کردیم."
    else:
        night_line = f"در شب {night_fa}، با کسی خداحافظی نکردیم."

    return [
        f"<b>نتیجه نهایی شب و روز {day_fa}:</b>",
        "",
        day_line,
        "",
        night_line,
    ]


def format_mason_history_outcome_lines_for_game(
    game: Game, gm: "GameManager", entry: MasonOutcomeEntry
) -> list[str]:
    def tag_for_uid(uid: int) -> str:
        p = game.players.get(uid)
        if p is None:
            return html.escape(str(uid))
        return html.escape(gm.format_player_tag(p))

    return format_mason_history_outcome_lines(entry, tag_for_uid)


def append_mason_outcome_to_timeline_lines(
    lines: list[str],
    entry: MasonOutcomeEntry | None,
    tag_for_uid: Callable[[int], str],
) -> list[str]:
    """افزودن بلوک نتیجه به انتهای خطوط اقدامات شب — بدون تکرار."""
    if entry is None:
        return lines
    outcome = format_mason_history_outcome_lines(entry, tag_for_uid)
    if not outcome:
        return lines
    marker = outcome[0]
    if any(marker in (x or "") for x in lines):
        return lines
    out = list(lines)
    if out and out[-1].strip():
        out.append("")
    out.extend(outcome)
    return out
