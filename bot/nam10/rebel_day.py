"""Namayande-10 — daytime Rebel (یاغی / Role.NATO) assassination driver.

Daytime UI/integration layer for the durable once-per-game Rebel
assassination whose eligibility/effect engine already lives in
``bot/nam10/night2.py`` (``night2_rebel_assassination_unlocked`` /
``night2_rebel_assassination_available`` / ``night2_rebel_assassination_effect``).
This module adds:

- a one-time private activation notice when the Mafia Boss or the
  Hacker has been eliminated (any pathway that stores the durable
  ``nmnd_night2_rebel_unlocked`` flag, including mine casualties);
- a private entry panel each eligible day (delivered after the day
  opening and all preceding night-results / table-inquiry stages);
- target selection limited to alive town-faction players (Rebel and all
  Mafia-aligned players excluded; seat order; seat + name labels only,
  never hidden roles);
- two-step confirmation (target pick -> final confirmation) with
  cancellation that never consumes the ability;
- the hard cutoff rule: the window closes the moment the assistant
  confirms the daily defense candidates (``d1dc`` confirm in
  ``bot/nam10/dayflow.py``) — all active rebel panels are finalized
  (buttons removed, player + Observer copies) and stale callbacks are
  rejected server-side; the unlocked, unused ability is preserved for
  later days;
- at-most-once final confirmation: ``night2_rebel_assassination_effect``
  is the single commit point; repeated callbacks are rejected.

All panels follow the shared PlayerMirrorCb + Observer-mirror
conventions (``register_mirror_prompt_pair`` /
``update_mirror_prompt_pair`` / ``close_mirror_prompt_keyboards``) so a
synthetic Rebel is operated by the registered Observer exactly like
every other private panel.
"""

from __future__ import annotations

import html
import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import Game, Phase, Player, Role

logger = logging.getLogger(__name__)

ACT_REBEL_OPEN = "rebben"
ACT_REBEL_PICK = "rebpick"
ACT_REBEL_OK = "rebok"
ACT_REBEL_CANCEL = "rebcancel"
ACT_REBEL_FINAL = "rebgo"

NAM10_REBEL_ACTS = frozenset(
    {
        ACT_REBEL_OPEN,
        ACT_REBEL_PICK,
        ACT_REBEL_OK,
        ACT_REBEL_CANCEL,
        ACT_REBEL_FINAL,
    }
)

STAGE_ENTRY = "entry"
STAGE_TARGET = "target"
STAGE_FINAL = "final"

ALERT_STALE = "این مرحله دیگر فعال نیست."
ALERT_FORBIDDEN = "شما مجاز به این عمل نیستید."
ALERT_NEED_TARGET = "ابتدا یک بازیکن را انتخاب کنید."
ALERT_WINDOW_CLOSED = "مهلت استفاده از قابلیت ترور برای امروز تمام شده است."


# ---------------------------------------------------------------------------
# Panel bodies
# ---------------------------------------------------------------------------


def build_rebel_activation_notice_html() -> str:
    return (
        "<b>🎯 قابلیت ترور فعال شد</b>\n\n"
        "با خروج یکی از اعضای اصلی تیم مافیا، قابلیت ترور شما فعال شده است.\n\n"
        "از این پس می\u200cتوانید یک بار در طول بازی، پیش از تأیید بازیکنان "
        "دفاعیه، از قابلیت ترور استفاده کنید.\n\n"
        "با اجرای ترور، شما نیز از بازی خارج می\u200cشوید."
    )


def build_rebel_entry_panel_html() -> str:
    return (
        "<b>🎯 قابلیت ترور</b>\n\n"
        "قابلیت ترور شما فعال است.\n\n"
        "در صورت تمایل، می\u200cتوانید پیش از تأیید بازیکنان دفاعیه، از آن "
        "استفاده کنید."
    )


def build_rebel_target_panel_html() -> str:
    return (
        "<b>🎯 انتخاب هدف ترور</b>\n\n"
        "یک بازیکن را برای ترور انتخاب کنید.\n\n"
        "پس از انتخاب، دکمه «✅ تأیید» را بزنید."
    )


def build_rebel_final_panel_html(game: Game, target_uid: int) -> str:
    name = _target_name_html(game, target_uid)
    return (
        "<b>⚠️ تأیید نهایی ترور</b>\n\n"
        f"شما <b>{name}</b> را به\u200cعنوان هدف ترور انتخاب کرده\u200cاید.\n\n"
        "با تأیید نهایی، شما از بازی خارج می\u200cشوید. بازیکن انتخاب\u200cشده "
        "نیز در صورتی که مصونیت معتبر نداشته باشد، همراه شما حذف خواهد شد."
    )


# ---------------------------------------------------------------------------
# Eligibility / window helpers
# ---------------------------------------------------------------------------


def _rebel_uid(game: Game) -> int | None:
    """The alive, non-converted Rebel (Role.NATO) holder, if any."""
    from bot.nam10.night2 import _holder

    rebel = _holder(game, Role.NATO)
    return rebel.user_id if rebel is not None else None


def _day_of_game(game: Game) -> int:
    return max(1, int(game.nmnd_narrator_host_day or 1))


def nam10_rebel_key(game: Game, uid: int) -> str:
    """Day-scoped mirror-pair key; previous-day panels never re-render."""
    from bot.nam10.night2 import _ui_key

    return _ui_key(game, f"reb{_day_of_game(game)}", uid)


def nam10_rebel_notice_key(game: Game, uid: int) -> str:
    from bot.nam10.night2 import _ui_key

    return _ui_key(game, "rebnotice", uid)


def _rebel_panel_owner_uid(game: Game) -> int | None:
    """The uid whose rebel panels are live/stale on Telegram (works even
    after the Rebel is eliminated, so their buttons can still be
    stripped)."""
    owner = game.nmnd_night2_rebel_panel_uid
    if owner is not None:
        return int(owner)
    return _rebel_uid(game)


def _set_rebel_panel_owner(game: Game, uid: int) -> None:
    game.nmnd_night2_rebel_panel_uid = int(uid)


def nam10_rebel_window_open(game: Game) -> bool:
    """Authoritative daytime window predicate.

    Open only while: night-2 Namayande-10 room, day-discussion stage, no
    pending publication, the assistant has NOT yet confirmed this day's
    defense candidates (cutoff flag), and no defense elimination
    sub-stage is already running.
    """
    from bot.nam10.nmnd_narrator import DAY_DISCUSS
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if not getattr(game, "nmnd_night2_mode", False):
        return False
    if game.phase == Phase.ENDED:
        return False
    if game.nmnd_narrator_step != DAY_DISCUSS:
        return False
    if game.nmnd_night2_publication_pending:
        return False
    if game.nmnd_night2_rebel_cutoff_day == _day_of_game(game):
        return False
    from bot.nam10.dayflow import nam10_rebel_day_substage_closed

    if nam10_rebel_day_substage_closed(game):
        return False
    return True


def nam10_rebel_assassin_day_usable(game: Game) -> bool:
    """Full pre-commit eligibility: open daytime window + available."""
    from bot.nam10.night2 import night2_rebel_assassination_available

    if not nam10_rebel_window_open(game):
        return False
    return night2_rebel_assassination_available(game)


# ---------------------------------------------------------------------------
# Callback plumbing
# ---------------------------------------------------------------------------


def _cb(game: Game, act: str, as_uid: int, tid: int = 0) -> str:
    from bot.observer_delivery import PlayerMirrorCb

    return PlayerMirrorCb(
        code=game.room_code, act=act, as_uid=as_uid, tid=tid
    ).pack()


def _button(game: Game, act: str, as_uid: int, text: str, *, tid: int = 0, style: str | None = None) -> InlineKeyboardButton:
    btn = InlineKeyboardButton(
        text=text, callback_data=_cb(game, act, as_uid, tid)
    )
    if style is not None:
        btn.style = style
    return btn


def _entry_keyboard(game: Game, rebel_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(
                    game,
                    ACT_REBEL_OPEN,
                    rebel_uid,
                    "🎯 استفاده از قابلیت ترور",
                    style="danger",
                )
            ]
        ]
    )


def _target_keyboard(
    game: Game, rebel_uid: int, selected_uid: int | None
) -> InlineKeyboardMarkup:
    from bot.nam10.night2 import _player_rows
    from bot.observer_delivery import PlayerMirrorCb

    rows = _player_rows(
        game,
        rebel_uid,
        ACT_REBEL_PICK,
        _rebel_target_pool(game, rebel_uid),
        [selected_uid] if selected_uid is not None else [],
    )
    for row in rows:
        for btn in row:
            data = PlayerMirrorCb.unpack(btn.callback_data or "")
            if data is None:
                continue
            # Unselected eligible players: blue (primary); the current
            # selection: red (danger).
            btn.style = (
                "danger" if data.tid == selected_uid else "primary"
            )
    rows.append([_button(game, ACT_REBEL_OK, rebel_uid, "✅ تأیید", style="success")])
    rows.append([_button(game, ACT_REBEL_CANCEL, rebel_uid, "↩️ انصراف")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _final_keyboard(game: Game, rebel_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(
                    game,
                    ACT_REBEL_FINAL,
                    rebel_uid,
                    "✅ تأیید نهایی",
                    style="success",
                )
            ],
            [_button(game, ACT_REBEL_CANCEL, rebel_uid, "↩️ انصراف")],
        ]
    )


def _rebel_target_pool(game: Game, rebel_uid: int) -> list[Player]:
    from bot.nam10.night2 import _town_members

    return [p for p in _town_members(game) if p.user_id != rebel_uid]


def _target_name_html(game: Game, uid: int) -> str:
    from bot.nam10.night2 import _button_label

    return _button_label(game, game.players.get(uid), uid)


def _audit(game: Game, event: str, **kw) -> None:
    try:
        from bot.nam10.night2 import _audit as _n2_audit

        _n2_audit(game, event, **kw)
    except Exception:  # pragma: no cover
        logger.exception("rebel audit failed room=%s", game.room_code)


def _persist(game: Game, reason: str) -> None:
    try:
        from bot.app_state import manager

        manager.persist_snapshot(game, reason=reason)
    except Exception:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Activation notice + entry panel delivery
# ---------------------------------------------------------------------------


async def dispatch_nam10_rebel_activation(bot, game: Game) -> bool:
    """One-time activation notice (+ entry panel while the window is
    open). Idempotent — called from elimination pathways and from the
    day opening; snapshot restores cannot duplicate it."""
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if not getattr(game, "nmnd_night2_mode", False):
        return False
    if game.phase == Phase.ENDED:
        return False
    if not game.nmnd_night2_rebel_unlocked:
        return False
    if game.nmnd_night2_rebel_assassin_used:
        return False
    rebel_uid = _rebel_uid(game)
    if rebel_uid is None:
        return False  # Rebel dead: never notice a dead player.

    sent_anything = False
    if not game.nmnd_night2_rebel_notice_sent:
        from bot.observer_delivery import register_mirror_prompt_pair

        notice_key = nam10_rebel_notice_key(game, rebel_uid)
        await register_mirror_prompt_pair(
            bot,
            game,
            rebel_uid,
            notice_key,
            build_rebel_activation_notice_html(),
            None,
            send_player=True,
            send_observer=True,
            # A label the copy of the message with the owning seat, so an
            # Observer always knows which seat the mirrored notice and
            # panel belong to (synthetic Rebel included).
            observer_same_text=False,
            parse_mode="HTML",
        )
        # Never treat the notice as delivered merely because the internal
        # flag path ran: a real Telegram ref must exist on at least one
        # channel (player DM for a real Rebel, Observer mirror for a
        # synthetic one). On failure the flag stays False so the next
        # dispatch/day opening retries instead of silently skipping.
        notice_entry = game.mirror_prompt_messages.get(notice_key) or {}
        if notice_entry.get("observer") or notice_entry.get("player"):
            game.nmnd_night2_rebel_notice_sent = True
            _audit(game, "night2.rebel_activation_notice_delivered")
            sent_anything = True
        else:
            _audit(game, "night2.rebel_notice_delivery_failed")

    if nam10_rebel_window_open(game):
        sent_panel = await send_nam10_rebel_entry_panel(bot, game)
        sent_anything = sent_anything or sent_panel
    if sent_anything:
        _persist(game, "night2_rebel_activation")
    return sent_anything


async def send_nam10_rebel_day_opening(bot, game: Game) -> None:
    """Day-opening hook: close yesterday's panels, then (re)send the
    entry panel for the new day. Runs after the day-start broadcast and
    every preceding night-to-day stage is complete; never blocks the
    day."""
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return
    if not getattr(game, "nmnd_night2_mode", False):
        return
    if game.phase == Phase.ENDED:
        return
    try:
        from bot.observer_delivery import close_mirror_prompt_keyboards

        host_day = _day_of_game(game)
        owner_uid = _rebel_panel_owner_uid(game)
        if owner_uid is not None:
            from bot.nam10.night2 import _ui_key

            keys = [
                _ui_key(game, f"reb{d}", owner_uid)
                for d in range(1, host_day)
            ]
            for key in keys:
                if key in game.mirror_prompt_messages:
                    try:
                        await close_mirror_prompt_keyboards(bot, game, key)
                    except Exception:
                        logger.exception(
                            "rebel stale panel close failed room=%s key=%s",
                            game.room_code,
                            key,
                        )
    except Exception:
        logger.exception(
            "rebel previous-day panel close failed room=%s", game.room_code
        )
    if not game.nmnd_night2_rebel_unlocked:
        return
    if game.nmnd_night2_rebel_assassin_used:
        return
    if _rebel_uid(game) is None:
        return
    try:
        await dispatch_nam10_rebel_activation(bot, game)
    except Exception:
        logger.exception(
            "rebel day-opening activation failed room=%s", game.room_code
        )


async def send_nam10_rebel_entry_panel(bot, game: Game) -> bool:
    """Private entry panel for the current day (idempotent per day)."""
    from bot.nam10.night2 import _publish_panel
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if not getattr(game, "nmnd_night2_mode", False):
        return False
    if game.nmnd_night2_rebel_assassin_used:
        return False
    if not game.nmnd_night2_rebel_unlocked:
        return False
    rebel_uid = _rebel_uid(game)
    if rebel_uid is None:
        return False
    day = _day_of_game(game)
    if (
        game.nmnd_night2_rebel_panel_day == day
        and game.nmnd_night2_rebel_stage
        in (STAGE_ENTRY, STAGE_TARGET, STAGE_FINAL)
    ):
        return False  # a live per-day panel already exists
    await _publish_panel(
        bot,
        game,
        rebel_uid,
        nam10_rebel_key(game, rebel_uid),
        build_rebel_entry_panel_html(),
        _entry_keyboard(game, rebel_uid),
    )
    _set_rebel_panel_owner(game, rebel_uid)
    game.nmnd_night2_rebel_panel_day = day
    game.nmnd_night2_rebel_stage = STAGE_ENTRY
    game.nmnd_night2_rebel_target_pending = None
    _audit(game, "night2.rebel_entry_panel_delivered", day=day)
    _persist(game, "night2_rebel_entry_panel")
    return True


async def close_nam10_rebel_window(bot, game: Game) -> bool:
    """Assistant defense-candidates confirmation cutoff.

    Sets the day cutoff, invalidates the live stage and strips the
    actionable buttons from the player and Observer copies. The
    unlocked, unused ability stays available for the next eligible
    day. Idempotent per day.
    """
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if not getattr(game, "nmnd_night2_mode", False):
        return False
    day = _day_of_game(game)
    if game.nmnd_night2_rebel_cutoff_day == day:
        return False
    game.nmnd_night2_rebel_cutoff_day = day
    owner_uid = _rebel_panel_owner_uid(game)
    if owner_uid is not None:
        key = nam10_rebel_key(game, owner_uid)
        if key in game.mirror_prompt_messages:
            try:
                from bot.observer_delivery import close_mirror_prompt_keyboards

                await close_mirror_prompt_keyboards(bot, game, key)
            except Exception:
                logger.exception(
                    "rebel cutoff panel close failed room=%s", game.room_code
                )
    if game.nmnd_night2_rebel_stage is not None:
        game.nmnd_night2_rebel_stage = None
        game.nmnd_night2_rebel_target_pending = None
    _audit(game, "night2.rebel_window_closed", host_day=day)
    _persist(game, "night2_rebel_window_closed")
    return True


# ---------------------------------------------------------------------------
# Act dispatch
# ---------------------------------------------------------------------------


async def dispatch_nam10_rebel_act(
    callback,
    bot,
    game: Game,
    gm,
    *,
    actor_uid: int,
    act: str,
    as_uid: int,
    tid: int,
) -> None:
    from bot.nam10.night2 import _may_act

    if act not in NAM10_REBEL_ACTS:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if game.phase == Phase.ENDED:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    rebel_uid = _rebel_uid(game)
    if as_uid != rebel_uid or not _may_act(game, actor_uid, as_uid):
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if game.nmnd_night2_rebel_assassin_used:
        await callback.answer(ALERT_STALE, show_alert=True)
        return

    if act == ACT_REBEL_OPEN:
        await _act_open(callback, bot, game, as_uid)
    elif act == ACT_REBEL_PICK:
        await _act_pick(callback, bot, game, as_uid, tid)
    elif act == ACT_REBEL_OK:
        await _act_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_REBEL_CANCEL:
        await _act_cancel(callback, bot, game, as_uid)
    elif act == ACT_REBEL_FINAL:
        await _act_final(callback, bot, game, gm, as_uid)


async def _act_open(callback, bot, game: Game, rebel_uid: int) -> None:
    if game.nmnd_night2_rebel_stage not in (STAGE_ENTRY, None):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if not nam10_rebel_window_open(game):
        await callback.answer(ALERT_WINDOW_CLOSED, show_alert=True)
        return
    game.nmnd_night2_rebel_stage = STAGE_TARGET
    game.nmnd_night2_rebel_target_pending = None
    from bot.nam10.night2 import _publish_panel

    await _publish_panel(
        bot,
        game,
        rebel_uid,
        nam10_rebel_key(game, rebel_uid),
        build_rebel_target_panel_html(),
        _target_keyboard(game, rebel_uid, None),
    )
    _persist(game, "night2_rebel_target_stage")
    await callback.answer("پنل انتخاب هدف باز شد.")


async def _act_pick(
    callback, bot, game: Game, rebel_uid: int, tid: int
) -> None:
    if game.nmnd_night2_rebel_stage != STAGE_TARGET:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if not nam10_rebel_window_open(game):
        await callback.answer(ALERT_WINDOW_CLOSED, show_alert=True)
        return
    pool_uids = {p.user_id for p in _rebel_target_pool(game, rebel_uid)}
    if tid not in pool_uids:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    # Tapping another player switches the selection; tapping the
    # selected target deselects it (exactly one target at a time).
    pending = (
        None if game.nmnd_night2_rebel_target_pending == tid else tid
    )
    game.nmnd_night2_rebel_target_pending = pending
    from bot.nam10.night2 import _publish_panel

    await _publish_panel(
        bot,
        game,
        rebel_uid,
        nam10_rebel_key(game, rebel_uid),
        build_rebel_target_panel_html(),
        _target_keyboard(game, rebel_uid, pending),
    )
    await callback.answer("ثبت شد.")


async def _act_ok(callback, bot, game: Game, gm, rebel_uid: int) -> None:
    if game.nmnd_night2_rebel_stage != STAGE_TARGET:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if not nam10_rebel_window_open(game):
        await callback.answer(ALERT_WINDOW_CLOSED, show_alert=True)
        return
    target_uid = game.nmnd_night2_rebel_target_pending
    if target_uid is None:
        await callback.answer(ALERT_NEED_TARGET, show_alert=True)
        return
    target = game.players.get(target_uid)
    if (
        target is None
        or not target.is_alive
        or target_uid
        not in {p.user_id for p in _rebel_target_pool(game, rebel_uid)}
    ):
        game.nmnd_night2_rebel_target_pending = None
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    game.nmnd_night2_rebel_stage = STAGE_FINAL
    from bot.nam10.night2 import _publish_panel

    await _publish_panel(
        bot,
        game,
        rebel_uid,
        nam10_rebel_key(game, rebel_uid),
        build_rebel_final_panel_html(game, target_uid),
        _final_keyboard(game, rebel_uid),
    )
    _persist(game, "night2_rebel_final_stage")
    await callback.answer("پنل تأیید نهایی باز شد.")


async def _act_cancel(callback, bot, game: Game, rebel_uid: int) -> None:
    if game.nmnd_night2_rebel_stage not in (STAGE_TARGET, STAGE_FINAL):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    # Never consumes the ability; returns to the entry panel view.
    game.nmnd_night2_rebel_target_pending = None
    game.nmnd_night2_rebel_stage = STAGE_ENTRY
    from bot.nam10.night2 import _publish_panel

    await _publish_panel(
        bot,
        game,
        rebel_uid,
        nam10_rebel_key(game, rebel_uid),
        build_rebel_entry_panel_html(),
        _entry_keyboard(game, rebel_uid),
    )
    _persist(game, "night2_rebel_cancelled")
    await callback.answer("انصراف ثبت شد؛ قابلیت حفظ شد.")


async def _act_final(
    callback, bot, game: Game, gm, rebel_uid: int
) -> None:
    if game.nmnd_night2_rebel_stage != STAGE_FINAL:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if not nam10_rebel_window_open(game):
        # The assistant confirmed the defense candidates in the
        # meantime: the window is closed; never commit, never consume.
        game.nmnd_night2_rebel_stage = STAGE_ENTRY
        game.nmnd_night2_rebel_target_pending = None
        await callback.answer(ALERT_WINDOW_CLOSED, show_alert=True)
        return
    target_uid = game.nmnd_night2_rebel_target_pending
    if target_uid is None:
        game.nmnd_night2_rebel_stage = STAGE_ENTRY
        await callback.answer(ALERT_NEED_TARGET, show_alert=True)
        return
    target = game.players.get(target_uid)
    if (
        target is None
        or not target.is_alive
        or target_uid
        not in {p.user_id for p in _rebel_target_pool(game, rebel_uid)}
    ):
        game.nmnd_night2_rebel_stage = STAGE_ENTRY
        game.nmnd_night2_rebel_target_pending = None
        await callback.answer("هدف دیگر در بازی نیست.", show_alert=True)
        return

    from bot.nam10.night2 import night2_rebel_assassination_effect

    # Atomic commit point (synchronous, no await inside): consume the
    # once-per-game ability and apply the established elimination
    # effects (Rebel always dies; Guardian immunity / current armor).
    result = night2_rebel_assassination_effect(game, target_uid)
    if not result.get("accepted"):
        game.nmnd_night2_rebel_stage = STAGE_ENTRY
        game.nmnd_night2_rebel_target_pending = None
        await callback.answer("قابلیت دیگر قابل استفاده نیست.", show_alert=True)
        return

    game.nmnd_night2_rebel_stage = None
    game.nmnd_night2_rebel_target_pending = None
    from bot.nam10.night2 import _update_panel

    await _update_panel(
        bot,
        game,
        rebel_uid,
        nam10_rebel_key(game, rebel_uid),
        "<b>🎯 ترور اجرا شد.</b>\n\n⏳ لطفاً منتظر اعلام نتیجه بمانید.",
        None,
    )
    await callback.answer("ترور اجرا شد.")
    await announce_rebel_assassination_result(bot, game, gm, result)
    # The committed assassination bypasses the rest of today's defence
    # workflow: close the defence UI and hand the assistant an explicit
    # next-night button (skipped when the game already ended).
    try:
        await prepare_post_assassination_day(bot, game, gm, result)
    except Exception:
        logger.exception(
            "post-assassination day bypass failed room=%s", game.room_code
        )


# ---------------------------------------------------------------------------
# Public result announcement
# ---------------------------------------------------------------------------


def build_rebel_result_broadcast_html(game: Game, result: dict) -> str:
    """Name-only public announcement; never exposes hidden roles."""
    rebel_tag = _public_name(game, result.get("rebel_uid"))
    target_tag = _public_name(game, result.get("target_uid"))
    lines = ["<b>📢 نتیجه ترور</b>", ""]
    lines.append(f"🎯 <b>{rebel_tag}</b> از بازی خارج شد.")
    if result.get("target_eliminated"):
        lines.append(f"🩸 <b>{target_tag}</b> نیز از بازی خارج شد.")
    elif result.get("armor_consumed"):
        lines.append(
            f"🛡 زره <b>{target_tag}</b> مصرف شد و او در بازی ماند."
        )
    else:
        lines.append(f"🛡 <b>{target_tag}</b> در بازی ماند.")
    return "\n".join(lines)


def _public_name(game: Game, uid) -> str:
    p = game.players.get(int(uid)) if uid is not None else None
    if p is None:
        return "؟"
    from bot.nam10.engine import is_synthetic_player_uid

    from bot.app_state import custom_display_name

    name = custom_display_name(p.user_id) or p.full_name or str(uid)
    if is_synthetic_player_uid(p.user_id):
        from bot.game import synthetic_player_base_name

        name = synthetic_player_base_name(name)
    return html.escape(name)


async def announce_rebel_assassination_result(
    bot, game: Game, gm, result: dict
) -> None:
    from bot.nam10.night2_publish import _process_elim_side_effects

    affected = {
        int(result.get("rebel_uid") or 0),
        int(result.get("target_uid") or 0),
    }
    affected.discard(0)
    _process_elim_side_effects(game, gm, only_uids=affected)
    from bot.nam10.engine import is_synthetic_player_uid
    from bot.observer_delivery import (
        broadcast_to_alive_players,
        flush_elimination_notifications,
    )

    await broadcast_to_alive_players(
        bot,
        game,
        build_rebel_result_broadcast_html(game, result),
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await flush_elimination_notifications(bot, game)
    try:
        from bot.nam10.no_host_mafia_win import nam10_maybe_end_on_faction_win

        if await nam10_maybe_end_on_faction_win(
            bot,
            game,
            gm,
            elim_source="rebel_assassination",
            elim_uid=int(result.get("rebel_uid") or 0),
        ):
            return
    except Exception:
        logger.exception(
            "rebel assassination victory gate failed room=%s", game.room_code
        )
    try:
        from bot.nam10.nmnd_narrator import push_host_step

        await push_host_step(bot, game, gm)
    except Exception:
        logger.exception(
            "rebel assassination host refresh failed room=%s", game.room_code
        )


# ---------------------------------------------------------------------------
# Post-assassination day bypass (committed assassination -> next night)
# ---------------------------------------------------------------------------


REBEL_NEXT_NIGHT_ACT = "rebnext"


def build_rebel_next_night_panel_html() -> str:
    return (
        "<b>🌙 پایان روز — آماده‌سازی شب بعد</b>\n\n"
        "یاغی از قابلیت ترور خود استفاده کرده و از بازی خارج شده است؛ "
        "بنابراین امروز مرحله دفاعیه برگزار نمی‌شود.\n\n"
        "بازیکنان باقی‌مانده را برای استراحت نیمروزی آماده کنید تا تیم "
        "مافیا فرصت مشورت داشته باشد.\n\n"
        "پس از آماده‌شدن بازیکنان، برای آغاز اقدامات شب بعد، دکمه زیر را "
        "فشار دهید."
    )


async def prepare_post_assassination_day(
    bot, game: Game, gm, result: dict
) -> bool:
    """After a committed daytime Rebel assassination, cancel the rest of
    today's defence workflow and hand the assistant an explicit
    next-night button.

    Only a validly committed assassination reaches here (the caller is
    ``_act_final``); opening/cancelling the panel never bypasses the day.
    Idempotent per day and skipped entirely when the game already ended.
    """
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if not getattr(game, "nmnd_night2_rebel_assassin_used", False):
        return False
    if game.phase == Phase.ENDED:
        return False
    day = _day_of_game(game)
    if getattr(game, "nam10_assassin_bypass_day", None) == day:
        return False
    game.nam10_assassin_bypass_day = day
    from bot.nam10.dayflow import close_nam10_defense_for_assassination

    await close_nam10_defense_for_assassination(bot, game)
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return True
    from bot.nam10.night2 import _ui_key

    key = _ui_key(game, f"rebnext{day}", assistant_uid)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌙 شروع شب بعدی",
                    callback_data=_cb(game, REBEL_NEXT_NIGHT_ACT, assistant_uid),
                    style="primary",
                )
            ]
        ]
    )
    from bot.observer_delivery import register_mirror_prompt_pair

    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        key,
        build_rebel_next_night_panel_html(),
        kb,
        send_player=True,
        send_observer=True,
        observer_same_text=False,
        parse_mode="HTML",
    )
    _persist(game, "nam10_assassin_bypass_day")
    try:
        from bot.game_audit_log import log_event

        log_event(game, "nam10.assassination_day_bypassed", host_day=day)
    except Exception:
        pass
    return True


async def handle_nam10_rebel_next_night_press(
    callback, bot, game: Game, manager, as_uid: int, actor_uid: int
) -> None:
    """«🌙 شروع شب بعدی» — starts the existing next-night entry once."""
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or as_uid != assistant_uid:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    if game.phase == Phase.ENDED:
        await callback.answer("بازی پایان یافته است.", show_alert=True)
        return
    if not getattr(game, "nmnd_night2_rebel_assassin_used", False):
        await callback.answer("این دکمه دیگر معتبر نیست.", show_alert=True)
        return
    day = _day_of_game(game)
    if getattr(game, "nam10_assassin_bypass_day", None) != day:
        await callback.answer("این دکمه دیگر معتبر نیست.", show_alert=True)
        return
    if getattr(game, "nam10_assassin_night_started_day", None) == day:
        await callback.answer("شب بعدی آغاز شده است.", show_alert=True)
        return
    from bot.nam10.night2 import _ui_key

    ui_key = _ui_key(game, f"rebnext{day}", assistant_uid)
    from bot.main import _answer_mirror_claim
    from bot.observer_delivery import (
        apply_mirror_claim_winner,
        game_observer_mirror_active,
        try_claim_mirror_ui,
    )

    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    game.nam10_assassin_night_started_day = day
    from bot.nam10.night2 import _update_panel

    try:
        await _update_panel(
            bot,
            game,
            assistant_uid,
            ui_key,
            build_rebel_next_night_panel_html() + "\n\n<i>✅ شب بعدی آغاز شد.</i>",
            None,
        )
    except Exception:
        pass
    from bot.nam10.nmnd_narrator import nam10_day1_defense_no_votes_enter_night
    from bot.nam10.no_host_night1 import on_no_host_entered_night1

    nam10_day1_defense_no_votes_enter_night(game)
    await on_no_host_entered_night1(bot, game, manager)
    _persist(game, "nam10_assassin_next_night_started")
    try:
        from bot.game_audit_log import log_event

        log_event(game, "nam10.assassin_next_night_started", host_day=day)
    except Exception:
        pass
