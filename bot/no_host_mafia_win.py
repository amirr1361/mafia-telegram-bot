"""پایان بازی با برد مافیا — مسیر بدون گرداننده."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.bazpors_narrator import (
    Role,
    _alive_faction_counts,
    _append_host_flush_note,
    _eliminate_player,
    _seat_fa,
    mafia_faction_wins,
    no_host_assistant_narrator_active,
    no_mafia_alive,
    trigger_win_gate_if_needed,
)
from bot.game import role_label_fa
from bot.models import Game

if TYPE_CHECKING:
    from bot.game import GameManager


def _win_picker_uid(game: Game) -> int:
    return game.bot_assistant_user_id or game.host_id


def _no_host_room_line(game: Game) -> str:
    code = html.escape(str(game.room_code))
    return f"🚪 <b>اتاق {code}</b>\n\n"


def build_no_host_mafia_win_announce_html(game: Game, gm: "GameManager") -> str:
    _, mafia_n, citizen_n = _alive_faction_counts(game, gm)
    if mafia_n == citizen_n:
        balance = (
            f"تعداد مافیا و شهروند <b>برابر شد</b> "
            f"({_seat_fa(mafia_n)} مافیا، {_seat_fa(citizen_n)} شهروند)."
        )
    else:
        balance = (
            f"تعداد مافیا ({_seat_fa(mafia_n)}) "
            f"<b>بیشتر از</b> شهروند ({_seat_fa(citizen_n)}) است."
        )
    return (
        _no_host_room_line(game)
        + "🏁 <b>پایان بازی — برد مافیا</b>\n\n"
        f"{balance}\n\n"
        "طبق قانون این سناریو، <b>تیم مافیا برنده است.</b>"
    )


def build_no_host_all_players_roles_roster_html(
    game: Game, gm: "GameManager"
) -> str:
    lines = [
        "📋 <b>فهرست بازیکنان و نقش‌ها</b>",
        "",
    ]
    players = sorted(
        (p for p in game.players.values() if p.role != Role.OBSERVER),
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    )
    if not players:
        lines.append("<i>بازیکنی ثبت نشده است.</i>")
        return "\n".join(lines)
    for p in players:
        tag = html.escape(gm.format_player_tag(p))
        role_txt = (
            html.escape(role_label_fa(p.role)) if p.role is not None else "؟"
        )
        seat = _seat_fa(p.seat) if p.seat is not None else "؟"
        status = "🟢 زنده" if p.is_alive else "💀 خارج‌شده"
        lines.append(f"• صندلی {seat} — {tag} — <b>{role_txt}</b> ({status})")
    return "\n".join(lines)


async def no_host_broadcast_mafia_win_and_finalize(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.post_game_flow import (
        broadcast_bazpors_game_end_to_players,
        finalize_game_winner,
    )

    await broadcast_bazpors_game_end_to_players(bot, game, "mafia")
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.mafia_win_broadcast",
            host_day=game.bazpors_narrator_host_day,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass
    await finalize_game_winner(bot, game, "mafia", _win_picker_uid(game))


async def no_host_broadcast_citizen_win_and_finalize(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.post_game_flow import (
        broadcast_bazpors_game_end_to_players,
        finalize_game_winner,
    )

    await broadcast_bazpors_game_end_to_players(bot, game, "citizen")
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.citizen_win_broadcast",
            host_day=game.bazpors_narrator_host_day,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass
    await finalize_game_winner(bot, game, "citizen", _win_picker_uid(game))


async def no_host_maybe_end_on_faction_win(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    elim_source: str | None = None,
    elim_uid: int | None = None,
) -> bool:
    """پس از حذف یا محاسبهٔ شب — اگر برد قطعی است، اعلام و پایان بازی."""
    if not no_host_assistant_narrator_active(game):
        return trigger_win_gate_if_needed(
            game, gm, elim_source=elim_source, elim_uid=elim_uid
        )

    from bot.no_host_night_ready import defer_no_host_faction_win_until_night_complete

    if defer_no_host_faction_win_until_night_complete(game):
        return False

    if no_mafia_alive(game, gm):
        await no_host_broadcast_citizen_win_and_finalize(bot, game, gm)
        return True

    if not mafia_faction_wins(game, gm):
        return False

    await no_host_broadcast_mafia_win_and_finalize(bot, game, gm)
    return True


async def no_host_eliminate_and_maybe_end_game(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    uid: int,
    *,
    elim_source: str | None = None,
) -> bool:
    """حذف بازیکن؛ در no_host در صورت برد مافیا/شهروند بازی تمام می‌شود."""
    note = _eliminate_player(game, gm, uid)
    if note:
        _append_host_flush_note(game, note)
    return await no_host_maybe_end_on_faction_win(
        bot, game, gm, elim_source=elim_source, elim_uid=uid
    )
