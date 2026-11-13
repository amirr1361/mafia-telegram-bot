"""اتمام اجباری شب — فقط سناریوی مذاکره (کمک‌کننده ربات).

الگوی ماسون (bot/mason_force_finish_night.py) برای مذاکره:
- فقط کمک‌کنندهٔ ربات دسترسی دارد.
- تأیید دو مرحله‌ای (دکمه «🌙 اتمام شب» → «✅ بله، اتمام شب» / «❌ انصراف»).
- لغو = بدون هیچ تغییری در بازی.
- تأیید = اقدامات تأییدشده حفظ؛ اقدامات بی‌تأیید انجام‌نشده؛ پیش‌فرض‌های
  هر نقش؛ محاسبه از طریق پایپ‌لاین موجود (بدون محاسبه‌گر دوم).
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
    _journalist_ready,
    _mafia_night1_parallel_ready,
    _ruintan_ready,
    _sniper_ready,
    no_host_parallel_night_collect_active,
)
from bot.room_mode import is_mozakere_scenario
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

MOZAKERE_FORCE_FINISH_BUTTON_TEXT = "🌙 اتمام شب"
MOZAKERE_FORCE_FINISH_CONFIRM_TEXT = (
    "⚠️ آیا مطمئن هستید که می‌خواهید شب جاری را به پایان برسانید؟"
)
MOZAKERE_FORCE_FINISH_CANCELLED_TEXT = "لغو شد؛ شب ادامه دارد."
MOZAKERE_NIGHT_PANEL_LOCKED_TEXT = "فاز شب به پایان رسید."
MOZAKERE_NIGHT_PHASE_ENDED_TEXT = "فاز شب به پایان رسیده است."

# اکت‌های شبانهٔ مذاکره — بعد از اتمام اجباری رد می‌شوند (پنل‌های روز از این مسیر نیستند).
MOZAKERE_NIGHT_CLOSED_ACTS = frozenset(
    {
        # منوی تیم مافیا + تأیید/بازگشت
        "nms", "nmg", "nmc", "nmb",
        # شات مافیا
        "msk", "msb", "msc",
        # مذاکره‌کننده
        "negp", "negc", "negb",
        # پزشک (شامل اوکی‌های غیرانتخابی)
        "dkt", "dkn", "dkc", "dkb", "dko", "dkng",
        # کارآگاه
        "ndp", "ndc", "ndb",
        # اسنایپر
        "skt", "skn", "skc", "skb",
        # خبرنگار
        "jrp", "jrc", "jrb", "jic",
        # اوکی‌های انتظار (شهروند / رویین‌تن / انتظار شب)
        "cic", "ruc", "nwok",
    }
)


class MozakereHelperCb(CallbackData, prefix="mzh"):
    """کمک‌کنندهٔ مذاکره — اتمام اجباری شب."""

    code: str
    act: str = "go"
    kind: str = "force_night"


def mozakere_night_force_finish_collection_active(game: Game) -> bool:
    """شب مذاکره در حال جمع‌آوری اقدامات موازی."""
    if not is_mozakere_scenario(game):
        return False
    if not no_host_parallel_night_collect_active(game):
        return False
    nc = game.bazpors_narrator_night_count
    return game.no_host_night_entry_dispatched_night == nc


def mozakere_night_player_actions_closed(game: Game) -> bool:
    """اتمام اجباری فقط همین شب را می‌بندد (Room 91 الگو).

    - لَچِ ثبت‌شده برای همین شب → بسته.
    - لَچِ شب‌های قبلی → باز (باید در ورود شب تازه پاک شده باشد).
    - لَچِ قدیمی بدون شمارهٔ شب (اسنپ‌شات لگاسی) → زمانی که جمع‌آوری موازیِ
      شب دوباره فعال است باز در نظر گرفته می‌شود؛ اتمام اجباری همیشه جمع‌آوری
      را می‌بندد، پس لَچ + جمع‌آوری فعال فقط شبِ بعدی می‌تواند باشد. با
      جمع‌آوری غیرفعال، بستگیِ همان شب حفظ می‌شود.
    """
    if not is_mozakere_scenario(game):
        return False
    if not game.mozakere_night_force_finished:
        return False
    from bot.no_host_night_ready import no_host_parallel_night_collect_active

    recorded = getattr(game, "mozakere_night_force_finished_night", None)
    if recorded is None:
        # Legacy snapshot: keep the same-night safety via phase/state.
        return not no_host_parallel_night_collect_active(game)
    return int(recorded) == int(game.bazpors_narrator_night_count)


def mozakere_night_act_is_closed_for_game(game: Game, act: str) -> bool:
    return (
        mozakere_night_player_actions_closed(game)
        and act in MOZAKERE_NIGHT_CLOSED_ACTS
    )


def find_mozakere_bot_assistant_game(
    user_id: int, gm: "GameManager | None" = None
) -> Game | None:
    if gm is None:
        from bot.app_state import manager as gm
    game = gm.find_active_participant_game(user_id)
    if game is None or not is_mozakere_scenario(game):
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
                    callback_data=MozakereHelperCb(
                        code=game.room_code, act="yes", kind="force_night"
                    ).pack(),
                    style="success",
                ),
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data=MozakereHelperCb(
                        code=game.room_code, act="no", kind="force_night"
                    ).pack(),
                ),
            ]
        ]
    )


def mozakere_force_finish_button_keyboard(game: Game) -> InlineKeyboardMarkup:
    """دکمهٔ «اتمام شب» روی پنل یادآور کمک‌کننده."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=MOZAKERE_FORCE_FINISH_BUTTON_TEXT,
                    callback_data=MozakereHelperCb(
                        code=game.room_code, act="go", kind="force_night_btn"
                    ).pack(),
                )
            ]
        ]
    )


def pending_mozakere_force_finish_labels(game: Game, gm: "GameManager") -> list[str]:
    from bot.no_host_night_ready import pending_no_host_night_actor_labels

    return pending_no_host_night_actor_labels(game)


def _normalize_pending_mozakere_mafia_actions(game: Game) -> list[str]:
    """منوی مافیا / شات / مذاکره — پیش‌فرض‌های اتمام اجباری.

    خروجی: کلیدهای اجباری‌شده برای audit.
    """
    from bot.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE, MAFIA_ACTION_SHOT

    forced: list[str] = []
    action = game.no_host_mafia_night1_chosen_action

    if not game.no_host_mafia_night1_done:
        # منو اصلاً تأیید نشده — بدون شات و بدون مذاکره.
        game.no_host_mafia_night1_flow_active = False
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_pending_action = None
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_shot_flow_active = False
        game.no_host_mafia_shot_pending_uid = None
        game.no_host_mafia_shot_awaiting_confirm = False
        # اگر «مذاکره» انتخاب شده بود ولی تأیید نهایی نشده بود، شب این مذاکره
        # انجام‌نشده در نظر گرفته می‌شود.
        game.mozakere_negotiation_tonight = False
        game.no_host_negotiator_flow_active = False
        game.no_host_negotiator_pick_confirmed = True
        game.no_host_negotiator_pending_tid = None
        forced.append("mafia")
        return forced

    if action == MAFIA_ACTION_NEGOTIATE:
        from bot.roles.mozakere_negotiator import find_alive_negotiator

        if find_alive_negotiator(game) is not None and (
            not game.no_host_negotiator_pick_confirmed
        ):
            # مذاکره انتخاب شده ولی هدفش تأیید نشده — مذاکره امشب انجام نمی‌شود.
            game.no_host_negotiator_flow_active = False
            game.no_host_negotiator_pick_confirmed = True
            game.no_host_negotiator_pending_tid = None
            game.mozakere_negotiation_tonight = False
            game.no_host_mafia_shot_done = True
            forced.append("negotiator")

    if action in (MAFIA_ACTION_SHOT, None):
        if not (
            game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
        ):
            game.no_host_mafia_shot_done = True
            game.no_host_mafia_shot_flow_active = False
            game.no_host_mafia_shot_pending_uid = None
            game.no_host_mafia_shot_awaiting_confirm = False
            forced.append("mafia_shot")
    return forced


def normalize_pending_mozakere_night_actions(game: Game, gm: "GameManager") -> dict:
    """اقدامات ناقص را مثل «انتخابی ندارم» / اوکی بدون اثر ثبت کن.

    خروجی: دیکشنری ماشین‌خوان ثبت‌شده در audit (کلید → «force_finished_no_action»).
    """
    from bot.no_host_night_ready import _alive_citizen_uids
    from bot.roles.doctor import commit_pick as doctor_commit_pick

    dispositions: dict[str, str] = {}

    def mark(key: str) -> None:
        dispositions[key] = "force_finished_no_action"

    for key in _normalize_pending_mozakere_mafia_actions(game):
        mark(key)

    if not _mafia_night1_parallel_ready(game):
        mark("mafia")

    if not _citizens_ready(game):
        done = set(game.no_host_citizen_night_confirmed_uids)
        for uid in _alive_citizen_uids(game):
            if uid not in done:
                game.no_host_citizen_night_confirmed_uids.append(uid)
        mark("citizen")

    if not _ruintan_ready(game):
        game.no_host_ruintan_night_confirmed = True
        mark("ruintan")

    if not _hunter_night1_ready(game):
        game.no_host_night1_hunter_done = True
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

            # بدون شلیک؛ مهمات (شمارندهٔ عمر مذاکره) دست‌نخورده می‌ماند.
            sniper_clear_pick(game)
            game.no_host_sniper_flow_active = False
            game.no_host_sniper_pending_target_uid = None
            game.no_host_sniper_pending_none = False
            game.no_host_sniper_pick_confirmed = True
            mark("sniper")

    if not _interrogator_ready(game):
        interrog = find_alive_role_holder(game, Role.INTERROGATOR)
        if interrog is not None:
            game.no_host_interrog_flow_active = False
            game.no_host_interrog_pick_confirmed = True
            mark("interrogator")

    if not _journalist_ready(game):
        jr = find_alive_role_holder(game, Role.JOURNALIST)
        if jr is not None:
            from bot.roles.mozakere_journalist import mozakere_journalist_active

            game.no_host_journalist_flow_active = False
            game.no_host_journalist_pending_tid = None
            if mozakere_journalist_active(game):
                game.no_host_journalist_pick_confirmed = True
            else:
                game.no_host_journalist_idle_confirmed = True
            mark("journalist")

    return dispositions


async def lock_mozakere_night_mirror_panels(bot: Bot, game: Game) -> None:
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
        "no_host_journalist",
        "no_host_negotiator",
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
            MOZAKERE_NIGHT_PANEL_LOCKED_TEXT,
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )


_FORCE_FINISH_INFLIGHT: set[str] = set()


async def force_finish_mozakere_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """اتمام اجباری شب — تضمین تک‌اجرایی برای فراخوانی همزمان/تکراری."""
    if game.room_code in _FORCE_FINISH_INFLIGHT:
        logger.info(
            "Mozakere force finish already in flight room=%s — duplicate ignored",
            game.room_code,
        )
        return
    _FORCE_FINISH_INFLIGHT.add(game.room_code)
    try:
        await _force_finish_mozakere_night_locked(bot, game, gm)
    finally:
        _FORCE_FINISH_INFLIGHT.discard(game.room_code)


async def _force_finish_mozakere_night_locked(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    try:
        from bot.night_helper_reminder import cleanup_night_helper_reminder

        await cleanup_night_helper_reminder(bot, game)
    except Exception:
        pass
    pending = pending_mozakere_force_finish_labels(game, gm)
    if pending:
        logger.info(
            "Force finishing Mozakere night room=%s night=%s. Pending: %s",
            game.room_code,
            game.bazpors_narrator_night_count,
            ", ".join(pending),
        )
    game.mozakere_night_force_finished = True
    game.mozakere_night_force_finished_night = int(
        game.bazpors_narrator_night_count
    )
    dispositions = normalize_pending_mozakere_night_actions(game, gm)
    await lock_mozakere_night_mirror_panels(bot, game)
    from bot.no_host_night_ready import finish_no_host_parallel_night_collect

    await finish_no_host_parallel_night_collect(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "mozakere.force_finish_night",
            night_count=game.bazpors_narrator_night_count,
            pending=pending,
            force_finished_no_action=dispositions,
        )
    except Exception:
        pass
    try:
        from bot.app_state import manager as _manager

        _manager.persist_snapshot(
            game, reason="mozakere_force_finish_night"
        )
    except Exception:
        pass


async def reject_mozakere_night_callback_if_closed(
    callback: CallbackQuery, game: Game
) -> bool:
    if mozakere_night_player_actions_closed(game):
        await callback.answer(MOZAKERE_NIGHT_PHASE_ENDED_TEXT, show_alert=True)
        return True
    return False


async def handle_mozakere_force_finish_button(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    assistant_uid: int,
) -> None:
    """دکمهٔ «🌙 اتمام شب» روی پنل یادآور — تأیید بله/انصراف."""
    if not mozakere_night_force_finish_collection_active(game):
        await callback.answer("هنوز تو فاز شب نیستیم.", show_alert=True)
        return
    await callback.answer()
    try:
        await bot.send_message(
            assistant_uid,
            MOZAKERE_FORCE_FINISH_CONFIRM_TEXT,
            reply_markup=_force_finish_confirm_keyboard(game),
        )
    except Exception:
        logger.exception(
            "mozakere force finish button confirm send failed room=%s",
            game.room_code,
        )


async def handle_mozakere_force_finish_callback(
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
    if not mozakere_night_force_finish_collection_active(game):
        await callback.answer("هنوز تو فاز شب نیستیم.", show_alert=True)
        return
    if act == "no":
        await callback.answer()
        try:
            await callback.message.edit_text(MOZAKERE_FORCE_FINISH_CANCELLED_TEXT)
        except Exception:
            pass
        return
    if act != "yes":
        await callback.answer("نامعتبر.", show_alert=True)
        return
    await callback.answer("شب به پایان رسید.")
    try:
        await callback.message.edit_text(
            MOZAKERE_FORCE_FINISH_CONFIRM_TEXT + "\n\n✅ شب به پایان رسید."
        )
    except Exception:
        pass
    await force_finish_mozakere_night(bot, game, gm)


async def handle_mozakere_helper_action(
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
        await handle_mozakere_force_finish_button(
            callback,
            bot,
            game,
            gm,
            assistant_uid=assistant_uid,
        )
        return
    if kind == "force_night":
        await handle_mozakere_force_finish_callback(
            callback,
            bot,
            game,
            gm,
            assistant_uid=assistant_uid,
            act=act,
        )
        return
    await callback.answer("نامعتبر.", show_alert=True)


async def handle_mozakere_force_finish_text(
    msg: Message, bot: Bot, user_id: int, gm: "GameManager | None" = None
) -> None:
    """دستور متنی «اتمام شب» — فقط کمک‌کنندهٔ مذاکره."""
    game = find_mozakere_bot_assistant_game(user_id, gm)
    if game is None:
        return
    if not mozakere_night_force_finish_collection_active(game):
        await msg.answer("هنوز تو فاز شب نیستیم.")
        return
    await msg.answer(
        MOZAKERE_FORCE_FINISH_CONFIRM_TEXT,
        reply_markup=_force_finish_confirm_keyboard(game),
    )
