"""اعلام بازیکنان دفاعیه — فقط سناریوی ماسون."""

from __future__ import annotations

import html

from bot.bazpors_narrator import day_vote_defender_uids, day_vote_participation_count
from bot.models import Game
from bot.text_fa import fa_digits as _fa_digits


def _defense_candidate_display_name(uid: int, game: Game) -> str:
    p = game.players.get(uid)
    if p is None:
        return str(uid)
    return p.full_name or str(uid)


def build_mason_defense_candidates_announcement_html(game: Game) -> str:
    """متن اعلام بازیکنان انتخاب‌شده برای دفاعیه پس از تأیید کمک‌کننده."""
    uids = sorted(day_vote_defender_uids(game))
    lines = ["🗳️ بازیکنان انتخاب‌شده برای دفاعیه:", ""]
    row = 0
    for uid in uids:
        p = game.players.get(uid)
        if p is None:
            continue
        row += 1
        name = html.escape(_defense_candidate_display_name(uid, game))
        prev = day_vote_participation_count(game, uid)
        lines.append(
            f"{row}. {name} | سابقه رأی‌گیری: {_fa_digits(prev)} بار"
        )
    if row == 0:
        lines.append("<i>هیچ بازیکنی انتخاب نشده است.</i>")
    return "\n".join(lines)
