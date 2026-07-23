"""جلسه بازپرسی روز — مسیر گردانندگی بدون گرداننده."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    BazporsNarrCb,
    Role,
    _clear_interrog_day_targets,
    _interrog_day_vote_pool,
    _mark_interrog_session_done,
    _seat_fa,
    hunter_chain_confirm_alert_text,
    hunter_vote_elim_names_html_block,
    no_host_assistant_narrator_active,
    push_host_step,
)
from bot.no_host_mafia_win import no_host_eliminate_and_maybe_end_game, no_host_maybe_end_on_faction_win
from bot.game import is_mafia_team, is_synthetic_player_uid
from bot.models import Game
from bot.roles.registry import find_alive_role_holder
from bot.observer_delivery import (
    PlayerMirrorCb,
    broadcast_to_alive_players,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)

if TYPE_CHECKING:
    from bot.game import GameManager

NO_HOST_INTERROG_DAY = "no_host_interrog_day"

INTERROG_DAY_FLOW_ACTS = frozenset(
    {
        "ih_req",
        "ih_req_back",
        "ih_req_ok",
        "ih_vtie",
        "ih_velim",
        "ih_vback",
        "ih_vok",
    }
)

IH_PHASE_ASSIST = "assist"
IH_PHASE_ASSIST_CONFIRM = "assist_confirm"
IH_PHASE_SESSION = "session"
IH_PHASE_VOTE = "vote"
IH_PHASE_VOTE_CONFIRM = "vote_confirm"


def _assistant_tag(game: Game, gm: "GameManager") -> str:
    uid = game.bot_assistant_user_id
    if uid is not None and uid in game.players:
        return gm.format_player_tag(game.players[uid])
    return "کمک‌کننده ربات"


def _interrogator_uid(game: Game) -> int | None:
    intr = find_alive_role_holder(game, Role.INTERROGATOR)
    return intr.user_id if intr else None


def _interrogator_alive(game: Game) -> bool:
    return _interrogator_uid(game) is not None


def _alive_uids_excluding(game: Game, exclude: int | None) -> list[int]:
    out: list[int] = []
    for uid, p in game.players.items():
        if p.is_alive and uid != exclude:
            out.append(uid)
    return sorted(out)


def _player_seat_name(game: Game, gm: "GameManager", uid: int) -> str:
    p = game.players.get(uid)
    if p is None:
        return "؟"
    seat = _seat_fa(p.seat) if p.seat is not None else "؟"
    name = html.escape(gm.format_player_tag(p))
    return f"صندلی {seat} — {name}"


def build_interrog_wait_player_html() -> str:
    """یکسان برای همهٔ زنده‌ها — بازپرس زنده یا مرده."""
    return (
        "⚖️ بازپرس در حال تصمیم‌گیری است.\n\n"
        "برای ادامه روی دکمه «✅ اوکی» بزنید."
    )


def build_interrog_interrogator_html() -> str:
    return (
        "⚖️ ════『 نقش: بازپرس 』════ ⚖️\n\n"
        "🎭 نقش شما بازپرس است.\n\n"
        "آیا تمایل دارید\n"
        "📌 جلسه بازپرسی ادامه پیدا کند و رأی‌گیری انجام شود\n"
        "یا\n"
        "📌 جلسه بازپرسی را منحل می‌کنید؟"
    )


def build_interrog_continue_broadcast_html() -> str:
    """پس از اتمام اوکی‌ها — یکسان چه بازپرس زنده باشد چه نباشد."""
    return "⚖️ جلسه بازپرسی با اخذ آرا ادامه پیدا می‌کند."


def build_interrog_session_assistant_wait_html() -> str:
    """پنل کمک‌کننده در فاز انتظار — نه پیام طولانی «جلسه در جریان است»."""
    return (
        "⏳ منتظر تأیید «✅ اوکی» همهٔ بازیکنان زنده باشید.\n\n"
        "پس از آن پنل اعلام نتیجه رأی بازپرسی برای شما ارسال می‌شود."
    )


def build_interrog_wait_ack_html() -> str:
    return (
        "⚖️ بازپرس در حال تصمیم‌گیری است.\n\n"
        "✅ تأیید شما ثبت شد.\n\n"
        "منتظر سایر بازیکنان و تصمیم بازپرس بمانید."
    )


def _wait_ok_keyboard(game: Game, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ اوکی",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="ihok", as_uid=uid
                    ).pack(),
                )
            ]
        ]
    )


def _interrogator_keyboard(game: Game, intr_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔘 بازپرسی ادامه پیدا کند",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="ihco", as_uid=intr_uid
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔘 بازپرسی منحل شود",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="ihdi", as_uid=intr_uid
                    ).pack(),
                )
            ],
        ]
    )


def _wait_ui_key(game: Game, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_interrog_wait", uid)


def _interrogator_ui_key(game: Game, intr_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_interrog_intr", intr_uid)


def interrog_day_session_wait_locked(game: Game) -> bool:
    """پنل «منتظر اوکی» یک‌بار به کمک‌کننده رسیده — دوباره ارسال/آینه نشود."""
    return bool(
        game.bazpors_narrator_step == NO_HOST_INTERROG_DAY
        and game.no_host_interrog_day_phase == IH_PHASE_SESSION
        and game.no_host_interrog_day_assistant_wait_sent
    )


def reset_no_host_interrog_day_state(game: Game) -> None:
    from bot.bazpors_narrator import clear_observer_narrator_mirror_ref

    game.no_host_interrog_day_phase = None
    game.no_host_interrog_day_session_signature = None
    game.no_host_interrog_day_assistant_wait_sent = False
    clear_observer_narrator_mirror_ref(game)
    game.no_host_interrog_day_ok_uids = []
    game.no_host_interrog_day_decision = None
    game.no_host_interrog_day_pending_vote = None


def should_enter_no_host_interrog_day(game: Game) -> bool:
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        return False
    return bool(
        no_host_assistant_narrator_active(game)
        and game.bazpors_interrog_ready_for_day
        and not game.bazpors_interrog_cancel_next_day
    )


def enter_no_host_interrog_day_step(game: Game) -> None:
    game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
    game.no_host_interrog_day_ok_uids = []
    game.no_host_interrog_day_pending_vote = None
    if _interrogator_alive(game):
        game.no_host_interrog_day_phase = IH_PHASE_ASSIST
        game.no_host_interrog_day_decision = None
    else:
        # بازپرس مرده — بازپرسی ادامه دارد؛ ابتدا پنل دستیار (درخواست به بازپرس)، بعد اوکی بازیکنان.
        game.no_host_interrog_day_decision = None
        game.no_host_interrog_day_phase = IH_PHASE_ASSIST


def build_no_host_interrog_day_assistant_panel(
    game: Game, gm: "GameManager"
) -> tuple[str, InlineKeyboardMarkup | None]:
    phase = game.no_host_interrog_day_phase or IH_PHASE_ASSIST
    code = game.room_code
    u1, u2 = game.bazpors_interrog_first_uid, game.bazpors_interrog_second_uid
    nominees = ""
    if u1 is not None and u2 is not None:
        nominees = (
            f"\n\nنامزدها: {_player_seat_name(game, gm, u1)}"
            f" و {_player_seat_name(game, gm, u2)}"
        )

    if phase == IH_PHASE_ASSIST:
        body = (
            "بازپرسی شروع شد و بازیکنان به ترتیب صحبت کردن. "
            "تأییدیه ادامه بازپرسی را برای بازپرس ارسال کن."
            f"{nominees}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📩 ارسال درخواست به بازپرس",
                        callback_data=BazporsNarrCb(
                            code=code, act="ih_req", tid=0
                        ).pack(),
                    )
                ]
            ]
        )
        return body, kb

    if phase == IH_PHASE_ASSIST_CONFIRM:
        body = (
            "آیا درخواست بازپرسی را برای بازپرس و سایر بازیکنان ارسال کنید؟"
            f"{nominees}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ تأیید ارسال",
                        callback_data=BazporsNarrCb(
                            code=code, act="ih_req_ok", tid=0
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ بازگشت",
                        callback_data=BazporsNarrCb(
                            code=code, act="ih_req_back", tid=0
                        ).pack(),
                    )
                ],
            ]
        )
        return body, kb

    if phase == IH_PHASE_SESSION:
        return build_interrog_session_assistant_wait_html(), None

    if phase == IH_PHASE_VOTE:
        body = (
            "🗳️ پس از شنیدن دفاعیه بازیکن انتخاب‌شده، نتیجه رأی‌گیری جلسه بازپرسی "
            "را مشخص کنید.\n\n"
            "⚠️ توجه: در صورت تأیید خروج بازیکن از بازی، ساید (تیم) او اعلام خواهد شد."
        )
        rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text="رأی‌ها مساوی شد و کسی از بازی خارج نمی‌شود",
                    callback_data=BazporsNarrCb(
                        code=code, act="ih_vtie", tid=0
                    ).pack(),
                )
            ]
        ]
        pool = _interrog_day_vote_pool(game)
        for p in pool:
            label = gm.format_player_tag(p)
            if len(label) > 48:
                label = label[:46] + "…"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"بازیکن {label} با اجماع آرا از بازی خارج شد",
                        callback_data=BazporsNarrCb(
                            code=code, act="ih_velim", tid=p.user_id
                        ).pack(),
                    )
                ]
            )
        return body, InlineKeyboardMarkup(inline_keyboard=rows)

    if phase == IH_PHASE_VOTE_CONFIRM:
        pending = game.no_host_interrog_day_pending_vote
        if pending == "tie":
            detail = "آرا مساوی — کسی خارج نمی‌شود"
        elif pending is not None and pending in game.players:
            detail = _player_seat_name(game, gm, pending)
        else:
            detail = "؟"
        body = (
            f"تأیید اعلام نتیجه رأی بازپرسی؟\n\n<b>{html.escape(detail)}</b>"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ تأیید",
                        callback_data=BazporsNarrCb(
                            code=code, act="ih_vok", tid=0
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ بازگشت",
                        callback_data=BazporsNarrCb(
                            code=code, act="ih_vback", tid=0
                        ).pack(),
                    )
                ],
            ]
        )
        return body, kb

    return "خطا: فاز بازپرسی نامشخص.", None


def _all_wait_ok_received(game: Game) -> bool:
    intr_uid = _interrogator_uid(game)
    needed = set(_alive_uids_excluding(game, intr_uid))
    done = set(game.no_host_interrog_day_ok_uids)
    return needed.issubset(done)


def _session_ready(game: Game) -> bool:
    if not _interrogator_alive(game):
        if game.no_host_interrog_day_decision is None:
            game.no_host_interrog_day_decision = "continue"
        return _all_wait_ok_received(game)
    return (
        _all_wait_ok_received(game)
        and game.no_host_interrog_day_decision is not None
    )


async def _dispatch_interrog_day_session_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پنل انتظار + اوکی برای همهٔ زنده‌ها (بازپرس زنده یا مرده)."""
    nc = game.bazpors_narrator_night_count
    sig = f"{nc}:interrog_day_session"
    if game.no_host_interrog_day_session_signature == sig:
        return
    game.no_host_interrog_day_session_signature = sig
    game.no_host_interrog_day_assistant_wait_sent = False
    from bot.bazpors_narrator import clear_observer_narrator_mirror_ref

    clear_observer_narrator_mirror_ref(game)
    game.no_host_interrog_day_ok_uids = []
    game.no_host_interrog_day_phase = IH_PHASE_SESSION
    if not _interrogator_alive(game):
        game.no_host_interrog_day_decision = "continue"
    await _send_session_panels(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.interrog_day_session_panels_sent",
            night_count=nc,
            interrogator_alive=_interrogator_alive(game),
        )
    except Exception:
        pass


async def bootstrap_no_host_interrog_day_after_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """ورود به بازپرسی روز پس از شب — گزارش شب، سپس پنل دستیار یا اوکی بازیکنان."""
    if game.bazpors_narrator_step != NO_HOST_INTERROG_DAY:
        return
    from bot.bazpors_narrator import (
        clear_narrator_panel_ref,
        deliver_assistant_pinned_night_end_report_if_needed,
    )

    clear_narrator_panel_ref(game)
    await deliver_assistant_pinned_night_end_report_if_needed(bot, game, gm)
    phase = game.no_host_interrog_day_phase or IH_PHASE_ASSIST
    if phase == IH_PHASE_SESSION:
        await _dispatch_interrog_day_session_panels(bot, game, gm)
        await _push_interrog_day_assistant_wait_panel_once(bot, game, gm)
        return
    await push_host_step(bot, game, gm, force_new_host_message=True)


async def _push_interrog_day_assistant_wait_panel_once(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if game.no_host_interrog_day_assistant_wait_sent:
        return
    await push_host_step(bot, game, gm, force_new_host_message=True)
    game.no_host_interrog_day_assistant_wait_sent = True


async def _deliver_interrog_assistant_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    force_new_message: bool = False,
) -> None:
    """پس از پایان فاز انتظار اوکی — پنل رأی/تأیید حتماً به کمک‌کننده برسد."""
    from bot.bazpors_narrator import clear_narrator_panel_ref

    game.no_host_interrog_day_assistant_wait_sent = False
    if force_new_message:
        clear_narrator_panel_ref(game)
    await push_host_step(bot, game, gm, force_new_host_message=force_new_message)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.interrog_day_assistant_panel_pushed",
            phase=game.no_host_interrog_day_phase,
            force_new=force_new_message,
        )
    except Exception:
        pass


async def maybe_recover_no_host_interrog_day_stuck_session(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """فقط بازیابی گیرکردن — نه از هر ``push_host_step`` (جلوگیری از اسپم)."""
    if game.bazpors_narrator_step != NO_HOST_INTERROG_DAY:
        return
    if game.no_host_interrog_day_phase != IH_PHASE_SESSION:
        return
    if interrog_day_session_wait_locked(game):
        return
    if game.no_host_interrog_day_session_signature is None:
        await _dispatch_interrog_day_session_panels(bot, game, gm)
    elif not game.no_host_interrog_day_assistant_wait_sent:
        await _push_interrog_day_assistant_wait_panel_once(bot, game, gm)


async def _go_to_next_day(bot: Bot, game: Game, gm: "GameManager") -> bool:
    """True = پنل کمک‌کننده همین‌جا فرستاده شد یا روز بعد آغاز شد؛ push_host_step اضافه لازم نیست."""
    from bot.bazpors_narrator import push_host_step
    from bot.no_host_handoff import maybe_prompt_handoff_before_day_start
    from bot.no_host_table_inquiry import (
        no_host_enter_table_inquiry_before_day,
        no_host_finish_day_start_after_table_inquiry,
    )

    reset_no_host_interrog_day_state(game)
    if not game.no_host_table_inquiry_resolved_for_day:
        await no_host_enter_table_inquiry_before_day(bot, game, gm)
        await push_host_step(bot, game, gm, force_new_host_message=True)
        return True
    if await maybe_prompt_handoff_before_day_start(bot, game, gm):
        return True
    game.no_host_table_inquiry_resolved_for_day = False
    await no_host_finish_day_start_after_table_inquiry(bot, game, gm)
    return True


async def _broadcast_all_alive(
    bot: Bot, game: Game, text: str, *, exclude: int | None = None
) -> None:
    await broadcast_to_alive_players(
        bot,
        game,
        text,
        parse_mode="HTML",
        exclude=exclude,
        is_synthetic_uid=is_synthetic_player_uid,
    )


async def _send_session_panels(bot: Bot, game: Game, gm: "GameManager") -> None:
    intr_uid = _interrogator_uid(game)
    wait_text = build_interrog_wait_player_html()
    for uid in _alive_uids_excluding(game, intr_uid):
        ui_key = _wait_ui_key(game, uid)
        await register_mirror_prompt_pair(
            bot,
            game,
            uid,
            ui_key,
            wait_text,
            _wait_ok_keyboard(game, uid),
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
    if intr_uid is not None:
        await register_mirror_prompt_pair(
            bot,
            game,
            intr_uid,
            _interrogator_ui_key(game, intr_uid),
            build_interrog_interrogator_html(),
            _interrogator_keyboard(game, intr_uid),
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )


async def _resolve_session_if_ready(
    bot: Bot, game: Game, gm: "GameManager"
) -> bool:
    if not _session_ready(game):
        return False
    decision = game.no_host_interrog_day_decision
    tag = html.escape(_assistant_tag(game, gm))
    if decision == "dissolve":
        if game.no_host_interrog_day_phase != IH_PHASE_SESSION:
            return True
        _mark_interrog_session_done(game)
        _clear_interrog_day_targets(game)
        text = (
            "⚖️ به تصمیم بازپرس، جلسه بازپرسی منحل شد "
            "و وارد روز بعد می‌شویم 🌅"
        )
        await _broadcast_all_alive(bot, game, text)
        if await no_host_maybe_end_on_faction_win(
            bot, game, gm, elim_source="interrog_dissolve"
        ):
            return True
        if not await _go_to_next_day(bot, game, gm):
            await push_host_step(bot, game, gm)
        return True

    if decision == "continue":
        if game.no_host_interrog_day_phase != IH_PHASE_SESSION:
            return True
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        await _broadcast_all_alive(
            bot, game, build_interrog_continue_broadcast_html()
        )
        await _deliver_interrog_assistant_panel(bot, game, gm, force_new_message=True)
        return True
    return False


async def _start_session_after_request_confirmed(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از تأیید ارسال درخواست — بازپرس زنده یا جایگزینی خودکار ادامه."""
    if not _interrogator_alive(game):
        game.no_host_interrog_day_decision = "continue"
    await start_no_host_interrog_day_session(bot, game, gm)


async def start_no_host_interrog_day_session(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if _interrogator_alive(game):
        game.no_host_interrog_day_decision = None
    await _dispatch_interrog_day_session_panels(bot, game, gm)
    await _push_interrog_day_assistant_wait_panel_once(bot, game, gm)


def process_no_host_interrog_day_narrator_cb(
    game: Game, gm: "GameManager", act: str, tid: int
) -> str | None:
    if game.bazpors_narrator_step != NO_HOST_INTERROG_DAY:
        return "نامعتبر."
    phase = game.no_host_interrog_day_phase

    if act == "ih_req":
        if phase != IH_PHASE_ASSIST:
            return "نامعتبر."
        game.no_host_interrog_day_phase = IH_PHASE_ASSIST_CONFIRM
        return None

    if act == "ih_req_back":
        if phase != IH_PHASE_ASSIST_CONFIRM:
            return "نامعتبر."
        game.no_host_interrog_day_phase = IH_PHASE_ASSIST
        return None

    if act == "ih_req_ok":
        if phase != IH_PHASE_ASSIST_CONFIRM:
            return "نامعتبر."
        return None

    if act == "ih_vtie":
        if phase != IH_PHASE_VOTE:
            return "نامعتبر."
        game.no_host_interrog_day_pending_vote = "tie"
        game.no_host_interrog_day_phase = IH_PHASE_VOTE_CONFIRM
        return None

    if act == "ih_velim":
        if phase != IH_PHASE_VOTE:
            return "نامعتبر."
        pool = {p.user_id for p in _interrog_day_vote_pool(game)}
        if tid not in pool:
            return "نامعتبر."
        game.no_host_interrog_day_pending_vote = tid
        game.no_host_interrog_day_phase = IH_PHASE_VOTE_CONFIRM
        return None

    if act == "ih_vback":
        if phase != IH_PHASE_VOTE_CONFIRM:
            return "نامعتبر."
        game.no_host_interrog_day_pending_vote = None
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        return None

    if act == "ih_vok":
        if phase != IH_PHASE_VOTE_CONFIRM:
            return "نامعتبر."
        if game.no_host_interrog_day_pending_vote is None:
            return "خطا."
        return None

    return "نامعتبر."


async def apply_no_host_interrog_day_narrator_async(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    act: str,
) -> None:
    if act == "ih_req_ok":
        await _start_session_after_request_confirmed(bot, game, gm)
        return
    if act == "ih_vok":
        await _apply_vote_result(bot, game, gm)


def _eliminated_faction_side_label(game: Game, uid: int) -> str:
    pl = game.players.get(uid)
    if pl is None or pl.role is None:
        return "شهروند"
    return "مافیا" if is_mafia_team(pl.role) else "شهروند"


async def _apply_vote_result(bot: Bot, game: Game, gm: "GameManager") -> None:
    pending = game.no_host_interrog_day_pending_vote
    tag = html.escape(_assistant_tag(game, gm))
    _mark_interrog_session_done(game)

    if pending == "tie":
        text = (
            f"⚖️ با تأیید 🎭 <b>{tag}</b>، آرا مساوی شد "
            "و کسی از بازی خارج نمی‌شود.\n\n"
            "🌅 روز بعد آغاز می‌شود..."
        )
        await _broadcast_all_alive(bot, game, text)
        _clear_interrog_day_targets(game)
        if await no_host_maybe_end_on_faction_win(
            bot, game, gm, elim_source="interrog_vote_tie"
        ):
            return
        if not await _go_to_next_day(bot, game, gm):
            await push_host_step(bot, game, gm)
        return

    if pending is not None and pending in game.players:
        names_block = hunter_vote_elim_names_html_block(game, gm, pending)
        if "\n" in names_block:
            elim_line = "بازیکنان زیر از بازی خارج می‌شوند"
        else:
            sole = html.escape(gm.format_player_tag(game.players[pending]))
            elim_line = f"بازیکن <b>{sole}</b> از بازی خارج می‌شود"
        side_label = _eliminated_faction_side_label(game, pending)
        text = (
            f"⚖️ با تأیید 🎭 <b>{tag}</b>،\n"
            f"{elim_line}:\n\n"
            f"{names_block}\n\n"
            f"ساید بازیکن خارج شده:\n{side_label}"
        )
        _clear_interrog_day_targets(game)
        if await no_host_eliminate_and_maybe_end_game(
            bot, game, gm, pending, elim_source="interrog_vote"
        ):
            await _broadcast_all_alive(bot, game, text)
            return
        await _broadcast_all_alive(bot, game, text)
        if not await _go_to_next_day(bot, game, gm):
            await push_host_step(bot, game, gm)


def no_host_interrog_vote_hunter_chain_alert(
    game: Game, gm: "GameManager", eliminated_uid: int | str | None
) -> str | None:
    """پاپ‌آپ پس از ih_vok وقتی زنجیرهٔ هانتر همراه را هم حذف کرد."""
    if eliminated_uid in (None, "tie") or not isinstance(eliminated_uid, int):
        return None
    return hunter_chain_confirm_alert_text(game, gm, eliminated_uid)


def no_host_interrog_day_act_active(game: Game, act: str) -> bool:
    if game.bazpors_narrator_step != NO_HOST_INTERROG_DAY:
        return False
    return act in ("ihok", "ihco", "ihdi")


def _player_may_act(game: Game, actor_uid: int, as_uid: int) -> bool:
    if actor_uid == as_uid:
        return True
    return bool(
        is_synthetic_player_uid(as_uid)
        and no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


async def dispatch_no_host_interrog_day_player(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    as_uid: int,
    actor_uid: int,
    act: str,
) -> None:
    if game.bazpors_narrator_step != NO_HOST_INTERROG_DAY:
        await callback.answer("این مرحله فعال نیست.", show_alert=True)
        return
    if game.no_host_interrog_day_phase != IH_PHASE_SESSION:
        await callback.answer("جلسه بازپرسی هنوز شروع نشده.", show_alert=True)
        return

    intr_uid = _interrogator_uid(game)

    if act == "ihok":
        if as_uid == intr_uid:
            await callback.answer(
                "بازپرس از پنل خود ادامه یا انحلال را انتخاب می‌کند.",
                show_alert=True,
            )
            return
        if as_uid not in game.players or not game.players[as_uid].is_alive:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        if not _player_may_act(game, actor_uid, as_uid):
            await callback.answer("فقط خود بازیکن می‌تواند تأیید کند.", show_alert=True)
            return
        if as_uid in game.no_host_interrog_day_ok_uids:
            await callback.answer("قبلاً ثبت شده است.", show_alert=True)
            return
        game.no_host_interrog_day_ok_uids.append(as_uid)
        await callback.answer("ثبت شد.")
        ui_key = _wait_ui_key(game, as_uid)
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            build_interrog_wait_ack_html(),
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )
        await _resolve_session_if_ready(bot, game, gm)
        return

    if act in ("ihco", "ihdi"):
        if intr_uid is None or as_uid != intr_uid:
            await callback.answer("فقط بازپرس این انتخاب را دارد.", show_alert=True)
            return
        if not _player_may_act(game, actor_uid, as_uid):
            await callback.answer("فقط بازپرس می‌تواند انتخاب کند.", show_alert=True)
            return
        if game.no_host_interrog_day_decision is not None:
            await callback.answer("قبلاً ثبت شده است.", show_alert=True)
            return
        game.no_host_interrog_day_decision = (
            "continue" if act == "ihco" else "dissolve"
        )
        label = "ادامه بازپرسی" if act == "ihco" else "انحلال بازپرسی"
        await callback.answer(f"ثبت شد: {label}.")
        await update_mirror_prompt_pair(
            bot,
            game,
            _interrogator_ui_key(game, intr_uid),
            build_interrog_interrogator_html()
            + f"\n\n<i>✅ انتخاب شما: {html.escape(label)}</i>",
            None,
            assistant_uid=intr_uid,
            parse_mode="HTML",
        )
        await _resolve_session_if_ready(bot, game, gm)
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
