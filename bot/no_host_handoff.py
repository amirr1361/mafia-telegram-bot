"""انتقال گردانندگی از no_host به semi_auto در نقاط مشخص فلو."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    BazporsNarrCb,
    Role,
    _enter_night_from_day_end,
    _mark_day_start_alive_snapshot,
    _sync_ki_as_today,
    clear_narrator_panel_ref,
    no_host_assistant_narrator_active,
    push_host_step,
)
from bot.tg_send import safe_send_message, safe_send_message_return
from bot.models import Game

if TYPE_CHECKING:
    from bot.game import GameManager

NO_HOST_HANDOFF_OFFER = "no_host_handoff_offer"

GATE_DAY1_AFTER_ELIM = "day1_after_elim"
GATE_AFTER_NIGHT_BEFORE_DAY = "after_night_before_day"


def handoff_available(game: Game) -> bool:
    return bool(
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "no_host"
        and no_host_assistant_narrator_active(game)
        and game.bot_assistant_user_id is not None
    )


def handoff_candidate_uids(game: Game) -> list[int]:
    """بازیکنان خارج‌شده (غیر ناظر) — نامزد دریافت پنل نیمه‌خودکار."""
    out: list[int] = []
    for uid, p in sorted(game.players.items(), key=lambda x: x[0]):
        if p.role == Role.OBSERVER or p.is_alive:
            continue
        out.append(uid)
    return out


def enter_handoff_offer(game: Game, gate: str) -> None:
    game.no_host_handoff_gate = gate
    game.bazpors_narrator_step = NO_HOST_HANDOFF_OFFER


async def deliver_no_host_handoff_offer_panels(
    bot: Bot,
    game: Game,
    gm: "GameManager",
) -> bool:
    """پنل انتقال — همیشه به کمک‌کننده و آینهٔ ناظر (مستقل از موفقیت اول)."""
    if game.bazpors_narrator_step != NO_HOST_HANDOFF_OFFER:
        return False
    text, kb = build_handoff_offer_panel(game, gm)
    from bot.bazpors_narrator import (
        dismiss_assistant_panel_message,
        dismiss_observer_narrator_mirror_message,
        _mirror_narrator_panel_to_observer,
        _remember_assistant_panel_ref,
    )

    await dismiss_assistant_panel_message(bot, game)
    await dismiss_observer_narrator_mirror_message(bot, game)

    assistant_ok = False
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is not None:
        sent = await safe_send_message_return(
            bot,
            assistant_uid,
            text,
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True,
        )
        if sent is not None:
            _remember_assistant_panel_ref(game, sent.chat.id, sent.message_id)
            assistant_ok = True

    await _mirror_narrator_panel_to_observer(bot, game, text, kb)
    return assistant_ok


def build_handoff_offer_panel(
    game: Game, gm: "GameManager"
) -> tuple[str, InlineKeyboardMarkup | None]:
    gate = game.no_host_handoff_gate or ""
    if gate == GATE_DAY1_AFTER_ELIM:
        ctx = (
            "پایان <b>روز اول</b> — قبل از <b>شب اول</b>، می‌توانید گردانندگی "
            "نیمه‌خودکار را به یکی از بازیکنانی که در رأی روز از بازی خارج شده‌اند "
            "منتقل کنید."
        )
    else:
        ctx = (
            "پایان <b>فاز شب</b> — قبل از <b>شروع روز بعد</b>، می‌توانید گردانندگی "
            "نیمه‌خودکار را به یکی از بازیکنان خارج‌شده منتقل کنید."
        )

    candidates = handoff_candidate_uids(game)
    lines = [
        "🔄 <b>انتقال گردانندگی (خودکار مستقل)</b>",
        "",
        ctx,
        "",
        "اگر انتقال دهید، از این نقطه به بعد همان بازیکن پنل گردانندگی خودکار مستقل "
        "را می‌گیرد و ربات مرحله‌به‌مرحله شب/روز را با او پیش می‌برد.",
        "",
        "<b>نامزدهای انتقال (خارج‌شده):</b>",
    ]
    if not candidates:
        lines.append("<i>کسی در فهرست خارج‌شده‌ها نیست — فقط ادامه با کمک‌کننده ربات.</i>")
    else:
        for uid in candidates:
            p = game.players[uid]
            tag = html.escape(gm.format_player_tag(p))
            lines.append(tag)

    rows: list[list[InlineKeyboardButton]] = []
    code = game.room_code
    for uid in candidates:
        p = game.players[uid]
        label = gm.format_player_tag(p)
        if len(label) > 42:
            label = label[:40] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🎙 {label}",
                    callback_data=BazporsNarrCb(
                        code=code, act="handoff_pick", tid=uid
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="ادامه با کمک‌کننده ربات (بدون انتقال)",
                callback_data=BazporsNarrCb(
                    code=code, act="handoff_skip", tid=0
                ).pack(),
            )
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def apply_handoff_to_semi_auto(game: Game, new_host_uid: int) -> None:
    from bot.bazpors_semi_auto_state import sync_bazpors_semi_auto_after_handoff

    game.bazpors_host_mode = "semi_auto"
    sync_bazpors_semi_auto_after_handoff(game)
    game.host_id = new_host_uid
    game.no_host_assistant_narrator_active = False
    game.no_host_observer_only_narrator_mirror = False
    game.no_host_night_parallel_collect_active = False
    clear_narrator_panel_ref(game)
    from bot.no_host_phase import reset_no_host_per_night_role_state

    reset_no_host_per_night_role_state(game)


def _semi_auto_start_day_after_night(game: Game, gm: "GameManager") -> None:
    from bot.bazpors_narrator import DAY_DISCUSS

    game.bazpors_narrator_host_day += 1
    _mark_day_start_alive_snapshot(game)
    game.bazpors_interrog_ready_for_day = False
    game.bazpors_interrog_cancel_next_day = False
    game.bazpors_narrator_step = DAY_DISCUSS
    _sync_ki_as_today(game, gm)


async def _resume_no_host_path_after_skip(
    bot: Bot, game: Game, gm: "GameManager", gate: str
) -> None:
    if gate == GATE_DAY1_AFTER_ELIM:
        from bot.bazpors_narrator import (
            no_host_day1_defense_no_votes_enter_night,
        )
        from bot.no_host_night1 import on_no_host_entered_night1

        no_host_day1_defense_no_votes_enter_night(game)
        await on_no_host_entered_night1(bot, game, gm)
        return

    from bot.no_host_table_inquiry import no_host_finish_day_start_after_table_inquiry

    game.no_host_table_inquiry_resolved_for_day = False
    await no_host_finish_day_start_after_table_inquiry(bot, game, gm)


async def _notify_semi_auto_host_after_handoff(
    bot: Bot, game: Game, new_host_uid: int
) -> None:
    p = game.players.get(new_host_uid)
    name = html.escape(p.full_name) if p else "گرداننده"
    await safe_send_message(
        bot,
        new_host_uid,
        (
            f"🎙 <b>گردانندگی خودکار مستقل به {name} منتقل شد.</b>\n\n"
            "پنل گردانندگی در پیام بعدی برای ادامهٔ بازی ارسال می‌شود؛ "
            "حتی اگر در رأی روز از بازی خارج شده‌اید، می‌توانید مرحله‌به‌مرحله "
            "شب/روز را با دکمه‌های همان پنل پیش ببرید."
        ),
        parse_mode="HTML",
    )


async def _resume_semi_auto_after_pick(
    bot: Bot, game: Game, gm: "GameManager", gate: str
) -> None:
    new_host_uid = game.host_id
    await _notify_semi_auto_host_after_handoff(bot, game, new_host_uid)
    if gate == GATE_DAY1_AFTER_ELIM:
        if game.bazpors_alive_at_day_start is None:
            game.bazpors_alive_at_day_start = {
                uid: True for uid in game.players
            }
        if game.bazpors_narrator_host_day < 1:
            game.bazpors_narrator_host_day = 1
        _enter_night_from_day_end(game)
        await push_host_step(bot, game, gm, force_new_host_message=True)
        return

    _semi_auto_start_day_after_night(game, gm)
    await push_host_step(bot, game, gm, force_new_host_message=True)


def maybe_offer_no_host_handoff(
    game: Game,
    *,
    gate: str,
) -> bool:
    """اگر واجد شرایط است مرحلهٔ پیشنهاد انتقال را فعال کن. True = پیشنهاد شد."""
    if not handoff_available(game):
        return False
    if not handoff_candidate_uids(game):
        return False
    enter_handoff_offer(game, gate)
    return True


def offer_handoff_after_night_before_day(game: Game) -> bool:
    """آماده‌سازی مرحلهٔ پیشنهاد انتقال (بدون ارسال پیام)."""
    return maybe_offer_no_host_handoff(game, gate=GATE_AFTER_NIGHT_BEFORE_DAY)


async def maybe_prompt_handoff_before_day_start(
    bot: Bot, game: Game, gm: "GameManager"
) -> bool:
    """پس از استعلام میز و بازپرسی — یک پیام جدید انتهای چت کمک‌کننده، سپس روز."""
    if not offer_handoff_after_night_before_day(game):
        return False
    await deliver_no_host_handoff_offer_panels(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.handoff_offered",
            gate=GATE_AFTER_NIGHT_BEFORE_DAY,
            assistant_uid=game.bot_assistant_user_id,
        )
    except Exception:
        pass
    return True


def offer_handoff_day1_after_elim(game: Game) -> bool:
    """پس از خروج رأی روز اول — قبل از شب اول."""
    return maybe_offer_no_host_handoff(game, gate=GATE_DAY1_AFTER_ELIM)


def process_handoff_narrator_cb(
    game: Game, gm: "GameManager", act: str, tid: int
) -> str | None:
    if game.bazpors_narrator_step != NO_HOST_HANDOFF_OFFER:
        return "نامعتبر."
    if act == "handoff_skip":
        if tid != 0:
            return "نامعتبر."
        return None
    if act == "handoff_pick":
        if tid not in game.players:
            return "نامعتبر."
        p = game.players[tid]
        if p.is_alive or p.role == Role.OBSERVER:
            return "فقط بازیکن خارج‌شده قابل انتخاب است."
        return None
    return "نامعتبر."


async def apply_handoff_narrator_async(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    act: str,
    tid: int,
) -> None:
    gate = game.no_host_handoff_gate
    if not gate:
        return

    if act == "handoff_skip":
        game.no_host_handoff_gate = None
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.handoff_declined",
                gate=gate,
                assistant_uid=game.bot_assistant_user_id,
            )
        except Exception:
            pass
        await _resume_no_host_path_after_skip(bot, game, gm, gate)
        return

    if act == "handoff_pick":
        new_host_uid = tid
        old_mode = "no_host"
        apply_handoff_to_semi_auto(game, new_host_uid)
        game.no_host_handoff_gate = None
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.handoff_accepted",
                gate=gate,
                from_mode=old_mode,
                to_mode="semi_auto",
                new_host_uid=new_host_uid,
                new_host_name=game.players[new_host_uid].full_name,
                assistant_uid=game.bot_assistant_user_id,
            )
        except Exception:
            pass
        await _resume_semi_auto_after_pick(bot, game, gm, gate)

