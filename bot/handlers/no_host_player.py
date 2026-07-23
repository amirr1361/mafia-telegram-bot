"""Handler router: no_host_player."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.types import CallbackQuery

from bot.app_state import manager
from bot.chaos_handshake import (
    chaos_handshake_mirror_act_active,
    dispatch_chaos_handshake_mirror,
)
from bot.main import (
    NoHostDay1DefenseCb,
    NoHostIntroNightStart,
    _answer_mirror_claim,
    _dispatch_no_host_day1_defense_act,
    _handle_no_host_intro_night_action,
    _player_end_dismiss_message,
    _process_no_host_day1_show_vote_panel,
    _process_no_host_day1_skip_night,
    _process_player_end_approve,
    apply_mirror_claim_winner,
    broadcast_game,
    broadcast_player_end_vote_started,
    no_host_bot_assistant_flow_enabled,
    notify_initiator_winner_keyboard,
    try_claim_mirror_ui,
)
from bot.bazpors_player_role_pick import (
    ROLE_PICK_CB_PREFIX as BAZPORS_ROLE_PICK_CB_PREFIX,
    ROLE_PICK_TAKEN_CB_PREFIX as BAZPORS_ROLE_PICK_TAKEN_CB_PREFIX,
    handle_player_role_pick_callback as handle_bazpors_role_pick,
    handle_player_role_pick_taken_callback as handle_bazpors_role_pick_taken,
    parse_role_pick_callback_data as parse_bazpors_role_pick,
    parse_role_pick_taken_callback_data as parse_bazpors_role_pick_taken,
)
from bot.mozakere_player_role_pick import (
    ROLE_PICK_CB_PREFIX as MOZAKERE_ROLE_PICK_CB_PREFIX,
    ROLE_PICK_TAKEN_CB_PREFIX as MOZAKERE_ROLE_PICK_TAKEN_CB_PREFIX,
    handle_player_role_pick_callback as handle_mozakere_role_pick,
    handle_player_role_pick_taken_callback as handle_mozakere_role_pick_taken,
    parse_role_pick_callback_data as parse_mozakere_role_pick,
    parse_role_pick_taken_callback_data as parse_mozakere_role_pick_taken,
)
from bot.mason_player_role_pick import (
    ROLE_PICK_CB_PREFIX as MASON_ROLE_PICK_CB_PREFIX,
    ROLE_PICK_TAKEN_CB_PREFIX as MASON_ROLE_PICK_TAKEN_CB_PREFIX,
    handle_player_role_pick_callback as handle_mason_role_pick,
    handle_player_role_pick_taken_callback as handle_mason_role_pick_taken,
    parse_role_pick_callback_data as parse_mason_role_pick,
    parse_role_pick_taken_callback_data as parse_mason_role_pick_taken,
)
from bot.no_host_citizen_night import (
    dispatch_no_host_citizen_night,
    no_host_citizen_act_active,
)
from bot.no_host_detective_night import (
    dispatch_no_host_detective_night,
    no_host_detective_act_active,
)
from bot.no_host_doctor_night import (
    dispatch_no_host_doctor_night,
    no_host_doctor_act_active,
)
from bot.no_host_interrog_day import (
    dispatch_no_host_interrog_day_player,
    no_host_interrog_day_act_active,
)
from bot.no_host_interrogator_night import (
    dispatch_no_host_interrogator_night,
    no_host_interrog_act_active,
)
from bot.no_host_mafia_nato import (
    dispatch_no_host_mafia_nato,
    mafia_nato_act_active,
)
from bot.no_host_mafia_night1 import (
    dispatch_no_host_mafia_night1,
    mafia_night1_act_active,
)
from bot.no_host_mafia_shot import (
    dispatch_no_host_mafia_shot,
    mafia_shot_act_active,
)
from bot.no_host_mozakere_negotiation import (
    dispatch_no_host_mozakere_negotiator,
    mozakere_negotiator_act_active,
)
from bot.no_host_mafia_yaku import (
    dispatch_no_host_mafia_yaku,
    mafia_yaku_act_active,
)
from bot.no_host_night1 import (
    dispatch_no_host_hunter_night1,
    hunter_night1_act_active,
)
from bot.no_host_ruintan_night import (
    dispatch_no_host_ruintan_night,
    no_host_ruintan_act_active,
)
from bot.no_host_shiad_night import (
    dispatch_no_host_shiad_night,
    no_host_shiad_act_active,
)
from bot.no_host_sniper_night import (
    dispatch_no_host_sniper_night,
    no_host_sniper_act_active,
)
from bot.observer_delivery import (
    game_observer_mirror_active,
    mirror_ui_claim_key,
    unpack_player_mirror_cb,
)
from bot.post_game_flow import finalize_game_winner
from bot.text_fa import fa_digits as _fa_digits
from bot.tg_send import safe_callback_answer


logger = logging.getLogger(__name__)
router = Router(name="no_host_player")


def register_no_host_player_handlers(dp) -> None:
    dp.include_router(router)


@router.callback_query(
    lambda c: c.data is not None
    and c.data.startswith(f"{BAZPORS_ROLE_PICK_TAKEN_CB_PREFIX}:")
)
async def cb_bazpors_player_role_pick_taken(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    packed = parse_bazpors_role_pick_taken(callback.data or "")
    if packed is None:
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return
    room_code, number = packed
    game = manager.get_game(room_code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    await handle_bazpors_role_pick_taken(callback, bot, game, number)


@router.callback_query(
    lambda c: c.data is not None
    and c.data.startswith(f"{BAZPORS_ROLE_PICK_CB_PREFIX}:")
)
async def cb_bazpors_player_role_pick(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    packed = parse_bazpors_role_pick(callback.data or "")
    if packed is None:
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return
    room_code, number = packed
    game = manager.get_game(room_code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    await handle_bazpors_role_pick(callback, bot, game, number)


@router.callback_query(
    lambda c: c.data is not None
    and c.data.startswith(f"{MOZAKERE_ROLE_PICK_TAKEN_CB_PREFIX}:")
)
async def cb_mozakere_player_role_pick_taken(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    packed = parse_mozakere_role_pick_taken(callback.data or "")
    if packed is None:
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return
    room_code, number = packed
    game = manager.get_game(room_code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    await handle_mozakere_role_pick_taken(callback, bot, game, number)


@router.callback_query(
    lambda c: c.data is not None
    and c.data.startswith(f"{MOZAKERE_ROLE_PICK_CB_PREFIX}:")
)
async def cb_mozakere_player_role_pick(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    packed = parse_mozakere_role_pick(callback.data or "")
    if packed is None:
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return
    room_code, number = packed
    game = manager.get_game(room_code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    await handle_mozakere_role_pick(callback, bot, game, number)


@router.callback_query(
    lambda c: c.data is not None
    and c.data.startswith(f"{MASON_ROLE_PICK_TAKEN_CB_PREFIX}:")
)
async def cb_mason_player_role_pick_taken(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    packed = parse_mason_role_pick_taken(callback.data or "")
    if packed is None:
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return
    room_code, number = packed
    game = manager.get_game(room_code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    await handle_mason_role_pick_taken(callback, bot, game, number)


@router.callback_query(
    lambda c: c.data is not None
    and c.data.startswith(f"{MASON_ROLE_PICK_CB_PREFIX}:")
)
async def cb_mason_player_role_pick(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    packed = parse_mason_role_pick(callback.data or "")
    if packed is None:
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return
    room_code, number = packed
    game = manager.get_game(room_code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    await handle_mason_role_pick(callback, bot, game, number)


@router.callback_query(NoHostDay1DefenseCb.filter())
async def cb_no_host_day1_defense(
    callback: CallbackQuery,
    callback_data: NoHostDay1DefenseCb,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if not game or not no_host_bot_assistant_flow_enabled(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id

    def _audit_reject(reason: str) -> None:
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act=callback_data.act,
                actor_uid=callback.from_user.id,
                assistant_uid=assistant_uid,
                source="nhd",
                target_uid=callback_data.tid or None,
                outcome="rejected",
                reject_reason=reason,
            )
        except Exception:
            pass

    if game_observer_mirror_active(game):
        _audit_reject("mirror_use_pmr")
        await callback.answer(
            "از دکمهٔ همان پیام خودتان (یا نسخهٔ ناظر) استفاده کنید.",
            show_alert=True,
        )
        return
    if assistant_uid is None:
        _audit_reject("no_assistant")
        await callback.answer("کمک‌کننده ربات مشخص نیست.", show_alert=True)
        return
    if not game.no_host_day1_defense_active:
        _audit_reject("defense_inactive")
        await callback.answer("پنل دفاعیه فعال نیست.", show_alert=True)
        return
    await _dispatch_no_host_day1_defense_act(
        callback,
        bot,
        game,
        assistant_uid,
        callback.from_user.id,
        callback_data.act,
        tid=callback_data.tid,
        source="nhd",
    )


@router.callback_query(NoHostIntroNightStart.filter())
async def cb_no_host_intro_night_start(
    callback: CallbackQuery,
    callback_data: NoHostIntroNightStart,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if not game or not no_host_bot_assistant_flow_enabled(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        await callback.answer("کمک‌کننده ربات مشخص نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game) and callback.from_user.id != assistant_uid:
        await callback.answer(
            "از دکمهٔ همان پیام خودتان (یا نسخهٔ ناظر) استفاده کنید.",
            show_alert=True,
        )
        return
    if callback.from_user.id != assistant_uid:
        await callback.answer("فقط کمک‌کننده ربات.", show_alert=True)
        return
    await _handle_no_host_intro_night_action(
        callback,
        bot,
        game,
        assistant_uid,
        callback.from_user.id,
        callback_data.act,
    )


@router.callback_query(lambda c: c.data is not None and c.data.startswith("msh:"))
async def cb_mason_helper(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    from bot.mason_helper_flow import MasonHelperCb, handle_mason_helper_action
    from bot.room_mode import is_mason_scenario

    if not callback.from_user or callback.message is None:
        return
    try:
        data = MasonHelperCb.unpack(callback.data or "")
    except ValueError:
        return
    game = manager.get_game(data.code)
    if not game or not is_mason_scenario(game) or not no_host_bot_assistant_flow_enabled(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        await callback.answer("کمک‌کننده ربات مشخص نیست.", show_alert=True)
        return
    if callback.from_user.id != assistant_uid:
        await callback.answer("فقط کمک‌کننده ربات.", show_alert=True)
        return
    await handle_mason_helper_action(
        callback,
        bot,
        game,
        manager,
        assistant_uid=assistant_uid,
        actor_uid=callback.from_user.id,
        act=data.act,
        kind=data.kind,
    )


@router.callback_query(lambda c: c.data is not None and c.data.startswith("pmr:"))
async def player_mirror_cb(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    callback_data = unpack_player_mirror_cb(callback.data or "")
    if callback_data is None:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    actor = callback.from_user.id
    as_uid = callback_data.as_uid
    act = callback_data.act
    room = game.room_code

    if chaos_handshake_mirror_act_active(game, act):
        await dispatch_chaos_handshake_mirror(
            callback,
            bot,
            game,
            manager,
            chooser_uid=as_uid,
            actor_uid=actor,
            target_uid=callback_data.tid,
            round_raw=callback_data.rid or "",
        )
        return

    from bot.mason_day_ability import (
        dispatch_mason_day_ability,
        mason_day_ability_act_active,
    )

    if mason_day_ability_act_active(game, act):
        await dispatch_mason_day_ability(
            callback,
            bot,
            game,
            manager,
            as_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    from bot.mason_night_entry import (
        dispatch_mason_night_wait_ok,
        mason_night_wait_act_active,
    )
    from bot.mason_night_role import (
        dispatch_mason_night_role,
        mason_night_role_act_active,
    )

    if mason_night_role_act_active(game, act):
        await dispatch_mason_night_role(
            callback,
            bot,
            game,
            manager,
            as_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if mason_night_wait_act_active(game, act):
        await dispatch_mason_night_wait_ok(
            callback,
            bot,
            game,
            manager,
            as_uid=as_uid,
            actor_uid=actor,
        )
        return

    if mafia_night1_act_active(game, act):
        await dispatch_no_host_mafia_night1(
            callback,
            bot,
            game,
            manager,
            mafia_uid=as_uid,
            actor_uid=actor,
            act=act,
        )
        return

    if mafia_shot_act_active(game, act):
        await dispatch_no_host_mafia_shot(
            callback,
            bot,
            game,
            manager,
            mafia_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if mafia_yaku_act_active(game, act):
        await dispatch_no_host_mafia_yaku(
            callback,
            bot,
            game,
            manager,
            mafia_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if mafia_nato_act_active(game, act):
        await dispatch_no_host_mafia_nato(
            callback,
            bot,
            game,
            manager,
            nato_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if mozakere_negotiator_act_active(game, act):
        await dispatch_no_host_mozakere_negotiator(
            callback,
            bot,
            game,
            manager,
            neg_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if hunter_night1_act_active(game, act):
        await dispatch_no_host_hunter_night1(
            callback,
            bot,
            game,
            manager,
            hunter_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if no_host_shiad_act_active(game, act):
        await dispatch_no_host_shiad_night(
            callback,
            bot,
            game,
            manager,
            sh_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if no_host_detective_act_active(game, act):
        await dispatch_no_host_detective_night(
            callback,
            bot,
            game,
            manager,
            det_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if no_host_doctor_act_active(game, act):
        await dispatch_no_host_doctor_night(
            callback,
            bot,
            game,
            manager,
            doc_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if no_host_interrog_day_act_active(game, act):
        await dispatch_no_host_interrog_day_player(
            callback,
            bot,
            game,
            manager,
            as_uid=as_uid,
            actor_uid=actor,
            act=act,
        )
        return

    if no_host_interrog_act_active(game, act):
        await dispatch_no_host_interrogator_night(
            callback,
            bot,
            game,
            manager,
            int_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if no_host_sniper_act_active(game, act):
        await dispatch_no_host_sniper_night(
            callback,
            bot,
            game,
            manager,
            sn_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    from bot.no_host_journalist_night import (
        dispatch_no_host_journalist_night,
        no_host_journalist_act_active,
    )

    if no_host_journalist_act_active(game, act):
        await dispatch_no_host_journalist_night(
            callback,
            bot,
            game,
            manager,
            jr_uid=as_uid,
            actor_uid=actor,
            act=act,
            tid=callback_data.tid,
        )
        return

    if no_host_ruintan_act_active(game, act):
        await dispatch_no_host_ruintan_night(
            callback,
            bot,
            game,
            manager,
            ru_uid=as_uid,
            actor_uid=actor,
        )
        return

    from bot.no_host_night_common import (
        dispatch_no_host_night_wait_ok,
        no_host_night_wait_ok_act_active,
    )

    if no_host_night_wait_ok_act_active(game, act):
        await dispatch_no_host_night_wait_ok(
            callback,
            bot,
            game,
            manager,
            as_uid=as_uid,
            actor_uid=actor,
        )
        return

    if no_host_citizen_act_active(game, act):
        await dispatch_no_host_citizen_night(
            callback,
            bot,
            game,
            manager,
            cit_uid=as_uid,
            actor_uid=actor,
        )
        return

    defense_acts = (
        "d1dc",
        "d1dn",
        "d1d0",
        "d1d1",
        "d1el",
        "d1ey",
        "d1en",
        "elim_yes",
        "elim_no",
    )
    if (
        act in defense_acts
        or act == "d1dt"
        or act.startswith("d1dt-")
        or act.startswith("d1dt:")
    ):
        assistant_uid = game.bot_assistant_user_id
        if assistant_uid is None or as_uid != assistant_uid:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        if not game.no_host_day1_defense_active:
            try:
                from bot.game_audit_log import log_no_host_day1_defense_callback

                log_no_host_day1_defense_callback(
                    game,
                    act=act,
                    actor_uid=actor,
                    assistant_uid=assistant_uid,
                    source="pmr",
                    target_uid=callback_data.tid or None,
                    outcome="rejected",
                    reject_reason="defense_inactive",
                )
            except Exception:
                pass
            await callback.answer("پنل دفاعیه فعال نیست.", show_alert=True)
            return
        await _dispatch_no_host_day1_defense_act(
            callback,
            bot,
            game,
            assistant_uid,
            actor,
            act,
            tid=callback_data.tid,
            source="pmr",
        )
        return

    if act in ("d1_skip", "d1_vote"):
        assistant_uid = game.bot_assistant_user_id
        if assistant_uid is None or as_uid != assistant_uid:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        from bot.no_host_day_vote import no_host_end_day_vote_cb_allowed

        if not no_host_end_day_vote_cb_allowed(game):
            await callback.answer(
                "الان زمان رأی‌گیری پایان روز نیست.", show_alert=True
            )
            return
        if act == "d1_skip":
            await _process_no_host_day1_skip_night(
                callback, bot, game, assistant_uid, actor
            )
        else:
            await _process_no_host_day1_show_vote_panel(
                callback, bot, game, assistant_uid, actor
            )
        return

    if not game_observer_mirror_active(game):
        await callback.answer("ناظر فعال نیست.", show_alert=True)
        return

    if act == "pea":
        ui_key = mirror_ui_claim_key(room, "player_end_vote", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor, as_uid)
        await _process_player_end_approve(callback, bot, game, as_uid)
        return

    if act == "pex":
        ui_key = mirror_ui_claim_key(room, "player_end_vote", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor, as_uid)
        await _player_end_dismiss_message(callback)
        return

    if act == "pbc" or act.startswith("pbc:"):
        ok = tid if act == "pbc" else int(act.split(":", 1)[1])
        if actor != as_uid:
            await callback.answer(
                "فقط همان بازیکنی که /request_end زده می‌تواند تأیید کند.",
                show_alert=True,
            )
            return
        ui_key = mirror_ui_claim_key(room, "player_end_broadcast", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor, as_uid)
        if manager.player_end_broadcast_confirm_expired(game):
            manager.clear_player_end_broadcast_pending(game)
            await callback.answer("مهلت تأیید تمام شده.", show_alert=True)
            try:
                await callback.message.edit_text(
                    "⌛ مهلت تأیید اولیه تمام شد. در صورت نیاز دوباره /request_end بزنید.",
                    reply_markup=None,
                )
            except Exception:
                pass
            return
        if ok == 0:
            manager.clear_player_end_broadcast_pending(game)
            await callback.answer("لغو شد.")
            try:
                await callback.message.edit_text(
                    "✖️ درخواست پایان جمعی را لغو کردید.",
                    reply_markup=None,
                )
            except Exception:
                pass
            return
        manager.clear_player_end_broadcast_pending(game)
        err = manager.start_player_end_vote(game, as_uid)
        if err:
            msgs = {
                "phase": "الان نمی‌توان این درخواست را ثبت کرد.",
                "host": "خطا.",
                "not_player": "شما در این اتاق نیستید.",
                "picker_pending": "اول برنده را ثبت کنید.",
                "already": "یک رأی فعال است.",
                "pending_confirm_other": "تداخل وضعیت؛ دوباره تلاش کنید.",
                "await_first_confirm": "وضعیت نامعتبر؛ دوباره /request_end بزنید.",
                "sandbox": "در اتاق تست شبکه سلامت رأی پایان جمعی فعال نیست.",
            }
            await callback.answer(msgs.get(err, "خطا."), show_alert=True)
            return
        await broadcast_player_end_vote_started(bot, game)
        await callback.answer("برای همه فرستاده شد.")
        try:
            n = len(game.players)
            await callback.message.edit_text(
                f"✅ درخواست برای همه فرستاده شد.\n"
                f"تا {_fa_digits(game.player_end_approval_minutes)} دقیقه باید هر {n} بازیکن یک بار تأیید کند.",
                reply_markup=None,
            )
        except Exception:
            pass
        return

    if act in ("egwm", "egwc") or act.startswith("egw:"):
        if act == "egwm":
            winner = "mafia"
        elif act == "egwc":
            winner = "citizen"
        else:
            winner = act.split(":", 1)[1]
        picker = game.player_end_winner_picker_id
        if picker is not None and as_uid != picker:
            await callback.answer("این پیام برای بازیکن دیگری است.", show_alert=True)
            return
        if picker is not None:
            if actor != as_uid and actor != game.observer_user_id:
                await callback.answer("فقط همان بازیکن یا ناظر.", show_alert=True)
                return
        elif actor != as_uid:
            await callback.answer(
                "فقط همان بازیکنی که باید برنده را ثبت کند.",
                show_alert=True,
            )
            return
        ui_key = mirror_ui_claim_key(room, "endgame_pick", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor, as_uid)
        if winner not in ("mafia", "citizen"):
            await callback.answer("گزینه نامعتبر.", show_alert=True)
            return
        await finalize_game_winner(bot, game, winner, as_uid)
        await callback.answer("نتیجه ثبت شد.")
        return

    if act == "egx":
        ui_key = mirror_ui_claim_key(room, "endgame_pick", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor, as_uid)
        if as_uid != (game.player_end_winner_picker_id or -1):
            await callback.answer("فقط کسی که باید برنده را ثبت کند.", show_alert=True)
            return
        await callback.answer("ثبت نتیجه لغو شد.")
        try:
            await callback.message.edit_text(
                "✖️ انتخاب برنده لغو شد. هر زمان آماده بودید دوباره /endgame بزنید "
                "یا همان پیام قبلی را باز کنید.",
                reply_markup=None,
            )
        except Exception:
            pass
        return

    if act == "elc":
        ui_key = mirror_ui_claim_key(room, "emergency_leave", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor, as_uid)
        if as_uid == game.host_id:
            await callback.answer("گرداننده از این مسیر خارج نمی‌شود.", show_alert=True)
            return
        if as_uid not in game.players:
            await callback.answer("بازیکن در این اتاق نیست.", show_alert=True)
            return
        host_id = game.host_id
        code = game.room_code
        cancel_s, elected = manager.remove_player_from_manual_game(game, as_uid)
        if cancel_s == "no":
            await callback.answer("خروج ممکن نیست.", show_alert=True)
            return
        await callback.answer("از بازی خارج شدید.")
        try:
            await callback.message.edit_text("✅ از بازی خارج شدید.", reply_markup=None)
        except Exception:
            pass
        leftover = manager.get_game(code)
        if leftover is None:
            try:
                await bot.send_message(
                    host_id,
                    "👋 آخرین بازیکن خارج شد؛ اتاق بسته شد.",
                )
            except Exception:
                pass
            return
        leaver_p = game.players.get(as_uid)
        leaver = manager.format_player_tag(leaver_p) if leaver_p else str(as_uid)
        await broadcast_game(
            bot,
            leftover,
            f"🚪 {leaver} بازی را با خروج اضطراری ترک کرد.",
            exclude=as_uid,
        )
        if cancel_s == "vote_cancelled":
            await broadcast_game(
                bot,
                leftover,
                "❎ درخواست پایان بدون گرداننده لغو شد، چون درخواست‌دهنده خارج شد.",
            )
        if elected is not None:
            await notify_initiator_winner_keyboard(bot, code, elected)
        return

    if act == "elx":
        ui_key = mirror_ui_claim_key(room, "emergency_leave", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor, as_uid)
        await callback.answer("لغو شد.")
        try:
            await callback.message.edit_text(
                "✖️ خروج اضطراری لغو شد. همچنان در بازی هستید.",
                reply_markup=None,
            )
        except Exception:
            pass
        return

    if act == "intro_night":
        assistant_uid = game.bot_assistant_user_id
        if assistant_uid is None or as_uid != assistant_uid:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        await _handle_no_host_intro_night_action(
            callback, bot, game, as_uid, actor, "go"
        )
        return

    if act == "intro_night_ok":
        assistant_uid = game.bot_assistant_user_id
        if assistant_uid is None or as_uid != assistant_uid:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        ui_key = mirror_ui_claim_key(room, "intro_night_start", as_uid)
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor, as_uid),
        ):
            return
        await _handle_no_host_intro_night_action(
            callback, bot, game, as_uid, actor, "ok"
        )
        return

    if act == "intro_night_back":
        assistant_uid = game.bot_assistant_user_id
        if assistant_uid is None or as_uid != assistant_uid:
            await callback.answer("نامعتبر.", show_alert=True)
            return
        await _handle_no_host_intro_night_action(
            callback, bot, game, as_uid, actor, "back"
        )
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
