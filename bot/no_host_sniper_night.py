"""شب — انتخاب شلیک اسنایپر (مسیر گردانندگی بدون گرداننده).

یک شلیک در کل بازی؛ گزینهٔ «انتخابی ندارم»؛ تأیید اجباری.
نتیجه پس از پایان فاز شب اعمال و به اسنایپر اعلام می‌شود.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_SNIPER,
    Role,
    _goto_discipline_ask,
    _goto_role_absent,
    _night_title_fa,
    _role_eliminated_from_game,
    no_host_assistant_narrator_active,
    push_host_step,
)
from bot.game import bazpors_counts_as_mafia_faction, is_synthetic_player_uid
from bot.no_host_night_common import (
    arm_no_host_role_pick_flow,
    no_host_after_role_night_pick,
    no_host_night_wait_phase_active,
    publish_no_host_night_wait_panel,
)
from bot.models import Game, Player
from bot.room_mode import is_mozakere_scenario, is_no_host_player_room
from bot.no_host_role_pick_common import (
    actor_may_act_on_role_panel,
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
    player_button_name,
    sync_role_mirror_panel,
    target_in_pool,
)
from bot.roles.registry import find_alive_role_holder, require_role_module
from bot.observer_delivery import (
    deliver_no_host_player_game_copy,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
    send_to_player,
)

_sniper_role = require_role_module(Role.SNIPER)

if TYPE_CHECKING:
    from bot.game import GameManager


def _sniper_ui_key(game: Game, sn_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_sniper", sn_uid)


def _player_button_name(p: Player | None, uid: int) -> str:
    return player_button_name(p, uid)


def _sniper_shot_pool(game: Game) -> list[Player]:
    return _sniper_role.shot_pool(game)


def build_no_host_sniper_pick_html(game: Game) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    if is_mozakere_scenario(game):
        from bot.roles.mozakere_sniper import mozakere_sniper_remaining_shots_panel_line

        shot_rule = (
            f"📜 {mozakere_sniper_remaining_shots_panel_line(game)}.\n\n"
        )
    else:
        shot_rule = (
            "📜 شما فقط <b>یک‌بار</b> در کل بازی می‌توانید از قابلیت شلیک استفاده کنید.\n\n"
        )
    return (
        f"🎯 {night_lbl} - ثبت انتخاب اسنایپر\n\n"
        "🔫 لطفاً <b>یک نفر</b> را از لیست زیر برای شلیک انتخاب کنید.\n\n"
        f"{shot_rule}"
        "⚠️ اگر به شهروند شلیک کنید، خودتان نیز از بازی خارج خواهید شد.\n\n"
        "👑 اگر به رئیس مافیا شلیک کنید، نه شما و نه رئیس مافیا از بازی "
        "خارج نخواهید شد.\n\n"
        "📩 نتیجه شلیک شما پس از پایان فاز امشب اعمال خواهد شد."
    )


def build_no_host_sniper_confirm_html(
    game: Game, gm: "GameManager", target_uid: int | None
) -> str:
    if target_uid is None:
        targets = "⭕ <b>انتخابی ندارم</b>"
    else:
        p = game.players.get(target_uid)
        targets = html.escape(_player_button_name(p, target_uid))
    return (
        f"{build_no_host_sniper_pick_html(game)}\n\n"
        f"🔫 هدف: <b>{targets}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_sniper_waiting_html(
    game: Game, gm: "GameManager", target_uid: int | None
) -> str:
    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    if target_uid is None:
        body = "شما این شب شلیک نکردید."
    else:
        p = game.players.get(target_uid)
        name = html.escape(_player_button_name(p, target_uid))
        body = f"شلیک به <b>{name}</b> ثبت شد."
    return (
        f"🎯 {night_lbl} - ثبت انتخاب اسنایپر\n\n"
        f"✅ {body}\n\n"
        "📩 نتیجه شلیک پس از پایان فاز امشب برایتان ارسال می‌شود.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def build_no_host_sniper_result_html(game: Game, gm: "GameManager") -> str | None:
    if not game.no_host_sniper_pick_confirmed:
        return None
    sn_uid = _sniper_role.sniper_uid_at_night_start(game)
    if sn_uid is None:
        return None

    nc = max(1, game.bazpors_narrator_night_count)
    night_lbl = _night_title_fa(nc)
    tgt_uid = _sniper_role.night_target_uid(game)

    if tgt_uid is None:
        return (
            f"🎯 {night_lbl} — نتیجه شلیک\n\n"
            "شما این شب شلیک نکردید.\n"
            "هنوز می‌توانید یک‌بار در بازی از شلیک استفاده کنید."
        )

    tgt = game.players.get(tgt_uid)
    name = html.escape(gm.format_player_tag(tgt) if tgt else str(tgt_uid))

    if tgt and _sniper_role.boss_immune(tgt):
        return (
            f"🎯 {night_lbl} — نتیجه شلیک\n\n"
            f"به <b>{name}</b> (رئیس مافیا) شلیک کردید.\n"
            "طبق قانون هیچ‌کس از بازی خارج نشد."
        )

    if tgt and bazpors_counts_as_mafia_faction(game, tgt):
        if _sniper_role.mafia_kill_blocked_by_doctor(game, tgt_uid):
            return (
                f"🎯 {night_lbl} — نتیجه شلیک\n\n"
                f"شلیک شما به <b>{name}</b> ثبت شد.\n"
                "هدف از بازی خارج نشد."
            )
        return (
            f"🎯 {night_lbl} — نتیجه شلیک\n\n"
            f"شلیک شما به <b>{name}</b> ثبت شد و او از بازی خارج شد."
        )

    sn_alive = game.players.get(sn_uid)
    if sn_alive and not sn_alive.is_alive:
        return (
            f"🎯 {night_lbl} — نتیجه شلیک\n\n"
            f"به <b>{name}</b> (شهروند) شلیک کردید و خودتان از بازی خارج شدید."
        )

    return (
        f"🎯 {night_lbl} — نتیجه شلیک\n\n"
        f"شلیک به <b>{name}</b> ثبت شد."
    )


def _pick_keyboard(
    game: Game, sn_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    del gm
    return build_pick_keyboard(
        game,
        sn_uid,
        pick_act="skt",
        players=_sniper_shot_pool(game),
        none_act="skn",
        none_text="⭕ انتخابی ندارم",
    )


def _confirm_keyboard(game: Game, sn_uid: int) -> InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        game,
        sn_uid,
        confirm_act="skc",
        back_act="skb",
        confirm_text="✅ بله، تأیید",
        back_text="↩️ بازگشت",
    )


def _should_run_no_host_sniper_flow(game: Game) -> bool:
    return (
        is_no_host_player_room(game)
        and no_host_assistant_narrator_active(game)
        and game.bazpors_narrator_step == NIGHT_ACTIONS
        and game.bazpors_night_substep == NS_SNIPER
    )


def _commit_sniper_pick(game: Game, target_uid: int | None) -> None:
    _sniper_role.commit_pick(game, target_uid)


def _advance_past_sniper_if_cannot_act(game: Game) -> bool:
    """اسنایپر مرده یا تیرش خالی شده — بدون پنل به مرحله بعد."""
    if not _should_run_no_host_sniper_flow(game):
        return False
    sn = find_alive_role_holder(game, Role.SNIPER)
    if sn is None:
        if _role_eliminated_from_game(game, Role.SNIPER):
            _goto_role_absent(game, Role.SNIPER)
        else:
            _goto_discipline_ask(game)
        return True
    if not _sniper_role.can_shoot(game):
        _sniper_role.clear_pick(game)
        _goto_discipline_ask(game)
        return True
    return False


async def start_no_host_sniper_night_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    at_night_entry: bool = False,
) -> bool:
    if at_night_entry:
        if not no_host_night_wait_phase_active(game):
            return False
    else:
        if not _should_run_no_host_sniper_flow(game):
            return False
        if _advance_past_sniper_if_cannot_act(game):
            return False
    sn = find_alive_role_holder(game, Role.SNIPER)
    if sn is None:
        return False
    if not _sniper_role.can_shoot(game):
        game.no_host_sniper_pick_confirmed = True
        if at_night_entry and not is_mozakere_scenario(game):
            from bot.no_host_night_common import publish_no_host_night_ack_panel

            wait = build_no_host_sniper_waiting_html(game, gm, None)
            await publish_no_host_night_ack_panel(
                bot,
                game,
                sn.user_id,
                _sniper_ui_key(game, sn.user_id),
                wait,
            )
        return False

    nc = game.bazpors_narrator_night_count

    if is_mozakere_scenario(game) and at_night_entry:
        sig = f"{nc}:sniper:mozakere_pick"
    else:
        sig = f"{nc}:sniper:night_entry" if at_night_entry else f"{nc}:sniper:{NS_SNIPER}"
    if game.no_host_sniper_dm_signature == sig and game.no_host_sniper_flow_active:
        return False
    if game.no_host_sniper_pick_confirmed:
        return False

    game.no_host_sniper_flow_active = True
    game.no_host_sniper_pending_target_uid = None
    game.no_host_sniper_dm_signature = sig

    text = build_no_host_sniper_pick_html(game)
    kb = _pick_keyboard(game, sn.user_id, gm)
    ui_key = _sniper_ui_key(game, sn.user_id)

    await register_mirror_prompt_pair(
        bot,
        game,
        sn.user_id,
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
            "no_host.sniper_night_panel_sent",
            sn_uid=sn.user_id,
            night_count=nc,
        )
    except Exception:
        pass
    return True


async def dispatch_no_host_sniper_night_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.no_host_night_entry import complete_no_host_role_night_if_already_picked

    await complete_no_host_role_night_if_already_picked(bot, game, gm)
    if game.no_host_sniper_pick_confirmed:
        if not no_host_night_wait_phase_active(game):
            return
        sn = find_alive_role_holder(game, Role.SNIPER)
        if sn is not None:
            pick = game.bazpors_sniper_night_target_uid or game.no_host_sniper_pending_tid
            if pick is not None:
                await publish_no_host_night_wait_panel(
                    bot,
                    game,
                    sn.user_id,
                    _sniper_ui_key(game, sn.user_id),
                    "",
                    gm=gm,
                    selection_uid=pick,
                    selection_none_label="شلیک نکردم",
                )
        return
    if _advance_past_sniper_if_cannot_act(game):
        await push_host_step(bot, game, gm)
        return
    await start_no_host_sniper_night_flow(bot, game, gm)


def no_host_sniper_act_active(game: Game, act: str) -> bool:
    return act in ("skt", "skn", "skc", "skb")


def _actor_may_act(game: Game, actor_uid: int, sn_uid: int) -> bool:
    return actor_may_act_on_role_panel(game, actor_uid, sn_uid)


async def _sync_panel(
    bot: Bot,
    game: Game,
    sn_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await sync_role_mirror_panel(
        bot, game, _sniper_ui_key(game, sn_uid), sn_uid, text, kb
    )


async def flush_no_host_sniper_result_pending(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not game.no_host_sniper_result_pending:
        return
    game.no_host_sniper_result_pending = False
    await send_no_host_sniper_shot_result_dm(bot, game, gm)


async def send_no_host_sniper_shot_result_dm(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not (
        game.bazpors_host_mode == "no_host"
        and no_host_assistant_narrator_active(game)
    ):
        return
    nc = game.bazpors_narrator_night_count
    if game.no_host_sniper_result_sent_night == nc:
        return
    body = build_no_host_sniper_result_html(game, gm)
    if not body:
        return

    sn_uid = _sniper_role.sniper_uid_at_night_start(game)
    if sn_uid is None:
        return

    sn = game.players.get(sn_uid)
    if sn and sn.is_alive:
        await send_to_player(
            bot,
            game,
            sn_uid,
            body,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await deliver_no_host_player_game_copy(
            bot,
            game,
            sn_uid,
            body,
            is_synthetic_uid=is_synthetic_player_uid,
            parse_mode="HTML",
        )
    game.no_host_sniper_result_sent_night = nc
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.sniper_result_sent",
            sn_uid=sn_uid,
            night_count=nc,
            target_uid=game.bazpors_sniper_night_target_uid,
        )
    except Exception:
        pass


async def dispatch_no_host_sniper_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    sn_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    arm_no_host_role_pick_flow(
        game,
        flow_active_attr="no_host_sniper_flow_active",
        pick_confirmed_attr="no_host_sniper_pick_confirmed",
        dm_signature_attr="no_host_sniper_dm_signature",
    )
    if not game.no_host_sniper_flow_active or game.no_host_sniper_pick_confirmed:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not no_host_night_wait_phase_active(game):
        await callback.answer("فاز شب فعال نیست.", show_alert=True)
        return
    sn = find_alive_role_holder(game, Role.SNIPER)
    if sn is None or sn.user_id != sn_uid or not _sniper_role.can_shoot(game):
        await callback.answer("اسنایپر نمی‌تواند شلیک کند.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, sn_uid):
        await callback.answer(
            "فقط اسنایپر می‌تواند این انتخاب را انجام دهد.", show_alert=True
        )
        return

    pool = _sniper_shot_pool(game)

    if act == "skt":
        if not target_in_pool(tid, pool):
            await callback.answer("این بازیکن در لیست نیست.", show_alert=True)
            return
        game.no_host_sniper_pending_target_uid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        text = build_no_host_sniper_confirm_html(game, gm, tid)
        kb = _confirm_keyboard(game, sn_uid)
        await _sync_panel(bot, game, sn_uid, text, kb)
        return

    if act == "skn":
        game.no_host_sniper_pending_target_uid = None
        await callback.answer("انتخابی ندارم؛ تأیید کنید.")
        text = build_no_host_sniper_confirm_html(game, gm, None)
        kb = _confirm_keyboard(game, sn_uid)
        await _sync_panel(bot, game, sn_uid, text, kb)
        return

    if act == "skb":
        game.no_host_sniper_pending_target_uid = None
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_sniper_pick_html(game)
        kb = _pick_keyboard(game, sn_uid, gm)
        await _sync_panel(bot, game, sn_uid, text, kb)
        return

    if act == "skc":
        pick = game.no_host_sniper_pending_target_uid
        if pick is not None and not target_in_pool(pick, pool):
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        if game.no_host_sniper_pick_confirmed:
            await callback.answer("قبلاً ثبت شده است.", show_alert=True)
            return
        _commit_sniper_pick(game, pick)
        game.no_host_sniper_pick_confirmed = True
        game.no_host_sniper_flow_active = False

        await callback.answer("ثبت شد.")
        await publish_no_host_night_wait_panel(
            bot,
            game,
            sn_uid,
            _sniper_ui_key(game, sn_uid),
            "",
            gm=gm,
            selection_uid=pick,
            selection_none_label="شلیک نکردم",
        )

        await no_host_after_role_night_pick(
            bot,
            game,
            gm,
            expected_substep=NS_SNIPER,
            advance=_goto_discipline_ask,
        )
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.sniper_pick_confirmed",
                sn_uid=sn_uid,
                target_uid=pick,
            )
        except Exception:
            pass
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
