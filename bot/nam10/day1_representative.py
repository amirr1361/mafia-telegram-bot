"""Namayande-10 Day-1 representative selection + afternoon-nap workflow.

Fork-only Day-1 stages inserted BEFORE the ordinary Day-1 defense pick panel
(``send_no_host_day1_defense_pick_panel``). The stage machine:

- ``day1_representative_intro``   - instructional panel (assistant + observer
  mirror) with the **👥 انتخاب نمایندگان** button.
- ``day1_representative_pick``    - native red/green toggle over all ten
  players (seat order, synthetic role suffixes hidden in this UI only),
  exactly-two selection, **✅ OK** confirm.
- ``day1_afternoon_nap``          - afternoon-nap / betrayal-vote introduction
  with the **✅ خواب نیمروزی انجام شد** button.
- ``day1_awaiting_betrayal_vote`` - transitional state; the nap ack hands
  control to the Day-1 betrayal-vote workflow
  (``bot/nam10/day1_betrayal.py``), so the ordinary Day-1 defense flow
  must not bypass it.

State lives exclusively in ``nam10_day1_*`` Game fields; the assistant and the
registered Observer operate on ONE shared selection state through the mirror
prompt pair. No defense nomination, Mafia panel, or elimination is started
here (deliberate feature boundary).
"""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.app_state import manager
from bot.models import Game, Player
from bot.text_fa import fa_digits as _fa_digits

from bot.observer_delivery import (
    PlayerMirrorCb,
    apply_mirror_claim_winner,
    close_mirror_prompt_keyboards,
    ensure_observer_mirror_prompt,
    game_observer_mirror_active,
    promote_mirror_prompt_to_panel,
    publish_mirror_prompt_pair,
    try_claim_mirror_ui,
    update_mirror_prompt_pair,
)

# Namayande-10 Day-1 stage names (snapshot-safe strings on Game).
NAM10_DAY1_STAGE_REP_INTRO = "day1_representative_intro"
NAM10_DAY1_STAGE_REP_PICK = "day1_representative_pick"
NAM10_DAY1_STAGE_AFTERNOON_NAP = "day1_afternoon_nap"
NAM10_DAY1_STAGE_AWAITING_BETRAYAL = "day1_awaiting_betrayal_vote"

NAM10_DAY1_STAGES = (
    NAM10_DAY1_STAGE_REP_INTRO,
    NAM10_DAY1_STAGE_REP_PICK,
    NAM10_DAY1_STAGE_AFTERNOON_NAP,
    NAM10_DAY1_STAGE_AWAITING_BETRAYAL,
)

# PlayerMirrorCb acts owned by this workflow (routed from
# bot/nam10/player_mirror.py::dispatch_namayande10_mirror).
ACT_REP_OPEN = "d1ri"  # 👥 انتخاب نمایندگان (intro -> pick panel)
ACT_REP_TOGGLE = "d1rt"  # player toggle button (tid = player uid)
ACT_REP_OK = "d1ro"  # ✅ OK confirm (exactly two selected)
ACT_NAP_ACK = "d1na"  # ✅ خواب نیمروزی انجام شد

NAM10_DAY1_REP_ACTS = (ACT_REP_OPEN, ACT_REP_TOGGLE, ACT_REP_OK, ACT_NAP_ACK)

NAP_ACK_HTML = "\n\n<i>✅ پایان خواب نیمروزی ثبت شد.</i>"

ALERT_NEED_TWO = "لطفاً دقیقاً دو نماینده انتخاب کنید."
ALERT_MAX_TWO = "حداکثر دو نماینده قابل انتخاب است؛ ابتدا یکی از انتخاب‌ها را حذف کنید."
ALERT_STALE_STAGE = "این مرحله دیگر فعال نیست."
ALERT_FORBIDDEN = "شما مجاز به این عمل نیستید."
ALERT_ALREADY = "این انتخاب قبلاً ثبت شده است."


def nam10_day1_rep_act_active(game: Game, act: str) -> bool:
    """Route gate: acts owned by the Day-1 representative workflow."""
    return act in NAM10_DAY1_REP_ACTS


def _audit(game: Game, event: str, **data) -> None:
    try:
        from bot.game_audit_log import log_event

        log_event(game, event, **data)
    except Exception:
        pass


def nam10_day1_rep_intro_ui_key(game: Game, assistant_uid: int) -> str:
    from bot.observer_delivery import mirror_ui_claim_key

    return mirror_ui_claim_key(game.room_code, "day1_rep_intro", assistant_uid)


def nam10_day1_rep_pick_ui_key(game: Game, assistant_uid: int) -> str:
    from bot.observer_delivery import mirror_ui_claim_key

    return mirror_ui_claim_key(game.room_code, "day1_rep_pick", assistant_uid)


def nam10_day1_nap_ui_key(game: Game, assistant_uid: int) -> str:
    from bot.observer_delivery import mirror_ui_claim_key

    return mirror_ui_claim_key(game.room_code, "day1_nap_ack", assistant_uid)


def nam10_day1_rep_authorized(game: Game, actor_uid: int) -> bool:
    """Only the assistant (or the registered Observer via mirror) may act."""
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return False
    if actor_uid == assistant_uid:
        return True
    return (
        game_observer_mirror_active(game)
        and game.observer_user_id == actor_uid
    )


def _rep_panel_players(game: Game) -> list[Player]:
    """All alive players in current seat order (no role information)."""
    alive = [p for p in game.players.values() if p.is_alive]
    return sorted(
        alive,
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    )


def _rep_display_name(game: Game, p: Player) -> str:
    """Seat label for the pick panel; synthetic role suffixes hidden here only."""
    from bot.game import is_synthetic_player_uid, synthetic_player_base_name

    label = manager.format_player_tag(p)
    if is_synthetic_player_uid(p.user_id):
        # Strip the decorative role suffix (e.g. «امیر-آپاچی» -> «امیر»)
        # without touching the stored player name. Real player names are
        # never stripped.
        base = synthetic_player_base_name(p.full_name)
        if p.username:
            label = f"{base} (@{p.username})"
        else:
            label = base
    return label


def build_nam10_day1_rep_intro_html() -> str:
    return (
        "🗳️ <b>فرآیند انتخاب نمایندگان روز اول آغاز شد</b>\n\n"
        "در روز اول، پس از صحبت هر بازیکن، رأی‌گیری برای انتخاب نماینده "
        "انجام می‌شود. بازیکنی که بیشترین رأی را کسب کند، نماینده اول خواهد بود.\n\n"
        "پس از پایان صحبت تمام بازیکنان، رأی‌گیری دوم برگزار می‌شود و "
        "نماینده دوم انتخاب خواهد شد.\n\n"
        "📌 <b>نکته:</b> اگر در رأی‌گیری اول دو بازیکن بیشترین رأی مساوی را "
        "کسب کنند، هر دو به‌عنوان نماینده انتخاب می‌شوند و رأی‌گیری دوم "
        "برگزار نخواهد شد.\n\n"
        "پس از مشخص‌شدن دو نماینده، دکمه زیر را بزنید."
    )


def nam10_day1_rep_intro_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_REP_OPEN, as_uid=assistant_uid
    ).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 انتخاب نمایندگان",
                    callback_data=cb,
                    style="primary",
                )
            ]
        ]
    )


def build_nam10_day1_rep_pick_html(game: Game) -> str:
    n = len({u for u in game.nam10_day1_rep_pending})
    sel = f"\n<i>انتخاب‌شده: {_fa_digits(n)} نفر</i>\n" if n else "\n"
    return (
        "👥 <b>انتخاب نمایندگان روز اول</b>\n\n"
        "🪑 لیست کامل بازیکنان (به ترتیب صندلی) در زیر آمده است.\n"
        "🔵 دکمه آبی: انتخاب‌نشده | 🔴 دکمه قرمز: انتخاب‌شده\n"
        "⚠️ دقیقاً دو نفر را انتخاب کنید؛ برای تغییر انتخاب، ابتدا یکی از "
        "دکمه‌های قرمز را بزنید.\n"
        "پس از انتخاب دو نماینده، دکمه «<b>✅ OK</b>» را بزنید."
        f"{sel}"
    )


def nam10_day1_rep_pick_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    """All players as native Telegram inline buttons.

    Unselected = blue (primary), selected = red (danger). Maximum two
    red buttons can ever exist; no auto-advance happens at two.
    """
    selected = {u for u in game.nam10_day1_rep_pending}
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in _rep_panel_players(game):
        tick = "✅" if p.user_id in selected else "☐"
        style = "danger" if p.user_id in selected else "primary"
        seat_no = _fa_digits(p.seat if p.seat is not None else 0)
        name = html.escape(_rep_display_name(game, p))[:24]
        cb = PlayerMirrorCb(
            code=game.room_code,
            act=ACT_REP_TOGGLE,
            as_uid=assistant_uid,
            tid=p.user_id,
        ).pack()
        row.append(
            InlineKeyboardButton(
                text=f"{tick} {seat_no}. {name}",
                callback_data=cb,
                style=style,
            )
        )
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    ok_cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_REP_OK, as_uid=assistant_uid
    ).pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ OK", callback_data=ok_cb, style="success"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _rep_names_line(game: Game) -> str:
    parts = []
    for idx, uid in enumerate(game.nam10_day1_rep_uids[:2], start=1):
        p = game.players.get(uid)
        label = (
            html.escape(_rep_display_name(game, p))
            if p is not None
            else str(uid)
        )
        word = "اول" if idx == 1 else "دوم"
        parts.append(f"نماینده {word}: <b>{label}</b>")
    return "، ".join(parts)


def build_nam10_day1_nap_html(game: Game) -> str:
    return (
        "🌤️ <b>نمایندگان روز اول انتخاب شدند</b>\n\n"
        "🌙 <b>خواب نیمروزی — فرآیند رأی خیانت</b>\n\n"
        f"دو نماینده روز اول مشخص شده‌اند: {_rep_names_line(game)}\n\n"
        "در این مرحله، گروه مافیا باید درباره رأی خیانت خود مشورت کرده و "
        "تصمیم‌گیری کند.\n\n"
        "لطفاً به تمام بازیکنان اعلام کنید که برای مشورت گروه مافیا و "
        "تصمیم‌گیری درباره رأی خیانت، به خواب نیمروزی بروند.\n\n"
        "پس از پایان خواب نیمروزی، دکمه زیر را بزنید."
    )


def nam10_day1_nap_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_NAP_ACK, as_uid=assistant_uid
    ).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ خواب نیمروزی انجام شد",
                    callback_data=cb,
                    style="success",
                )
            ]
        ]
    )


async def nam10_start_day1_representative_flow(bot: Bot, game: Game) -> None:
    """Stage ``day1_representative_intro`` - replaces the Day-1 defense pick
    panel on first presentation (idempotent; never restarts a flow)."""
    if game.nam10_day1_stage is not None:
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    game.nam10_day1_stage = NAM10_DAY1_STAGE_REP_INTRO
    game.nam10_day1_rep_uids = []
    game.nam10_day1_rep_pending = []
    game.nam10_day1_nap_acked = False
    ui_key = nam10_day1_rep_intro_ui_key(game, assistant_uid)
    await publish_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        build_nam10_day1_rep_intro_html(),
        nam10_day1_rep_intro_keyboard(game, assistant_uid),
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_representative_intro_started",
        assistant_uid=assistant_uid,
        observer_uid=game.observer_user_id,
    )


async def _open_pick_panel(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    """👥 pressed: transition intro -> pick (one-shot transition via claim)."""
    from bot.main import _answer_mirror_claim

    intro_key = nam10_day1_rep_intro_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, intro_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    await apply_mirror_claim_winner(bot, game, intro_key, actor_uid, assistant_uid)
    await callback.answer("پنل انتخاب نمایندگان فعال شد.")
    game.nam10_day1_stage = NAM10_DAY1_STAGE_REP_PICK
    pick_key = nam10_day1_rep_pick_ui_key(game, assistant_uid)
    text = build_nam10_day1_rep_pick_html(game)
    kb = nam10_day1_rep_pick_keyboard(game, assistant_uid)
    promoted = await _promote_with_observer_fallback(
        bot,
        game,
        from_ui_key=intro_key,
        to_ui_key=pick_key,
        assistant_uid=assistant_uid,
        text=text,
        kb=kb,
    )
    if not promoted:
        await publish_mirror_prompt_pair(
            bot, game, assistant_uid, pick_key, text, kb, parse_mode="HTML"
        )
    _audit(
        game,
        "no_host.day1_representative_pick_opened",
        assistant_uid=assistant_uid,
        actor_uid=actor_uid,
    )


async def _promote_with_observer_fallback(
    bot: Bot,
    game: Game,
    *,
    from_ui_key: str,
    to_ui_key: str,
    assistant_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> bool:
    """Promote the previous panel message into the next stage panel; make
    sure the Observer copy exists even when the observer registered late."""
    promoted = await promote_mirror_prompt_to_panel(
        bot,
        game,
        from_ui_key=from_ui_key,
        to_ui_key=to_ui_key,
        assistant_uid=assistant_uid,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await ensure_observer_mirror_prompt(
        bot,
        game,
        assistant_uid,
        to_ui_key,
        text,
        kb,
        parse_mode="HTML",
    )
    return promoted


async def _toggle_rep(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    target_uid: int,
) -> None:
    """Native red/green toggle; shared state for assistant + Observer."""
    if target_uid not in game.players or not game.players[target_uid].is_alive:
        await callback.answer("بازیکن زنده نیست.", show_alert=True)
        return
    pending = [u for u in game.nam10_day1_rep_pending if u != target_uid]
    was_selected = target_uid in game.nam10_day1_rep_pending
    if not was_selected:
        if len(pending) >= 2:
            # A third selection is never stored while two are selected.
            _audit(
                game,
                "no_host.day1_representative_toggle_rejected",
                target_uid=target_uid,
                reject_reason="max_two_selected",
            )
            await callback.answer(ALERT_MAX_TWO, show_alert=True)
            return
        pending.append(target_uid)
    game.nam10_day1_rep_pending = pending
    await callback.answer("به‌روز شد.")
    pick_key = nam10_day1_rep_pick_ui_key(game, assistant_uid)
    await update_mirror_prompt_pair(
        bot,
        game,
        pick_key,
        build_nam10_day1_rep_pick_html(game),
        nam10_day1_rep_pick_keyboard(game, assistant_uid),
        assistant_uid=assistant_uid,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_representative_toggled",
        target_uid=target_uid,
        selected=not was_selected,
        actor_uid=actor_uid,
    )


async def _confirm_reps(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    """✅ OK: exactly two distinct selections -> store in selection order."""
    from bot.main import _answer_mirror_claim

    if len({u for u in game.nam10_day1_rep_pending}) != 2:
        _audit(
            game,
            "no_host.day1_representative_confirm_rejected",
            reject_reason="need_two",
            actor_uid=actor_uid,
        )
        await callback.answer(ALERT_NEED_TWO, show_alert=True)
        return
    pick_key = nam10_day1_rep_pick_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, pick_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    # Re-validate after the claim: a concurrent toggle may have changed the
    # pending set between validation and claim.
    pending = [u for u in game.nam10_day1_rep_pending]
    if len({u for u in pending}) != 2:
        game.mirror_action_claims.pop(pick_key, None)
        await callback.answer(ALERT_NEED_TWO, show_alert=True)
        return
    # Selection order is authoritative: first selected -> rep 1.
    ordered = list(dict.fromkeys(pending))
    await apply_mirror_claim_winner(
        bot, game, pick_key, actor_uid, assistant_uid
    )
    await callback.answer("ثبت شد.")
    game.nam10_day1_rep_uids = ordered
    game.nam10_day1_rep_pending = []
    game.nam10_day1_stage = NAM10_DAY1_STAGE_AFTERNOON_NAP
    # Disable any leftover actionable copy of the intro panel.
    await close_mirror_prompt_keyboards(
        bot, game, nam10_day1_rep_intro_ui_key(game, assistant_uid)
    )
    nap_key = nam10_day1_nap_ui_key(game, assistant_uid)
    nap_text = build_nam10_day1_nap_html(game)
    nap_kb = nam10_day1_nap_keyboard(game, assistant_uid)
    promoted = await _promote_with_observer_fallback(
        bot,
        game,
        from_ui_key=pick_key,
        to_ui_key=nap_key,
        assistant_uid=assistant_uid,
        text=nap_text,
        kb=nap_kb,
    )
    if not promoted:
        await publish_mirror_prompt_pair(
            bot, game, assistant_uid, nap_key, nap_text, nap_kb,
            parse_mode="HTML",
        )
    _audit(
        game,
        "no_host.day1_representative_confirmed",
        assistant_uid=assistant_uid,
        actor_uid=actor_uid,
        rep_uids=[int(u) for u in ordered],
    )


async def _ack_afternoon_nap(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    """✅ خواب نیمروزی انجام شد: idempotent acknowledgement, panels closed."""
    from bot.main import _answer_mirror_claim

    if game.nam10_day1_nap_acked:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    nap_key = nam10_day1_nap_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, nap_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    await apply_mirror_claim_winner(
        bot, game, nap_key, actor_uid, assistant_uid
    )
    await callback.answer("ثبت شد.")
    game.nam10_day1_nap_acked = True
    game.nam10_day1_stage = NAM10_DAY1_STAGE_AWAITING_BETRAYAL
    # Close both actionable copies (assistant + Observer mirror).
    await update_mirror_prompt_pair(
        bot,
        game,
        nap_key,
        build_nam10_day1_nap_html(game) + NAP_ACK_HTML,
        None,
        assistant_uid=assistant_uid,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_afternoon_nap_acked",
        assistant_uid=assistant_uid,
        actor_uid=actor_uid,
    )
    # Replace the old feature boundary: the Day-1 betrayal-vote workflow
    # (Stage A) starts immediately after the afternoon-nap ack.
    from bot.nam10.day1_betrayal import nam10_start_day1_betrayal_collection

    await nam10_start_day1_betrayal_collection(bot, game)


async def dispatch_nam10_day1_representative_act(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    act: str,
    *,
    tid: int = 0,
) -> None:
    """Route a Day-1 representative/nap PlayerMirrorCb press."""
    from bot.room_mode import is_namayande10_no_host_room

    _audit(
        game,
        "no_host.day1_representative_cb",
        act=act,
        actor_uid=actor_uid,
        assistant_uid=assistant_uid,
        target_uid=tid or None,
        outcome="received",
    )
    if not is_namayande10_no_host_room(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    if not nam10_day1_rep_authorized(game, actor_uid):
        _audit(
            game,
            "no_host.day1_representative_cb",
            act=act,
            actor_uid=actor_uid,
            outcome="rejected",
            reject_reason="forbidden_actor",
        )
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return

    def _stale() -> None:
        _audit(
            game,
            "no_host.day1_representative_cb",
            act=act,
            actor_uid=actor_uid,
            outcome="rejected",
            reject_reason="stale_stage",
        )

    if act == ACT_REP_OPEN:
        if game.nam10_day1_stage != NAM10_DAY1_STAGE_REP_INTRO:
            _stale()
            await callback.answer(ALERT_STALE_STAGE, show_alert=True)
            return
        await _open_pick_panel(
            callback, bot, game, assistant_uid, actor_uid
        )
        return

    if act == ACT_REP_TOGGLE:
        if game.nam10_day1_stage != NAM10_DAY1_STAGE_REP_PICK:
            _stale()
            await callback.answer(ALERT_STALE_STAGE, show_alert=True)
            return
        await _toggle_rep(
            callback, bot, game, assistant_uid, actor_uid, tid
        )
        return

    if act == ACT_REP_OK:
        if game.nam10_day1_stage != NAM10_DAY1_STAGE_REP_PICK:
            _stale()
            await callback.answer(ALERT_STALE_STAGE, show_alert=True)
            return
        await _confirm_reps(
            callback, bot, game, assistant_uid, actor_uid
        )
        return

    if act == ACT_NAP_ACK:
        if game.nam10_day1_stage != NAM10_DAY1_STAGE_AFTERNOON_NAP:
            _stale()
            await callback.answer(ALERT_STALE_STAGE, show_alert=True)
            return
        await _ack_afternoon_nap(
            callback, bot, game, assistant_uid, actor_uid
        )
        return

    _audit(
        game,
        "no_host.day1_representative_cb",
        act=act,
        actor_uid=actor_uid,
        outcome="rejected",
        reject_reason="unknown_act",
    )
    await callback.answer("عمل نامعتبر.", show_alert=True)
