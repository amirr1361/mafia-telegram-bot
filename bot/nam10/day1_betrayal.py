"""Namayande-10 Day-1 betrayal-vote workflow (after the afternoon nap).

Continues the fork Day-1 stage machine from ``bot/nam10/day1_representative.py``:

- ``day1_betrayal_collect`` - the Mafia Boss privately picks ONE of four
  add/subtract options; every other alive player acknowledges a waiting
  panel (the registered Observer may ack synthetic players only).
- ``day1_target_intro``     - assistant/Observer panel with the
  **👥 انتخاب تارگت‌ها** button.
- ``day1_target_pick``      - native red/green toggle over all alive
  players (representatives are eligible), exactly two targets, **✅ OK**.
- ``day1_ext_vote``         - external/verbal voting stage; clicking
  **🔎 مشاهده رأی خیانت** reveals the stored, immutable Boss choice
  publicly to all alive players.
- ``day1_defense_outcome``  - the assistant/Observer records the Day-1
  outcome: eliminate target 1, eliminate target 2, or no elimination.
- ``day1_final_nap``        - final afternoon nap before Night 1.
- ``day1_night_entered``    - terminal marker; the existing independent
  Namayande Night-1 flow owns everything from here.

The Boss choice is immutable and never disclosed before the explicit
reveal press. Target elimination never triggers the handoff /
transfer-of-host workflow in this fork flow: the required sequence is
elimination -> final afternoon nap -> Night 1. No vote tallies are
calculated anywhere in this module; all voting happens externally and is
only recorded by the assistant/Observer.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.app_state import manager
from bot.models import Game, Phase, Player
from bot.text_fa import fa_digits as _fa_digits

from bot.observer_delivery import (
    PlayerMirrorCb,
    apply_mirror_claim_winner,
    broadcast_to_alive_players,
    close_mirror_prompt_keyboards,
    flush_elimination_notifications,
    game_observer_mirror_active,
    mirror_ui_claim_key,
    publish_mirror_prompt_pair,
    register_mirror_prompt_pair,
    try_claim_mirror_ui,
    update_mirror_prompt_pair,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stages and acts
# ---------------------------------------------------------------------------

NAM10_DAY1_STAGE_BETRAYAL_COLLECT = "day1_betrayal_collect"
NAM10_DAY1_STAGE_TARGET_INTRO = "day1_target_intro"
NAM10_DAY1_STAGE_TARGET_PICK = "day1_target_pick"
NAM10_DAY1_STAGE_EXT_VOTE = "day1_ext_vote"
NAM10_DAY1_STAGE_OUTCOME = "day1_defense_outcome"
NAM10_DAY1_STAGE_FINAL_NAP = "day1_final_nap"
NAM10_DAY1_STAGE_NIGHT_ENTERED = "day1_night_entered"

# PlayerMirrorCb acts owned by this workflow (routed from
# bot/nam10/player_mirror.py::dispatch_namayande10_mirror).
ACT_BW_OK = "d1bw"  # waiting-panel ✅ اوکی (as_uid = the acknowledging player)
ACT_BOSS_ADD = "d1ba"  # Boss: add one vote (tid = representative uid)
ACT_BOSS_SUB = "d1bs"  # Boss: subtract one vote (tid = representative uid)
ACT_BOSS_OK = "d1bak"  # Boss: ✅ تأیید انتخاب — commit the pending choice
ACT_TGT_OPEN = "d1to"  # 👥 انتخاب تارگت‌ها (intro -> pick panel)
ACT_TGT_TOGGLE = "d1tt"  # target toggle button (tid = player uid)
ACT_TGT_OK = "d1tok"  # ✅ OK confirm (exactly two targets)
ACT_REVEAL = "d1rv"  # 🔎 مشاهده رأی خیانت (public reveal)
ACT_OUT_T1 = "d1o1"  # 🚪 خروج target 1
ACT_OUT_T2 = "d1o2"  # 🚪 خروج target 2
ACT_OUT_NONE = "d1o0"  # 🌙 خروجی نداشتیم
ACT_FINAL_NAP = "d1fn"  # ✅ انجام شد (final nap ack)

NAM10_DAY1_BETRAYAL_ACTS = (
    ACT_BW_OK,
    ACT_BOSS_ADD,
    ACT_BOSS_SUB,
    ACT_BOSS_OK,
    ACT_TGT_OPEN,
    ACT_TGT_TOGGLE,
    ACT_TGT_OK,
    ACT_REVEAL,
    ACT_OUT_T1,
    ACT_OUT_T2,
    ACT_OUT_NONE,
    ACT_FINAL_NAP,
)

OUTCOME_ELIM_1 = "elim_1"
OUTCOME_ELIM_2 = "elim_2"
OUTCOME_NONE = "none"

BW_ACK_HTML = "\n\n<i>✅ ثبت شد.</i>"
FINAL_NAP_ACK_HTML = "\n\n<i>✅ ثبت شد. شب آغاز می‌شود.</i>"

ALERT_NEED_OPTION = "ابتدا یک گزینه را انتخاب کنید."
ALERT_STALE_STAGE = "این مرحله دیگر فعال نیست."
ALERT_FORBIDDEN = "شما مجاز به این عمل نیستید."
ALERT_ALREADY = "این انتخاب قبلاً ثبت شده است."
ALERT_NEED_TWO_TARGETS = "لطفاً دقیقاً دو تارگت انتخاب کنید."
ALERT_MAX_TWO_TARGETS = (
    "حداکثر دو تارگت قابل انتخاب است؛ ابتدا یکی از انتخاب‌ها را حذف کنید."
)


def nam10_day1_betrayal_act_active(game: Game, act: str) -> bool:
    """Route gate: acts owned by the Day-1 betrayal-vote workflow."""
    return act in NAM10_DAY1_BETRAYAL_ACTS


def _audit(game: Game, event: str, **data) -> None:
    try:
        from bot.game_audit_log import log_event

        log_event(game, event, **data)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shared helpers (re-used from the representative module)
# ---------------------------------------------------------------------------


def _panel_players(game: Game) -> list[Player]:
    """All alive players in current seat order (no role information)."""
    from bot.nam10.day1_representative import _rep_panel_players

    return _rep_panel_players(game)


def _display_name(game: Game, p: Player | None) -> str:
    """Player label without synthetic role suffixes (UI only)."""
    from bot.nam10.day1_representative import _rep_display_name

    return _rep_display_name(game, p)


def _assistant_authorized(game: Game, actor_uid: int) -> bool:
    from bot.nam10.day1_representative import nam10_day1_rep_authorized

    return nam10_day1_rep_authorized(game, actor_uid)


def _alive_mafia_boss(game: Game) -> Player | None:
    from bot.nam10.nmnd_narrator import Role
    from bot.nam10.role_registry import find_alive_role_holder

    return find_alive_role_holder(game, Role.MAFIA_BOSS)


def _seat_may_act_for_player(
    game: Game, actor_uid: int, seat_uid: int
) -> bool:
    """The seat player itself; a synthetic seat only via the Observer."""
    if actor_uid == seat_uid:
        return True
    from bot.nam10.engine import is_synthetic_player_uid

    return bool(
        is_synthetic_player_uid(seat_uid)
        and game_observer_mirror_active(game)
        and game.observer_user_id == actor_uid
    )


def _bw_ui_key(game: Game, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "day1_bw", uid)


def _boss_ui_key(game: Game, boss_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "day1_boss", boss_uid)


def _tgt_intro_ui_key(game: Game, assistant_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "day1_tgt_intro", assistant_uid)


def _tgt_pick_ui_key(game: Game, assistant_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "day1_tgt_pick", assistant_uid)


def _ext_vote_ui_key(game: Game, assistant_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "day1_ext_vote", assistant_uid)


def _outcome_ui_key(game: Game, assistant_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "day1_outcome", assistant_uid)


def _final_nap_ui_key(game: Game, assistant_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "day1_final_nap", assistant_uid)


# ---------------------------------------------------------------------------
# Stage A panels — betrayal-vote collection
# ---------------------------------------------------------------------------


def build_day1_betrayal_wait_html() -> str:
    return (
        "🌙 <b>رأی خیانت گروه مافیا</b>\n\n"
        "گروه مافیا در حال تصمیم‌گیری و ثبت رأی خیانت است.\n\n"
        "لطفاً منتظر بمانید و برای تأیید آمادگی خود، دکمه زیر را بزنید."
    )


def _bw_ok_keyboard(game: Game, uid: int) -> InlineKeyboardMarkup:
    cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_BW_OK, as_uid=uid
    ).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ اوکی", callback_data=cb, style="primary"
                )
            ]
        ]
    )


BOSS_PANEL_HEADER = "🗳️ <b>مرحله ثبت رأی خیانت</b>"
BOSS_PANEL_REPS_TITLE = "نمایندگان انتخاب‌شده در روز اول:"
BOSS_PANEL_HINT = (
    "رئیس مافیا می‌تواند یک رأی به یکی از نمایندگان اضافه کند یا یک رأی "
    "از او کم کند."
)
BOSS_PANEL_INSTRUCTION = (
    "لطفاً یکی از گزینه‌های زیر را انتخاب و سپس تأیید کنید."
)
BOSS_CONFIRM_TEXT = "✅ تأیید انتخاب"


def _rep_index(game: Game, rep_uid: int) -> int | None:
    reps = [int(u) for u in game.nam10_day1_rep_uids[:2]]
    if rep_uid in reps:
        return reps.index(rep_uid) + 1
    return None


def _rep_annotated_text(game: Game, rep_uid: int) -> str:
    from bot.nam10.mafia_team_notify import plain_player_name

    idx = _rep_index(game, rep_uid)
    idx_txt = _fa_digits(idx) if idx else "؟"
    p = game.players.get(rep_uid)
    name = (
        plain_player_name(p, rep_uid)
        if p is not None
        else str(rep_uid)
    )
    return f"<b>نماینده {idx_txt}:</b> {name}"


def build_day1_boss_betrayal_html(game: Game, boss_uid: int) -> str:
    reps = [int(u) for u in game.nam10_day1_rep_uids[:2]]
    parts = [
        BOSS_PANEL_HEADER,
        BOSS_PANEL_REPS_TITLE,
        *(_rep_annotated_text(game, uid) for uid in reps),
        BOSS_PANEL_HINT,
        BOSS_PANEL_INSTRUCTION,
    ]
    pending_op = game.nam10_day1_betrayal_pending_op
    pending_rep = game.nam10_day1_betrayal_pending_rep_uid
    if pending_op and pending_rep is not None:
        opt = _boss_option_text(game, str(pending_op), int(pending_rep))
        parts.append(
            f"<i>انتخاب موقت شما: {opt}</i>\n\n"
            f"{BOSS_CONFIRM_TEXT} را بزنید تا رأی خیانت ثبت شود."
        )
    return "\n\n".join(parts)


def _boss_option_text(game: Game, op: str, rep_uid: int) -> str:
    idx = _rep_index(game, rep_uid)
    idx_txt = _fa_digits(idx) if idx else "؟"
    if op == "add":
        return f"➕ افزودن یک رأی به نماینده {idx_txt}"
    return f"➖ کسر یک رأی از نماینده {idx_txt}"


def _boss_betrayal_keyboard(
    game: Game, boss_uid: int
) -> InlineKeyboardMarkup:
    """Spec panel: one option per OWN keyboard row, in the fixed order
    add/sub Representative 1 then add/sub Representative 2.

    The Mafia Boss may never affect their own representative seat — both
    rows for that seat are omitted entirely (no disabled placeholders).
    All options are blue (primary); the single pending selection is red
    (danger); exactly one '✅ تأیید انتخاب' button sits on its own row.
    Representative mapping rides on the callback ``tid`` (actual player
    uid) — never on button text or ordering.
    """
    pending_op = game.nam10_day1_betrayal_pending_op
    pending_rep = game.nam10_day1_betrayal_pending_rep_uid
    rows: list[list[InlineKeyboardButton]] = []
    for rep_uid in [int(u) for u in game.nam10_day1_rep_uids[:2]]:
        if rep_uid == boss_uid:
            continue
        for act, op in ((ACT_BOSS_ADD, "add"), (ACT_BOSS_SUB, "sub")):
            cb = PlayerMirrorCb(
                code=game.room_code, act=act, as_uid=boss_uid, tid=rep_uid
            ).pack()
            selected = (
                pending_op == op and pending_rep is not None and int(pending_rep) == rep_uid
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_boss_option_text(game, op, rep_uid),
                        callback_data=cb,
                        style="danger" if selected else "primary",
                    )
                ]
            )
    ok_cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_BOSS_OK, as_uid=boss_uid
    ).pack()
    rows.append(
        [
            InlineKeyboardButton(
                text=BOSS_CONFIRM_TEXT, callback_data=ok_cb, style="success"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def nam10_start_day1_betrayal_collection(bot: Bot, game: Game) -> bool:
    """Stage A: waiting panels for alive non-Boss players + the private
    Mafia Boss panel (idempotent; only entered from the awaiting state)."""
    from bot.nam10.day1_representative import NAM10_DAY1_STAGE_AWAITING_BETRAYAL
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if game.nam10_day1_stage != NAM10_DAY1_STAGE_AWAITING_BETRAYAL:
        return False
    if game.phase == Phase.ENDED:
        return False
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return False
    boss = _alive_mafia_boss(game)
    if boss is None:
        _audit(
            game,
            "no_host.day1_betrayal_start_blocked",
            reason="no_alive_mafia_boss",
        )
        return False

    game.nam10_day1_betrayal_op = None
    game.nam10_day1_betrayal_rep_uid = None
    game.nam10_day1_betrayal_boss_uid = None
    game.nam10_day1_betrayal_pending_op = None
    game.nam10_day1_betrayal_pending_rep_uid = None
    game.nam10_day1_betrayal_waiting_confirmed_uids = []
    game.nam10_day1_target_pending = []
    game.nam10_day1_target_uids = []
    game.nam10_day1_betrayal_revealed = False
    game.nam10_day1_defense_outcome = None
    game.nam10_day1_final_nap_acked = False
    game.nam10_day1_stage = NAM10_DAY1_STAGE_BETRAYAL_COLLECT

    waiting: list[int] = []
    for p in _panel_players(game):
        if p.user_id == boss.user_id:
            continue
        waiting.append(p.user_id)
        bw_key = _bw_ui_key(game, p.user_id)
        await register_mirror_prompt_pair(
            bot,
            game,
            p.user_id,
            bw_key,
            build_day1_betrayal_wait_html(),
            _bw_ok_keyboard(game, p.user_id),
            send_player=True,
            send_observer=game_observer_mirror_active(game),
            observer_same_text=False,
            parse_mode="HTML",
        )

    boss_key = _boss_ui_key(game, boss.user_id)
    await register_mirror_prompt_pair(
        bot,
        game,
        boss.user_id,
        boss_key,
        build_day1_boss_betrayal_html(game, boss.user_id),
        _boss_betrayal_keyboard(game, boss.user_id),
        send_player=True,
        send_observer=game_observer_mirror_active(game),
        observer_same_text=False,
        parse_mode="HTML",
    )

    _audit(
        game,
        "no_host.day1_betrayal_collection_started",
        boss_uid=boss.user_id,
        waiting_uids=waiting,
        rep_uids=[int(u) for u in game.nam10_day1_rep_uids[:2]],
    )
    manager.persist_snapshot(game, reason="day1_betrayal_collect_start")
    return True


async def _bw_ok(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    player_uid: int,
    actor_uid: int,
) -> None:
    """Waiting-panel ✅ اوکی: per-player ack, idempotent, panel closed."""
    from bot.main import _answer_mirror_claim

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_BETRAYAL_COLLECT:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    p = game.players.get(player_uid)
    if p is None or not p.is_alive:
        await callback.answer("بازیکن زنده نیست.", show_alert=True)
        return
    if not _seat_may_act_for_player(game, actor_uid, player_uid):
        _audit(
            game,
            "no_host.day1_betrayal_cb",
            act=ACT_BW_OK,
            actor_uid=actor_uid,
            as_uid=player_uid,
            outcome="rejected",
            reject_reason="forbidden_actor",
        )
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if player_uid in game.nam10_day1_betrayal_waiting_confirmed_uids:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    bw_key = _bw_ui_key(game, player_uid)
    err = try_claim_mirror_ui(game, bw_key, actor_uid, player_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    await apply_mirror_claim_winner(
        bot, game, bw_key, actor_uid, player_uid
    )
    game.nam10_day1_betrayal_waiting_confirmed_uids = [
        *game.nam10_day1_betrayal_waiting_confirmed_uids,
        player_uid,
    ]
    await callback.answer("ثبت شد.")
    await update_mirror_prompt_pair(
        bot,
        game,
        bw_key,
        build_day1_betrayal_wait_html() + BW_ACK_HTML,
        None,
        assistant_uid=player_uid,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_betrayal_waiting_acked",
        player_uid=player_uid,
        actor_uid=actor_uid,
    )
    await _maybe_complete_betrayal_collect(bot, game)


async def _boss_choose(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    as_uid: int,
    actor_uid: int,
    op: str,
    rep_uid: int,
) -> None:
    """Boss add/subtract press: the pending (tentative) selection.

    Blue/r olem swap: choosing another option replaces the previous
    selection (previous red returns to blue) and the vote is NOT applied
    until the separate '✅ تأیید انتخاب' confirmation. A committed choice
    is immutable.
    """
    from bot.main import _answer_mirror_claim

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_BETRAYAL_COLLECT:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    boss = _alive_mafia_boss(game)
    if boss is None or as_uid != boss.user_id:
        _audit(
            game,
            "no_host.day1_betrayal_cb",
            act="d1ba/d1bs",
            actor_uid=actor_uid,
            as_uid=as_uid,
            outcome="rejected",
            reject_reason="not_mafia_boss",
        )
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if not _seat_may_act_for_player(game, actor_uid, boss.user_id):
        _audit(
            game,
            "no_host.day1_betrayal_cb",
            act="d1ba/d1bs",
            actor_uid=actor_uid,
            as_uid=boss.user_id,
            outcome="rejected",
            reject_reason="forbidden_actor",
        )
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if game.nam10_day1_betrayal_op is not None:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if rep_uid not in [int(u) for u in game.nam10_day1_rep_uids[:2]]:
        await callback.answer("نماینده انتخابی نامعتبر است.", show_alert=True)
        return
    if rep_uid == boss.user_id:
        _audit(
            game,
            "no_host.day1_betrayal_cb",
            act="d1ba/d1bs",
            actor_uid=actor_uid,
            as_uid=as_uid,
            outcome="rejected",
            reject_reason="boss_own_representative",
        )
        await callback.answer(
            "نمی‌توانید به رأی نمایندهٔ خودتان اثر بگذارید.", show_alert=True
        )
        return
    boss_key = _boss_ui_key(game, boss.user_id)
    err = try_claim_mirror_ui(game, boss_key, actor_uid, boss.user_id)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    # Re-validate after the claim; the committed choice stays immutable.
    if game.nam10_day1_betrayal_op is not None:
        game.mirror_action_claims.pop(boss_key, None)
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    game.nam10_day1_betrayal_pending_op = op
    game.nam10_day1_betrayal_pending_rep_uid = rep_uid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await update_mirror_prompt_pair(
        bot,
        game,
        boss_key,
        build_day1_boss_betrayal_html(game, boss.user_id),
        _boss_betrayal_keyboard(game, boss.user_id),
        assistant_uid=boss.user_id,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_boss_betrayal_pending_selected",
        op=op,
        rep_uid=rep_uid,
        boss_uid=boss.user_id,
        actor_uid=actor_uid,
    )


async def _boss_confirm(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    as_uid: int,
    actor_uid: int,
) -> None:
    """'✅ تأیید انتخاب': commits the pending choice exactly once.

    Refuses confirmation without a valid pending selection; afterwards
    the committed choice is immutable and repeated presses / replayed
    callbacks are rejected. On commit the existing betrayal-vote effect
    (the stored Boss choice) is applied exactly once, the Boss panel
    closes, and ONE private informational notification goes to the other
    authorised Mafia teammates (with the Observer/​mirroring policy).
    """
    from bot.main import _answer_mirror_claim

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_BETRAYAL_COLLECT:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    boss = _alive_mafia_boss(game)
    if boss is None or as_uid != boss.user_id:
        _audit(
            game,
            "no_host.day1_betrayal_cb",
            act=ACT_BOSS_OK,
            actor_uid=actor_uid,
            as_uid=as_uid,
            outcome="rejected",
            reject_reason="not_mafia_boss",
        )
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if not _seat_may_act_for_player(game, actor_uid, boss.user_id):
        _audit(
            game,
            "no_host.day1_betrayal_cb",
            act=ACT_BOSS_OK,
            actor_uid=actor_uid,
            as_uid=boss.user_id,
            outcome="rejected",
            reject_reason="forbidden_actor",
        )
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if game.nam10_day1_betrayal_op is not None:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    pending_op = game.nam10_day1_betrayal_pending_op
    pending_rep = game.nam10_day1_betrayal_pending_rep_uid
    if not pending_op or pending_rep is None:
        await callback.answer(ALERT_NEED_OPTION, show_alert=True)
        return
    rep_uid = int(pending_rep)
    if rep_uid not in [int(u) for u in game.nam10_day1_rep_uids[:2]]:
        await callback.answer("نماینده انتخابی نامعتبر است.", show_alert=True)
        return
    if rep_uid == boss.user_id:
        await callback.answer(
            "نمی‌توانید به رأی نمایندهٔ خودتان اثر بگذارید.", show_alert=True
        )
        return
    boss_key = _boss_ui_key(game, boss.user_id)
    err = try_claim_mirror_ui(game, boss_key, actor_uid, boss.user_id)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    # Re-validate after the claim: the commit happens exactly once.
    if game.nam10_day1_betrayal_op is not None:
        game.mirror_action_claims.pop(boss_key, None)
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if not game.nam10_day1_betrayal_pending_op or (
        game.nam10_day1_betrayal_pending_rep_uid is None
    ):
        game.mirror_action_claims.pop(boss_key, None)
        await callback.answer(ALERT_NEED_OPTION, show_alert=True)
        return
    game.nam10_day1_betrayal_op = str(pending_op)
    game.nam10_day1_betrayal_rep_uid = rep_uid
    game.nam10_day1_betrayal_boss_uid = boss.user_id
    game.nam10_day1_betrayal_pending_op = None
    game.nam10_day1_betrayal_pending_rep_uid = None
    await apply_mirror_claim_winner(
        bot, game, boss_key, actor_uid, boss.user_id
    )
    rep = game.players.get(rep_uid)
    from bot.nam10.mafia_team_notify import (
        build_betrayal_vote_notification_text,
        notify_mafia_teammates,
    )

    rep_index = _rep_index(game, rep_uid) or 0
    chosen = _boss_option_text(game, str(pending_op), rep_uid)
    await callback.answer("ثبت شد.")
    await update_mirror_prompt_pair(
        bot,
        game,
        boss_key,
        build_day1_boss_betrayal_html(game, boss.user_id)
        + f"\n\n<i>✅ رأی خیانت شما ثبت شد.</i>\n\n<i>انتخاب شما: {chosen}</i>",
        None,
        assistant_uid=boss.user_id,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_boss_betrayal_selected",
        op=str(pending_op),
        rep_uid=rep_uid,
        boss_uid=boss.user_id,
        actor_uid=actor_uid,
    )
    # ONE private notification to the other authorised Mafia teammates.
    notification = build_betrayal_vote_notification_text(
        str(pending_op), rep_uid, rep_index, rep
    )
    try:
        await notify_mafia_teammates(
            bot,
            game,
            notification,
            exclude_uid=boss.user_id,
            event="no_host.day1_boss_betrayal_teammates_notified",
        )
    except Exception:
        logger.exception(
            "betrayal teammate notification failed room=%s", game.room_code
        )
    await _maybe_complete_betrayal_collect(bot, game)


async def _maybe_complete_betrayal_collect(bot: Bot, game: Game) -> bool:
    """Idempotent completion gate: Boss choice + every required ack.

    The required set is recomputed from authoritative game state on every
    check, so a player eliminated while the stage is open is dropped from
    the obligations instead of blocking the stage forever.
    """
    if game.nam10_day1_stage != NAM10_DAY1_STAGE_BETRAYAL_COLLECT:
        return False
    if game.nam10_day1_betrayal_op is None:
        return False
    boss = _alive_mafia_boss(game)
    boss_uid = boss.user_id if boss is not None else None
    confirmed = {
        int(u) for u in game.nam10_day1_betrayal_waiting_confirmed_uids
    }
    required = {
        int(u)
        for u, p in game.players.items()
        if p.is_alive and u != boss_uid
    }
    if not required.issubset(confirmed):
        return False
    game.nam10_day1_stage = NAM10_DAY1_STAGE_TARGET_INTRO
    _audit(
        game,
        "no_host.day1_betrayal_collection_completed",
        boss_uid=game.nam10_day1_betrayal_boss_uid,
        confirmed_uids=sorted(confirmed),
    )
    assistant_uid = game.bot_assistant_user_id
    intro_key = _tgt_intro_ui_key(game, assistant_uid)
    await publish_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        intro_key,
        build_day1_target_intro_html(),
        _target_intro_keyboard(game, assistant_uid),
        parse_mode="HTML",
    )
    manager.persist_snapshot(game, reason="day1_target_intro")
    return True


# ---------------------------------------------------------------------------
# Stage B panels — representative-target selection
# ---------------------------------------------------------------------------


def build_day1_target_intro_html() -> str:
    return (
        "🗳️ <b>فرآیند انتخاب تارگت‌های نمایندگان</b>\n\n"
        "رأی خیانت گروه مافیا ثبت شد.\n\n"
        "در این مرحله، هر یک از دو نماینده روز اول باید صحبت کرده و "
        "تارگت موردنظر خود را معرفی کنند.\n\n"
        "بازیکنانی که به‌عنوان تارگت معرفی می‌شوند، فرصت دفاع از خود را "
        "دارند. هر تارگت می‌تواند یک بازیکن دیگر را نیز برای صحبت در "
        "حمایت از خود انتخاب کند.\n\n"
        "پس از مشخص‌شدن دو تارگت، از فهرست بازیکنان، نام دو نفر "
        "معرفی‌شده توسط نمایندگان را انتخاب کنید."
    )


def _target_intro_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_TGT_OPEN, as_uid=assistant_uid
    ).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 انتخاب تارگت‌ها",
                    callback_data=cb,
                    style="primary",
                )
            ]
        ]
    )


def build_day1_target_pick_html(game: Game) -> str:
    n = len({u for u in game.nam10_day1_target_pending})
    sel = f"\n<i>انتخاب‌شده: {_fa_digits(n)} نفر</i>\n" if n else "\n"
    return (
        "👥 <b>انتخاب تارگت‌های نمایندگان</b>\n\n"
        "🪑 لیست بازیکنان زنده (به ترتیب صندلی) در زیر آمده است.\n"
        "🔵 دکمه آبی: انتخاب‌نشده | 🔴 دکمه قرمز: انتخاب‌شده\n"
        "⚠️ دقیقاً دو تارگت را انتخاب کنید؛ برای تغییر انتخاب، ابتدا یکی "
        "از دکمه‌های قرمز را بزنید.\n"
        "پس از انتخاب دو تارگت، دکمه «<b>✅ OK</b>» را بزنید."
        f"{sel}"
    )


def _target_pick_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    """All alive players (representatives included) as toggle buttons."""
    selected = {u for u in game.nam10_day1_target_pending}
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in _panel_players(game):
        tick = "✅" if p.user_id in selected else "☐"
        style = "danger" if p.user_id in selected else "primary"
        seat_no = _fa_digits(p.seat if p.seat is not None else 0)
        name = html.escape(_display_name(game, p))[:24]
        cb = PlayerMirrorCb(
            code=game.room_code,
            act=ACT_TGT_TOGGLE,
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
        code=game.room_code, act=ACT_TGT_OK, as_uid=assistant_uid
    ).pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ OK", callback_data=ok_cb, style="success"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _open_target_panel(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    from bot.main import _answer_mirror_claim
    from bot.nam10.day1_representative import _promote_with_observer_fallback

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_TARGET_INTRO:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    intro_key = _tgt_intro_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, intro_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    await apply_mirror_claim_winner(
        bot, game, intro_key, actor_uid, assistant_uid
    )
    await callback.answer("پنل انتخاب تارگت‌ها فعال شد.")
    game.nam10_day1_stage = NAM10_DAY1_STAGE_TARGET_PICK
    pick_key = _tgt_pick_ui_key(game, assistant_uid)
    text = build_day1_target_pick_html(game)
    kb = _target_pick_keyboard(game, assistant_uid)
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
        "no_host.day1_target_pick_opened",
        assistant_uid=assistant_uid,
        actor_uid=actor_uid,
    )


async def _toggle_target(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    target_uid: int,
) -> None:
    if target_uid not in game.players or not game.players[target_uid].is_alive:
        await callback.answer("بازیکن زنده نیست.", show_alert=True)
        return
    pending = [u for u in game.nam10_day1_target_pending if u != target_uid]
    was_selected = target_uid in game.nam10_day1_target_pending
    if not was_selected:
        if len(pending) >= 2:
            _audit(
                game,
                "no_host.day1_target_toggle_rejected",
                target_uid=target_uid,
                reject_reason="max_two_selected",
            )
            await callback.answer(ALERT_MAX_TWO_TARGETS, show_alert=True)
            return
        pending.append(target_uid)
    game.nam10_day1_target_pending = pending
    await callback.answer("به‌روز شد.")
    pick_key = _tgt_pick_ui_key(game, assistant_uid)
    await update_mirror_prompt_pair(
        bot,
        game,
        pick_key,
        build_day1_target_pick_html(game),
        _target_pick_keyboard(game, assistant_uid),
        assistant_uid=assistant_uid,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_target_toggled",
        target_uid=target_uid,
        selected=not was_selected,
        actor_uid=actor_uid,
    )


async def _confirm_targets(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    from bot.main import _answer_mirror_claim
    from bot.nam10.day1_representative import _promote_with_observer_fallback

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_TARGET_PICK:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    pending = [u for u in game.nam10_day1_target_pending]
    if len({u for u in pending}) != 2:
        _audit(
            game,
            "no_host.day1_target_confirm_rejected",
            reject_reason="need_two",
            actor_uid=actor_uid,
        )
        await callback.answer(ALERT_NEED_TWO_TARGETS, show_alert=True)
        return
    pick_key = _tgt_pick_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, pick_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    # Re-validate after the claim.
    pending = [u for u in game.nam10_day1_target_pending]
    ordered = list(dict.fromkeys(pending))
    if (
        len(ordered) != 2
        or any(
            u not in game.players or not game.players[u].is_alive
            for u in ordered
        )
    ):
        game.mirror_action_claims.pop(pick_key, None)
        await callback.answer(ALERT_NEED_TWO_TARGETS, show_alert=True)
        return
    await apply_mirror_claim_winner(
        bot, game, pick_key, actor_uid, assistant_uid
    )
    await callback.answer("ثبت شد.")
    game.nam10_day1_target_uids = ordered
    game.nam10_day1_target_pending = []
    game.nam10_day1_stage = NAM10_DAY1_STAGE_EXT_VOTE
    # Close any leftover actionable copy of the intro panel.
    await close_mirror_prompt_keyboards(
        bot, game, _tgt_intro_ui_key(game, assistant_uid)
    )
    ext_key = _ext_vote_ui_key(game, assistant_uid)
    ext_text = build_day1_ext_vote_html()
    ext_kb = _ext_vote_keyboard(game, assistant_uid)
    promoted = await _promote_with_observer_fallback(
        bot,
        game,
        from_ui_key=pick_key,
        to_ui_key=ext_key,
        assistant_uid=assistant_uid,
        text=ext_text,
        kb=ext_kb,
    )
    if not promoted:
        await publish_mirror_prompt_pair(
            bot,
            game,
            assistant_uid,
            ext_key,
            ext_text,
            ext_kb,
            parse_mode="HTML",
        )
    _audit(
        game,
        "no_host.day1_targets_confirmed",
        assistant_uid=assistant_uid,
        actor_uid=actor_uid,
        target_uids=ordered,
    )
    manager.persist_snapshot(game, reason="day1_targets_confirmed")


# ---------------------------------------------------------------------------
# Stage C — external voting wait + public reveal
# ---------------------------------------------------------------------------


def build_day1_ext_vote_html() -> str:
    return (
        "🗳️ <b>رأی‌گیری روز اول — مرحله دوم</b>\n\n"
        "دو تارگت نمایندگان مشخص شدند.\n\n"
        "لطفاً رأی‌گیری مرحله دوم را برای دو بازیکن معرفی‌شده برگزار کنید.\n\n"
        "پس از پایان رأی‌گیری و ثبت نتیجه آن در فرآیند حضوری بازی، دکمه "
        "زیر را بزنید تا رأی خیانت گروه مافیا آشکار شود."
    )


def _ext_vote_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_REVEAL, as_uid=assistant_uid
    ).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 مشاهده رأی خیانت",
                    callback_data=cb,
                    style="primary",
                )
            ]
        ]
    )


def build_day1_betrayal_reveal_html(game: Game) -> str:
    op = game.nam10_day1_betrayal_op
    rep = game.players.get(game.nam10_day1_betrayal_rep_uid)
    name = (
        html.escape(_display_name(game, rep))
        if rep is not None
        else str(game.nam10_day1_betrayal_rep_uid)
    )
    if op == "add":
        line = f"➕ یک رأی به {name} اضافه شد."
    else:
        line = f"➖ یک رأی از {name} کسر شد."
    return f"🔴 <b>نتیجه رأی خیانت</b>\n\n{line}"


async def _reveal_betrayal(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    from bot.main import _answer_mirror_claim
    from bot.nam10.day1_representative import _promote_with_observer_fallback

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_EXT_VOTE:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    if game.nam10_day1_betrayal_revealed:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    ext_key = _ext_vote_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, ext_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    # Duplicate-protection flags are set before any Telegram traffic.
    game.nam10_day1_betrayal_revealed = True
    game.nam10_day1_stage = NAM10_DAY1_STAGE_OUTCOME
    await apply_mirror_claim_winner(
        bot, game, ext_key, actor_uid, assistant_uid
    )
    await callback.answer("رأی خیانت آشکار شد.")
    # Turn the reveal control into the Day-1 outcome panel.
    outcome_key = _outcome_ui_key(game, assistant_uid)
    outcome_text = build_day1_outcome_html()
    outcome_kb = _outcome_keyboard(game, assistant_uid)
    promoted = await _promote_with_observer_fallback(
        bot,
        game,
        from_ui_key=ext_key,
        to_ui_key=outcome_key,
        assistant_uid=assistant_uid,
        text=outcome_text,
        kb=outcome_kb,
    )
    if not promoted:
        await publish_mirror_prompt_pair(
            bot,
            game,
            assistant_uid,
            outcome_key,
            outcome_text,
            outcome_kb,
            parse_mode="HTML",
        )
    # Public announcement to every currently alive player (the Boss
    # included); synthetic seats are delivered through Observer mirrors.
    from bot.game import is_synthetic_player_uid

    await broadcast_to_alive_players(
        bot,
        game,
        build_day1_betrayal_reveal_html(game),
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    _audit(
        game,
        "no_host.day1_betrayal_revealed",
        op=game.nam10_day1_betrayal_op,
        rep_uid=game.nam10_day1_betrayal_rep_uid,
        actor_uid=actor_uid,
    )


# ---------------------------------------------------------------------------
# Stage D — Day-1 defensive outcome
# ---------------------------------------------------------------------------


def build_day1_outcome_html() -> str:
    return (
        "⚖️ <b>مرحله تعیین نتیجه دفاعیه روز اول</b>\n\n"
        "رأی‌گیری دفاعیه دو تارگت به پایان رسیده است.\n\n"
        "لطفاً نتیجه نهایی رأی‌گیری را از گزینه‌های زیر انتخاب کنید."
    )


def _outcome_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    targets = [int(u) for u in game.nam10_day1_target_uids[:2]]
    rows: list[list[InlineKeyboardButton]] = []
    for act, idx in ((ACT_OUT_T1, 0), (ACT_OUT_T2, 1)):
        uid = targets[idx] if idx < len(targets) else None
        p = game.players.get(uid) if uid else None
        if p is not None:
            name = html.escape(_display_name(game, p))
        else:
            name = str(uid) if uid else "؟"
        cb = PlayerMirrorCb(
            code=game.room_code,
            act=act,
            as_uid=assistant_uid,
            tid=uid or 0,
        ).pack()
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🚪 خروج {name}",
                    callback_data=cb,
                    style="primary",
                )
            ]
        )
    none_cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_OUT_NONE, as_uid=assistant_uid
    ).pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="🌙 خروجی نداشتیم",
                callback_data=none_cb,
                style="primary",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _choose_outcome(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    outcome: str,
) -> None:
    from bot.main import _answer_mirror_claim

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_OUTCOME:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    if game.nam10_day1_defense_outcome is not None:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    targets = [int(u) for u in game.nam10_day1_target_uids[:2]]
    target_uid: int | None = None
    if outcome in (OUTCOME_ELIM_1, OUTCOME_ELIM_2):
        idx = 0 if outcome == OUTCOME_ELIM_1 else 1
        if idx >= len(targets):
            await callback.answer("تارگت نامعتبر است.", show_alert=True)
            return
        target_uid = targets[idx]
        p = game.players.get(target_uid)
        if p is None or not p.is_alive:
            await callback.answer(
                "این بازیکن قبلاً خارج شده است.", show_alert=True
            )
            return
    outcome_key = _outcome_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, outcome_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    # Re-validate after the claim.
    if game.nam10_day1_defense_outcome is not None:
        game.mirror_action_claims.pop(outcome_key, None)
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    game.nam10_day1_defense_outcome = outcome
    await apply_mirror_claim_winner(
        bot, game, outcome_key, actor_uid, assistant_uid
    )
    if outcome == OUTCOME_NONE:
        await callback.answer("ثبت شد.")
        await update_mirror_prompt_pair(
            bot,
            game,
            outcome_key,
            build_day1_outcome_html()
            + "\n\n<i>✅ خروجی ثبت نشد؛ خواب نیمروزی آغاز می‌شود.</i>",
            None,
            assistant_uid=assistant_uid,
            parse_mode="HTML",
        )
        _audit(
            game,
            "no_host.day1_defense_outcome_selected",
            outcome=outcome,
            actor_uid=actor_uid,
        )
        await _enter_final_nap_stage(bot, game, assistant_uid)
        return

    # Eliminate the chosen target with the fork-compatible Day-1
    # elimination machinery. Handoff/transfer-of-host is intentionally
    # NOT invoked: target elimination -> final nap -> Night 1.
    from bot.nam10.dayflow import build_no_host_day1_elim_broadcast_html
    from bot.nam10.nmnd_narrator import (
        eliminate_player_from_game,
        hunter_chain_confirm_alert_text,
    )
    from bot.nam10.no_host_mafia_win import nam10_maybe_end_on_faction_win
    from bot.game import is_synthetic_player_uid

    chain_alert = hunter_chain_confirm_alert_text(
        game, manager, target_uid, public=True
    )
    eliminate_player_from_game(
        game, manager, target_uid, elim_source="day_vote"
    )
    armor_saved = game.players[target_uid].is_alive
    ended = False
    if not armor_saved:
        await flush_elimination_notifications(bot, game)
        broadcast = build_no_host_day1_elim_broadcast_html(
            game, assistant_uid, target_uid
        )
        await broadcast_to_alive_players(
            bot,
            game,
            broadcast,
            exclude=assistant_uid,
            parse_mode="HTML",
            is_synthetic_uid=is_synthetic_player_uid,
        )
        await callback.answer(
            chain_alert or "حذف ثبت شد.", show_alert=bool(chain_alert)
        )
        ended = await nam10_maybe_end_on_faction_win(
            bot,
            game,
            manager,
            elim_source="day_vote",
            elim_uid=target_uid,
        )
    else:
        # Armored seat survived the elimination attempt (not reachable in
        # the Namayande roster; handled defensively without fabricating).
        await callback.answer("ثبت شد.")
    if ended:
        _audit(
            game,
            "no_host.day1_defense_outcome_selected",
            outcome=outcome,
            target_uid=target_uid,
            actor_uid=actor_uid,
            game_ended=True,
        )
        return
    if not armor_saved:
        from bot.nam10.rebel_day import dispatch_nam10_rebel_activation

        try:
            await dispatch_nam10_rebel_activation(bot, game)
        except Exception:
            logger.exception(
                "rebel daytime activation failed room=%s", game.room_code
            )
    await update_mirror_prompt_pair(
        bot,
        game,
        outcome_key,
        build_day1_outcome_html()
        + "\n\n<i>✅ نتیجه ثبت شد؛ خواب نیمروزی آغاز می‌شود.</i>",
        None,
        assistant_uid=assistant_uid,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_defense_outcome_selected",
        outcome=outcome,
        target_uid=target_uid,
        actor_uid=actor_uid,
    )
    await _enter_final_nap_stage(bot, game, assistant_uid)


async def _enter_final_nap_stage(
    bot: Bot, game: Game, assistant_uid: int
) -> None:
    game.nam10_day1_stage = NAM10_DAY1_STAGE_FINAL_NAP
    nap_key = _final_nap_ui_key(game, assistant_uid)
    await publish_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        nap_key,
        build_day1_final_nap_html(),
        _final_nap_keyboard(game, assistant_uid),
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_final_nap_started",
        outcome=game.nam10_day1_defense_outcome,
    )
    manager.persist_snapshot(game, reason="day1_final_nap")


# ---------------------------------------------------------------------------
# Stage E — final afternoon nap -> Night 1
# ---------------------------------------------------------------------------


def build_day1_final_nap_html() -> str:
    return (
        "🌙 <b>خواب نیمروزی پیش از آغاز شب</b>\n\n"
        "در این مرحله، از تمام بازیکنان بخواهید به خواب نیمروزی بروند تا "
        "گروه مافیا فرصت مشورت پیش از انجام اقدامات شبانه خود را داشته "
        "باشد.\n\n"
        "پس از پایان خواب نیمروزی، دکمه زیر را بزنید."
    )


def _final_nap_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    cb = PlayerMirrorCb(
        code=game.room_code, act=ACT_FINAL_NAP, as_uid=assistant_uid
    ).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ انجام شد", callback_data=cb, style="success"
                )
            ]
        ]
    )


async def _final_nap_ack(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    from bot.main import _answer_mirror_claim

    if game.nam10_day1_stage != NAM10_DAY1_STAGE_FINAL_NAP:
        await callback.answer(ALERT_STALE_STAGE, show_alert=True)
        return
    if game.nam10_day1_final_nap_acked:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    nap_key = _final_nap_ui_key(game, assistant_uid)
    err = try_claim_mirror_ui(game, nap_key, actor_uid, assistant_uid)
    if err == "already_claimed":
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    if err not in (None, "dup_self") and await _answer_mirror_claim(
        callback, err
    ):
        return
    # Re-validate after the claim: night entry happens exactly once.
    if game.nam10_day1_final_nap_acked:
        game.mirror_action_claims.pop(nap_key, None)
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    game.nam10_day1_final_nap_acked = True
    game.nam10_day1_stage = NAM10_DAY1_STAGE_NIGHT_ENTERED
    await apply_mirror_claim_winner(
        bot, game, nap_key, actor_uid, assistant_uid
    )
    await callback.answer("ثبت شد.")
    await update_mirror_prompt_pair(
        bot,
        game,
        nap_key,
        build_day1_final_nap_html() + FINAL_NAP_ACK_HTML,
        None,
        assistant_uid=assistant_uid,
        parse_mode="HTML",
    )
    _audit(
        game,
        "no_host.day1_final_nap_acked",
        assistant_uid=assistant_uid,
        actor_uid=actor_uid,
    )
    manager.persist_snapshot(game, reason="day1_final_nap_acked")
    # Enter the existing independent Namayande Night-1 flow exactly once.
    from bot.nam10.nmnd_narrator import nam10_day1_defense_no_votes_enter_night

    nam10_day1_defense_no_votes_enter_night(game)
    _audit(
        game,
        "no_host.day1_night1_entry_started",
        night_count=game.nmnd_narrator_night_count,
    )
    from bot.nam10.no_host_night1 import on_no_host_entered_night1

    await on_no_host_entered_night1(bot, game, manager)


# ---------------------------------------------------------------------------
# Dispatch + restore resume
# ---------------------------------------------------------------------------


async def dispatch_nam10_day1_betrayal_act(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    actor_uid: int,
    act: str,
    *,
    as_uid: int = 0,
    tid: int = 0,
) -> None:
    """Route a Day-1 betrayal-workflow PlayerMirrorCb press."""
    from bot.room_mode import is_namayande10_no_host_room

    _audit(
        game,
        "no_host.day1_betrayal_cb",
        act=act,
        actor_uid=actor_uid,
        as_uid=as_uid or None,
        target_uid=tid or None,
        outcome="received",
    )
    if not is_namayande10_no_host_room(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return

    assistant_uid = game.bot_assistant_user_id

    if act == ACT_BW_OK:
        await _bw_ok(callback, bot, game, as_uid, actor_uid)
        return
    if act in (ACT_BOSS_ADD, ACT_BOSS_SUB):
        await _boss_choose(
            callback,
            bot,
            game,
            as_uid,
            actor_uid,
            "add" if act == ACT_BOSS_ADD else "sub",
            tid,
        )
        return
    if act == ACT_BOSS_OK:
        await _boss_confirm(callback, bot, game, as_uid, actor_uid)
        return

    # Assistant/Observer stage panels share one state through the mirror.
    if assistant_uid is None or as_uid != assistant_uid:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    if not _assistant_authorized(game, actor_uid):
        _audit(
            game,
            "no_host.day1_betrayal_cb",
            act=act,
            actor_uid=actor_uid,
            outcome="rejected",
            reject_reason="forbidden_actor",
        )
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return

    if act == ACT_TGT_OPEN:
        await _open_target_panel(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act == ACT_TGT_TOGGLE:
        await _toggle_target(
            callback, bot, game, assistant_uid, actor_uid, tid
        )
        return
    if act == ACT_TGT_OK:
        await _confirm_targets(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act == ACT_REVEAL:
        await _reveal_betrayal(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act == ACT_OUT_T1:
        await _choose_outcome(
            callback, bot, game, assistant_uid, actor_uid, OUTCOME_ELIM_1
        )
        return
    if act == ACT_OUT_T2:
        await _choose_outcome(
            callback, bot, game, assistant_uid, actor_uid, OUTCOME_ELIM_2
        )
        return
    if act == ACT_OUT_NONE:
        await _choose_outcome(
            callback, bot, game, assistant_uid, actor_uid, OUTCOME_NONE
        )
        return
    if act == ACT_FINAL_NAP:
        await _final_nap_ack(
            callback, bot, game, assistant_uid, actor_uid
        )
        return

    _audit(
        game,
        "no_host.day1_betrayal_cb",
        act=act,
        actor_uid=actor_uid,
        outcome="rejected",
        reject_reason="unknown_act",
    )
    await callback.answer("عمل نامعتبر.", show_alert=True)


async def nam10_resume_restored_day1_betrayal_rooms(
    bot: Bot, room_codes: list[str] | None
) -> list[str]:
    """Fork rooms restored while resting on the OLD
    ``day1_awaiting_betrayal_vote`` boundary continue automatically into
    the active betrayal-vote collection stage after a service restart."""
    resumed: list[str] = []
    for code in room_codes or []:
        game = manager.get_game(code)
        if game is None or game.phase == Phase.ENDED:
            continue
        if game.nam10_day1_stage != "day1_awaiting_betrayal_vote":
            continue
        try:
            if await nam10_start_day1_betrayal_collection(bot, game):
                resumed.append(code)
        except Exception:
            logger.exception(
                "day1 betrayal resume failed room=%s", code
            )
    return resumed
