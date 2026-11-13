"""Night v2 publication and mine-casualty flow (Namayande-10 fork).

Turns the committed internal night resolution (``night2.py``) into the
actual day transition:

1. Branch A (no mine): hand the night to the existing disciplinary
   elimination -> summary broadcast -> table inquiry -> day machine
   (``no_host_night_resolve`` / ``no_host_table_inquiry``). All pieces are
   the established Namayande implementations; this module only prepares
   the narrator state and pushes the existing helper panel.
2. Branch B (mine triggered by the confirmed plain Boss shot):
     - B1  announce mine activation to every player (buttonless) and send
       the nap request to the bot helper; the helper must press
       ``✅ خواب نیمروزی انجام شد`` and then explicitly confirm
       (two-step nap confirmation).
     - B2  send the mafia-exit selection panel to the authorised
       decision-maker (first living role in the priority chain
       رئیس مافیا -> یاغی -> هکر) and private waiting panels with
       ``✅ اوکی`` to every other living player.
     - B3  when the confirmed target and all waiting acknowledgements are
       in, eliminate the chosen mafia member exactly once through the
       established elimination semantics.
     - B4  continue with the same discipline/summary/day flow as Branch A.

Idempotency: stage transitions and sends are guarded by stage fields plus
the ``nmnd_night2_dispositions`` ledger, so duplicate callbacks, retries,
snapshot restores and service restarts can neither skip nor replay a
stage.
"""

from __future__ import annotations

import html
import logging

from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.app_state import manager
from bot.models import Game, Phase, Role
from bot.nam10.night2 import (
    BOSS_MODE_SHOT_NEUTRALIZED,
    ELIM_CAUSE_FORCE_SOLDIER,
    ELIM_CAUSE_FORCE_SNIPER,
    nam10_night2_mode,
)
from bot.nam10.nmnd_narrator import BazporsNarrCb
from bot.observer_delivery import (
    PlayerMirrorCb,
    broadcast_to_alive_players,
)
from bot.tg_send import safe_callback_answer, safe_send_message

logger = logging.getLogger(__name__)

ELIM_CAUSE_MINE_MAFIA = "mine_mafia"

# -- Publication stages (persisted on the game model) ------------------------
N2PUB_MINE_ANNOUNCE = "mine_announce"
N2PUB_MINE_NAP_WAIT = "mine_nap_wait"
N2PUB_MINE_NAP_CONFIRM = "mine_nap_confirm"
N2PUB_MINE_CHOOSER = "mine_chooser"
N2PUB_DISCIPLINE = "discipline_ask"

_MINE_STAGES_BEFORE_CHOICE = (
    N2PUB_MINE_ANNOUNCE,
    N2PUB_MINE_NAP_WAIT,
    N2PUB_MINE_NAP_CONFIRM,
)

# -- Helper (narrator Bzn callbacks) -----------------------------------------
NAP_PRESS_ACT = "nnap"       # ✅ خواب نیمروزی انجام شد
NAP_CONFIRM_ACT = "nnapok"   # second-step confirmation
NAP_BACK_ACT = "nnapback"    # back to step one
NARRATOR_PUBLISH_ACTS = frozenset(
    {NAP_PRESS_ACT, NAP_CONFIRM_ACT, NAP_BACK_ACT}
)

# -- Player mirror callbacks (PlayerMirrorCb) --------------------------------
PUB_ACT_CHOICE_PICK = "mpck"  # mafia chooser pick (tid = uid)
PUB_ACT_CHOICE_OK = "mpok"    # mafia chooser confirm
PUB_ACT_WAIT_OK = "mwok"      # waiting acknowledgement (others)
NIGHT2_PUBLISH_ACTS = frozenset(
    {PUB_ACT_CHOICE_PICK, PUB_ACT_CHOICE_OK, PUB_ACT_WAIT_OK}
)

MINE_ACTIVATE_BROADCAST_HTML = (
    "<b>💥 مین فعال شد!</b>\n\n"
    "برای مشخص‌شدن خروجی تیم مافیا، لازم است خواب نیمروزی برگزار شود تا "
    "اعضای این تیم دربارهٔ انتخاب یکی از نفرات خود تصمیم‌گیری کنند.\n\n"
    "لطفاً منتظر راهنمایی کمک‌کنندهٔ ربات بمانید."
)

MINE_HELPER_NAP_HTML = (
    "<b>💥 مین فعال شده است!</b>\n\n"
    "لطفاً از تمام بازیکنان بخواهید چشم‌های خود را ببندند تا اعضای تیم "
    "مافیا بتوانند دربارهٔ خروج یکی از نفرات خود مشورت کنند.\n\n"
    "پس از پایان خواب نیمروزی، دکمهٔ زیر را انتخاب کنید."
)

MINE_HELPER_NAP_CONFIRM_HTML = (
    "<b>💥 مین فعال شده است!</b>\n\n"
    "آیا خواب نیمروزی کامل شده است؟\n\n"
    "پس از تأیید نهایی، پنل انتخاب خروجی برای نمایندهٔ تیم مافیا ارسال "
    "می‌شود."
)

MINE_ARMS_DOWN_HTML = (
    "<b>📱 لطفاً از همهٔ بازیکنان بخواهید گوشی‌های خود را تحویل دهند.</b>\n\n"
    "پنل انتخاب خروجی برای نمایندهٔ تیم مافیا ارسال شد و تیم مافیا در حال "
    "تصمیم‌گیری است."
)

MINE_CHOOSER_PANEL_BODY = (
    "<b>🔴 انتخاب خروجی تیم مافیا</b>\n\n"
    "به‌دلیل فعال‌شدن مین، یک نفر از اعضای زندهٔ تیم مافیا باید از بازی "
    "خارج شود.\n\n"
    "پس از مشورت، بازیکن موردنظر را از گزینه‌های زیر انتخاب و تصمیم خود "
    "را تأیید کنید."
)

MINE_WAITING_BODY = (
    "<b>⏳ تیم مافیا در حال تصمیم‌گیری برای تعیین خروجی است.</b>\n\n"
    "لطفاً منتظر بمانید."
)

MINE_WAITING_DONE_BODY = (
    "<b>⏳ تیم مافیا در حال تصمیم‌گیری برای تعیین خروجی است.</b>\n\n"
    "<b>✅ آمادگی شما ثبت شد؛ لطفاً منتظر بمانید.</b>"
)

CHOOSER_CONFIRMED_BODY = (
    "<b>🔴 انتخاب خروجی تیم مافیا</b>\n\n"
    "<b>✅ تصمیم شما ثبت شد؛ لطفاً منتظر بمانید.</b>\n\n"
)


def night2_publication_active(game: Game) -> bool:
    return bool(getattr(game, "nmnd_night2_publication_active", False))


def night2_publication_stage(game: Game) -> str | None:
    return getattr(game, "nmnd_night2_publication_stage", None)


# ---------------------------------------------------------------------------
# Panel keys / shared helpers
# ---------------------------------------------------------------------------


def _ui_key(game: Game, prefix: str, uid: int) -> str:
    from bot.nam10.night2 import _ui_key as key

    return key(game, prefix, uid)


def _chooser_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2mchoice", uid)


def _mwait_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2mwait", uid)


def _seat_order(game: Game, players) -> list:
    return sorted(
        players,
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def _publish_panel_owner(bot, game, owner_uid: int, key: str, text: str, kb):
    from bot.nam10.night2 import _publish_panel

    return _publish_panel(bot, game, owner_uid, key, text, kb)


def _update_panel_owner(bot, game, owner_uid: int, key: str, text: str, kb):
    from bot.nam10.night2 import _update_panel

    return _update_panel(bot, game, owner_uid, key, text, kb)


def _button_label(game: Game, p, uid: int) -> str:
    from bot.nam10.night2 import _button_label as fn

    return fn(game, p, uid)


def _may_act(game: Game, actor_uid: int, owner_uid: int) -> bool:
    from bot.nam10.night2 import _may_act as fn

    return fn(game, actor_uid, owner_uid)


def _is_mafia_member(game: Game, p) -> bool:
    from bot.nam10.night2 import _is_mafia_member as fn

    return fn(game, p)


def _mine_mafia_targets(game: Game) -> list:
    """Living mafia-team members in seat order (authoritative membership)."""
    out = [
        p
        for p in game.players.values()
        if p.is_alive and _is_mafia_member(game, p)
    ]
    return _seat_order(game, out)


def _mine_chooser_uid(game: Game) -> int | None:
    """First living role in the priority chain: Boss -> Rebel -> Hacker."""
    from bot.nam10.night2 import _holder

    for role in (Role.MAFIA_BOSS, Role.NATO, Role.SHIAD):
        holder = _holder(game, role)
        if holder is not None:
            return holder.user_id
    return None


def _audit(game: Game, event: str, **kw) -> None:
    try:
        from bot.game_audit_log import log_event

        log_event(game, event, **kw)
    except Exception:
        pass


def _persist(game: Game, reason: str) -> None:
    try:
        manager.persist_snapshot(game, reason=reason)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Elimination side effects (mirror the legacy elimination machinery)
# ---------------------------------------------------------------------------


def _night_eliminations_this_night(game: Game) -> list[dict]:
    nc = int(game.nmnd_narrator_night_count or 0)
    return [
        rec
        for rec in list(game.nmnd_night2_eliminations)
        if int(rec.get("night") or 0) == nc and rec.get("uid") in game.players
    ]


def _process_elim_side_effects(game: Game, gm, only_uids: set[int] | None = None) -> None:
    """Legacy elimination side effects for published night deaths.

    Queues the established eliminated-player notification (delivered by
    ``flush_elimination_notifications`` after the night summary) and
    applies the hunter-chain / interrog sync behaviour of
    ``_eliminate_player``. Runs exactly once per (uid, night).
    """
    from bot.observer_delivery import queue_player_elimination_notify
    from bot.nam10.nmnd_narrator import (
        _hunter_companion_if_eliminated,
        _sync_interrog_day_state,
    )

    nc = int(game.nmnd_narrator_night_count or 0)
    with_mark = str(nc)
    for rec in _night_eliminations_this_night(game):
        uid = int(rec.get("uid") or 0)
        if only_uids is not None and uid not in only_uids:
            continue
        pl = game.players.get(uid)
        if pl is None or pl.is_alive:
            continue
        mark = f"pub_elim_notify:{uid}"
        if game.nmnd_night2_dispositions.get(mark) == with_mark:
            continue
        game.nmnd_night2_dispositions[mark] = with_mark
        queue_player_elimination_notify(game, uid)
        try:
            _hunter_companion_if_eliminated(game, gm, uid, public=False)
        except Exception:
            logger.exception(
                "night2 hunter companion side effect failed room=%s uid=%s",
                game.room_code,
                uid,
            )
        _sync_interrog_day_state(game)


# ---------------------------------------------------------------------------
# Tick: start / continue the publication flow
# ---------------------------------------------------------------------------


async def nam10_night2_publish_tick(bot, game: Game, gm) -> bool:
    """Run/continue the post-resolution publication flow.

    Safe to call repeatedly (act dispatch, helper callbacks, snapshot
    restore reissue): every call either advances a stage or does nothing.
    """
    if game.phase == Phase.ENDED:
        return False
    try:
        from bot.nam10.night2 import PENDING_COLLECTING

        if game.nmnd_night2_phase != PENDING_COLLECTING:
            # شب از فاز جمع‌آوری خارج شده — یادآور کمک‌کننده دیگر لازم نیست.
            from bot.night_helper_reminder import cleanup_night_helper_reminder

            await cleanup_night_helper_reminder(bot, game)
    except Exception:
        pass
    if not game.nmnd_night2_publication_pending:
        return False
    if not game.nmnd_night2_resolved:
        return False
    _process_elim_side_effects(game, gm)
    if not night2_publication_active(game):
        # The mine branch is decided by the authoritative internal outcome.
        if game.nmnd_night2_mine_casualty_pending:
            game.nmnd_night2_publication_stage = N2PUB_MINE_ANNOUNCE
        else:
            game.nmnd_night2_publication_stage = N2PUB_DISCIPLINE
        game.nmnd_night2_publication_active = True
        _audit(
            game,
            "night2.publication_started",
            night=game.nmnd_night2_night_count,
            mine_branch=game.nmnd_night2_mine_casualty_pending,
        )
        _persist(game, "night2_publication_started")
    return await _advance_publication(bot, game, gm)


async def _advance_publication(bot, game: Game, gm) -> bool:
    stage = night2_publication_stage(game)
    if stage is None:
        stage = (
            N2PUB_MINE_ANNOUNCE
            if game.nmnd_night2_mine_casualty_pending
            else N2PUB_DISCIPLINE
        )
        game.nmnd_night2_publication_stage = stage
    if game.nmnd_night2_mine_casualty_pending and stage in _MINE_STAGES_BEFORE_CHOICE:
        return await _advance_mine_announce(bot, game, gm, stage)
    if stage == N2PUB_MINE_CHOOSER:
        if game.nmnd_night2_mine_casualty_pending:
            applied = _maybe_apply_mine_casualty(bot, game, gm)
            if not applied:
                return False
        # Applied or already applied: fall through to the discipline ask.
        game.nmnd_night2_publication_stage = N2PUB_DISCIPLINE
    if night2_publication_stage(game) == N2PUB_DISCIPLINE:
        return await _start_discipline_stage(bot, game, gm)
    return False


# ---------------------------------------------------------------------------
# Branch B: mine announcement, nap two-step, mafia choice
# ---------------------------------------------------------------------------


async def _advance_mine_announce(bot, game: Game, gm, stage: str) -> bool:
    if stage == N2PUB_MINE_ANNOUNCE:
        if not game.nmnd_night2_mine_announced:
            # Announce exactly once per night.
            game.nmnd_night2_mine_announced = True
            from bot.nam10.engine import is_synthetic_player_uid

            await broadcast_to_alive_players(
                bot,
                game,
                MINE_ACTIVATE_BROADCAST_HTML,
                parse_mode="HTML",
                is_synthetic_uid=is_synthetic_player_uid,
            )
            assistant = game.bot_assistant_user_id
            if assistant is not None:
                from bot.nam10.nmnd_narrator import BazporsNarrCb

                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ خواب نیمروزی انجام شد",
                                style="success",
                                callback_data=BazporsNarrCb(
                                    code=game.room_code,
                                    act=NAP_PRESS_ACT,
                                ).pack(),
                            )
                        ]
                    ]
                )
                await safe_send_message(
                    bot,
                    assistant,
                    MINE_HELPER_NAP_HTML,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            _audit(
                game,
                "night2.mine_activation_announced",
                night=game.nmnd_night2_night_count,
            )
        game.nmnd_night2_publication_stage = N2PUB_MINE_NAP_WAIT
        _persist(game, "night2_mine_b1")
        return True
    # NAP_WAIT / NAP_CONFIRM: nothing to do until the helper acts.
    return False


def _mine_wait_pending_uids(game: Game) -> list[int]:
    chooser = game.nmnd_night2_mine_chooser_uid
    acked = set(game.nmnd_night2_mine_wait_acked or [])
    alives = _seat_order(
        game,
        [pl for pl in game.players.values() if pl.is_alive],
    )
    return [
        pl.user_id
        for pl in alives
        if pl.user_id != chooser and pl.user_id not in acked
    ]


def _mine_wait_keyboard(game: Game, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ اوکی",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=PUB_ACT_WAIT_OK, as_uid=uid
                    ).pack(),
                    style="primary",
                )
            ]
        ]
    )


def _chooser_rows(game: Game, uid: int) -> list[list[InlineKeyboardButton]]:
    pending = game.nmnd_night2_mine_chooser_pending_uid
    rows: list[list[InlineKeyboardButton]] = []
    for p in _mine_mafia_targets(game):
        sel = p.user_id == pending
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_label(game, p, p.user_id),
                    style="danger" if sel else "primary",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act=PUB_ACT_CHOICE_PICK,
                        as_uid=uid,
                        tid=p.user_id,
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ تأیید",
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act=PUB_ACT_CHOICE_OK, as_uid=uid
                ).pack(),
                style="success",
            )
        ]
    )
    return rows


async def _send_mine_chooser_panel(bot, game: Game, uid: int) -> None:
    from bot.nam10.night2 import _publish_panel

    key = _chooser_key(game, uid)
    body = MINE_CHOOSER_PANEL_BODY
    if game.nmnd_night2_mine_casualty_uid is not None:
        tpl = game.players.get(game.nmnd_night2_mine_casualty_uid)
        body = (
            CHOOSER_CONFIRMED_BODY
            + "بازیکن انتخاب‌شده: "
            + _button_label(game, tpl, game.nmnd_night2_mine_casualty_uid)
        )
        await _publish_panel(
            bot, game, uid, key, body, None
        )
        return
    body = MINE_CHOOSER_PANEL_BODY
    rows = _chooser_rows(game, uid)
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def _arm_mine_choice(bot, game: Game, gm) -> bool:
    chooser = _mine_chooser_uid(game)
    targets = _mine_mafia_targets(game)
    if chooser is None or not targets:
        # Safely unresolved: no authorised decision-maker exists. Record
        # the deferred consequence; never invent a victim or a chooser.
        game.nmnd_night2_dispositions["mine_casualty"] = (
            f"unresolvable:{game.nmnd_night2_night_count}"
        )
        game.nmnd_night2_mine_casualty_pending = False
        _update_mine_outcome(
            game,
            {
                "mafia_casualty_deferred": False,
                "mafia_casualty_uid": None,
                "mafia_casualty_unresolved": True,
            },
        )
        _audit(
            game,
            "night2.mine_casualty_unresolvable",
            night=game.nmnd_night2_night_count,
        )
        _persist(game, "night2_mine_casualty_unresolvable")
        from bot.nam10.night2 import night2_apply_deferred_sniper_elimination

        night2_apply_deferred_sniper_elimination(game)
        _process_elim_side_effects(game, gm)
        _persist(game, "night2_sniper_deferred_applied")
        game.nmnd_night2_publication_stage = N2PUB_DISCIPLINE
        assistant = game.bot_assistant_user_id
        if assistant is not None:
            await safe_send_message(
                bot,
                assistant,
                "⚠️ پیامد مین: هیچ نمایندهٔ زنده‌ای با نقش "
                "رئیس مافیا، یاغی یا هکر برای تصمیم‌گیری خروجی تیم مافیا "
                "یافت نشد؛ این مرحله بدون حذف خودکار متوقف ماند.",
                parse_mode="HTML",
            )
        return True

    game.nmnd_night2_mine_chooser_uid = chooser
    game.nmnd_night2_mine_chooser_pending_uid = None
    game.nmnd_night2_mine_wait_acked = [
        uid
        for uid in (game.nmnd_night2_mine_wait_acked or [])
        if uid != chooser
    ]
    game.nmnd_night2_publication_stage = N2PUB_MINE_CHOOSER
    _persist(game, "night2_mine_choice_armed")

    # Helper guidance (arms-down message) — once per night.
    if game.nmnd_night2_dispositions.get("mine_b2_sent") != "1":
        game.nmnd_night2_dispositions["mine_b2_sent"] = "1"
        assistant = game.bot_assistant_user_id
        if assistant is not None:
            await safe_send_message(
                bot, assistant, MINE_ARMS_DOWN_HTML, parse_mode="HTML"
            )

    # Chooser selection panel (mirror-routed; the Observer operates a
    # synthetic seat through the standard mirror policy).
    await _send_mine_chooser_panel(bot, game, chooser)

    # Private waiting panels with OK for every other living player.
    waiting = _mine_wait_pending_uids(game)
    for uid in waiting:
        from bot.nam10.night2 import _publish_panel

        await _publish_panel(
            bot,
            game,
            uid,
            _mwait_key(game, uid),
            MINE_WAITING_BODY,
            _mine_wait_keyboard(game, uid),
        )
    _audit(
        game,
        "night2.mine_choice_panels_dispatched",
        night=game.nmnd_night2_night_count,
        chooser_uid=chooser,
        waiting_uids=waiting,
    )
    _persist(game, "night2_mine_choice_dispatched")
    return True


def _maybe_apply_mine_casualty(bot, game: Game, gm) -> bool:
    """Apply the chosen mafia exit once every requirement is satisfied."""
    if night2_publication_stage(game) != N2PUB_MINE_CHOOSER:
        return False
    if not game.nmnd_night2_mine_casualty_pending:
        game.nmnd_night2_publication_stage = N2PUB_DISCIPLINE
        return True
    target = game.nmnd_night2_mine_casualty_uid
    if target is None:
        # The authorised decision-maker has not confirmed yet.
        return False
    if _mine_wait_pending_uids(game):
        # Waiting acknowledgements still outstanding.
        return False
    _apply_mine_casualty(game, gm, target)
    # Room 32 ordering: the deferred temporary-Sniper elimination is
    # applied strictly AFTER the confirmed Mafia sacrifice.
    from bot.nam10.night2 import night2_apply_deferred_sniper_elimination

    night2_apply_deferred_sniper_elimination(game)
    _process_elim_side_effects(game, gm)
    _persist(game, "night2_sniper_deferred_applied")
    game.nmnd_night2_publication_stage = N2PUB_DISCIPLINE
    return True


def _update_mine_outcome(game: Game, updates: dict) -> None:
    outcome = game.nmnd_night2_outcome
    if not isinstance(outcome, dict):
        outcome = {}
        game.nmnd_night2_outcome = outcome
    mine = dict(outcome.get("mine") or {})
    mine.update(updates)
    outcome["mine"] = mine


# ---------------------------------------------------------------------------
# Branch B player mirror acts (chooser pick/confirm, waiting ok)
# ---------------------------------------------------------------------------


async def dispatch_night2_publish_act(
    callback: CallbackQuery,
    bot,
    game: Game,
    gm,
    *,
    actor_uid: int,
    act: str,
    as_uid: int,
    tid: int,
) -> None:
    if game.phase == Phase.ENDED or not night2_publication_active(game):
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not _may_act(game, actor_uid, as_uid):
        await callback.answer("این پنل برای شما نیست.", show_alert=True)
        return
    pl = game.players.get(as_uid)
    if pl is None or not pl.is_alive:
        await callback.answer("نامعتبر.", show_alert=True)
        return

    stage = night2_publication_stage(game)

    if act == PUB_ACT_CHOICE_PICK:
        if stage != N2PUB_MINE_CHOOSER:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if game.nmnd_night2_mine_casualty_uid is not None:
            await callback.answer("تأیید قبلاً ثبت شده است.", show_alert=True)
            return
        if game.nmnd_night2_mine_chooser_uid != as_uid:
            await callback.answer(
                "این پنل فقط برای نمایندهٔ تیم مافیا است.", show_alert=True
            )
            return
        if as_uid not in {t.user_id for t in _mine_mafia_targets(game)}:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        if tid not in {t.user_id for t in _mine_mafia_targets(game)}:
            await callback.answer("هدف نامعتبر است.", show_alert=True)
            return
        if game.nmnd_night2_mine_chooser_pending_uid == tid:
            game.nmnd_night2_mine_chooser_pending_uid = None
        else:
            game.nmnd_night2_mine_chooser_pending_uid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        await _send_mine_chooser_panel(bot, game, as_uid)
        _persist(game, "night2_mine_choice_selected")
        return

    if act == PUB_ACT_CHOICE_OK:
        if stage != N2PUB_MINE_CHOOSER:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if game.nmnd_night2_mine_chooser_uid != as_uid:
            await callback.answer(
                "این پنل فقط برای نمایندهٔ تیم مافیا است.", show_alert=True
            )
            return
        if game.nmnd_night2_mine_casualty_uid is not None:
            await callback.answer("تأیید قبلاً ثبت شده است.", show_alert=True)
            return
        target = game.nmnd_night2_mine_chooser_pending_uid
        if not target:
            await callback.answer(
                "ابتدا یک بازیکن را انتخاب کنید.", show_alert=True
            )
            return
        # Re-validate eligibility at confirmation time.
        tpl = game.players.get(target)
        if tpl is None or not tpl.is_alive or not any(
            t.user_id == target for t in _mine_mafia_targets(game)
        ):
            await callback.answer("هدف نامعتبر است.", show_alert=True)
            return
        game.nmnd_night2_mine_casualty_uid = target
        game.nmnd_night2_mine_chooser_pending_uid = None
        await callback.answer("ثبت شد.")
        from bot.nam10.night2 import _update_panel

        await _update_panel(
            bot,
            game,
            as_uid,
            _chooser_key(game, as_uid),
            CHOOSER_CONFIRMED_BODY
            + "بازیکن انتخاب‌شده: "
            + _button_label(game, tpl, target),
            None,
        )
        _audit(
            game,
            "night2.mine_casualty_confirmed",
            chooser_uid=as_uid,
            target_uid=target,
            night=game.nmnd_night2_night_count,
        )
        _persist(game, "night2_mine_casualty_confirmed")
        await _advance_publication(bot, game, gm)
        return

    if act == PUB_ACT_WAIT_OK:
        if stage != N2PUB_MINE_CHOOSER:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if game.nmnd_night2_mine_chooser_uid == as_uid:
            # The authorised decision-maker cannot ack the waiting panel.
            await callback.answer(
                "شما باید از پنل انتخاب خروجی استفاده کنید.", show_alert=True
            )
            return
        if as_uid in (game.nmnd_night2_mine_wait_acked or []):
            await callback.answer("قبلاً ثبت شده است.", show_alert=True)
            return
        game.nmnd_night2_mine_wait_acked = list(
            game.nmnd_night2_mine_wait_acked or []
        )
        game.nmnd_night2_mine_wait_acked.append(as_uid)
        await callback.answer("ثبت شد.")
        from bot.nam10.night2 import _update_panel

        await _update_panel(
            bot,
            game,
            as_uid,
            _mwait_key(game, as_uid),
            MINE_WAITING_DONE_BODY,
            None,
        )
        _audit(
            game,
            "night2.mine_wait_acked",
            uid=as_uid,
            night=game.nmnd_night2_night_count,
            remaining=_mine_wait_pending_uids(game),
        )
        _persist(game, "night2_mine_wait_acked")
        await _advance_publication(bot, game, gm)
        return

    await callback.answer("نامعتبر.", show_alert=True)


def _apply_mine_casualty(game: Game, gm, uid: int) -> None:
    from bot.nam10.night2 import night2_apply_elimination

    # Established elimination semantics (is_alive + durable record +
    # rebel unlock + audit), then the legacy notification/hunter-chain
    # behaviour through the shared side-effect helper.
    night2_apply_elimination(game, uid, ELIM_CAUSE_MINE_MAFIA)
    _process_elim_side_effects(game, gm, only_uids={uid})
    game.nmnd_night2_mine_casualty_uid = uid
    game.nmnd_night2_mine_casualty_pending = False
    game.nmnd_night2_dispositions[f"mine_casualty:{uid}"] = "applied"
    _update_mine_outcome(
        game,
        {
            "mafia_casualty_deferred": False,
            "mafia_casualty_uid": uid,
            "mafia_casualty_applied": True,
        },
    )
    try:
        win = gm.check_winner(game) if gm is not None else None
        if win:
            _audit(
                game,
                "night2.mine_casualty_game_ended",
                uid=uid,
                winner=win,
            )
    except Exception:
        pass
    _audit(
        game,
        "night2.mine_casualty_applied",
        uid=uid,
        night=game.nmnd_night2_night_count,
        chooser_uid=game.nmnd_night2_mine_chooser_uid,
    )
    _persist(game, "night2_mine_casualty_applied")


# ---------------------------------------------------------------------------
# Narrator (helper) callbacks: nap two-step confirmation
# ---------------------------------------------------------------------------


def _nap_kb(game: Game, act: str) -> InlineKeyboardMarkup:
    from bot.nam10.nmnd_narrator import BazporsNarrCb

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        "✅ خواب نیمروزی انجام شد"
                        if act == NAP_PRESS_ACT
                        else "✅ تأیید نهایی خواب نیمروزی"
                    ),
                    style="success"
                    if act == NAP_PRESS_ACT
                    else "success",
                    callback_data=BazporsNarrCb(
                        code=game.room_code, act=act
                    ).pack(),
                )
            ]
        ]
    )


async def handle_narrator_publish_act(
    callback: CallbackQuery, bot, game: Game, gm, act: str
) -> bool:
    """Helper nap buttons; returns True when the act was routed here."""
    if act not in NARRATOR_PUBLISH_ACTS:
        return False
    operator = game.bot_assistant_user_id
    obs = game.observer_user_id
    actor = callback.from_user.id if callback.from_user else None
    if actor is None or actor not in (operator, obs):
        await safe_callback_answer(
            callback, "این دکمه مخصوص کمک‌کنندهٔ ربات است.", show_alert=True
        )
        return True
    stage = night2_publication_stage(game)

    if act == NAP_PRESS_ACT:
        if stage != N2PUB_MINE_NAP_WAIT:
            await safe_callback_answer(
                callback, "این مرحله دیگر فعال نیست.", show_alert=True
            )
            return True
        game.nmnd_night2_publication_stage = N2PUB_MINE_NAP_CONFIRM
        _persist(game, "night2_mine_nap_step2")
        _audit(
            game,
            "night2.mine_nap_pressed",
            night=game.nmnd_night2_night_count,
            actor_uid=actor,
        )
        body = MINE_HELPER_NAP_CONFIRM_HTML
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ تأیید نهایی خواب نیمروزی",
                        style="success",
                        callback_data=BazporsNarrCb(
                            code=game.room_code, act=NAP_CONFIRM_ACT
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ بازگشت",
                        style="primary",
                        callback_data=BazporsNarrCb(
                            code=game.room_code, act=NAP_BACK_ACT
                        ).pack(),
                    )
                ],
            ]
        )
        message = callback.message
        edited = False
        if message is not None:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    text=body,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                edited = True
            except Exception:
                edited = False
        await safe_callback_answer(callback, "ثبت شد.")
        if not edited:
            await safe_send_message(
                bot, actor, body, parse_mode="HTML", reply_markup=kb
            )
        return True

    if act == NAP_BACK_ACT:
        if stage != N2PUB_MINE_NAP_CONFIRM:
            await safe_callback_answer(
                callback, "این مرحله دیگر فعال نیست.", show_alert=True
            )
            return True
        game.nmnd_night2_publication_stage = N2PUB_MINE_NAP_WAIT
        _persist(game, "night2_mine_nap_back")
        await safe_callback_answer(callback, "بازگشت ثبت شد.")
        try:
            if callback.message is not None:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=MINE_HELPER_NAP_HTML,
                    parse_mode="HTML",
                    reply_markup=_nap_kb(game, NAP_PRESS_ACT),
                )
        except Exception:
            await safe_send_message(
                bot,
                actor,
                MINE_HELPER_NAP_HTML,
                parse_mode="HTML",
                reply_markup=_nap_kb(game, NAP_PRESS_ACT),
            )
        return True

    # NAP_CONFIRM_ACT — the explicit second-step confirmation.
    if stage != N2PUB_MINE_NAP_CONFIRM:
        await safe_callback_answer(
            callback, "این مرحله دیگر فعال نیست.", show_alert=True
        )
        return True
    game.nmnd_night2_mine_nap_confirmed = True
    game.nmnd_night2_dispositions[
        f"mine_nap_confirmed:{game.nmnd_night2_night_count}"
    ] = "1"
    _audit(
        game,
        "night2.mine_nap_confirmed",
        night=game.nmnd_night2_night_count,
        actor_uid=actor,
    )
    await safe_callback_answer(callback, "ثبت شد.")
    if callback.message is not None:
        try:
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text="✅ خواب نیمروزی تأیید شد.\n\n📱 پنل انتخاب خروجی در "
                "حال ارسال است…",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass
    await _arm_mine_choice(bot, game, gm)
    return True


# ---------------------------------------------------------------------------
# Branch A / B4: discipline ask (existing helper panel)
# ---------------------------------------------------------------------------


def _check_game_ended(game: Game, gm) -> bool:
    try:
        return bool(gm.check_winner(game)) if gm is not None else False
    except Exception:
        return False


async def _resolve_publication_game_ended(
    bot, game: Game, gm, asked_key: str
) -> bool:
    """Win already decided at publication time — skip the discipline ask.

    When the winner is already determined when the publication flow
    reaches the discipline stage (established ``check_winner``
    semantics), asking the assistant for a disciplinary elimination
    would be pointless — but the established post-night flow must still
    run so the night results are broadcast and the winner is announced
    and finalized. This hand-off reproduces exactly the state the
    established ``disc_no_ok`` confirmation passes to
    ``nam10_complete_discipline_and_resolve`` (kick=None, no
    disciplinary broadcast); that path then finishes through the
    established faction-win handler
    (``nam10_maybe_end_on_faction_win``).
    """
    from bot.nam10.nmnd_narrator import (
        CONFIRM_DISCIPLINE_NO,
        NS_DISCIPLINE_ASK,
        nam10_assistant_narrator_active,
    )

    _audit(
        game,
        "night2.publication_game_ended",
        night=game.nmnd_night2_night_count,
    )
    if not nam10_assistant_narrator_active(game):
        # The hand-off is defined for the established assistant-driven
        # no-host contract; leave any other configuration untouched.
        return False
    # Mirror the confirmed-no-kick state of the established flow.
    game.nmnd_night_discipline_kick_uid = None
    game.nmnd_narrator_step = CONFIRM_DISCIPLINE_NO
    game.nmnd_night_substep = NS_DISCIPLINE_ASK
    _persist(game, "night2_discipline_game_ended")
    from bot.nam10.no_host_night_resolve import (
        nam10_complete_discipline_and_resolve,
    )

    try:
        await nam10_complete_discipline_and_resolve(
            bot,
            game,
            gm,
            send_discipline_broadcast=False,
        )
    except Exception:
        logger.exception(
            "night2 game-end resolve failed room=%s", game.room_code
        )
        return False
    # Publication is settled together with the game end: retries,
    # replayed callbacks or snapshot-restore reissues must not re-run it.
    # NOTE: no snapshot persist here — the finalize path above already
    # removed the room snapshot (end_game -> delete_game_snapshot); a
    # persist after that would resurrect a stale, already-ended room
    # snapshot row for the next restart's restore pass.
    game.nmnd_night2_dispositions[asked_key] = "1"
    game.nmnd_night2_dispositions[
        f"discipline_game_ended:{game.nmnd_night2_night_count}"
    ] = "resolved"
    game.nmnd_night2_publication_pending = False
    game.nmnd_night2_publication_stage = None
    return True


async def _start_discipline_stage(bot, game: Game, gm) -> bool:
    """Hand the night to the established disciplinary flow."""
    # Deliver the ask panel exactly once per night (no duplicates on
    # retries, extra ticks or snapshot-restore reissues). The legacy
    # narrator/panel machinery owns every later refresh.
    asked_key = f"discipline_asked:{game.nmnd_night2_night_count}"
    if game.nmnd_night2_dispositions.get(asked_key) == "1":
        return False
    if _check_game_ended(game, gm):
        return await _resolve_publication_game_ended(bot, game, gm, asked_key)
    game.nmnd_night2_publication_stage = N2PUB_DISCIPLINE
    from bot.nam10.nmnd_narrator import (
        NS_DISCIPLINE_ASK,
        NIGHT_ACTIONS,
        _deliver_current_host_panel,
    )

    game.nmnd_narrator_step = NIGHT_ACTIONS
    game.nmnd_night_substep = NS_DISCIPLINE_ASK
    game.nmnd_night_discipline_kick_uid = None
    _audit(
        game,
        "night2.discipline_dispatched",
        night=game.nmnd_night2_night_count,
        mine_casualty_applied=game.nmnd_night2_mine_casualty_uid is not None,
    )
    _persist(game, "night2_discipline_ask")
    try:
        await _deliver_current_host_panel(
            bot, game, gm, force_new_message=True
        )
    except Exception:
        logger.exception(
            "night2 discipline panel delivery failed room=%s",
            game.room_code,
        )
        return False
    # Mark only after a successful delivery so a failed send can be
    # retried on the next tick.
    game.nmnd_night2_dispositions[asked_key] = "1"
    _persist(game, "night2_discipline_ask_delivered")
    return True


# ---------------------------------------------------------------------------
# Night-report bridge (host / observer full report parity)
# ---------------------------------------------------------------------------


def _n2r_name_of(game: Game, gm, uid) -> str:
    pl = game.players.get(uid) if uid is not None else None
    if pl is None:
        return "؟"
    try:
        return html.escape(gm.format_player_tag(pl))
    except Exception:
        return html.escape(str(getattr(pl, "full_name", None) or uid))


def _n2r_role_label(guessed) -> str:
    if not guessed:
        return None
    from bot.nam10.role_labels import nam10_role_label_fa

    try:
        return nam10_role_label_fa(Role(guessed))
    except ValueError:
        return None


def night2_night_report_extra_section(game: Game, gm) -> str:
    """Host-only full night report lines derived from the night2 outcome.

    The public summary broadcast never uses these lines. This is the
    authoritative role-by-role block for Night v2 rooms; every line is
    backed by the committed outcome or the persisted night state — a
    skipped, intercepted, cancelled or already-spent ability is labelled
    as such and is never silently omitted.
    """
    if not nam10_night2_mode(game):
        return ""
    outcome = game.nmnd_night2_outcome if isinstance(game.nmnd_night2_outcome, dict) else {}
    dispositions = game.nmnd_night2_dispositions if isinstance(
        game.nmnd_night2_dispositions, dict
    ) else {}

    def name_of(uid):
        return _n2r_name_of(game, gm, uid)

    lines: list[str] = []

    # 0) NATO (Mafia Boss) — always first when this night used it ----------
    nato = outcome.get("nato") or {}
    nato_activated = bool(nato.get("activated"))
    if nato_activated:
        role_txt = _n2r_role_label(nato.get("guessed_role"))
        t_name = (
            name_of(nato.get("target_uid"))
            if nato.get("target_uid") is not None
            else None
        )
        lines.append(
            "🎭 ناتویی مافیا: موفق"
            if nato.get("success")
            else "🎭 ناتویی مافیا: ناموفق"
        )
        lines.append(
            f"🎯 نقش حدس‌زده‌شده: {role_txt}"
            if role_txt
            else "🎯 نقش حدس‌زده‌شده: ثبت نشد."
        )
        lines.append(
            f"👤 بازیکن انتخاب‌شده: {t_name}"
            if t_name
            else "👤 بازیکن انتخاب‌شده: ثبت نشد."
        )
        lines.append(
            "🚪 نتیجه: بازیکن انتخاب‌شده از بازی خارج شد."
            if nato.get("eliminated")
            else "📋 نتیجه: هیچ بازیکنی بر اثر ناتویی از بازی خارج نشد."
        )
        mine_out = outcome.get("mine") or {}
        if nato.get("eliminated") and mine_out.get("triggered_by_nato"):
            lines.append("💣 مین روی هدف ناتو منفجر شد.")
    elif nato.get("incomplete"):
        lines.append("⚪ ناتویی: ناقص ثبت شد.")

    # 1) Mafia shot -------------------------------------------------------
    shot = game.nmnd_night2_shot_result or {}
    outcome_shot = outcome.get("shot") or {}
    mode = shot.get("mode") or outcome_shot.get("mode")
    # Night-v2 shot state is durable across nights so late retries keep
    # the authoritative record; it must never be rendered into a night
    # it does not belong to (a Night v2 NATO night must not inherit the
    # previous night's confirmed shot or its mine-neutralization line).
    shot_night = shot.get("night")
    shot_is_current_night = (
        shot_night is not None
        and int(shot_night) == int(game.nmnd_night2_night_count or 0)
    )
    if nato_activated:
        # A NATO night has NO ordinary Mafia shot; the NATO block above
        # fully replaces the shot line (nothing to register).
        pass
    elif shot.get("accepted") and shot_is_current_night:
        t_name = name_of(shot.get("target_uid"))
        if shot.get("mode") == BOSS_MODE_SHOT_NEUTRALIZED:
            mode_fa = "با خنثی‌سازی"
        else:
            mode_fa = "بدون خنثی‌سازی"
        mine_disp = shot.get("mine_disposition")
        if shot.get("eliminated"):
            lines.append(f"🔴 شات مافیا: {mode_fa} — هدف: {t_name}")
            if mine_disp == "triggered":
                lines.append("💣 مین روی هدف شات منفجر شد.")
                cas = game.nmnd_night2_mine_casualty_uid
                if cas is not None:
                    lines.append(
                        f"💥 مین فعال شد — خروجی مافیا: {name_of(cas)}"
                    )
                else:
                    lines.append(
                        "💥 مین فعال شد — خروجی مافیا هنوز مشخص نشده است."
                    )
            elif mine_disp == "neutralized":
                # FINAL matrix: with neutralization the mine never
                # explodes and no Mafia-casualty selection runs.
                lines.append("💣 مین روی هدف شات خنثی شد.")
            elif mine_disp == "permanently_neutralized":
                # Legacy value from records written before the final
                # matrix; frozen historical reports render unchanged.
                lines.append("💣 مین خنثی شد.")
        else:
            lines.append(f"🔴 شات مافیا: {mode_fa} — هدف: {t_name}")
            lines.append(
                "💉 پزشک بازیکن هدف را نجات داد؛ بازیکن از بازی خارج نشد."
            )
            if mine_disp == "neutralized":
                lines.append("💣 مین روی هدف شات خنثی شد.")
    elif outcome_shot.get("skipped") and outcome_shot.get("reason") == "nato_mode":
        pass
    else:
        lines.append("🔴 شات مافیا: ثبت نشد.")

    # 2) Hacker ------------------------------------------------------------
    pair = list(game.nmnd_night2_hacker_uids or [])
    if len(pair) == 2:
        lines.append(
            f"💻 هکر: مبدأ: {name_of(pair[0])} — مقصد: {name_of(pair[1])}"
        )
    else:
        lines.append("💻 هکر: ثبت نشد.")

    # 3) Doctor -------------------------------------------------------------
    doc = outcome.get("doctor") or {}
    if doc.get("cancelled"):
        reason = str(doc.get("cancelled_reason") or "")
        if reason == "cancelled_by_nato":
            # NATO belongs to the Mafia Boss, not to the Rebel/Yaghi.
            lines.append("💉 پزشک: به دلیل اجرای ناتویی، امشب امکان نجات نداشت.")
        else:
            lines.append("💉 پزشک: قابلیت این شب لغو شد.")
    elif doc.get("save_target_uid") is not None:
        if (
            shot_is_current_night
            and shot.get("doctor_save_ineffective")
            and doc.get("save_target_uid") == shot.get("target_uid")
        ):
            lines.append(
                "💉 نجات پزشک نتوانست مانع خروج بازیکن بر اثر انفجار مین شود."
            )
        else:
            status = (
                "توسط هکر خنثی شد"
                if doc.get("nullified_by_hacker")
                else "ثبت شد"
            )
            lines.append(
                f"💉 پزشک: هدف نجات: {name_of(doc.get('save_target_uid'))} — {status}"
            )
    else:
        lines.append("💉 پزشک: ثبت نشد.")

    # 4) Guide + granted extra investigation ---------------------------------
    guide = outcome.get("guide") or {}
    kind = guide.get("grant_kind")
    recipient = guide.get("recipient_uid")
    if recipient is None:
        lines.append("🧭 راهنما: ثبت نشد.")
    else:
        kind_txt = {
            "extra_sent": "استعلام کارآگاهی اعطا شد",
            "intercepted": "توسط هکر قطع شد",
            "mafia_id": "هویت راهنما به بازیکن اطلاع داده شد",
            "dead": "هدف خارج از بازی بود",
        }.get(str(kind), str(kind))
        lines.append(
            f"🧭 راهنما: بازیکن انتخاب‌شده: {name_of(recipient)}"
            + (f" — {kind_txt}" if kind_txt else "")
        )
        if str(kind) == "extra_sent":
            ex_target = guide.get("extra_target_uid")
            if ex_target is None:
                lines.append(
                    f"🔎 استعلام: در اختیار {name_of(guide.get('extra_uid'))}"
                    " قرار گرفت."
                )
            else:
                result_txt = {
                    "positive": "مثبت",
                    "negative": "منفی",
                }.get(str(guide.get("extra_result") or ""), "ثبت شد")
                lines.append(
                    f"🔎 استعلام: {name_of(guide.get('extra_uid'))} از "
                    f"{name_of(ex_target)} — {result_txt}"
                )

    # 5) Guardian armor -------------------------------------------------------
    guard = outcome.get("guardian") or {}
    if guard.get("attempt_uid") is None:
        lines.append("🛡️ محافظ: ثبت نشد.")
    elif guard.get("granted"):
        lines.append(
            f"🛡️ محافظ: بازیکن تحت حفاظت: {name_of(guard.get('attempt_uid'))}"
            " — زره اعمال شد"
        )
    elif guard.get("nullified_by_hacker"):
        lines.append(
            f"🛡️ محافظ: بازیکن {name_of(guard.get('attempt_uid'))}"
            " — زره توسط هکر خنثی شد"
        )
    else:
        lines.append(
            f"🛡️ محافظ: بازیکن {name_of(guard.get('attempt_uid'))}"
            " — زره اعمال نشد"
        )

    # 6) Lawyer immunity -------------------------------------------------------
    law = outcome.get("lawyer") or {}
    if law.get("attempt_uid") is None:
        if dispositions.get("lawyer_none"):
            lines.append("⚖️ وکیل: انتخابی نداشت.")
        else:
            lines.append("⚖️ وکیل: ثبت نشد.")
    elif law.get("granted"):
        lines.append(
            f"⚖️ وکیل: بازیکن انتخاب‌شده: {name_of(law.get('attempt_uid'))}"
            " — مصونیت اعمال شد"
        )
    elif law.get("nullified_by_hacker"):
        lines.append(
            f"⚖️ وکیل: بازیکن {name_of(law.get('attempt_uid'))}"
            " — مصونیت توسط هکر خنثی شد"
        )
    else:
        lines.append(
            f"⚖️ وکیل: بازیکن {name_of(law.get('attempt_uid'))}"
            " — مصونیت اعمال نشد"
        )

    # 6.5) Soldier + temporary Sniper ---------------------------------------
    # Force-finish eliminations (12/13, helper force-finish) are read
    # from the durable elimination records: the role holder lookup
    # cannot help because the eliminated players are already dead.
    force_elim_recs: dict[str, dict] = {}
    for rec in _night_eliminations_this_night(game):
        cause = str(rec.get("cause") or "")
        if cause in (ELIM_CAUSE_FORCE_SOLDIER, ELIM_CAUSE_FORCE_SNIPER):
            force_elim_recs[cause] = rec
    snp = outcome.get("soldier_sniper") or {}
    sniper_force_uid = (
        force_elim_recs[ELIM_CAUSE_FORCE_SNIPER].get("uid")
        if ELIM_CAUSE_FORCE_SNIPER in force_elim_recs
        else None
    )
    if ELIM_CAUSE_FORCE_SOLDIER in force_elim_recs:
        lines.append(
            "🪖 سرباز: "
            f"{name_of(force_elim_recs[ELIM_CAUSE_FORCE_SOLDIER].get('uid'))}"
            " به دلیل ثبت‌نکردن انتخاب خود هنگام اتمام اجباری شب از بازی خارج شد."
        )
    elif snp.get("grant_status") or snp.get("soldier_uid") is not None:
        soldier_uid = snp.get("soldier_uid")
        recipient = snp.get("recipient_uid")
        status = str(snp.get("grant_status") or "")
        if soldier_uid is None:
            lines.append("🪖 سرباز: ثبت نشد.")
        elif status == "mafia_target":
            lines.append(
                f"🪖 سرباز: بازیکن انتخاب‌شده: {name_of(recipient)}"
                " — سرباز از بازی خارج شد."
            )
        elif status == "intercepted":
            lines.append(
                f"🪖 سرباز: قابلیت اسنایپر به {name_of(recipient)}"
                " — توسط هکر قطع شد."
            )
        elif status == "delivered":
            lines.append(
                f"🪖 سرباز: قابلیت اسنایپر به {name_of(recipient)} داده شد."
            )
            if snp.get("skipped"):
                if sniper_force_uid is not None:
                    lines.append(
                        "🎯 اسنایپر موقت: "
                        f"{name_of(sniper_force_uid)}"
                        " به دلیل ثبت‌نکردن هدف شلیک هنگام اتمام اجباری شب از بازی خارج شد."
                    )
                else:
                    lines.append(
                        f"🎯 اسنایپر: {name_of(recipient)} شلیک نکرد."
                    )
            elif snp.get("target_uid") is not None:
                elim = snp.get("eliminated_uid")
                if elim is None:
                    lines.append(
                        "🎯 اسنایپر: شلیک به "
                        f"{name_of(snp.get('target_uid'))} — هیچ‌کس خارج نشد."
                    )
                elif snp.get("sniper_eliminated"):
                    lines.append(
                        "🎯 اسنایپر: شلیک به "
                        f"{name_of(snp.get('target_uid'))}"
                        " — شلیک‌کننده از بازی خارج شد."
                    )
                else:
                    lines.append(f"🎯 اسنایپر: {name_of(elim)} از بازی خارج شد.")
        else:
            lines.append("🪖 سرباز: وضعیت قابلیت اسنایپر مشخص نشد.")
    elif sniper_force_uid is not None:
        # Defensive fallback: the elimination record exists but the
        # outcome block was not rendered (e.g. partial snapshot).
        lines.append(
            "🎯 اسنایپر موقت: "
            f"{name_of(sniper_force_uid)}"
            " به دلیل ثبت‌نکردن هدف شلیک هنگام اتمام اجباری شب از بازی خارج شد."
        )

    # 7) Mine layer -------------------------------------------------------------
    mine = outcome.get("mine") or {}
    attempt = mine.get("attempt_uid")
    if attempt is not None and mine.get("placed"):
        lines.append(
            f"💣 مین‌گذار: مین روی {name_of(attempt)} گذاشته شد."
        )
    elif attempt is not None and mine.get("nullified_by_hacker"):
        lines.append(
            f"💣 مین‌گذار: مین روی {name_of(attempt)}"
            " — توسط هکر خنثی شد"
        )
    elif attempt is not None:
        reason = str(mine.get("reason") or "")
        suffix = (
            " — مین‌گذار حذف شده بود"
            if reason == "mine_layer_not_present"
            else " — کاشته نشد"
        )
        lines.append(f"💣 مین‌گذار: هدف {name_of(attempt)}{suffix}")
    elif dispositions.get("mine_none"):
        lines.append("💣 مین‌گذار: انتخابی نداشت.")
    else:
        lines.append("💣 مین‌گذار: ثبت نشد.")

    # NATO outcome lines are rendered at the top of this section (see
    # step 0); nothing NATO-related is repeated here.
    if outcome.get("rebel_assassination"):
        reb = outcome.get("rebel_assassination") or {}
        t_name = (
            name_of(reb.get("target_uid")) if reb.get("target_uid") is not None else None
        )
        if t_name is not None:
            success = reb.get("success")
            suffix = (
                " — خارج شد"
                if success
                else (" — ناموفق" if success is False else "")
            )
            lines.append(f"🩸 ترور یاغی: {t_name}{suffix}")

    return "\n".join(lines)
