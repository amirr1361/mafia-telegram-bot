"""Russian-Mafia-only immutable mid-game elimination reports."""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.game import is_mafia_team, is_synthetic_player_uid
from bot.models import Game, Phase, Role
from bot.russian_mafia import (
    ROLE_GODFATHER,
    ROLE_SIMPLE_MAFIA,
    ROLE_TERROR,
    is_russian_mafia_game,
    russian_mafia_observer_registered,
)
from bot.tg_send import safe_callback_answer, safe_send_message

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

RUSSIAN_MAFIA_ELIM_REPORT_INVITE_HTML = (
    "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
    "روی دکمه «گزارش بازی» بزنید."
)
RUSSIAN_MAFIA_ELIM_REPORT_BUTTON_TEXT = "📋 گزارش بازی"
_TG_HTML_SAFE_LIMIT = 3500

router = Router(name="russian_mafia_elim_report")


class RussianMafiaElimReportCb(CallbackData, prefix="rmrep"):
    code: str
    as_uid: int
    gts: int


def _game_created_ts(game: Game) -> int:
    created = game.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return int(created.timestamp())


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fa(value: int) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def split_html_message_chunks(
    text: str, *, limit: int = _TG_HTML_SAFE_LIMIT
) -> list[str]:
    body = (text or "").strip()
    if not body:
        return []
    if len(body) <= limit:
        return [body]
    chunks: list[str] = []
    remaining = body
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 3:
            cut = window.rfind("\n")
        if cut < limit // 3:
            cut = window.rfind(" ")
        if cut < limit // 3:
            cut = limit
        piece = remaining[:cut].rstrip()
        if not piece:
            piece = remaining[:limit]
            cut = len(piece)
        chunks.append(piece)
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def _role_label(role: Role | None) -> str:
    return {
        ROLE_GODFATHER: "گادفادر",
        ROLE_TERROR: "ترور",
        ROLE_SIMPLE_MAFIA: "مافیای ساده",
        Role.DOCTOR: "پزشک",
        Role.DETECTIVE: "کارآگاه",
        Role.CITIZEN: "شهروند ساده",
    }.get(role, "نامشخص")


def _roster_lines(game: Game, gm: "GameManager") -> list[str]:
    players = sorted(
        (p for p in game.players.values() if p.role != Role.OBSERVER),
        key=lambda p: (p.seat is None, p.seat or 0, p.user_id),
    )
    mafia = [p for p in players if is_mafia_team(p.role)]
    town = [p for p in players if not is_mafia_team(p.role)]
    lines: list[str] = []
    for marker, group in (("🔴", mafia), ("🟢", town)):
        for idx, player in enumerate(group, start=1):
            seat = player.seat if player.seat is not None else idx
            name = html.escape(gm.format_player_tag(player))
            lines.append(
                f"{marker} <b>{_fa(int(seat))}</b>- {name} — "
                f"{html.escape(_role_label(player.role))}"
            )
    return lines


def _audit_records(game: Game) -> list[dict[str, object]]:
    if not game.audit_log_path:
        return []
    try:
        lines = Path(game.audit_log_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, object]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _timeline_html(game: Game, gm: "GameManager") -> str:
    records = _audit_records(game)

    def name(uid: object) -> str:
        try:
            player = game.players.get(int(uid))
        except (TypeError, ValueError):
            player = None
        if player is None:
            return "بازیکن نامشخص"
        return html.escape(gm.format_player_tag(player))

    days: dict[int, list[str]] = {}
    nights: dict[int, list[str]] = {}

    def day(no: int, line: str) -> None:
        bucket = days.setdefault(max(1, no), [])
        if line not in bucket:
            bucket.append(line)

    def night(no: int, line: str) -> None:
        bucket = nights.setdefault(max(1, no), [])
        if line not in bucket:
            bucket.append(line)

    for rec in records:
        event = str(rec.get("event") or "")
        russian = rec.get("russian")
        data = russian if isinstance(russian, dict) else {}
        try:
            day_no = int(data.get("day") or rec.get("day") or 1)
        except (TypeError, ValueError):
            day_no = 1
        try:
            night_no = int(data.get("night") or rec.get("night") or 1)
        except (TypeError, ValueError):
            night_no = 1

        if event == "russian.action_confirmed":
            slot = str(rec.get("slot") or "")
            target_uid = rec.get("target_uid")
            if slot == "mafia":
                night(night_no, f"🔴 شات مافیا: {name(target_uid)}")
            elif slot == "doctor":
                night(night_no, f"💉 نجات پزشک: {name(target_uid)}")
            elif slot == "detective":
                alignment = str(rec.get("alignment") or "")
                suffix = ""
                if alignment:
                    suffix = " — " + ("مثبت" if alignment == "positive" else "منفی")
                night(
                    night_no,
                    f"🔎 استعلام کارآگاه: {name(target_uid)}{suffix}",
                )
            continue

        if event == "player.eliminated":
            source = str(rec.get("source") or "")
            uid = rec.get("uid")
            if source == "night_shot":
                night(night_no, f"💀 خروج با شات شب: {name(uid)}")
            elif source == "discipline":
                night(night_no, f"⚖️ اخراج انضباطی: {name(uid)}")
            elif source == "terror":
                day(day_no, f"💥 خروج با اقدام ترور: {name(uid)}")
            else:
                day(day_no, f"🗳️ خروج روز: {name(uid)}")
            continue

        if event == "russian.night_resolved":
            dead_uid = rec.get("eliminated_uid")
            if dead_uid is None:
                night(night_no, "نتیجه نهایی شب: با کسی خداحافظی نکردیم.")
            else:
                night(
                    night_no,
                    f"نتیجه نهایی شب: با {name(dead_uid)} خداحافظی کردیم.",
                )
            continue

        if event == "russian.terror_resolved":
            casualties = rec.get("casualty_uids")
            if isinstance(casualties, list):
                labels = " و ".join(name(uid) for uid in casualties)
                day(day_no, f"نتیجه اقدام ترور: {labels} از بازی خارج شدند.")

    if not days and not nights:
        return ""
    blocks: list[str] = ["🧭 <b>اتفاقات در طول بازی</b>"]
    max_index = max([*days.keys(), *nights.keys()], default=1)
    for index in range(1, max_index + 1):
        if index in days:
            blocks.extend(
                ["", f"☀️ <b>روز {_fa(index)}</b>", *days[index]]
            )
        if index in nights:
            blocks.extend(
                ["", f"🌙 <b>شب {_fa(index)}</b>", *nights[index]]
            )
    return "\n".join(blocks)


def build_russian_mafia_elim_cutoff_report_html(
    game: Game, gm: "GameManager"
) -> str:
    from bot.main import build_game_final_report_header_html

    parts = [
        build_game_final_report_header_html(
            game.room_code, "russian_mafia", game.max_players
        ),
        "",
        "────────────",
        "",
        "📋 <b>بازیکنان و نقش‌ها</b>",
        *_roster_lines(game, gm),
    ]
    timeline = _timeline_html(game, gm)
    if timeline:
        parts.extend(["", "────────────", "", timeline])
    return "\n".join(parts)


def capture_russian_mafia_elim_report_cutoff(
    game: Game, gm: "GameManager", uid: int
) -> dict[str, Any] | None:
    if not is_russian_mafia_game(game) or not game.roles_dealt:
        return None
    if game.phase == Phase.LOBBY:
        return None
    player = game.players.get(uid)
    if player is None or player.role == Role.OBSERVER or player.is_alive:
        return None
    existing = game.russian_mafia_elim_report_cutoffs.get(uid)
    if isinstance(existing, dict) and existing.get("report_html"):
        return existing
    entry: dict[str, Any] = {
        "uid": uid,
        "room_code": game.room_code,
        "game_created_ts": _game_created_ts(game),
        "elim_ts": _utc_iso_now(),
        "elim_event_seq": len(_audit_records(game)),
        "report_html": build_russian_mafia_elim_cutoff_report_html(game, gm),
        "invite_sent": False,
    }
    game.russian_mafia_elim_report_cutoffs[uid] = entry
    try:
        if game.phase != Phase.ENDED:
            from bot.game_snapshot import persist_game_snapshot

            persist_game_snapshot(game, reason="russian_elim_report_cutoff")
    except Exception:
        logger.exception(
            "Russian Mafia cutoff persistence failed room=%s uid=%s",
            game.room_code,
            uid,
        )
    return entry


def russian_mafia_elim_report_keyboard(
    game: Game, as_uid: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=RUSSIAN_MAFIA_ELIM_REPORT_BUTTON_TEXT,
                    callback_data=RussianMafiaElimReportCb(
                        code=game.room_code,
                        as_uid=as_uid,
                        gts=_game_created_ts(game),
                    ).pack(),
                )
            ]
        ]
    )


async def send_russian_mafia_elim_report_invitation(
    bot: Bot, game: Game, gm: "GameManager", uid: int
) -> bool:
    from bot.observer_delivery import observer_player_copy_prefix

    entry = capture_russian_mafia_elim_report_cutoff(game, gm, uid)
    if entry is None or entry.get("invite_sent"):
        return False
    text = RUSSIAN_MAFIA_ELIM_REPORT_INVITE_HTML
    kb = russian_mafia_elim_report_keyboard(game, uid)
    sent_any = False
    if not is_synthetic_player_uid(uid):
        sent_any = bool(
            await safe_send_message(
                bot, uid, text, parse_mode="HTML", reply_markup=kb
            )
        )
    if russian_mafia_observer_registered(game):
        observer = game.observer_user_id
        if observer is not None and observer != uid:
            sent_any = bool(
                await safe_send_message(
                    bot,
                    observer,
                    observer_player_copy_prefix(game, uid) + text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            ) or sent_any
    entry["invite_sent"] = True
    try:
        if game.phase != Phase.ENDED:
            from bot.game_snapshot import persist_game_snapshot

            persist_game_snapshot(game, reason="russian_elim_report_invited")
    except Exception:
        logger.exception(
            "Russian Mafia invitation persistence failed room=%s uid=%s",
            game.room_code,
            uid,
        )
    return sent_any


async def maybe_send_russian_mafia_elim_report_invite(
    bot: Bot, game: Game, uid: int
) -> None:
    if not is_russian_mafia_game(game):
        return
    try:
        from bot.app_state import manager

        await send_russian_mafia_elim_report_invitation(
            bot, game, manager, uid
        )
    except Exception:
        logger.exception(
            "Russian Mafia elim report invitation failed room=%s uid=%s",
            game.room_code,
            uid,
        )


def resolve_russian_mafia_elim_report_html(
    game: Game, as_uid: int, *, gts: int
) -> str | None:
    if not is_russian_mafia_game(game) or _game_created_ts(game) != int(gts):
        return None
    entry = game.russian_mafia_elim_report_cutoffs.get(as_uid)
    if not isinstance(entry, dict):
        return None
    if int(entry.get("game_created_ts") or 0) != int(gts):
        return None
    body = entry.get("report_html")
    return body if isinstance(body, str) and body.strip() else None


async def deliver_russian_mafia_elim_report_chunks(
    bot: Bot, chat_id: int, report_html: str
) -> bool:
    ok = False
    for chunk in split_html_message_chunks(report_html):
        ok = bool(
            await safe_send_message(bot, chat_id, chunk, parse_mode="HTML")
        ) or ok
    return ok


async def handle_russian_mafia_elim_report_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    *,
    as_uid: int,
    gts: int,
) -> None:
    actor = callback.from_user.id if callback.from_user else None
    if actor is None:
        await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return
    player = game.players.get(as_uid)
    if player is None or player.role == Role.OBSERVER:
        await safe_callback_answer(
            callback, "گزارش این بازیکن در دسترس نیست.", show_alert=True
        )
        return
    if player.is_alive:
        await safe_callback_answer(
            callback, "این گزارش فقط برای بازیکن حذف‌شده است.", show_alert=True
        )
        return
    observer_authorized = (
        russian_mafia_observer_registered(game)
        and actor == game.observer_user_id
    )
    if actor != as_uid and not observer_authorized:
        await safe_callback_answer(
            callback, "اجازهٔ مشاهدهٔ این گزارش را ندارید.", show_alert=True
        )
        return
    report = resolve_russian_mafia_elim_report_html(game, as_uid, gts=gts)
    if report is None:
        await safe_callback_answer(
            callback,
            "گزارش این دست دیگر در دسترس نیست (اتاق عوض یا پاک شده).",
            show_alert=True,
        )
        return
    await safe_callback_answer(callback)
    await deliver_russian_mafia_elim_report_chunks(bot, actor, report)


@router.callback_query(RussianMafiaElimReportCb.filter())
async def cb_russian_mafia_elim_report(
    callback: CallbackQuery,
    bot: Bot,
    callback_data: RussianMafiaElimReportCb,
) -> None:
    from bot.app_state import manager

    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if game is None or not is_russian_mafia_game(game):
        await safe_callback_answer(
            callback, "اتاق دیگر فعال نیست.", show_alert=True
        )
        return
    await handle_russian_mafia_elim_report_callback(
        callback,
        bot,
        game,
        as_uid=int(callback_data.as_uid),
        gts=int(callback_data.gts),
    )


def register_russian_mafia_elim_report_handlers(dp: Any) -> None:
    dp.include_router(router)
