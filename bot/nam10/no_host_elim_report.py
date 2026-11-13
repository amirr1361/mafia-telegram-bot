"""Bazpors-only: mid-game elimination report invitation + immutable cutoff."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.nam10.engine import is_synthetic_player_uid
from bot.models import Game, Phase, Role
from bot.tg_send import safe_callback_answer, safe_send_message

if TYPE_CHECKING:
    from bot.nam10.engine import GameManager

logger = logging.getLogger(__name__)

NAM10_ELIM_REPORT_INVITE_HTML = (
    "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
    "روی دکمه «گزارش بازی» بزنید."
)
NAM10_ELIM_REPORT_BUTTON_TEXT = "📋 گزارش بازی"

_TG_HTML_SAFE_LIMIT = 3500

router = Router(name="nmnd_elim_report")


class BazporsElimReportCb(CallbackData, prefix="bzrep"):
    """دکمهٔ گزارش حذف راهنما — as_uid بازیکن حذف‌شده."""

    code: str
    as_uid: int
    gts: int


def is_fork_elim_report_scenario(game: Game) -> bool:
    """راهنما و اتاق تست شبکهٔ سلامت — نه مذاکره/ماسون/روسی."""
    return game.scenario_name in ("namayande", "nmnd_salamat_test")


def _game_created_ts(game: Game) -> int:
    created = game.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return int(created.timestamp())


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_html_message_chunks(text: str, *, limit: int = _TG_HTML_SAFE_LIMIT) -> list[str]:
    """تقسیم پیام HTML بلند — ترجیح مرز پاراگراف/خط."""
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


def _nam10_unlogged_night_resolved_records(
    game: Game, gm: "GameManager"
) -> list[dict[str, Any]]:
    """Pseudo ``night.resolved`` records for resolved-but-unlogged nights.

    Night v2 resolution commits internally (definitions committed) while
    the publication flow (discipline ask, summary broadcast) is still
    finishing; ``log_night_resolved`` runs only at the end. An
    elimination report captured inside that window would otherwise show
    no night timeline at all. This rebuilds the exact same full report
    the resolver is about to log — no future, no invented content.
    """
    from bot.nam10.night2 import nam10_night2_mode

    if not nam10_night2_mode(game):
        return []
    nc = max(1, int(game.nmnd_narrator_night_count or 1))
    if not (
        game.nmnd_night2_resolved
        and int(game.nmnd_night2_resolved_night or 0) == nc
    ):
        return []
    existing: list[dict[str, Any]] = []
    import json as _json
    from pathlib import Path

    try:
        raw_path = str(getattr(game, "audit_log_path", "") or "")
        if raw_path.strip():
            for line in Path(raw_path).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    existing.append(rec)
    except Exception:
        existing = []
    for rec in existing:
        if str(rec.get("event") or "") != "night.resolved":
            continue
        bz = rec.get("bazpors")
        if isinstance(bz, dict) and int(bz.get("night_count") or 0) == nc:
            return []  # already logged — timeline will include it
    from bot.nam10.nmnd_narrator import _compose_full_night_report
    from bot.nam10.night2_publish import night2_night_report_extra_section

    alive_before = game.nmnd_alive_at_night_start or {
        uid: p.is_alive for uid, p in game.players.items()
    }
    full = _compose_full_night_report(game, gm, alive_before)
    extra = night2_night_report_extra_section(game, gm)
    if extra:
        full = full + "\n" + extra
    return [
        {
            "event": "night.resolved",
            "bazpors": {"night_count": nc},
            "night_report_html": full,
        }
    ]


def build_nam10_elim_cutoff_report_html(game: Game, gm: "GameManager") -> str:
    """گزارش جزئی راهنما تا لحظهٔ حذف — بدون برنده."""
    from bot.main import (
        _build_bazpors_timeline_html,
        _build_session_recap_roster_lines,
        build_game_final_report_header_html,
    )
    from bot.post_game_flow import build_post_session_recap_snapshot

    snap = build_post_session_recap_snapshot(game, "citizen")
    rows_raw = snap.get("rows")
    rows: list[dict[str, object]] = rows_raw if isinstance(rows_raw, list) else []
    scenario_name = str(game.scenario_name or "namayande")
    roster_block = "\n".join(
        _build_session_recap_roster_lines(
            rows, scenario_name=scenario_name, nam10=True
        )
    )
    pseudo_records = _nam10_unlogged_night_resolved_records(game, gm)
    if pseudo_records:
        pseudo_snap = dict(snap)
        pseudo_snap["_pseudo_records"] = pseudo_records
    else:
        pseudo_snap = snap
    timeline_html = _build_bazpors_timeline_html(pseudo_snap)
    parts: list[str] = [
        build_game_final_report_header_html(
            game.room_code, game.scenario_name, game.max_players
        ),
        "",
        "📋 <b>بازیکنان و نقش‌ها</b>",
        roster_block,
    ]
    if timeline_html:
        parts.extend(["", "────────────", "", timeline_html])
    del gm
    return "\n".join(parts)


def capture_nam10_elim_report_cutoff(
    game: Game, gm: "GameManager", uid: int
) -> dict[str, Any] | None:
    """ثبت یک‌بارهٔ گزارش قطعی در لحظهٔ حذف — idempotent."""
    if not is_fork_elim_report_scenario(game):
        return None
    if not game.roles_dealt:
        return None
    if game.phase == Phase.LOBBY:
        return None
    player = game.players.get(uid)
    if player is None or player.role == Role.OBSERVER:
        return None
    if player.is_alive:
        return None
    existing = game.nmnd_elim_report_cutoffs.get(uid)
    if isinstance(existing, dict) and existing.get("report_html"):
        return existing

    report_html = build_nam10_elim_cutoff_report_html(game, gm)
    entry: dict[str, Any] = {
        "uid": uid,
        "room_code": game.room_code,
        "game_created_ts": _game_created_ts(game),
        "elim_ts": _utc_iso_now(),
        "report_html": report_html,
        "invite_sent": False,
    }
    game.nmnd_elim_report_cutoffs[uid] = entry
    return entry


def nmnd_elim_report_keyboard(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=NAM10_ELIM_REPORT_BUTTON_TEXT,
                    callback_data=BazporsElimReportCb(
                        code=game.room_code,
                        as_uid=as_uid,
                        gts=_game_created_ts(game),
                    ).pack(),
                )
            ]
        ]
    )


async def send_nam10_elim_report_invitation(
    bot: Bot, game: Game, gm: "GameManager", uid: int
) -> bool:
    """ارسال دعوت گزارش پس از پیام حذف — بدون تکرار."""
    from bot.observer_delivery import (
    no_host_observer_registered as nam10_observer_registered,
    observer_player_copy_prefix,
)

    entry = capture_nam10_elim_report_cutoff(game, gm, uid)
    if entry is None:
        return False
    if entry.get("invite_sent"):
        return False

    text = NAM10_ELIM_REPORT_INVITE_HTML
    kb = nmnd_elim_report_keyboard(game, uid)
    synthetic = is_synthetic_player_uid(uid)
    sent_any = False
    direct_sent = False
    observer_sent = False

    if not synthetic:
        if await safe_send_message(
            bot, uid, text, parse_mode="HTML", reply_markup=kb
        ):
            sent_any = True
            direct_sent = True

    if nam10_observer_registered(game):
        obs = game.observer_user_id
        if obs is not None and obs != uid:
            body = observer_player_copy_prefix(game, uid) + text
            if await safe_send_message(
                bot, obs, body, parse_mode="HTML", reply_markup=kb
            ):
                sent_any = True
                observer_sent = True

    entry["invite_sent"] = True
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "nam10.elim_report_invite",
            uid=uid,
            synthetic=synthetic,
            direct_sent=direct_sent,
            observer_sent=observer_sent,
            sent_any=sent_any,
        )
    except Exception:
        pass
    return sent_any


async def maybe_send_nam10_elim_report_invite(
    bot: Bot, game: Game, uid: int
) -> None:
    """قلاب پس از پیام حذف — خطا نباید جریان بازی را بشکند."""
    if not is_fork_elim_report_scenario(game):
        return
    try:
        from bot.app_state import manager

        await send_nam10_elim_report_invitation(bot, game, manager, uid)
    except Exception:
        logger.exception(
            "bazpors elim report invite failed room=%s uid=%s",
            game.room_code,
            uid,
        )


def resolve_nam10_elim_report_html(
    game: Game, as_uid: int, *, gts: int
) -> str | None:
    if not is_fork_elim_report_scenario(game):
        return None
    if _game_created_ts(game) != int(gts):
        return None
    entry = game.nmnd_elim_report_cutoffs.get(as_uid)
    if not isinstance(entry, dict):
        return None
    if int(entry.get("game_created_ts") or 0) != int(gts):
        return None
    html_body = entry.get("report_html")
    if not isinstance(html_body, str) or not html_body.strip():
        return None
    return html_body


async def deliver_nam10_elim_report_chunks(
    bot: Bot, chat_id: int, report_html: str
) -> bool:
    chunks = split_html_message_chunks(report_html)
    if not chunks:
        return False
    ok = False
    for part in chunks:
        if await safe_send_message(bot, chat_id, part, parse_mode="HTML"):
            ok = True
    return ok


async def handle_nam10_elim_report_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    *,
    as_uid: int,
    gts: int,
) -> None:
    """خواندن گزارش حذف‌شده — بازیکن مرده یا ناظر؛ بدون تغییر وضعیت بازی."""
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

    obs = game.observer_user_id
    if actor != as_uid and actor != obs:
        await safe_callback_answer(
            callback, "اجازهٔ مشاهدهٔ این گزارش را ندارید.", show_alert=True
        )
        return

    report_html = resolve_nam10_elim_report_html(game, as_uid, gts=gts)
    if report_html is None:
        await safe_callback_answer(
            callback,
            "گزارش این دست دیگر در دسترس نیست (اتاق عوض یا پاک شده).",
            show_alert=True,
        )
        return

    # گزارش زنده: در هر درخواست، گزارش تجمعی از روی تاریخچهٔ قطعیِ
    # فعلی بازسازی می‌شود؛ اسنپ‌شاتِ ثبت‌شده فقط عقب‌نشینی ایمن است.
    from bot.app_state import manager as _live_manager

    try:
        _fresh_html = build_nam10_elim_cutoff_report_html(game, _live_manager)
    except Exception:
        logger.exception(
            "nam10 live report rebuild failed room=%s", game.room_code
        )
        _fresh_html = None
    if _fresh_html and _fresh_html.strip():
        report_html = _fresh_html
        _entry = game.nmnd_elim_report_cutoffs.get(as_uid)
        if isinstance(_entry, dict):
            _entry["report_html"] = _fresh_html

    await safe_callback_answer(callback)
    await deliver_nam10_elim_report_chunks(bot, actor, report_html)


@router.callback_query(BazporsElimReportCb.filter())
async def cb_nam10_elim_report(
    callback: CallbackQuery,
    bot: Bot,
    callback_data: BazporsElimReportCb,
) -> None:
    from bot.app_state import manager

    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if game is None or not is_fork_elim_report_scenario(game):
        await safe_callback_answer(
            callback, "اتاق دیگر فعال نیست.", show_alert=True
        )
        return
    await handle_nam10_elim_report_callback(
        callback,
        bot,
        game,
        as_uid=int(callback_data.as_uid),
        gts=int(callback_data.gts),
    )


def _unused_fork_register_nam10_elim_report_handlers(dp: Any) -> None:
    dp.include_router(router)
