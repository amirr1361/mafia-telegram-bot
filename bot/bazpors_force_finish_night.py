"""اتمام اجباری شب — فقط سناریوی بازپرس (کمک‌کنندهٔ ربات، حالت بدون گرداننده).

الگوی مذاکره (bot/mozakere_force_finish_night.py) برای بازپرس:
- فقط کمک‌کنندهٔ ربات دسترسی دارد.
- تأیید دومرحله‌ای (دکمه «🌙 اتمام شب» → «✅ بله، اتمام شب» / «❌ انصراف»).
- لغو = بدون هیچ تغییری در بازی.
- تأیید = اقدامات تأییدشده حفظ؛ اقدامات بی‌تأیید بدون اثر؛ پیش‌فرض‌های
  هر نقش («انتخابی ندارم» / اوکی بدون هدف)؛ محاسبه فقط از طریق
  پایپ‌لاین موجود شب بازپرس (بدون موتور محاسبهٔ دوم).
- گیم‌پلی نقش‌ها و هدف‌های مجاز در بازی عادی دست‌نخورده می‌مانند.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.main import no_host_bot_assistant_flow_enabled
from bot.models import Game, Role
from bot.no_host_night_ready import (
    _citizens_ready,
    _detective_ready,
    _doctor_ready,
    _hunter_night1_ready,
    _interrogator_ready,
    _mafia_night1_parallel_ready,
    _ruintan_ready,
    _sniper_ready,
    no_host_parallel_night_collect_active,
)
from bot.room_mode import is_bazpors_no_host_room, is_mozakere_scenario
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

BAZPORS_FORCE_FINISH_BUTTON_TEXT = "🌙 اتمام شب"
BAZPORS_FORCE_FINISH_CONFIRM_TEXT = (
    "⚠️ تأیید اتمام شب\n\n"
    "آیا مطمئن هستید که می‌خواهید شب جاری را به پایان برسانید؟\n\n"
    "اقدامات تأییدشده محاسبه می‌شوند و اقداماتی که هنوز تأیید نشده‌اند، "
    "بدون اثر در نظر گرفته خواهند شد."
)
BAZPORS_FORCE_FINISH_CANCELLED_TEXT = "لغو شد؛ شب ادامه دارد."
BAZPORS_NIGHT_PANEL_LOCKED_TEXT = "فاز شب به پایان رسید."
BAZPORS_NIGHT_PHASE_ENDED_TEXT = "فاز شب به پایان رسیده است."

# اکت‌های شبانهٔ بازپرس — بعد از اتمام اجباری رد می‌شوند
# (اکت‌های پنل‌های روز مثل d1dn/d1dt از این مجموعه نیستند).
BAZPORS_NIGHT_CLOSED_ACTS = frozenset(
    {
        # منوی تیم مافیا + تأیید/بازگشت
        "nms", "nmy", "nmn", "nmg", "nmc", "nmb",
        # شات مافیا
        "msk", "msb", "msc",
        # ناتو (شامل حدس نقش در فاز نقش، با پیشوند n1r-)
        "n1c", "n1b", "n2p", "n2c", "n2b",
        # یاکوزایی
        "ysp", "ysb", "ysc", "ycp", "ycb", "ycc",
        # پزشک (شامل اوکی‌های غیرانتخابی)
        "dkt", "dkn", "dkc", "dkb", "dko", "dkng",
        # کارآگاه
        "ndp", "ndc", "ndb",
        # اسنایپر
        "skt", "skn", "skc", "skb",
        # شیاد
        "sgt", "sgc", "sgb",
        # بازپرسِ نقش (interrogator)
        "nii1", "nii1s", "nii2", "nii2a", "nii2r", "niisk",
        # هانتر
        "hnp", "hns", "hnc", "hnb",
        # اوکی‌های انتظار (شهروند / رویین‌تن)
        "cic", "ruc",
    }
)


class BazporsHelperCb(CallbackData, prefix="bzh"):
    """کمک‌کنندهٔ بازپرس — اتمام اجباری شب."""

    code: str
    act: str = "go"
    kind: str = "force_night"


def bazpors_night_force_finish_collection_active(game: Game) -> bool:
    """شب بازپرس (بدون گرداننده) در حال جمع‌آوری اقدامات موازی."""
    if not is_bazpors_no_host_room(game):
        return False
    if not no_host_parallel_night_collect_active(game):
        return False
    nc = game.bazpors_narrator_night_count
    if not nc or nc < 1:
        return False
    return game.no_host_night_entry_dispatched_night == nc


def bazpors_night_player_actions_closed(game: Game) -> bool:
    """Room 91: the force-finish latch is valid ONLY for the night it was
    recorded on. A later night (or a legacy snapshot without a recorded
    night) must not permanently block the currently active collection."""
    if not is_bazpors_no_host_room(game):
        return False
    if not game.bazpors_night_force_finished:
        return False
    recorded = game.bazpors_night_force_finished_night
    if recorded is None:
        # Legacy latch without a night identifier: force-finish always
        # closed that night's collection, so if parallel collection is
        # active again this can only be a LATER night — keep it open.
        # With no active collection, keep the legacy same-night safety.
        return not no_host_parallel_night_collect_active(game)
    return recorded == game.bazpors_narrator_night_count


def bazpors_night_act_is_closed_for_game(game: Game, act: str) -> bool:
    if not bazpors_night_player_actions_closed(game):
        return False
    if act in BAZPORS_NIGHT_CLOSED_ACTS:
        return True
    # حدس نقش ناتو در فاز نقش — n1r-<role>
    return act.startswith("n1r-")


def find_bazpors_bot_assistant_game(
    user_id: int, gm: "GameManager | None" = None
) -> Game | None:
    if gm is None:
        from bot.app_state import manager as gm
    game = gm.find_active_participant_game(user_id)
    if game is None or not is_bazpors_no_host_room(game):
        return None
    if not no_host_bot_assistant_flow_enabled(game):
        return None
    if game.bot_assistant_user_id != user_id:
        return None
    return game


def _force_finish_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، اتمام شب",
                    callback_data=BazporsHelperCb(
                        code=game.room_code, act="yes", kind="force_night"
                    ).pack(),
                    style="success",
                ),
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data=BazporsHelperCb(
                        code=game.room_code, act="no", kind="force_night"
                    ).pack(),
                ),
            ]
        ]
    )


def bazpors_force_finish_button_keyboard(game: Game) -> InlineKeyboardMarkup:
    """دکمهٔ «اتمام شب» روی پنل یادآور کمک‌کننده."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BAZPORS_FORCE_FINISH_BUTTON_TEXT,
                    callback_data=BazporsHelperCb(
                        code=game.room_code, act="go", kind="force_night_btn"
                    ).pack(),
                )
            ]
        ]
    )


def pending_bazpors_force_finish_labels(game: Game, gm: "GameManager") -> list[str]:
    from bot.no_host_night_ready import pending_no_host_night_actor_labels

    return pending_no_host_night_actor_labels(game)


def _normalize_pending_bazpors_mafia_actions(game: Game) -> list[str]:
    """منوی مافیا / شات / ناتو / یاکوزایی — پیش‌فرض‌های اتمام اجباری.

    خروجی: کلیدهای اجباری‌شده برای audit. اقدام تأییدشده (شات ثبت‌شده)
    هرگز بازنویسی نمی‌شود.
    """
    from bot.no_host_mafia_night1 import (
        MAFIA_ACTION_NATO,
        MAFIA_ACTION_SHOT,
        MAFIA_ACTION_YAKU,
    )
    from bot.roles.night_state import yaku_night_state

    forced: list[str] = []
    action = game.no_host_mafia_night1_chosen_action

    if not game.no_host_mafia_night1_done:
        # منو اصلاً تأیید نشده — بدون شات و بدون ناتو/یاکوزایی.
        game.no_host_mafia_night1_flow_active = False
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_pending_action = None
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_shot_flow_active = False
        game.no_host_mafia_shot_pending_uid = None
        game.no_host_mafia_shot_awaiting_confirm = False
        forced.append("mafia")
        return forced

    if action == MAFIA_ACTION_YAKU and not yaku_night_state(game).no_host_done:
        # یاکوزایی تأیید نشده — امشب هیچ اقدام یاکوزایی انجام نمی‌شود.
        state = yaku_night_state(game)
        state.no_host_flow_active = False
        state.no_host_done = True
        state.no_host_phase = None
        state.no_host_pending_sac_uid = None
        state.no_host_pending_civ_uid = None
        forced.append("yaku")

    if action == MAFIA_ACTION_NATO and not game.no_host_mafia_nato_done:
        # ناتو تأیید نشده — بدون اعطای نقش/هدف.
        game.no_host_mafia_nato_flow_active = False
        game.no_host_mafia_nato_done = True
        game.no_host_mafia_nato_phase = None
        game.no_host_mafia_nato_pending_role = None
        game.no_host_mafia_nato_pending_target_uid = None
        forced.append("nato")

    if action in (MAFIA_ACTION_SHOT, None):
        if not (
            game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
        ):
            # شات تأیید نشده — بدون شات و بدون هدف.
            game.no_host_mafia_shot_done = True
            game.no_host_mafia_shot_flow_active = False
            game.no_host_mafia_shot_pending_uid = None
            game.no_host_mafia_shot_awaiting_confirm = False
            forced.append("mafia_shot")
    return forced


def normalize_pending_bazpors_night_actions(game: Game, gm: "GameManager") -> dict:
    """اقدامات ناقص را مثل «انتخابی ندارم» / اوکیِ بدون اثر ثبت کن.

    خروجی: دیکشنری ماشین‌خوان ثبت‌شده در audit (کلید → «force_finished_no_action»).
    مهمات اسنایپر و شارژهای یک‌بارمصرف فقط با اتمام اجباری مصرف نمی‌شوند.
    """
    from bot.no_host_night_ready import _alive_citizen_uids
    from bot.roles.doctor import commit_pick as doctor_commit_pick

    dispositions: dict[str, str] = {}

    def mark(key: str) -> None:
        dispositions[key] = "force_finished_no_action"

    for key in _normalize_pending_bazpors_mafia_actions(game):
        mark(key)

    if not _mafia_night1_parallel_ready(game):
        mark("mafia")

    if not _citizens_ready(game):
        done = set(game.no_host_citizen_night_confirmed_uids)
        for uid in _alive_citizen_uids(game):
            if uid not in done:
                game.no_host_citizen_night_confirmed_uids.append(uid)
        # اوکی صرفِ شهروند ساده — به‌عنوان اوکیِ داده‌شده ثبت می‌شود.
        mark("citizen")

    if not _ruintan_ready(game):
        game.no_host_ruintan_night_confirmed = True
        mark("ruintan")

    if not _hunter_night1_ready(game):
        game.no_host_night1_hunter_flow_active = False
        game.no_host_night1_hunter_done = True
        game.no_host_hunter_pending_pick_uid = None
        game.no_host_hunter_awaiting_confirm = False
        if game.no_host_hunter1_dm_signature is None:
            game.no_host_hunter1_dm_signature = (
                f"{game.bazpors_narrator_night_count}:hunter:n1"
            )
        mark("hunter")

    if not _detective_ready(game):
        det = find_alive_role_holder(game, Role.DETECTIVE)
        if det is not None:
            game.no_host_detective_flow_active = False
            game.no_host_detective_pending_tid = None
            game.no_host_detective_pick_confirmed = True
            mark("detective")

    if not _doctor_ready(game):
        doc = find_alive_role_holder(game, Role.DOCTOR)
        if doc is not None:
            game.no_host_doctor_flow_active = False
            game.no_host_doctor_pending_save_uids = []
            game.no_host_doctor_pending_none = False
            # «انتخابی ندارم» — بدون نجات؛ شمارنده‌های نجات خود دست‌نخورده.
            doctor_commit_pick(game, None)
            game.no_host_doctor_pick_confirmed = True
            mark("doctor")

    if not _sniper_ready(game):
        sn = find_alive_role_holder(game, Role.SNIPER)
        if sn is not None:
            from bot.roles.sniper import clear_pick as sniper_clear_pick

            # بدون شلیک؛ گلوله (قابلیت یک‌بارمصرف) مصرف نمی‌شود.
            sniper_clear_pick(game)
            game.no_host_sniper_flow_active = False
            game.no_host_sniper_pending_target_uid = None
            game.no_host_sniper_pending_none = False
            game.no_host_sniper_pick_confirmed = True
            mark("sniper")

    if not _interrogator_ready(game):
        intr = find_alive_role_holder(game, Role.INTERROGATOR)
        if intr is not None:
            game.no_host_interrog_flow_active = False
            game.no_host_interrog_ui_phase = None
            game.no_host_interrog_night_gate_pending = False
            game.no_host_interrog_pick_confirmed = True
            mark("interrogator")

    from bot.no_host_night_ready import _role_pick_ready

    if not _role_pick_ready(game, Role.SHIAD, "no_host_shiad_pick_confirmed"):
        sh = find_alive_role_holder(game, Role.SHIAD)
        if sh is not None:
            # شیاد تأیید نکرده — بدون دخالت و بدون افکت انتخابی.
            game.no_host_shiad_flow_active = False
            game.no_host_shiad_pending_tid = None
            game.bazpors_shiad_target_uid = None
            game.no_host_shiad_pick_confirmed = True
            mark("shiad")

    return dispositions


async def lock_bazpors_night_mirror_panels(bot: Bot, game: Game) -> None:
    from bot.observer_delivery import update_mirror_prompt_pair

    nc = max(1, game.bazpors_narrator_night_count)
    lockable_kinds = {
        "night1_mafia",
        "night1_mafia_confirm",
        f"mafia_shot_n{nc}",
        f"mafia_shot_confirm_n{nc}",
        "no_host_citizen",
        "no_host_doctor",
        "no_host_detective",
        "no_host_sniper",
        "no_host_shiad",
        "no_host_interrog",
        "no_host_ruintan",
        "night1_hunter",
        "night1_nato",
        "night1_nato_role_confirm",
        "night1_nato_player_confirm",
    }
    for key in list(game.mirror_prompt_messages):
        parts = key.split(":", 2)
        if len(parts) != 3:
            continue
        kind, room, uid_s = parts
        if room != game.room_code:
            continue
        if kind not in lockable_kinds and not kind.startswith("mafia_shot_n"):
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
            BAZPORS_NIGHT_PANEL_LOCKED_TEXT,
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )


_FORCE_FINISH_INFLIGHT: set[str] = set()


async def force_finish_bazpors_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """اتمام اجباری شب بازپرس — تضمین تک‌اجرایی برای فراخوانی همزمان/تکراری."""
    if game.room_code in _FORCE_FINISH_INFLIGHT:
        logger.info(
            "Bazpors force finish already in flight room=%s — duplicate ignored",
            game.room_code,
        )
        return
    if game.bazpors_night_force_finished:
        # Room 91: idempotent only for the latched NIGHT — a later night
        # (or a restored legacy latch) must be force-finishable again.
        if bazpors_night_player_actions_closed(game):
            return
        # Stale latch from a previous night, or from a legacy snapshot
        # whose collection is active again — clear it before re-latching.
        game.bazpors_night_force_finished = False
        game.bazpors_night_force_finished_night = None
    if not no_host_parallel_night_collect_active(game):
        # بین تلاش اول و رسیدن اینجا، شب به‌طور عادی بسته شده است — کاری نکن.
        return
    _FORCE_FINISH_INFLIGHT.add(game.room_code)
    try:
        await _force_finish_bazpors_night_locked(bot, game, gm)
    finally:
        _FORCE_FINISH_INFLIGHT.discard(game.room_code)


async def _force_finish_bazpors_night_locked(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    try:
        from bot.night_helper_reminder import cleanup_night_helper_reminder

        await cleanup_night_helper_reminder(bot, game)
    except Exception:
        pass
    pending = pending_bazpors_force_finish_labels(game, gm)
    if pending:
        logger.info(
            "Force finishing Bazpors night room=%s night=%s. Pending: %s",
            game.room_code,
            game.bazpors_narrator_night_count,
            ", ".join(pending),
        )
    game.bazpors_night_force_finished = True
    game.bazpors_night_force_finished_night = game.bazpors_narrator_night_count
    dispositions = normalize_pending_bazpors_night_actions(game, gm)
    await lock_bazpors_night_mirror_panels(bot, game)
    from bot.no_host_night_ready import finish_no_host_parallel_night_collect

    await finish_no_host_parallel_night_collect(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "bazpors.force_finish_night",
            night_count=game.bazpors_narrator_night_count,
            pending=pending,
            force_finished_no_action=dispositions,
        )
    except Exception:
        pass
    try:
        from bot.app_state import manager as _manager

        _manager.persist_snapshot(
            game, reason="bazpors_force_finish_night"
        )
    except Exception:
        pass


async def handle_bazpors_force_finish_button(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    assistant_uid: int,
) -> None:
    """«🌙 اتمام شب» button — yes/cancel confirmation keeps ONE message.

    No new message is sent: the reminder itself is edited into the
    confirmation panel and stays on the same message_id until «❌ انصراف»
    or «✅ بله، اتمام شب» is pressed.
    """
    if not bazpors_night_force_finish_collection_active(game):
        await callback.answer("هنوز تو فاز شب نیستیم.", show_alert=True)
        return
    if game.night_helper_reminder_force_confirm_open:
        await callback.answer(BAZPORS_NIGHT_PHASE_ENDED_TEXT)
        return
    await callback.answer()
    message_id = game.night_helper_reminder_message_id
    if message_id is None:
        # Reminder message not bound yet (pre-send / after restart) —
        # keep the legacy separate-message confirm flow.
        try:
            await bot.send_message(
                assistant_uid,
                BAZPORS_FORCE_FINISH_CONFIRM_TEXT,
                reply_markup=_force_finish_confirm_keyboard(game),
            )
        except Exception:
            logger.exception(
                "bazpors force finish button confirm send failed room=%s",
                game.room_code,
            )
        return
    chat_id = game.night_helper_reminder_chat_id or assistant_uid
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=BAZPORS_FORCE_FINISH_CONFIRM_TEXT,
            reply_markup=_force_finish_confirm_keyboard(game),
            parse_mode="HTML",
        )
        game.night_helper_reminder_force_confirm_open = True
    except Exception:
        logger.exception(
            "bazpors force finish confirm edit failed room=%s",
            game.room_code,
        )


async def handle_bazpors_force_finish_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    assistant_uid: int,
    act: str,
) -> None:
    if callback.message is None:
        return
    if bazpors_night_player_actions_closed(game):
        # Room 91: night-aware — only the latched night itself is closed.
        await callback.answer(BAZPORS_NIGHT_PHASE_ENDED_TEXT, show_alert=True)
        return
    if not bazpors_night_force_finish_collection_active(game):
        await callback.answer("هنوز تو فاز شب نیستیم.", show_alert=True)
        return
    if act == "no":
        await callback.answer()
        from bot.night_helper_reminder import (
            restore_night_helper_reminder_after_cancel,
        )

        await restore_night_helper_reminder_after_cancel(bot, game)
        if (
            game.night_helper_reminder_message_id is None
            and callback.message is not None
        ):
            # Separate fallback confirm message — close it the legacy way.
            try:
                await callback.message.edit_text(
                    BAZPORS_FORCE_FINISH_CANCELLED_TEXT
                )
            except Exception:
                pass
        return
    if act != "yes":
        await callback.answer("نامعتبر.", show_alert=True)
        return
    await callback.answer("شب به پایان رسید.")
    game.night_helper_reminder_force_confirm_open = False
    if (
        game.night_helper_reminder_message_id is None
        and callback.message is not None
    ):
        # Separate fallback confirm message — close it the legacy way.
        try:
            await callback.message.edit_text(
                BAZPORS_FORCE_FINISH_CONFIRM_TEXT + "\n\n✅ شب به پایان رسید."
            )
        except Exception:
            pass
    # Reminder/fallback message is deleted by cleanup — no intermediate edit.
    await force_finish_bazpors_night(bot, game, gm)


async def handle_bazpors_helper_action(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    assistant_uid: int,
    actor_uid: int,
    act: str,
    kind: str,
) -> None:
    if kind == "force_night_btn":
        await handle_bazpors_force_finish_button(
            callback,
            bot,
            game,
            gm,
            assistant_uid=assistant_uid,
        )
        return
    if kind == "force_night":
        await handle_bazpors_force_finish_callback(
            callback,
            bot,
            game,
            gm,
            assistant_uid=assistant_uid,
            act=act,
        )
        return
    await callback.answer("نامعتبر.", show_alert=True)


async def handle_bazpors_force_finish_text(
    msg: Message, bot: Bot, user_id: int, gm: "GameManager | None" = None
) -> None:
    """دستور متنی «اتمام شب» — فقط کمک‌کنندهٔ بازپرس."""
    game = find_bazpors_bot_assistant_game(user_id, gm)
    if game is None:
        return
    if not bazpors_night_force_finish_collection_active(game):
        await msg.answer("هنوز تو فاز شب نیستیم.")
        return
    await msg.answer(
        BAZPORS_FORCE_FINISH_CONFIRM_TEXT,
        reply_markup=_force_finish_confirm_keyboard(game),
    )
