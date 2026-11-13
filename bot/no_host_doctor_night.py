"""شب — انتخاب نجات پزشک (مسیر گردانندگی بدون گرداننده).

هر شب حداکثر یک نفر؛ گزینهٔ «انتخابی ندارم»؛ تأیید اجباری.
نجات خود حداکثر دو بار در کل بازی. نجات پس از پایان شب اعمال می‌شود.
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_DOC,
    Role,
    _advance_after_doc,
    _night_title_fa,
    _seat_fa,
    no_host_assistant_narrator_active,
    push_host_step,
)
from bot.no_host_night_common import (
    arm_no_host_role_pick_flow,
    no_host_after_role_night_pick,
    no_host_night_wait_phase_active,
    publish_no_host_night_wait_panel,
)
from bot.no_host_night_ready import no_host_parallel_night_collect_active
from bot.models import Game, Player
from bot.roles.registry import find_alive_role_holder
from bot.observer_delivery import (
    mirror_ui_claim_key,
    no_host_observer_registered,
    publish_mirror_prompt_pair,
    update_mirror_prompt_pair,
)
from bot.no_host_role_pick_common import (
    actor_may_act_on_role_panel,
    append_pending_selection_line,
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
    build_single_action_keyboard,
    player_button_name,
    sync_role_mirror_panel,
    target_in_pool,
    with_inline_confirm_row,
)

from bot.room_mode import is_mozakere_scenario, is_no_host_player_room
from bot.roles.doctor import (
    MAX_SELF_SAVES,
    commit_pick as _commit_doctor_pick,
    doctor_save_capacity,
    save_pool as _doctor_save_pool,
    self_save_limit_reached,
    void_night_pick,
)
from bot.roles.mozakere_doctor import MOZAKERE_MAX_SELF_SAVES, mozakere_doctor_save_capacity
from bot.roles.night_state import doctor_night_state

logger = logging.getLogger(__name__)


def _doctor_ui_key(game: Game, doc_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_doctor", doc_uid)


def _player_button_name(
    p: Player | None, uid: int, display_name: str | None = None
) -> str:
    return player_button_name(p, uid, display_name)


def _mozakere_dual_pick_active(game: Game) -> bool:
    return is_mozakere_scenario(game) and mozakere_doctor_save_capacity(game) >= 2


def _unified_pick_scenario(game: Game) -> bool:
    """تأیید سبز درون‌صفحه‌ای + لغو انتخاب: مذاکره + بازپرس."""
    return is_mozakere_scenario(game) or game.scenario_name == "bazpors"


def _doctor_capacity(game: Game) -> int:
    """ظرفیت نجات امشب — مذاکره بر اساس تعداد زنده؛ بازپرس همیشه ۱."""
    return doctor_save_capacity(game)


def _mozakere_pick_ordinal_fa(step: int) -> str:
    return {1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم"}.get(step, str(step))


def _mozakere_dual_pick_step(game: Game) -> int:
    """مرحلهٔ فعلی انتخاب چندتایی مذاکره (۱ تا ظرفیت)."""
    if not _mozakere_dual_pick_active(game):
        return 1
    return max(1, len(doctor_night_state(game).get_save_uids()) + 1)


def _mozakere_pick_should_continue(game: Game) -> bool:
    if not _mozakere_dual_pick_active(game):
        return False
    return len(doctor_night_state(game).get_save_uids()) < mozakere_doctor_save_capacity(
        game
    )


def _doctor_none_button_text(game: Game) -> str:
    if is_mozakere_scenario(game):
        return "انتخابی ندارم"
    return "⭕ انتخابی ندارم"


def _mozakere_doctor_rules_blurb(game: Game) -> str:
    from bot.roles.mozakere_doctor import mozakere_alive_player_count

    cap = mozakere_doctor_save_capacity(game)
    alive = mozakere_alive_player_count(game)
    n = doctor_night_state(game).self_save_count
    return (
        f"👤 با {_seat_fa(alive)} بازیکن زنده، امشب تا {_seat_fa(cap)} نجات دارید.\n\n"
        "همچنین در طول بازی، می‌توانید تا دو بار خودتان را نجات دهید.\n"
        f"📊 تعداد دفعات نجات خود تا این لحظه: {_seat_fa(n)} از "
        f"{_seat_fa(MOZAKERE_MAX_SELF_SAVES)}"
    )


def _pick_pool_for_keyboard(game: Game) -> list[Player]:
    pool = _doctor_save_pool(game)
    if _mozakere_dual_pick_active(game) and _mozakere_dual_pick_step(game) > 1:
        saved = set(doctor_night_state(game).get_save_uids())
        pool = [p for p in pool if p.user_id not in saved]
    return pool


def _pending_save_uid(game: Game) -> int | None:
    uids = doctor_night_state(game).no_host_pending_save_uids
    return uids[0] if uids else None


def _set_pending_save_uid(game: Game, uid: int | None) -> None:
    doctor_night_state(game).set_no_host_pending_save_uids(
        [uid] if uid is not None else []
    )


def build_no_host_doctor_nato_blocked_html() -> str:
    return (
        "🚨 ════『 عملیات ناتویی 』════ 🚨\n\n"
        "🕶️ تیم مافیا امشب قصد اجرای\n"
        "🔥 عملیات ناتویی 🔥\n"
        "را دارند.\n\n"
        "⛔ در نتیجه،\n"
        "امشب امکان انتخاب هیچ بازیکنی برای شما وجود ندارد.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✅ لطفاً دکمه «اوکی» را انتخاب کنید.\n"
        "━━━━━━━━━━━━━━━━━━"
    )


def build_no_host_doctor_pick_html(game: Game) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    if is_mozakere_scenario(game):
        cap = mozakere_doctor_save_capacity(game)
        if cap >= 2:
            pick_line = (
                f"🛡️ لطفاً تا <b>{_seat_fa(cap)} نفر</b> را "
                "از لیست زیر برای نجات انتخاب کنید."
            )
        else:
            pick_line = "🛡️ لطفاً <b>یک نفر</b> را از لیست زیر برای نجات انتخاب کنید."
        return (
            f"💉 {night_lbl} - ثبت انتخاب پزشک\n\n"
            f"{pick_line}\n\n"
            f"{_mozakere_doctor_rules_blurb(game)}\n\n"
            "📩 انتخاب شما پس از پایان فاز امشب اعمال خواهد شد."
        )
    n = doctor_night_state(game).self_save_count
    return (
        f"💉 {night_lbl} - ثبت انتخاب پزشک\n\n"
        "🛡️ لطفاً <b>یک نفر</b> را از لیست زیر برای نجات انتخاب کنید.\n\n"
        "👤 شما در طول بازی حداکثر دو بار می‌توانید خودتان را نجات دهید.\n\n"
        f"📊 تعداد دفعات نجات خود تا این لحظه: {_seat_fa(n)} از {_seat_fa(MAX_SELF_SAVES)}\n\n"
        "📩 انتخاب شما پس از پایان فاز امشب اعمال خواهد شد."
    )


def build_no_host_doctor_confirm_html(
    game: Game, gm: "GameManager", target_uid: int | None
) -> str:
    if target_uid is None:
        targets = "⭕ <b>انتخابی ندارم</b>"
    else:
        p = game.players.get(target_uid)
        targets = html.escape(
            _player_button_name(p, target_uid, gm.user_display_names.get(target_uid))
        )
    return (
        f"{build_no_host_doctor_pick_html(game)}\n\n"
        f"🛡️ نجات: <b>{targets}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_doctor_finalized_pick_html(
    game: Game, gm: "GameManager" | None = None
) -> str:
    """پیام پس از تأیید نهایی — مذاکره: فقط نام بازیکن‌ها، بدون نقش."""
    uids = doctor_night_state(game).get_save_uids()
    if not uids:
        selection = "انتخابی ندارم"
    else:
        names = [
            html.escape(
                _player_button_name(
                    game.players.get(uid),
                    uid,
                    gm.user_display_names.get(uid) if gm is not None else None,
                )
            )
            for uid in uids
        ]
        selection = "انتخاب:\n" + "\n".join(names)
    return (
        "✅ انتخاب شما ثبت شد:\n\n"
        f"{selection}\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید."
    )


def build_no_host_doctor_waiting_html(
    game: Game, gm: "GameManager"
) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    uids = doctor_night_state(game).get_save_uids()
    if not uids:
        body = "شما این شب کسی را نجات ندادید."
    elif len(uids) == 1:
        uid = uids[0]
        p = game.players.get(uid)
        name = html.escape(gm.format_player_tag(p) if p else str(uid))
        body = f"نجات <b>{name}</b> ثبت شد."
    else:
        names = []
        for uid in uids:
            p = game.players.get(uid)
            names.append(html.escape(gm.format_player_tag(p) if p else str(uid)))
        body = f"نجات <b>{' و '.join(names)}</b> ثبت شد."
    return (
        f"💉 {night_lbl} - ثبت انتخاب پزشک\n\n"
        f"✅ {body}\n\n"
        "📩 اعمال نجات پس از پایان فاز امشب است.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def _pick_keyboard(
    game: Game, doc_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    pending = list(game.no_host_doctor_pending_save_uids)
    none_pending = bool(game.no_host_doctor_pending_none)
    if not pending and not none_pending:
        pending = list(doctor_night_state(game).get_save_uids())
    kb = build_pick_keyboard(
        game,
        doc_uid,
        pick_act="dkt",
        players=_pick_pool_for_keyboard(game),
        none_act="dkn",
        none_text=_doctor_none_button_text(game),
        selected_uids=pending,
        none_selected=none_pending,
        display_names=gm.user_display_names,
    )
    if _unified_pick_scenario(game):
        kb = with_inline_confirm_row(game, doc_uid, kb, confirm_act="dkc")
    return kb


def _mozakere_doctor_pending_line(game: Game, gm: "GameManager") -> str:
    """خط انتخاب فعلی برای پنل چندانتخابی پزشک (مذاکره)."""
    if game.no_host_doctor_pending_none:
        return "⭕ انتخاب فعلی: <b>انتخابی ندارم</b>"
    pending = list(game.no_host_doctor_pending_save_uids)
    if pending:
        names = [
            html.escape(
                _player_button_name(
                    game.players.get(uid),
                    uid,
                    gm.user_display_names.get(uid),
                )
            )
            for uid in pending
        ]
        return "🛡️ انتخاب فعلی: <b>" + "، ".join(names) + "</b>"
    return "🛡️ انتخاب فعلی: <i>هنوز انتخابی ثبت نشده است</i>"


def _mozakere_doctor_pending_text(game: Game, gm: "GameManager") -> str:
    return append_pending_selection_line(
        build_no_host_doctor_pick_html(game),
        [_mozakere_doctor_pending_line(game, gm)],
    )


async def _sync_mozakere_doctor_panel(
    bot: Bot, game: Game, doc_uid: int, gm: "GameManager"
) -> None:
    text = _mozakere_doctor_pending_text(game, gm)
    kb = _pick_keyboard(game, doc_uid, gm)
    await _sync_panel(bot, game, doc_uid, text, kb)


def _nato_blocked_keyboard(game: Game, doc_uid: int) -> InlineKeyboardMarkup:
    return build_single_action_keyboard(
        game, doc_uid, act="dko", text="✅ اوکی"
    )


def _mozakere_negotiation_skip_keyboard(game: Game, doc_uid: int) -> InlineKeyboardMarkup:
    return build_single_action_keyboard(
        game, doc_uid, act="dkng", text="✅ اوکی"
    )


def _confirm_keyboard(game: Game, doc_uid: int) -> InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        game,
        doc_uid,
        confirm_act="dkc",
        back_act="dkb",
        confirm_text="✅ بله، تأیید",
        back_text="↩️ بازگشت",
    )


def _should_run_no_host_doctor_flow(game: Game) -> bool:
    return (
        is_no_host_player_room(game)
        and no_host_assistant_narrator_active(game)
        and game.bazpors_narrator_step == NIGHT_ACTIONS
        and game.bazpors_night_substep == NS_DOC
    )


async def _disable_superseded_doctor_panels(
    bot: Bot, game: Game, doc_uid: int
) -> None:
    """Room 7 (Bazpors): close the superseded pre-NATO doctor panel copies.

    Runs BEFORE the NATO-blocked OK-only panel is delivered, while the
    tracked refs of the old target-selection panel still exist. The real
    player's copy is re-edited in place by the normal delivery path (same
    message_id), so it is never touched here; the observer-mirrored copy is
    the one superseded by ``fresh_observer_copy`` and must be closed
    explicitly. forbear on Telegram errors: try deleting the message, fall
    back to keyboard-only removal; both failures are non-fatal because
    stale callbacks are already rejected by the dispatch guards."""
    from aiogram.exceptions import TelegramBadRequest

    from bot.game import is_synthetic_player_uid

    entry = game.mirror_prompt_messages.get(_doctor_ui_key(game, doc_uid)) or {}
    for role in ("player", "observer"):
        ref = entry.get(role)
        if not (isinstance(ref, tuple) and len(ref) == 2):
            continue
        if role == "player" and not is_synthetic_player_uid(doc_uid):
            # Real doctor: the player copy is edited in place below — do not
            # delete the message we are about to update.
            continue
        chat_id, message_id = int(ref[0]), int(ref[1])
        deleted = False
        try:
            deleted = bool(await bot.delete_message(chat_id, message_id))
        except TelegramBadRequest:
            deleted = False
        except Exception:
            logger.debug(
                "doctor nato cleanup: delete failed chat_id=%s message_id=%s",
                chat_id,
                message_id,
            )
        if deleted:
            continue
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except TelegramBadRequest:
            pass  # keyboard already removed / message gone
        except Exception:
            logger.debug(
                "doctor nato cleanup: keyboard removal failed "
                "chat_id=%s message_id=%s",
                chat_id,
                message_id,
            )


async def _send_doctor_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    doc_uid: int,
    *,
    sig: str,
    nato_blocked: bool,
) -> bool:
    doc_state = doctor_night_state(game)
    pick = doc_state.no_host_pick()
    if pick.dm_signature == sig and pick.pick_confirmed:
        return False
    ui_key = _doctor_ui_key(game, doc_uid)
    pick.flow_active = True
    doc_state.clear_no_host_pending_save_uids()
    game.no_host_doctor_pending_none = False
    pick.dm_signature = sig
    doc_state.no_host_nato_blocked_panel = nato_blocked

    if nato_blocked:
        # Room 7 (Bazpors): the NATO-blocked replacement SUPERSEDES the old
        # target-selection panel. update_mirror_prompt_pair drops the tracked
        # observer ref via fresh_observer_copy without touching the live
        # message — so close the superseded copy(ies) FIRST, while the
        # tracked refs still exist, or the old keyboard stays visible and
        # looks actionable (duplicate panels in the observer mirror).
        if game.scenario_name == "bazpors":
            await _disable_superseded_doctor_panels(bot, game, doc_uid)
        text = build_no_host_doctor_nato_blocked_html()
        kb = _nato_blocked_keyboard(game, doc_uid)
        log_kind = "no_host.doctor_nato_blocked_panel_sent"
    else:
        text = build_no_host_doctor_pick_html(game)
        kb = _pick_keyboard(game, doc_uid, gm)
        log_kind = "no_host.doctor_night_panel_sent"

    await publish_mirror_prompt_pair(
        bot,
        game,
        doc_uid,
        ui_key,
        text,
        kb,
        fresh_observer_copy=True,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            log_kind,
            doc_uid=doc_uid,
            night_count=game.bazpors_narrator_night_count,
            self_saves=doc_state.self_save_count,
            nato_blocked=nato_blocked,
        )
    except Exception:
        pass
    return True


async def start_no_host_doctor_night_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    at_night_entry: bool = False,
) -> bool:
    if at_night_entry:
        if not no_host_night_wait_phase_active(game):
            return False
    elif not _should_run_no_host_doctor_flow(game):
        return False
    doc = find_alive_role_holder(game, Role.DOCTOR)
    if doc is None:
        return False
    nc = game.bazpors_narrator_night_count
    sig = f"{nc}:doc:night_entry" if at_night_entry else f"{nc}:doc:{NS_DOC}"
    if game.no_host_doctor_pick_confirmed:
        return False
    nato_blocked = bool(game.bazpors_nato_action_registered)
    return await _send_doctor_panel(
        bot, game, gm, doc.user_id, sig=sig, nato_blocked=nato_blocked
    )


async def apply_no_host_doctor_nato_blocked_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از تأیید ناتویی — باطل کردن انتخاب پزشک و جایگزینی پنل (اگر هنوز تأیید نکرده)."""
    if not game.bazpors_nato_action_registered:
        return
    void_night_pick(game)
    doc = find_alive_role_holder(game, Role.DOCTOR)
    if doc is None:
        return
    if game.no_host_doctor_pick_confirmed:
        game.no_host_doctor_pick_confirmed = False
        game.no_host_doctor_flow_active = True
        game.no_host_doctor_dm_signature = None
    nc = game.bazpors_narrator_night_count
    sig = f"{nc}:doc:nato_blocked"
    sent = await _send_doctor_panel(
        bot, game, gm, doc.user_id, sig=sig, nato_blocked=True
    )
    if not sent:
        # Already-acked NATO panel (signature matched + confirmed): make
        # sure the doctor's panel copies for the player AND the observer
        # are closed (kb=None) instead of staying interactive.
        game.no_host_doctor_nato_blocked_panel = True
        await _sync_panel(
            bot,
            game,
            doc.user_id,
            build_no_host_doctor_nato_blocked_html(),
            None,
        )


async def dispatch_no_host_doctor_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.no_host_night_entry import complete_no_host_role_night_if_already_picked

    await complete_no_host_role_night_if_already_picked(bot, game, gm)
    if game.no_host_doctor_pick_confirmed:
        if not no_host_night_wait_phase_active(game):
            return
        doc = find_alive_role_holder(game, Role.DOCTOR)
        if doc is not None:
            await _publish_doctor_pick_finalized_panel(
                bot, game, gm, doc.user_id
            )
        return
    await start_no_host_doctor_night_flow(bot, game, gm)


def no_host_doctor_act_active(game: Game, act: str) -> bool:
    return act in ("dkt", "dkn", "dkc", "dkb", "dko", "dkng")


def _actor_may_act(game: Game, actor_uid: int, doc_uid: int) -> bool:
    return actor_may_act_on_role_panel(game, actor_uid, doc_uid)


async def _sync_panel(
    bot: Bot,
    game: Game,
    doc_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await sync_role_mirror_panel(
        bot, game, _doctor_ui_key(game, doc_uid), doc_uid, text, kb
    )


async def _publish_doctor_pick_finalized_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    doc_uid: int,
) -> None:
    ui_key = _doctor_ui_key(game, doc_uid)
    if is_mozakere_scenario(game):
        body = build_no_host_doctor_finalized_pick_html(game, gm)
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            body,
            None,
            assistant_uid=doc_uid,
            parse_mode="HTML",
        )
        return
    uids = doctor_night_state(game).get_save_uids()
    pick = uids[0] if uids else None
    await publish_no_host_night_wait_panel(
        bot,
        game,
        doc_uid,
        ui_key,
        "",
        gm=gm,
        selection_uid=pick,
    )


async def _complete_no_host_doctor_pick(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    doc_uid: int,
) -> None:
    game.no_host_doctor_pick_confirmed = True
    game.no_host_doctor_flow_active = False
    game.no_host_doctor_pending_save_uids = []
    game.no_host_doctor_pending_none = False
    uids = doctor_night_state(game).get_save_uids()
    pick = uids[0] if uids else None
    await callback.answer("ثبت شد.")
    await _publish_doctor_pick_finalized_panel(bot, game, gm, doc_uid)
    await no_host_after_role_night_pick(
        bot, game, gm, expected_substep=NS_DOC, advance=_advance_after_doc
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.doctor_pick_confirmed",
            doc_uid=doc_uid,
            save_uid=pick,
            save_uids=uids,
            self_save_pending=doctor_night_state(game).pending_self_save,
        )
    except Exception:
        pass


async def dispatch_no_host_doctor_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    doc_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    from bot.no_host_mozakere_negotiation_reset import (
        MOZAKERE_NEGOTIATION_PENDING_ALERT,
        mozakere_negotiation_pending,
    )

    if mozakere_negotiation_pending(game):
        # Room 44: no town action may be recorded while the mafia
        # negotiation is pending. Runs BEFORE any state mutation or
        # flow re-arming and holds even if Telegram cleanup failed.
        await callback.answer(
            MOZAKERE_NEGOTIATION_PENDING_ALERT, show_alert=True
        )
        return
    arm_no_host_role_pick_flow(
        game,
        flow_active_attr="no_host_doctor_flow_active",
        pick_confirmed_attr="no_host_doctor_pick_confirmed",
        dm_signature_attr="no_host_doctor_dm_signature",
    )
    if act == "dkng":
        from bot.no_host_mozakere_negotiation_reset import (
            MOZAKERE_DOCTOR_NEGOTIATION_SKIP_HTML,
            mozakere_doctor_negotiation_skip_active,
        )

        if not is_mozakere_scenario(game) or not mozakere_doctor_negotiation_skip_active(
            game
        ):
            await callback.answer("این دکمه فعال نیست.", show_alert=True)
            return
        if not _actor_may_act(game, actor_uid, doc_uid):
            await callback.answer(
                "فقط پزشک می‌تواند این انتخاب را انجام دهد.", show_alert=True
            )
            return
        await callback.answer("ثبت شد.")
        await _sync_panel(
            bot, game, doc_uid, MOZAKERE_DOCTOR_NEGOTIATION_SKIP_HTML, None
        )
        return
    if game.no_host_doctor_nato_blocked_panel and act != "dko":
        await callback.answer(
            "امشب به‌دلیل عملیات ناتویی امکان انتخاب ندارید؛ «اوکی» را بزنید.",
            show_alert=True,
        )
        return
    from bot.roles.doctor import blocked_this_night

    if blocked_this_night(game) and not game.no_host_doctor_nato_blocked_panel:
        # Yakuza committed this night: the doctor's pick is cancelled by the
        # rules - reject stale panel presses so no void pick is recorded.
        await callback.answer(
            "امشب پزشک به‌دلیل عملیات مافیا (یاکوزایی) انتخاب ندارد.",
            show_alert=True,
        )
        return
    if not game.no_host_doctor_flow_active or game.no_host_doctor_pick_confirmed:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not no_host_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    doc = find_alive_role_holder(game, Role.DOCTOR)
    if doc is None or doc.user_id != doc_uid:
        await callback.answer("پزشک در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, doc_uid):
        await callback.answer("فقط پزشک می‌تواند این انتخاب را انجام دهد.", show_alert=True)
        return

    if act == "dko":
        if not game.no_host_doctor_nato_blocked_panel:
            await callback.answer("این دکمه فقط پس از عملیات ناتویی فعال است.", show_alert=True)
            return
        if game.no_host_doctor_pick_confirmed:
            await callback.answer("قبلاً ثبت شده است.", show_alert=True)
            return
        _commit_doctor_pick(game, None)
        game.no_host_doctor_pick_confirmed = True
        game.no_host_doctor_flow_active = False
        await callback.answer("ثبت شد.")
        await _sync_panel(bot, game, doc_uid, build_no_host_doctor_nato_blocked_html(), None)
        if not no_host_parallel_night_collect_active(game):
            await no_host_after_role_night_pick(
                bot, game, gm, expected_substep=NS_DOC, advance=_advance_after_doc
            )
        else:
            from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

            await maybe_finish_no_host_parallel_night(bot, game, gm)
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.doctor_nato_blocked_ack",
                doc_uid=doc_uid,
            )
        except Exception:
            pass
        return

    pool = _doctor_save_pool(game)

    if _unified_pick_scenario(game):
        # مذاکره/بازپرس — پنل انتخاب واحد: انتظار + تأیید سبز در همان صفحه.
        cap = _doctor_capacity(game)
        if act == "dkt":
            if not target_in_pool(tid, pool):
                await callback.answer("این بازیکن در لیست نیست.", show_alert=True)
                return
            if tid == doc.user_id and self_save_limit_reached(game):
                await callback.answer(
                    "شما قبلاً دو بار خود را نجات داده‌اید.",
                    show_alert=True,
                )
                return
            pending = list(game.no_host_doctor_pending_save_uids)
            if tid in pending:
                # زدن دوباره روی انتخاب فعلی = لغو آن انتخاب.
                pending.remove(tid)
                await callback.answer("انتخاب لغو شد.")
            elif len(pending) >= cap:
                if cap == 1:
                    # ظرفیت ۱ — انتخاب جدید جایگزین انتخاب قبلی می‌شود.
                    pending = [tid]
                    await callback.answer("انتخاب شد؛ تأیید کنید.")
                else:
                    await callback.answer(
                        f"ظرفیت نجات امشب تکمیل است (حداکثر {_seat_fa(cap)} نفر).",
                        show_alert=True,
                    )
                    return
            else:
                pending.append(tid)
                await callback.answer("انتخاب شد؛ تأیید کنید.")
            game.no_host_doctor_pending_save_uids = pending
            game.no_host_doctor_pending_none = False
            await _sync_mozakere_doctor_panel(bot, game, doc_uid, gm)
            return
        if act == "dkn":
            if game.no_host_doctor_pending_none:
                game.no_host_doctor_pending_none = False
                await callback.answer("انتخابی ندارم — لغو شد.")
            else:
                game.no_host_doctor_pending_none = True
                game.no_host_doctor_pending_save_uids = []
                await callback.answer("انتخابی ندارم؛ تأیید کنید.")
            await _sync_mozakere_doctor_panel(bot, game, doc_uid, gm)
            return
        if act == "dkb":
            game.no_host_doctor_pending_save_uids = []
            game.no_host_doctor_pending_none = False
            await callback.answer("بازگشت به لیست.")
            text = build_no_host_doctor_pick_html(game)
            kb = _pick_keyboard(game, doc_uid, gm)
            await _sync_panel(bot, game, doc_uid, text, kb)
            return
        if act == "dkc":
            if game.no_host_doctor_pick_confirmed:
                await callback.answer("قبلاً ثبت شده است.", show_alert=True)
                return
            if game.no_host_doctor_pending_none:
                _commit_doctor_pick(game, None)
                await _complete_no_host_doctor_pick(
                    callback, bot, game, gm, doc_uid
                )
                return
            pending = list(game.no_host_doctor_pending_save_uids)
            if not pending:
                await callback.answer(
                    "ابتدا یک بازیکن انتخاب کنید یا «انتخابی ندارم» را بزنید.",
                    show_alert=True,
                )
                return
            for uid in pending:
                if not target_in_pool(uid, pool):
                    await callback.answer("انتخاب نامعتبر.", show_alert=True)
                    return
                if uid == doc.user_id and self_save_limit_reached(game):
                    await callback.answer(
                        "شما قبلاً دو بار خود را نجات داده‌اید.",
                        show_alert=True,
                    )
                    return
            for uid in pending:
                _commit_doctor_pick(game, uid)
            await _complete_no_host_doctor_pick(callback, bot, game, gm, doc_uid)
            return

    if act == "dkt":
        if not target_in_pool(tid, pool):
            await callback.answer("این بازیکن در لیست نیست.", show_alert=True)
            return
        _set_pending_save_uid(game, tid)
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        text = build_no_host_doctor_confirm_html(game, gm, tid)
        kb = _confirm_keyboard(game, doc_uid)
        await _sync_panel(bot, game, doc_uid, text, kb)
        return

    if act == "dkn":
        _set_pending_save_uid(game, None)
        await callback.answer("انتخابی ندارم؛ تأیید کنید.")
        text = build_no_host_doctor_confirm_html(game, gm, None)
        kb = _confirm_keyboard(game, doc_uid)
        await _sync_panel(bot, game, doc_uid, text, kb)
        return

    if act == "dkb":
        _set_pending_save_uid(game, None)
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_doctor_pick_html(game)
        kb = _pick_keyboard(game, doc_uid, gm)
        await _sync_panel(bot, game, doc_uid, text, kb)
        return

    if act == "dkc":
        pick = _pending_save_uid(game)
        if pick is not None and not target_in_pool(pick, pool):
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        if game.no_host_doctor_pick_confirmed:
            await callback.answer("قبلاً ثبت شده است.", show_alert=True)
            return
        _commit_doctor_pick(game, pick)
        await _complete_no_host_doctor_pick(callback, bot, game, gm, doc_uid)
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
