"""اتمام اجباری شب — فقط سناریوی نماینده (nam10 fork، کمک‌کننده ربات).

الگوی ماسون/مذاکره: دکمهٔ «🌙 اتمام شب» روی یادآور → تأیید دو مرحله‌ای.
- لغو = بدون هیچ تغییری در بازی.
- تأیید = اقدامات تأییدشده حفظ؛ ناتو/پزشکِ لغوشده حفظ؛ اقدامات بی‌تأیید
  انجام‌نشده؛ پیش‌فرض بدون اقدام؛ سربازِ بی‌گیرنده (پنل تحویل‌شده و
  بدون تأیید) و اسنایپرِ موقتِ بی‌شلیک (پنل تحویل‌شده و بدون تأیید) →
  حذف واقعی در همان شب (فقط ترکیب‌های ۱۲/۱۳ نماینده). اگر پنل به‌خاطر
  خطای ارسال در دسترس نبوده، مسیر امن قبلی (بدون جریمه) اجرا می‌شود.
- محاسبه از طریق پایپ‌لاین موجود (night2_maybe_finish / publish tick).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.models import Game, Phase, Role
from bot.observer_delivery import PlayerMirrorCb

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

NAM10_FORCE_FINISH_BUTTON_TEXT = "🌙 اتمام شب"
NAM10_FORCE_FINISH_CONFIRM_TEXT = (
    "⚠️ آیا مطمئن هستید که می‌خواهید شب را به پایان برسانید؟\n\n"
    "پس از تأیید، ربات فقط اقدامات تأییدشده را محاسبه می‌کند و اقداماتی را که "
    "هنوز تأیید نشده‌اند، انجام‌نشده در نظر می‌گیرد."
)
NAM10_FORCE_FINISH_CANCELLED_TEXT = "لغو شد؛ شب ادامه دارد."
NAM10_NIGHT_PANEL_LOCKED_TEXT = "فاز شب به پایان رسید."
NAM10_NIGHT_PHASE_ENDED_TEXT = "فاز شب به پایان رسیده است."

NAM10_FORCE_FINISH_ACTS = frozenset({"n2fft", "n2ffy", "n2ffn"})


def nam10_force_finish_act_active(act: str) -> bool:
    return act in NAM10_FORCE_FINISH_ACTS


def nam10_night_force_finish_collection_active(game: Game) -> bool:
    from bot.nam10.night2 import (
        PENDING_COLLECTING,
        nam10_night2_mode,
    )

    if not nam10_night2_mode(game):
        return False
    if game.phase == Phase.ENDED:
        return False
    if game.nmnd_night2_phase != PENDING_COLLECTING:
        return False
    return bool(
        game.nmnd_night2_entry_dispatched
        and game.bot_assistant_user_id is not None
    )


def nam10_night_player_actions_closed(game: Game) -> bool:
    return game.nmnd_night2_force_finished


def find_nam10_bot_assistant_game(
    user_id: int, gm: "GameManager | None" = None
) -> Game | None:
    if gm is None:
        from bot.app_state import manager as gm
    game = gm.find_active_participant_game(user_id)
    if game is None:
        return None
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return None
    if game.bot_assistant_user_id != user_id:
        return None
    return game


def nam10_force_finish_button_keyboard(game: Game) -> InlineKeyboardMarkup | None:
    if not nam10_night_force_finish_collection_active(game):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=NAM10_FORCE_FINISH_BUTTON_TEXT,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="n2fft",
                        as_uid=0,
                        tid=0,
                    ).pack(),
                )
            ]
        ]
    )


def _force_finish_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، اتمام شب",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="n2ffy",
                        as_uid=0,
                        tid=0,
                    ).pack(),
                    style="success",
                ),
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="n2ffn",
                        as_uid=0,
                        tid=0,
                    ).pack(),
                ),
            ]
        ]
    )


def _force_ack(game: Game, key: str, uid: int) -> None:
    acked = game.nmnd_night2_waiting_acked.setdefault(key, [])
    if uid not in acked:
        acked.append(uid)


async def _normalize_pending_nam10_night_actions(
    bot: Bot, game: Game
) -> dict:
    """اقدامات ناقص را مثل «انتخابی ندارم» / اوکی بدون اثر ثبت کن.

    خروجی: دیکشنری ماشین‌خوان برای audit («force_finished_no_action»).
    """
    from bot.nam10.night2 import (
        BOSS_PHASE_DONE,
        BOSS_PHASE_NATO_PLAYER,
        BOSS_PHASE_NATO_ROLE,
        ELIM_CAUSE_FORCE_SOLDIER,
        ELIM_CAUSE_FORCE_SNIPER,
        GRANT_STATUS_DELIVERED,
        GRANT_STATUS_PENDING,
        GRANT_STATUS_VOID,
        _audit,
        _holder,
        _is_simple_citizen,
        _alive_players,
        _night2_extra_owed,
        _night2_panel_available,
        _sniper_key,
        _soldier_key,
        night2_active_shooter,
        night2_apply_elimination,
        night2_guardian_exempt_after_assassin,
        night2_maybe_grant_guide_extra,
    )

    dispositions: dict[str, str] = {}

    def mark(key: str) -> None:
        dispositions[key] = "force_finished_no_action"

    nc = int(game.nmnd_narrator_night_count or 0)

    # 1. Shooter (Boss / Rebel / Hacker) — شلیک ثبت‌نشده → بدون شلیک.
    nato_stages = (BOSS_PHASE_NATO_ROLE, BOSS_PHASE_NATO_PLAYER)
    if game.nmnd_night2_boss_phase != BOSS_PHASE_DONE:
        was_nato_stage = game.nmnd_night2_boss_phase in nato_stages
        game.nmnd_night2_boss_phase = BOSS_PHASE_DONE
        game.nmnd_night2_shot_pending_uid = None
        game.nmnd_night2_shot_target_uid = None
        if was_nato_stage:
            # ناتوی نیمه‌کاره → لغو هدف‌گیری؛ فعال‌سازی و لغو پزشک حفظ می‌شود.
            game.nmnd_night2_nato_pending_role_idx = None
            game.nmnd_night2_nato_role = None
            game.nmnd_night2_nato_pending_uid = None
            game.nmnd_night2_nato_target_uid = None
            mark("nato_cancelled")
        else:
            mark("shot")

    # 2. Doctor — انتخاب ثبت‌نشده → لغو نجات (بدون ذخیره).
    if (
        game.nmnd_night2_doctor_uid is None
        and not game.nmnd_night2_doctor_cancelled
        and _holder(game, Role.DOCTOR) is not None
    ):
        game.nmnd_night2_doctor_cancelled = True
        game.nmnd_night2_doctor_cancel_reason = "force_finished"
        game.nmnd_night2_doctor_pending_uid = None
        mark("doctor")

    # 3. Hacker — جفت تأییدنشده → بدون interference.
    if not game.nmnd_night2_hacker_uids and _holder(game, Role.SHIAD) is not None:
        if (
            game.nmnd_night2_hacker_pending_uids
            or game.nmnd_night2_hacker_stage is not None
            or game.nmnd_night2_hacker_src_pending is not None
            or game.nmnd_night2_hacker_dst_pending is not None
        ):
            game.nmnd_night2_hacker_pending_uids = []
            game.nmnd_night2_hacker_stage = None
            game.nmnd_night2_hacker_src_pending = None
            game.nmnd_night2_hacker_dst_pending = None
            game.nmnd_night2_dispositions["hacker_none"] = (
                "force_finished_no_action"
            )
            mark("hacker")

    # 4. Guide — گیرنده تأییدنشده → بدون گیرنده.
    if (
        game.nmnd_night2_guide_uids.get(nc) is None
        and _holder(game, Role.INTERROGATOR) is not None
    ):
        game.nmnd_night2_guide_pending_uid = None
        game.nmnd_night2_dispositions["guide_none"] = "force_finished_no_action"
        mark("guide")

    # 5. Guardian — انتخاب ثبت‌نشده → بدون زره؛ حالت معافیت → اوکی اجباری.
    guard_holder = _holder(game, Role.DETECTIVE)
    if guard_holder is not None:
        if night2_guardian_exempt_after_assassin(game):
            _force_ack(game, Role.DETECTIVE.value, guard_holder.user_id)
            mark("guardian_ack")
        elif game.nmnd_night2_guardian_uid is None:
            game.nmnd_night2_guardian_pending_uid = None
            game.nmnd_night2_dispositions["guardian_none"] = (
                "force_finished_no_action"
            )
            mark("guardian")

    # 6. Mine — جای‌گذاری ثبت‌نشده → بدون مین؛ مین مصرف‌شده → اوکی اجباری.
    mine = _holder(game, Role.RUINTAN)
    if mine is not None:
        if game.nmnd_night2_mine_used:
            _force_ack(game, Role.RUINTAN.value, mine.user_id)
            mark("mine_ack")
        elif game.nmnd_night2_mine_uid is None:
            game.nmnd_night2_mine_pending_uid = None
            game.nmnd_night2_mine_pending_none = False
            game.nmnd_night2_dispositions["mine_none"] = (
                "force_finished_no_action"
            )
            mark("mine")

    # 7. Lawyer — انتخاب ثبت‌نشده → بدون مصونیت؛ مصرف‌شده → اوکی اجباری.
    law = _holder(game, Role.HUNTER)
    if law is not None:
        if game.nmnd_night2_lawyer_used:
            _force_ack(game, Role.HUNTER.value, law.user_id)
            mark("lawyer_ack")
        elif game.nmnd_night2_lawyer_uid is None:
            game.nmnd_night2_lawyer_pending_uid = None
            game.nmnd_night2_lawyer_pending_none = False
            game.nmnd_night2_dispositions["lawyer_none"] = (
                "force_finished_no_action"
            )
            mark("lawyer")

    # 8. Rebel — اوکی انتظار اجباری (وقتی شلیک‌دهندهٔ شب نیست).
    rebel = _holder(game, Role.NATO)
    if (
        rebel is not None
        and night2_active_shooter(game) is not rebel
    ):
        _force_ack(game, Role.NATO.value, rebel.user_id)
        mark("rebel_ack")

    # 9. Citizens — اوکی انتظار اجباری.
    for p in _alive_players(game):
        if _is_simple_citizen(game, p):
            _force_ack(game, Role.CITIZEN.value, p.user_id)
    if any(_is_simple_citizen(game, p) for p in _alive_players(game)):
        mark("citizen_ack")

    # 10. Soldier — گیرندهٔ تأییدنشده:
    #   - گرانت در انتظار تحویل (انتخاب تأیید شده ولی وابستگی بیرونی
    #     ناتمام) → مثل قبل VOID + سلب دائمی؛ حذف نمی‌شود (تأیید کرده).
    #   - پنل انتخاب تحویل‌شده و بدون تأیید → حذف واقعی سرباز در همین شب.
    #   - پنل در دسترس نبوده (خطای ارسال) → مسیر امن قبلی، بدون جریمه.
    soldier = _holder(game, Role.SOLDIER)
    if soldier is not None:
        if game.nmnd_night2_soldier_grant_status == GRANT_STATUS_PENDING:
            # گرانت در انتظار → بدون تحویل و بدون استراق؛ شارژ سوخت.
            game.nmnd_night2_soldier_grant_status = GRANT_STATUS_VOID
            game.nmnd_night2_soldier_pending_uid = None
            game.nmnd_night2_soldier_forfeited = True
            mark("soldier_grant_void")
        elif game.nmnd_night2_soldier_used:
            if (
                game.nmnd_night2_soldier_used_night != nc
                and soldier.user_id
                not in game.nmnd_night2_waiting_acked.get(
                    Role.SOLDIER.value, []
                )
            ):
                _force_ack(game, Role.SOLDIER.value, soldier.user_id)
                mark("soldier_ack")
        elif game.nmnd_night2_soldier_uid is None:
            if _night2_panel_available(
                game, _soldier_key(game, soldier.user_id)
            ):
                # حذف واقعی در همین شب؛ بدون گیرندهٔ خیالی و بدون تحویل.
                game.nmnd_night2_soldier_used = True
                game.nmnd_night2_soldier_used_night = nc
                game.nmnd_night2_soldier_grant_status = GRANT_STATUS_VOID
                game.nmnd_night2_soldier_pending_uid = None
                game.nmnd_night2_soldier_forfeited = True
                night2_apply_elimination(
                    game, soldier.user_id, ELIM_CAUSE_FORCE_SOLDIER
                )
                _audit(
                    game,
                    "night2.force_finish_soldier_eliminated",
                    soldier_uid=soldier.user_id,
                    night=nc,
                )
                mark("soldier_force_eliminated")
            else:
                # پنل تحویل نشده بود → مسیر امن قبلی + ثبت مشکل ارسال.
                game.nmnd_night2_soldier_used = True
                game.nmnd_night2_soldier_used_night = nc
                game.nmnd_night2_soldier_grant_status = GRANT_STATUS_VOID
                game.nmnd_night2_soldier_pending_uid = None
                game.nmnd_night2_soldier_forfeited = True
                _audit(
                    game,
                    "night2.force_finish_soldier_panel_unavailable",
                    soldier_uid=soldier.user_id,
                    night=nc,
                )
                mark("soldier_forfeited_panel_unavailable")

    # 11. Temporary Sniper — گرانت تحویل‌شده و شلیک تأییدنشده:
    #   - هدف تأییدشده → مثل قبل حفظ می‌شود (شلیک عادی در resolution).
    #   - پنل تحویل‌شده و بدون هدف تأییدشده → حذف واقعی گیرنده در همین
    #     شب؛ شارژ مادام‌العمر سرباز مصرف‌شده می‌ماند؛ سرباز جریمه نمی‌شود.
    #   - پنل در دسترس نبوده → مسیر امن قبلی (بدون شلیک، بدون جریمه).
    if (
        game.nmnd_night2_soldier_grant_status == GRANT_STATUS_DELIVERED
        and game.nmnd_night2_sniper_night == nc
        and not game.nmnd_night2_sniper_resolved
    ):
        recipient_uid = game.nmnd_night2_soldier_uid
        panel_ok = (
            recipient_uid is not None
            and _night2_panel_available(
                game, _sniper_key(game, recipient_uid)
            )
        )
        game.nmnd_night2_sniper_pending_uid = None
        game.nmnd_night2_sniper_target_uid = None
        game.nmnd_night2_sniper_skipped = True
        game.nmnd_night2_sniper_resolved = True
        if panel_ok:
            night2_apply_elimination(
                game, recipient_uid, ELIM_CAUSE_FORCE_SNIPER
            )
            _audit(
                game,
                "night2.force_finish_temp_sniper_eliminated",
                sniper_uid=recipient_uid,
                night=nc,
            )
            mark("sniper_force_eliminated")
        else:
            _audit(
                game,
                "night2.force_finish_sniper_panel_unavailable",
                sniper_uid=recipient_uid,
                night=nc,
            )
            mark("sniper_no_shot_panel_unavailable")

    # 12. NATO agent — ناتوی مستقل نیمه‌کاره لغو شد؛ اوکی/شلیک انتظار.
    agent = _holder(game, Role.NATO_AGENT)
    if agent is not None:
        if night2_active_shooter(game) is agent:
            pass  # شلیکِ منتقله در بند ۱ بسته شد.
        elif agent.user_id not in game.nmnd_night2_waiting_acked.get(
            Role.NATO_AGENT.value, []
        ):
            _force_ack(game, Role.NATO_AGENT.value, agent.user_id)
            mark("nato_agent_ack")

    # 13. Guide aftermath — تصمیم گرانت با هر دو انتخاب معلوم.
    await night2_maybe_grant_guide_extra(bot, game)

    # 14. استعلام اضافهٔ گرانت‌شده — بدون هدف و بدون نتیجه.
    if _night2_extra_owed(game):
        game.nmnd_night2_extra_target_pending = None
        game.nmnd_night2_dispositions["extra_none"] = "force_finished_no_action"
        mark("extra")

    return dispositions


async def lock_nam10_night_mirror_panels(bot: Bot, game: Game) -> None:
    from bot.observer_delivery import update_mirror_prompt_pair

    lockable_kinds = {
        "n2boss",
        "n2doc",
        "n2shiad",
        "n2guide",
        "n2guard",
        "n2mine",
        "n2law",
        "n2rebel",
        "n2citizen",
        "n2extra",
        "n2soldier",
        "n2sniper",
        "n2nato",
    }
    for key in list(game.mirror_prompt_messages):
        parts = key.split(":", 2)
        if len(parts) != 3:
            continue
        kind, room, uid_s = parts
        if room != game.room_code or kind not in lockable_kinds:
            continue
        entry = game.mirror_prompt_messages.get(key, {})
        if not (entry.get("player") or entry.get("observer")):
            continue
        try:
            as_uid = int(uid_s)
        except ValueError:
            continue
        await update_mirror_prompt_pair(
            bot,
            game,
            key,
            NAM10_NIGHT_PANEL_LOCKED_TEXT,
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )


async def force_finish_nam10_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.nam10.night2 import (
        PENDING_COLLECTING,
        _audit,
        night2_maybe_finish,
        night2_required_keys,
    )
    from bot.nam10.night2_publish import nam10_night2_publish_tick

    try:
        from bot.night_helper_reminder import cleanup_night_helper_reminder

        await cleanup_night_helper_reminder(bot, game)
    except Exception:
        pass
    pending = list(night2_required_keys(game))
    logger.info(
        "Force finishing Namayande night room=%s night=%s. Pending: %s",
        game.room_code,
        game.nmnd_night2_night_count,
        ",".join(pending),
    )
    game.nmnd_night2_force_finished = True
    dispositions = await _normalize_pending_nam10_night_actions(bot, game)
    await lock_nam10_night_mirror_panels(bot, game)
    if game.nmnd_night2_phase == PENDING_COLLECTING:
        # Existing deterministic pipeline (resolution + publication).
        night2_maybe_finish(game, gm, force=True)
        await nam10_night2_publish_tick(bot, game, gm)
    _audit(
        game,
        "nam10.force_finish_night",
        night_count=game.nmnd_night2_night_count,
        pending=pending,
        force_finished_no_action=dispositions,
    )
    try:
        from bot.app_state import manager as _manager

        _manager.persist_snapshot(game, reason="nam10_force_finish_night")
    except Exception:
        pass


async def dispatch_nam10_force_finish_act(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    actor_uid: int,
    act: str,
) -> None:
    if act not in NAM10_FORCE_FINISH_ACTS:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    if actor_uid != game.bot_assistant_user_id:
        await callback.answer("فقط کمک‌کننده ربات.", show_alert=True)
        return
    if not nam10_night_force_finish_collection_active(game):
        await callback.answer("هنوز تو فاز شب نیستیم.", show_alert=True)
        return
    if callback.message is None:
        return
    if act == "n2ffn":
        await callback.answer()
        try:
            await callback.message.edit_text(NAM10_FORCE_FINISH_CANCELLED_TEXT)
        except Exception:
            pass
        return
    if act == "n2fft":
        await callback.answer()
        try:
            await bot.send_message(
                game.bot_assistant_user_id,
                NAM10_FORCE_FINISH_CONFIRM_TEXT,
                reply_markup=_force_finish_confirm_keyboard(game),
            )
        except Exception:
            logger.exception(
                "nam10 force finish confirm send failed room=%s",
                game.room_code,
            )
        return
    # act == "n2ffy"
    await callback.answer("شب به پایان رسید.")
    try:
        await callback.message.edit_text(
            NAM10_FORCE_FINISH_CONFIRM_TEXT + "\n\n✅ شب به پایان رسید."
        )
    except Exception:
        pass
    await force_finish_nam10_night(bot, game, gm)


async def handle_nam10_force_finish_text(
    msg: Message, bot: Bot, user_id: int, gm: "GameManager | None" = None
) -> None:
    """دستور متنی «اتمام شب» — فقط کمک‌کنندهٔ نماینده."""
    game = find_nam10_bot_assistant_game(user_id, gm)
    if game is None:
        return
    if not nam10_night_force_finish_collection_active(game):
        await msg.answer("هنوز تو فاز شب نیستیم.")
        return
    await msg.answer(
        NAM10_FORCE_FINISH_CONFIRM_TEXT,
        reply_markup=_force_finish_confirm_keyboard(game),
    )
