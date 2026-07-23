"""شب — پنل خبرنگار (فقط سناریوی مذاکره، مسیر no_host).

قبل از انجام مذاکره: پنل انتظار + دکمهٔ اوکی.
بعد از مذاکره: انتخاب بازیکن برای بررسی recruit از طریق مذاکره.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.bazpors_narrator import NIGHT_START, Role, _night_title_fa, no_host_assistant_narrator_active
from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.no_host_night_common import (
    arm_no_host_role_pick_flow,
    no_host_night_wait_phase_active,
    no_host_role_ack_keyboard,
    publish_no_host_night_wait_panel,
)
from bot.no_host_role_pick_common import (
    actor_may_act_on_role_panel,
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
    player_button_name,
    sync_role_mirror_panel,
    target_in_pool,
)
from bot.observer_delivery import (
    deliver_no_host_player_game_copy,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
    send_to_player,
    update_mirror_prompt_pair,
)
from bot.room_mode import is_mozakere_scenario, is_no_host_player_room
from bot.roles.mozakere_journalist import (
    commit_check as commit_journalist_check,
    find_alive_journalist,
    investigation_pool,
    load_result as load_journalist_result,
    mozakere_journalist_active,
)
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager


def _journalist_ui_key(game: Game, jr_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_journalist", jr_uid)


def _player_button_name(p: Player | None, uid: int) -> str:
    return player_button_name(p, uid)


def build_no_host_journalist_idle_html(*, confirmed: bool = False) -> str:
    if confirmed:
        return (
            "🟢 <b>خبرنگار</b>\n\n"
            "✅ تأیید شما ثبت شد.\n\n"
            "⏳ لطفاً منتظر اتمام فاز شب بمانید."
        )
    return (
        "🟢 <b>خبرنگار</b>\n\n"
        "مذاکره هنوز انجام نشده است تا شب بعد صبر کنید."
    )


def build_no_host_journalist_pick_html(game: Game) -> str:
    if mozakere_journalist_active(game):
        return (
            "👤 مذاکره به پایان رسید. اکنون استعلام چه کسی را می‌خواهید بگیرید؟"
        )
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"🟢 {night_lbl} — خبرنگار\n\n"
        "یک بازیکن را انتخاب کنید تا بررسی شود آیا با مذاکره به تیم مافیا "
        "پیوسته است یا نه."
    )


def build_no_host_journalist_confirm_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    del gm
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    if mozakere_journalist_active(game):
        return (
            "👤 <b>خبرنگار</b>\n\n"
            f"انتخاب شما:\n<b>{name}</b>\n\n"
            "آیا این انتخاب را تأیید می‌کنید؟"
        )
    return (
        f"{build_no_host_journalist_pick_html(game)}\n\n"
        f"🎯 انتخاب شما: <b>{name}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_journalist_waiting_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    return (
        f"🟢 {night_lbl} — خبرنگار\n\n"
        f"✅ بررسی روی <b>{name}</b> ثبت شد.\n\n"
        "📩 نتیجه پس از پایان فاز امشب برایتان ارسال می‌شود.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def build_no_host_journalist_result_html(game: Game, gm: "GameManager") -> str | None:
    if not game.no_host_journalist_pick_confirmed:
        return None
    jr = find_alive_journalist(game)
    snap = game.bazpors_alive_at_night_start or {}
    jr_uid = None
    if jr is not None:
        jr_uid = jr.user_id
    else:
        for uid, pl in game.players.items():
            if pl.role == Role.JOURNALIST and snap.get(uid, pl.is_alive):
                jr_uid = uid
                break
    if jr_uid is None:
        return None

    result = load_journalist_result(game)
    if result is None:
        return None

    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    tgt = game.players.get(result.target_uid)
    name = html.escape(
        gm.format_player_tag(tgt) if tgt else str(result.target_uid)
    )
    return (
        f"🟢 {night_lbl} — نتیجهٔ خبرنگار\n\n"
        f"🎯 هدف: <b>{name}</b>\n\n"
        f"{result.detail_fa()}"
    )


def _should_run_no_host_journalist_flow(game: Game) -> bool:
    return (
        is_mozakere_scenario(game)
        and is_no_host_player_room(game)
        and no_host_night_wait_phase_active(game)
        and find_alive_journalist(game) is not None
    )


def _idle_keyboard(game: Game, jr_uid: int) -> InlineKeyboardMarkup:
    return no_host_role_ack_keyboard(game, jr_uid, "jic")


def _pick_keyboard(
    game: Game, jr_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    del gm
    return build_pick_keyboard(
        game,
        jr_uid,
        pick_act="jrp",
        players=investigation_pool(game),
    )


def _confirm_keyboard(game: Game, jr_uid: int) -> InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        game,
        jr_uid,
        confirm_act="jrc",
        back_act="jrb",
        confirm_text="✅ تأیید",
        back_text="↩️ بازگشت",
    )


async def activate_journalist_after_mozakere_negotiation(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از commit مذاکره — پنل انتخاب خبرنگار حتی اگر قبلاً اوکی زده باشد."""
    if not _should_run_no_host_journalist_flow(game):
        return
    if not mozakere_journalist_active(game):
        return
    jr = find_alive_journalist(game)
    if jr is None:
        return

    game.no_host_journalist_idle_confirmed = False
    game.no_host_journalist_pick_confirmed = False
    game.no_host_journalist_flow_active = True
    game.no_host_journalist_pending_tid = None
    game.no_host_journalist_dm_signature = None

    text = build_no_host_journalist_pick_html(game)
    kb = _pick_keyboard(game, jr.user_id, gm)
    ui_key = _journalist_ui_key(game, jr.user_id)
    await register_mirror_prompt_pair(
        bot,
        game,
        jr.user_id,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.journalist_post_negotiation_panel_sent",
            jr_uid=jr.user_id,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass


async def start_no_host_journalist_night_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    at_night_entry: bool = False,
) -> bool:
    if not _should_run_no_host_journalist_flow(game):
        return False
    if at_night_entry and game.bazpors_narrator_step != NIGHT_START:
        return False

    jr = find_alive_journalist(game)
    if jr is None:
        return False

    nc = game.bazpors_narrator_night_count
    active = mozakere_journalist_active(game)
    sig = (
        f"{nc}:journalist:night_entry:{'pick' if active else 'idle'}"
        if at_night_entry
        else f"{nc}:journalist:{'pick' if active else 'idle'}"
    )

    if active:
        if game.no_host_journalist_pick_confirmed:
            return False
        if game.no_host_journalist_dm_signature == sig:
            return False
        game.no_host_journalist_flow_active = True
        game.no_host_journalist_pending_tid = None
        game.no_host_journalist_dm_signature = sig
        text = build_no_host_journalist_pick_html(game)
        kb = _pick_keyboard(game, jr.user_id, gm)
    else:
        if game.no_host_journalist_idle_confirmed:
            return False
        if game.no_host_journalist_dm_signature == sig:
            return False
        game.no_host_journalist_dm_signature = sig
        text = build_no_host_journalist_idle_html(confirmed=False)
        kb = _idle_keyboard(game, jr.user_id)

    ui_key = _journalist_ui_key(game, jr.user_id)
    await register_mirror_prompt_pair(
        bot,
        game,
        jr.user_id,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.journalist_night_panel_sent",
            jr_uid=jr.user_id,
            night_count=nc,
            active=active,
        )
    except Exception:
        pass
    return True


async def dispatch_no_host_journalist_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not _should_run_no_host_journalist_flow(game):
        return
    jr = find_alive_journalist(game)
    if jr is None:
        return
    if mozakere_journalist_active(game):
        if game.no_host_journalist_pick_confirmed:
            pick = game.mozakere_journalist_target_uid or game.no_host_journalist_pending_tid
            if pick is not None:
                await publish_no_host_night_wait_panel(
                    bot,
                    game,
                    jr.user_id,
                    _journalist_ui_key(game, jr.user_id),
                    "",
                    gm=gm,
                    selection_uid=pick,
                )
            return
    elif game.no_host_journalist_idle_confirmed:
        return
    await start_no_host_journalist_night_flow(bot, game, gm)


async def flush_no_host_journalist_result_pending(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not game.no_host_journalist_result_pending:
        return
    game.no_host_journalist_result_pending = False
    await send_no_host_journalist_result_dm(bot, game, gm)


async def send_no_host_journalist_result_dm(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not (
        is_mozakere_scenario(game)
        and game.bazpors_host_mode == "no_host"
        and no_host_assistant_narrator_active(game)
    ):
        return
    nc = game.bazpors_narrator_night_count
    if game.no_host_journalist_result_sent_night == nc:
        return
    body = build_no_host_journalist_result_html(game, gm)
    if not body:
        return
    jr = find_alive_journalist(game)
    if jr is None:
        snap = game.bazpors_alive_at_night_start or {}
        for uid, pl in game.players.items():
            if pl.role == Role.JOURNALIST and snap.get(uid, False):
                await deliver_no_host_player_game_copy(
                    bot,
                    game,
                    uid,
                    body,
                    is_synthetic_uid=is_synthetic_player_uid,
                    parse_mode="HTML",
                )
                game.no_host_journalist_result_sent_night = nc
                return
        return
    await send_to_player(
        bot,
        game,
        jr.user_id,
        body,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    game.no_host_journalist_result_sent_night = nc
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.journalist_result_sent",
            jr_uid=jr.user_id,
            night_count=nc,
        )
    except Exception:
        pass


def no_host_journalist_act_active(game: Game, act: str) -> bool:
    if not is_mozakere_scenario(game):
        return False
    return act in ("jic", "jrp", "jrc", "jrb")


def _actor_may_act(game: Game, actor_uid: int, jr_uid: int) -> bool:
    return actor_may_act_on_role_panel(game, actor_uid, jr_uid)


async def _sync_panel(
    bot: Bot,
    game: Game,
    jr_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await sync_role_mirror_panel(
        bot, game, _journalist_ui_key(game, jr_uid), jr_uid, text, kb
    )


async def dispatch_no_host_journalist_idle_confirm(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    jr_uid: int,
    actor_uid: int,
) -> None:
    if not _should_run_no_host_journalist_flow(game):
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if mozakere_journalist_active(game):
        await callback.answer("خبرنگار اکنون باید بازیکن انتخاب کند.", show_alert=True)
        return
    jr = find_alive_journalist(game)
    if jr is None or jr.user_id != jr_uid:
        await callback.answer("خبرنگار در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, jr_uid):
        await callback.answer("فقط خبرنگار می‌تواند این دکمه را بزند.", show_alert=True)
        return
    if game.no_host_journalist_idle_confirmed:
        await callback.answer("قبلاً تأیید کرده‌اید.")
        return

    game.no_host_journalist_idle_confirmed = True
    await callback.answer("تأیید ثبت شد.")
    text = build_no_host_journalist_idle_html(confirmed=True)
    await update_mirror_prompt_pair(
        bot,
        game,
        _journalist_ui_key(game, jr_uid),
        text,
        None,
        assistant_uid=jr_uid,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.journalist_idle_confirmed",
            jr_uid=jr_uid,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass

    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)


async def dispatch_no_host_journalist_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    jr_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    if act == "jic":
        await dispatch_no_host_journalist_idle_confirm(
            callback, bot, game, gm, jr_uid=jr_uid, actor_uid=actor_uid
        )
        return

    arm_no_host_role_pick_flow(
        game,
        flow_active_attr="no_host_journalist_flow_active",
        pick_confirmed_attr="no_host_journalist_pick_confirmed",
        dm_signature_attr="no_host_journalist_dm_signature",
    )
    if not game.no_host_journalist_flow_active or game.no_host_journalist_pick_confirmed:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not mozakere_journalist_active(game):
        await callback.answer("مذاکره هنوز انجام نشده است.", show_alert=True)
        return
    if not no_host_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    jr = find_alive_role_holder(game, Role.JOURNALIST)
    if jr is None or jr.user_id != jr_uid:
        await callback.answer("خبرنگار در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, jr_uid):
        await callback.answer("فقط خبرنگار می‌تواند این انتخاب را انجام دهد.", show_alert=True)
        return

    pool = investigation_pool(game)

    if act == "jrp":
        if not target_in_pool(tid, pool):
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        game.no_host_journalist_pending_tid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        text = build_no_host_journalist_confirm_html(game, gm, tid)
        kb = _confirm_keyboard(game, jr_uid)
        await _sync_panel(bot, game, jr_uid, text, kb)
        return

    if act == "jrb":
        game.no_host_journalist_pending_tid = None
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_journalist_pick_html(game)
        kb = _pick_keyboard(game, jr_uid, gm)
        await _sync_panel(bot, game, jr_uid, text, kb)
        return

    if act == "jrc":
        pick = game.no_host_journalist_pending_tid
        if pick is None or not target_in_pool(pick, pool):
            await callback.answer("ابتدا یک بازیکن انتخاب کنید.", show_alert=True)
            return
        if game.no_host_journalist_pick_confirmed:
            await callback.answer("بررسی قبلاً ثبت شده است.", show_alert=True)
            return
        commit_journalist_check(game, pick)
        game.no_host_journalist_pick_confirmed = True
        game.no_host_journalist_flow_active = False
        game.no_host_journalist_pending_tid = None

        await callback.answer("ثبت شد.")
        await publish_no_host_night_wait_panel(
            bot,
            game,
            jr_uid,
            _journalist_ui_key(game, jr_uid),
            "",
            gm=gm,
            selection_uid=pick,
        )
        try:
            from bot.game_audit_log import log_event
            from bot.roles.mozakere_journalist import load_result

            jr_result = load_result(game)
            log_event(
                game,
                "no_host.journalist_pick_confirmed",
                jr_uid=jr_uid,
                target_uid=pick,
                actor_uid=actor_uid,
                night_count=game.bazpors_narrator_night_count,
                journalist_positive=(
                    jr_result.is_positive if jr_result is not None else None
                ),
            )
        except Exception:
            pass

        from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

        await maybe_finish_no_host_parallel_night(bot, game, gm)
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
