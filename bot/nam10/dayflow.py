"""Fork day-flow drivers — extracted closure of main.py no-host drivers.

Independent of the Bazpors day1-defense / day-vote / intro-night flows: all
state reads/writes go through the ``nam10_*`` / ``nmnd_*`` fork fields, and
no-host module helpers resolve inside ``bot.nam10``.
"""

from __future__ import annotations

from bot.nam10.role_labels import nam10_role_label_fa

import html
import logging

logger = logging.getLogger(__name__)

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.app_state import manager
from bot.models import Game, Phase, Player, Role
from bot.text_fa import fa_digits as _fa_digits


from bot.game import (
    is_mafia_team,
    is_synthetic_player_uid,
    scenario_role_label_fa,
)


from bot.nam10.nmnd_narrator import (
    begin_no_host_day1_defense_pick,
    day_vote_defender_uids,
    day_vote_participation_count,
    day_vote_pick_uids,
    eliminate_player_from_game,
    nam10_day1_after_elim_enter_night,
    nam10_day1_defense_no_votes_enter_night,
    nam10_day1_no_exit_enter_night,
    nam10_skip_day1_vote_enter_night,
    push_host_step,
    set_day_vote_defender_uids,
    set_day_vote_pick_uids,
)


from bot.nam10.no_host_night1 import (
    on_no_host_entered_night1,
)


from bot.nam10.no_host_phase import (
    nam10_run_day1_end_vote_flow,
)


from bot.observer_delivery import (
    PlayerMirrorCb,
    apply_mirror_claim_winner,
    broadcast_to_alive_players,
    broadcast_to_players,
    close_mirror_prompt_keyboards,
    flush_elimination_notifications,
    game_observer_mirror_active,
    mirror_ui_claim_key,
    mirrored_intro_night_confirm_keyboard,
    mirrored_intro_night_start_keyboard,
    no_host_observer_registered as nam10_observer_registered,
    promote_mirror_prompt_to_panel,
    register_mirror_prompt_pair,
    send_to_player,
    try_claim_mirror_ui,
    update_mirror_prompt_pair,
)


from bot.post_game_flow import (
    build_post_session_recap_snapshot,
)


from bot.room_mode import (
    is_mason_scenario,
    no_host_bot_assistant_flow_enabled as nam10_bot_assistant_flow_enabled,
)


from bot.tg_send import (
    safe_send_message,
)


from bot.main import (
    NoHostBotAssistantPick,
    NoHostDay1DefenseCb,
    NoHostIntroNightStart,
    _answer_mirror_claim,
    _bazpors_auto_host_final_report_header,
    _build_bazpors_game_end_winner_html,
    _build_bazpors_timeline_html,
    _build_session_recap_roster_lines,
    _defense_toggle_target_uid,
    build_game_final_report_header_html,
    ensure_private_role_card_delivered,
)



async def send_no_host_bot_assistant_prompt(bot: Bot, game: Game) -> None:
    """مرحلهٔ بعد از تأیید/رد ناظر — فقط اتاق no_host و فقط به سازنده."""
    if not nam10_bot_assistant_flow_enabled(game):
        return
    creator_id = game.host_id
    if creator_id not in game.players or is_synthetic_player_uid(creator_id):
        return
    if game.bot_assistant_user_id is not None:
        return
    await safe_send_message(
        bot,
        creator_id,
        build_no_host_bot_assistant_prompt_html(),
        parse_mode="HTML",
        reply_markup=nam10_bot_assistant_pick_keyboard(game),
    )

def nam10_bot_assistant_pick_keyboard(game: Game) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sorted(
        [
            pl
            for pl in game.players.values()
            if not is_synthetic_player_uid(pl.user_id)
        ],
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        lab = manager.format_player_tag(p)[:40]
        row.append(
            InlineKeyboardButton(
                text=lab,
                callback_data=NoHostBotAssistantPick(
                    code=game.room_code, act="pick", tid=p.user_id
                ).pack(),
            )
        )
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="🎲 انتخاب تصادفی",
                callback_data=NoHostBotAssistantPick(
                    code=game.room_code, act="random", tid=0
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_no_host_bot_assistant_prompt_html() -> str:
    return (
        "🤖 برای این بازی باید یک نفر به‌عنوان «کمک‌کننده ربات» انتخاب شود.\n\n"
        "چه کسی را انتخاب می‌کنید؟ از لیست زیر یکی را بزنید "
        "یا «انتخاب تصادفی»."
    )

async def finalize_no_host_bot_assistant(
    bot: Bot, game: Game, assistant_uid: int, *, random_pick: bool = True
) -> None:
    if not nam10_bot_assistant_flow_enabled(game):
        return
    game.bot_assistant_user_id = assistant_uid
    game.nam10_assistant_narrator_active = True
    game.nam10_observer_only_narrator_mirror = True
    await ensure_private_role_card_delivered(bot, game, assistant_uid)
    await send_to_player(
        bot,
        game,
        assistant_uid,
        build_no_host_bot_assistant_private_html(random_pick=random_pick),
        parse_mode="HTML",
    )
    announce = build_no_host_assistant_announcement_html(game, assistant_uid)
    await broadcast_to_players(
        bot,
        game,
        announce,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.bot_assistant_picked",
            assistant_uid=assistant_uid,
            observer_uid=game.observer_user_id,
            random_pick=random_pick,
        )
    except Exception:
        pass
    await send_no_host_intro_night_start_prompt(bot, game)

async def send_no_host_intro_night_start_prompt(
    bot: Bot,
    game: Game,
    *,
    observer_only: bool = False,
) -> None:
    """فقط کمک‌کننده ربات؛ اگر ناظر ثبت شده همان پیام بدون پیش‌وند آینه."""
    if not nam10_bot_assistant_flow_enabled(game):
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.nam10_intro_night_started:
        return
    text = build_no_host_intro_night_start_html()
    kb = intro_night_start_keyboard_for(game, assistant_uid)
    ui_key = mirror_ui_claim_key(
        game.room_code, "intro_night_start", assistant_uid
    )
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_player=not observer_only,
        send_observer=nam10_observer_registered(game),
        observer_same_text=True,
        parse_mode="HTML",
    )
    # ناظر دیرتر ثبت شده: پیام کمک‌کننده هنوز دکمهٔ قدیمی (nhi) دارد — کیبورد آینه را هم‌گام کن.
    if observer_only and game_observer_mirror_active(game):
        entry = game.mirror_prompt_messages.get(ui_key, {})
        if entry.get("player"):
            await update_mirror_prompt_pair(
                bot,
                game,
                ui_key,
                text,
                kb,
                assistant_uid=assistant_uid,
                parse_mode="HTML",
            )

def intro_night_start_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_intro_night_start_keyboard(game, assistant_uid)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌙 شروع شب معارفه",
                    callback_data=NoHostIntroNightStart(
                        code=game.room_code, act="go"
                    ).pack(),
                ),
            ],
        ]
    )

def build_no_host_intro_night_start_html() -> str:
    return (
        "🌙 <b>شروع شب معارفه</b>\n\n"
        "با فشردن دکمه زیر، شب معارفه آغاز خواهد شد.\n\n"
        "⚠️ <b>توجه:</b>\n"
        "پس از فشردن این دکمه، پیامی برای تمامی اعضای تیم مافیا ارسال می‌شود "
        "که در آن هم‌تیمی‌هایشان معرفی خواهند شد.\n\n"
        "❗ لطفاً فقط زمانی این دکمه را بزنید که روز معارفه به‌طور کامل "
        "به پایان رسیده باشد."
    )

def build_no_host_bot_assistant_private_html(*, random_pick: bool) -> str:
    if random_pick:
        lead = "شما به‌صورت تصادفی به‌عنوان «کمک‌کننده ربات» انتخاب شدید."
    else:
        lead = "شما به‌عنوان «کمک‌کننده ربات» انتخاب شدید."
    return f"🤖 {lead}\n📌 هر زمان لازم باشد، از شما کمک خواهم گرفت."

def build_no_host_assistant_announcement_html(game: Game, assistant_uid: int) -> str:
    ap = game.players.get(assistant_uid)
    assistant_tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    lines = [
        f"🤖 <b>{assistant_tag}</b> به‌عنوان کمک‌کننده ربات در این بازی انتخاب شد.",
        "",
    ]
    if nam10_observer_registered(game):
        obs_tag = html.escape(
            manager.format_user_tag(
                game.observer_user_id,
                game.observer_full_name,
                game.observer_username,
            )
        )
        lines.extend(
            [
                f"👁️ <b>{obs_tag}</b> به‌عنوان ناظر بازی انتخاب شد.",
                "",
                "📩 ناظر بازی تمامی پیام‌های خصوصی‌ای که ربات برای بازیکنان "
                "ارسال می‌کند را مشاهده خواهد کرد.",
            ]
        )
    return "\n".join(lines)

async def _dispatch_no_host_day1_defense_act(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    act: str,
    *,
    tid: int = 0,
    source: str = "nhd",
) -> None:
    try:
        from bot.game_audit_log import log_no_host_day1_defense_callback

        log_no_host_day1_defense_callback(
            game,
            act=act,
            actor_uid=actor_uid,
            assistant_uid=assistant_uid,
            source=source,
            target_uid=tid or None,
            outcome="received",
        )
    except Exception:
        pass
    if not _no_host_day1_defense_actor_may_act(game, actor_uid, assistant_uid):
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act=act,
                actor_uid=actor_uid,
                assistant_uid=assistant_uid,
                source=source,
                target_uid=tid or None,
                outcome="rejected",
                reject_reason="forbidden_actor",
            )
        except Exception:
            pass
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return
    target_uid = _defense_toggle_target_uid(act, tid)
    if target_uid is not None:
        err = await _no_host_day1_defense_toggle(
            bot, game, assistant_uid, target_uid
        )
        if err:
            await callback.answer(err, show_alert=True)
            return
        await callback.answer("به‌روز شد.")
        return
    if act in ("confirm", "d1dc"):
        await _no_host_day1_defense_confirm(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("none", "d1dn"):
        await _no_host_day1_defense_no_votes(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("no_exit", "d1d0"):
        await _no_host_day1_defense_outcome_no_exit(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("has_exit", "d1d1"):
        await _no_host_day1_defense_outcome_has_exit(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act == "d1el" and tid:
        await _no_host_day1_defense_pick_elim(
            callback, bot, game, assistant_uid, actor_uid, tid
        )
        return
    if act in ("elim_yes", "d1ey"):
        await _no_host_day1_defense_confirm_elim_yes(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("elim_no", "d1en"):
        await _no_host_day1_defense_confirm_elim_no(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    try:
        from bot.game_audit_log import log_no_host_day1_defense_callback

        log_no_host_day1_defense_callback(
            game,
            act=act,
            actor_uid=actor_uid,
            assistant_uid=assistant_uid,
            source=source,
            target_uid=tid or None,
            outcome="rejected",
            reject_reason="unknown_act",
        )
    except Exception:
        pass
    await callback.answer("عمل نامعتبر.", show_alert=True)

async def _no_host_day1_defense_toggle(
    bot: Bot, game: Game, assistant_uid: int, target_uid: int
) -> str | None:
    if game.nam10_day1_defense_phase != "pick":
        return "این مرحله دیگر فعال نیست."
    if target_uid not in game.players or not game.players[target_uid].is_alive:
        return "بازیکن زنده نیست."
    picked = day_vote_pick_uids(game)
    if target_uid in picked:
        picked.discard(target_uid)
    else:
        picked.add(target_uid)
    set_day_vote_pick_uids(game, picked)
    await refresh_no_host_day1_defense_pick_panel(bot, game)
    return None

async def refresh_no_host_day1_defense_pick_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.nam10_day1_defense_phase != "pick":
        return
    text = build_no_host_day1_defense_pick_html(game)
    kb = day1_defense_pick_keyboard_for(game, assistant_uid)
    ui_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    await update_mirror_prompt_pair(
        bot, game, ui_key, text, kb, assistant_uid=assistant_uid, parse_mode="HTML"
    )

def day1_defense_pick_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    mirror = game_observer_mirror_active(game)
    return _no_host_day1_defense_pick_keyboard(game, assistant_uid, mirror=mirror)

def _no_host_day1_defense_pick_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    picked = day_vote_pick_uids(game)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in _alive_players_sorted(game):
        tick = "✅" if p.user_id in picked else "☐"
        name = html.escape(manager.format_player_tag(p)[:24])
        if mirror:
            cb = PlayerMirrorCb(
                code=game.room_code,
                act="d1dt",
                as_uid=assistant_uid,
                tid=p.user_id,
            ).pack()
        else:
            cb = NoHostDay1DefenseCb(
                code=game.room_code, act="tog", tid=p.user_id
            ).pack()
        row.append(
            InlineKeyboardButton(
                text=f"{tick} {name}",
                callback_data=cb,
                style="danger" if p.user_id in picked else "primary",
            )
        )
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if mirror:
        confirm_cb = PlayerMirrorCb(
            code=game.room_code, act="d1dc", as_uid=assistant_uid
        ).pack()
        none_cb = PlayerMirrorCb(
            code=game.room_code, act="d1dn", as_uid=assistant_uid
        ).pack()
    else:
        confirm_cb = NoHostDay1DefenseCb(
            code=game.room_code, act="confirm"
        ).pack()
        none_cb = NoHostDay1DefenseCb(code=game.room_code, act="none").pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="⏭️ برو به مرحله بعد",
                callback_data=confirm_cb,
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🌙 دفاعیه نداریم",
                callback_data=none_cb,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _alive_players_sorted(game: Game) -> list[Player]:
    alive = [p for p in game.players.values() if p.is_alive]
    return sorted(alive, key=lambda p: (p.seat if p.seat is not None else 999, p.user_id))

def build_no_host_day1_defense_pick_html(game: Game) -> str:
    picked = day_vote_pick_uids(game)
    n = len(picked)
    sel = f"\n<i>انتخاب‌شده: {_fa_digits(n)} نفر</i>\n" if n else "\n"
    return (
        "🌅 روز شروع شد.\n"
        "از لیست زیر، بازیکنانی را انتخاب کنید که در پایان روز "
        "با رأی اکثریت برای دفاع انتخاب شده‌اند. 🗳️⚖️\n"
        "سپس دکمه «برو به مرحله بعد» را بزنید. ⏭️\n"
        "اگر هیچ بازیکنی وارد مرحله دفاعیه نشده است، "
        "دکمه «دفاعیه نداریم» را بزنید تا بازی وارد شب شود. 🌙"
        f"{sel}"
    )

def _no_host_day1_defense_pick_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.nmnd_narrator_host_day)
    kind = "day1_defense_pick" if d == 1 else f"day_defense_pick_{d}"
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)

async def _no_host_day1_defense_pick_elim(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    target_uid: int,
) -> None:
    if game.nam10_day1_defense_phase not in ("pick_elim", "outcome"):
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    allowed = {p.user_id for p in _day1_defense_pool_players(game)}
    if target_uid not in allowed:
        await callback.answer(
            "فقط بازیکنان ثبت‌شده در دفاعیه قابل انتخاب هستند.",
            show_alert=True,
        )
        return
    if target_uid in _nam10_day_lawyer_protected_uids(game):
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act="d1el",
                actor_uid=actor_uid,
                assistant_uid=assistant_uid,
                source="dispatch",
                target_uid=target_uid,
                outcome="rejected",
                reject_reason="lawyer_protected",
            )
        except Exception:
            pass
        await callback.answer(
            "⚖️ "
            + html.escape(
                manager.format_player_tag(game.players.get(target_uid))
            )
            + " به دلیل حمایت معتبر وکیل در شب گذشته، وارد دفاعیه نمی‌شود.",
            show_alert=True,
        )
        await announce_nam10_lawyer_defense_skip(bot, game, target_uid)
        return
    game.nam10_day1_pending_elim_uid = target_uid
    game.nam10_day1_defense_phase = "confirm_elim"
    await callback.answer("تأیید کنید.")
    await send_no_host_day1_confirm_elim_panel(bot, game, target_uid)

async def send_no_host_day1_confirm_elim_panel(
    bot: Bot, game: Game, target_uid: int
) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    text = build_no_host_day1_confirm_elim_html(game, target_uid)
    kb = _no_host_day1_confirm_elim_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    confirm_key = _no_host_day1_confirm_elim_ui_key(game, assistant_uid)
    pick_key = _no_host_day1_pick_elim_ui_key(game, assistant_uid)
    outcome_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    promoted = False
    for from_key in (outcome_key, pick_key):
        if await promote_mirror_prompt_to_panel(
            bot,
            game,
            from_ui_key=from_key,
            to_ui_key=confirm_key,
            assistant_uid=assistant_uid,
            text=text,
            reply_markup=kb,
        ):
            promoted = True
            break
    if not promoted:
        await register_mirror_prompt_pair(
            bot,
            game,
            assistant_uid,
            confirm_key,
            text,
            kb,
            send_observer=nam10_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
        await close_mirror_prompt_keyboards(bot, game, outcome_key)
        await close_mirror_prompt_keyboards(bot, game, pick_key)

def build_no_host_day1_confirm_elim_html(game: Game, target_uid: int) -> str:
    p = game.players.get(target_uid)
    tag = html.escape(
        manager.format_player_tag(p) if p else str(target_uid)
    )
    return (
        "⚠️ <b>تأیید حذف</b>\n\n"
        f"آیا مطمئن هستید که <b>{tag}</b> با اجماع رأی‌گیری "
        "از بازی خارج شد؟"
    )

def _no_host_day1_pick_elim_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.nmnd_narrator_host_day)
    kind = "day1_defense_pick_elim" if d == 1 else f"day_defense_pick_elim_{d}"
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)

def _no_host_day1_defense_outcome_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.nmnd_narrator_host_day)
    kind = "day1_defense_outcome" if d == 1 else f"day_defense_outcome_{d}"
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)

def _no_host_day1_confirm_elim_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.nmnd_narrator_host_day)
    kind = (
        "day1_defense_confirm_elim"
        if d == 1
        else f"day_defense_confirm_elim_{d}"
    )
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)

def _no_host_day1_confirm_elim_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    if mirror:
        yes_cb = PlayerMirrorCb(
            code=game.room_code, act="d1ey", as_uid=assistant_uid
        ).pack()
        no_cb = PlayerMirrorCb(
            code=game.room_code, act="d1en", as_uid=assistant_uid
        ).pack()
    else:
        yes_cb = NoHostDay1DefenseCb(code=game.room_code, act="elim_yes").pack()
        no_cb = NoHostDay1DefenseCb(code=game.room_code, act="elim_no").pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔹 بله، تأیید و حذف از بازی",
                    callback_data=yes_cb,
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔹 خیر، بازگشت به انتخاب",
                    callback_data=no_cb,
                )
            ],
        ]
    )

def nam10_rebel_day_substage_closed(game: Game) -> bool:
    """Defense-outcome sub-stages imply the assistant already confirmed
    the daily defense candidates, so the Rebel assassination window for
    this day is closed as well."""
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if not getattr(game, "nam10_day1_defense_active", False):
        return False
    return game.nam10_day1_defense_phase in (
        "outcome",
        "pick_elim",
        "confirm_elim",
    )


def _nam10_day_lawyer_protected_uids(game: Game) -> set[int]:
    """Lawyer protection valid for the day in progress (Namayande-10).

    Night N resolution stores the protected uid plus the narrator night
    count of that night. The predicate is day-scoped, so a protection
    obtained in night N applies to the day immediately following night N
    and never to later days. The intro Day 1 has night_count == 0 and no
    protection can exist before the first night's resolution, so no
    retroactive application is possible. Hacker-nullified Lawyer picks
    never store the durable immunity at all, so they grant nothing here.
    The ability itself was consumed at its valid night confirmation and
    is intentionally NOT consumed again here.
    """
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return set()
    nc = int(game.nmnd_narrator_night_count or 0)
    if nc <= 0:
        return set()
    from bot.nam10.night2 import night2_lawyer_defense_immunity

    return {
        uid
        for uid in game.players
        if night2_lawyer_defense_immunity(
            game, uid, day_after_night=nc
        )
    }


async def announce_nam10_lawyer_defense_skip(
    bot: Bot, game: Game, target_uid: int
) -> bool:
    """Public buttonless announcement when valid Lawyer protection skips a
    daytime defence (Namayande-10 no-host).

    Text: ``⚖️ [name] به دلیل حمایت معتبر وکیل در شب گذشته، وارد
    دفاعیه نمی‌شود.`` — delivered to every currently living player
    (including the protected player; synthetic seats mirror to the
    registered Observer). It never reveals the Lawyer's identity or any
    other private night action. Idempotent per (player, day): retries,
    callback replays and restarts never duplicate it.
    """
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    if target_uid not in _nam10_day_lawyer_protected_uids(game):
        return False
    # The player must be among THIS day's confirmed defence candidates
    # and actually excluded because of the protection; protection that
    # was never exercised on a candidate stays silent (Room 17: the
    # announcement fired for a player who was not selected).
    if target_uid not in day_vote_defender_uids(game):
        return False
    day = max(1, int(game.nmnd_narrator_host_day or 1))
    announced = getattr(game, "nam10_lawyer_defense_announced", None)
    if not isinstance(announced, dict):
        announced = {}
        game.nam10_lawyer_defense_announced = announced
    key = str(int(target_uid))
    if announced.get(key) == day:
        return False
    announced[key] = day
    p = game.players.get(target_uid)
    name = html.escape(
        manager.format_player_tag(p) if p is not None else str(target_uid)
    )
    text = (
        f"⚖️ {name} به دلیل حمایت معتبر وکیل در شب گذشته، "
        "وارد دفاعیه نمی‌شود."
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "nam10.lawyer_defense_skip_announced",
            target_uid=target_uid,
            host_day=day,
        )
    except Exception:
        pass
    await broadcast_to_alive_players(
        bot,
        game,
        text,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    return True


def _day1_defense_pool_players(game: Game) -> list[Player]:
    pool: list[Player] = []
    for uid in sorted(day_vote_defender_uids(game)):
        p = game.players.get(uid)
        if p is not None and p.is_alive:
            pool.append(p)
    return pool

async def _no_host_day1_defense_outcome_no_exit(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.nam10_day1_defense_phase not in ("outcome", "pick_elim"):
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act="no_exit",
                actor_uid=actor_uid,
                assistant_uid=assistant_uid,
                source="dispatch",
                outcome="rejected",
                reject_reason="wrong_phase",
            )
        except Exception:
            pass
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    ui_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    game.nam10_day1_pending_elim_uid = None
    await callback.answer("ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ خروجی نداشتیم — وارد شب یک می‌شویم.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    broadcast = build_no_host_day1_defense_no_exit_broadcast_html(
        game, assistant_uid
    )
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    from bot.russian_mafia_flow import apply_russian_day_result

    if await apply_russian_day_result(
        bot, game, eliminated_uid=None, reason="no_exit"
    ):
        return
    nam10_day1_no_exit_enter_night(game)
    await on_no_host_entered_night1(bot, game, manager)
    try:
        from bot.game_audit_log import (
            log_event,
            log_no_host_day1_defense_callback,
        )

        log_no_host_day1_defense_callback(
            game,
            act="no_exit",
            actor_uid=actor_uid,
            assistant_uid=assistant_uid,
            source="dispatch",
            outcome="completed",
        )
        log_event(
            game,
            "no_host.day1_defense_outcome",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
            had_exit=False,
        )
    except Exception:
        pass

def build_no_host_day1_defense_no_exit_broadcast_html(
    game: Game, assistant_uid: int
) -> str:
    from bot.nam10.no_host_day_vote import (
        nam10_day_ordinal_fa,
        nam10_upcoming_night_ordinal_fa,
    )

    ap = game.players.get(assistant_uid)
    tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    day_w = nam10_day_ordinal_fa(game.nmnd_narrator_host_day)
    night_w = nam10_upcoming_night_ordinal_fa(game)
    return (
        f"🌙 <b>پایان روز {day_w}</b>\n\n"
        f"<b>{tag}</b> تأیید کرد که پس از دفاعیه، "
        "هیچ بازیکنی با اجماع رأی از بازی خارج نشد؛ "
        f"بنابراین وارد فاز شب {night_w} می‌شویم.\n\n"
        "😴 لطفاً برای چند لحظه بخوابید تا گروه مافیا بیدار شده و "
        "درباره تصمیم امشب خود مشورت کند.\n\n"
        f"پس از پایان مشورت و با تأیید <b>{tag}</b>، انتخاب تمام بازیکنان "
        "از طریق پیام خصوصی دریافت و ثبت خواهد شد.\n\n"
        "📩 همه بازیکنان باید یکی از گزینه‌هایی را که ربات برایشان "
        "ارسال می‌کند انتخاب کنند.\n\n"
        f"✅ وقتی همه بازیکنان انتخاب خود را انجام دادند، "
        f"<b>{tag}</b> می‌تواند تأیید کند تا نتیجه شب {night_w} برای همه ارسال شود."
    )

async def _no_host_day1_defense_outcome_has_exit(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.nam10_day1_defense_phase != "outcome":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    pool = _day1_defense_pool_players(game)
    if not pool:
        await callback.answer(
            "لیست دفاعیه خالی است؛ ابتدا بازیکنان دفاعیه را ثبت کنید.",
            show_alert=True,
        )
        return
    ui_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        game.mirror_action_claims[ui_key] = actor_uid
    game.nam10_day1_defense_phase = "pick_elim"
    game.nam10_day1_pending_elim_uid = None
    await callback.answer("بازیکن خارج‌شده را انتخاب کنید.")
    await send_no_host_day1_pick_elim_panel(bot, game)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_pick_elim_opened",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass

async def send_no_host_day1_pick_elim_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    text = build_no_host_day1_pick_elim_html(game)
    kb = _no_host_day1_pick_elim_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    pick_key = _no_host_day1_pick_elim_ui_key(game, assistant_uid)
    confirm_key = _no_host_day1_confirm_elim_ui_key(game, assistant_uid)
    outcome_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    promoted = False
    for from_key in (pick_key, confirm_key, outcome_key):
        if await promote_mirror_prompt_to_panel(
            bot,
            game,
            from_ui_key=from_key,
            to_ui_key=pick_key,
            assistant_uid=assistant_uid,
            text=text,
            reply_markup=kb,
        ):
            promoted = True
            break
    if not promoted:
        await register_mirror_prompt_pair(
            bot,
            game,
            assistant_uid,
            pick_key,
            text,
            kb,
            send_observer=nam10_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )

def build_no_host_day1_pick_elim_html(game: Game) -> str:
    n = len(_day1_defense_pool_players(game))
    return (
        "💀 <b>خروجی دفاعیه — انتخاب بازیکن خارج‌شده</b>\n\n"
        f"📋 از بین <b>{n}</b> بازیکن دفاعیه، کسی را که با اجماع رأی "
        "از بازی خارج شد انتخاب کنید."
    )

def _no_host_day1_pick_elim_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    protected = _nam10_day_lawyer_protected_uids(game)
    pending_elim = game.nam10_day1_pending_elim_uid
    for p in _day1_defense_pool_players(game):
        if p.user_id in protected:
            continue
        name = html.escape(manager.format_player_tag(p)[:28])
        if mirror:
            cb = PlayerMirrorCb(
                code=game.room_code, act="d1el", as_uid=assistant_uid, tid=p.user_id
            ).pack()
        else:
            cb = NoHostDay1DefenseCb(
                code=game.room_code, act="d1el", tid=p.user_id
            ).pack()
        row.append(
            InlineKeyboardButton(
                text=name,
                callback_data=cb,
                style=(
                    "danger" if p.user_id == pending_elim else "primary"
                ),
            )
        )
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if mirror:
        back_cb = PlayerMirrorCb(
            code=game.room_code, act="d1d0", as_uid=assistant_uid
        ).pack()
    else:
        back_cb = NoHostDay1DefenseCb(code=game.room_code, act="no_exit").pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ خروجی نداشتیم",
                callback_data=back_cb,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _no_host_day1_defense_no_votes(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.nam10_day1_defense_phase != "pick":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    ui_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    set_day_vote_pick_uids(game, set())
    set_day_vote_defender_uids(game, set())
    await callback.answer("ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ پیام پایان روز برای بازیکنان ارسال شد؛ وارد شب یک می‌شویم.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    broadcast = build_no_host_day1_no_defense_votes_broadcast_html(
        game, assistant_uid
    )
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    from bot.russian_mafia_flow import apply_russian_day_result

    if await apply_russian_day_result(
        bot, game, eliminated_uid=None, reason="none"
    ):
        return
    nam10_day1_defense_no_votes_enter_night(game)
    await on_no_host_entered_night1(bot, game, manager)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_no_votes",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass

def build_no_host_day1_no_defense_votes_broadcast_html(
    game: Game, assistant_uid: int
) -> str:
    from bot.nam10.no_host_day_vote import (
        nam10_day_ordinal_fa,
        nam10_upcoming_night_ordinal_fa,
    )

    ap = game.players.get(assistant_uid)
    tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    day_w = nam10_day_ordinal_fa(game.nmnd_narrator_host_day)
    night_w = nam10_upcoming_night_ordinal_fa(game)
    return (
        f"🌙 <b>پایان روز {day_w}</b>\n\n"
        f"<b>{tag}</b> تأیید کرد که در پایان روز و پس از رأی‌گیری، "
        "هیچ بازیکنی آرای لازم برای دفاعیه را کسب نکرده است؛ "
        f"بنابراین وارد فاز شب {night_w} می‌شویم.\n\n"
        "😴 لطفاً برای چند لحظه بخوابید تا گروه مافیا بیدار شده و "
        "درباره تصمیم امشب خود مشورت کند.\n\n"
        f"پس از پایان مشورت و با تأیید <b>{tag}</b>، انتخاب تمام بازیکنان "
        "از طریق پیام خصوصی دریافت و ثبت خواهد شد.\n\n"
        "📩 همه بازیکنان باید یکی از گزینه‌هایی را که ربات برایشان "
        "ارسال می‌کند انتخاب کنند.\n\n"
        f"✅ وقتی همه بازیکنان انتخاب خود را انجام دادند، "
        f"<b>{tag}</b> می‌تواند تأیید کند تا نتیجه شب {night_w} برای همه ارسال شود."
    )

async def _no_host_day1_defense_confirm_elim_yes(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.nam10_day1_defense_phase != "confirm_elim":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    target_uid = game.nam10_day1_pending_elim_uid
    if target_uid is None or target_uid not in game.players:
        await callback.answer("بازیکن انتخاب نشده.", show_alert=True)
        return
    if not game.players[target_uid].is_alive:
        await callback.answer("این بازیکن قبلاً خارج شده است.", show_alert=True)
        return
    if target_uid in _nam10_day_lawyer_protected_uids(game):
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act="elim_yes",
                actor_uid=actor_uid,
                assistant_uid=assistant_uid,
                source="dispatch",
                target_uid=target_uid,
                outcome="rejected",
                reject_reason="lawyer_protected",
            )
        except Exception:
            pass
        await callback.answer(
            "⚖️ "
            + html.escape(
                manager.format_player_tag(game.players.get(target_uid))
            )
            + " به دلیل حمایت معتبر وکیل در شب گذشته، وارد دفاعیه نمی‌شود.",
            show_alert=True,
        )
        await announce_nam10_lawyer_defense_skip(bot, game, target_uid)
        return

    ui_key = _no_host_day1_confirm_elim_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    from bot.russian_mafia_flow import finish_russian_confirmed_elimination

    if await finish_russian_confirmed_elimination(
        callback, bot, game, assistant_uid, target_uid
    ):
        return
    from bot.nam10.nmnd_narrator import hunter_chain_confirm_alert_text

    chain_alert = hunter_chain_confirm_alert_text(
        game, manager, target_uid, public=True
    )
    eliminate_player_from_game(
        game, manager, target_uid, elim_source="day_vote"
    )
    armor_saved = game.players[target_uid].is_alive
    if not armor_saved:
        from bot.room_mode import is_mason_scenario

        if is_mason_scenario(game):
            from bot.mason_day_ability import (
                dismiss_mason_day_ability_panel_for_eliminated,
            )

            await dismiss_mason_day_ability_panel_for_eliminated(
                bot, game, target_uid
            )
    if not armor_saved:
        await flush_elimination_notifications(bot, game)
    if armor_saved:
        await callback.answer("زره مصرف شد؛ بازیکن در بازی ماند.", show_alert=True)
    elif chain_alert:
        await callback.answer(chain_alert, show_alert=True)
    else:
        await callback.answer("حذف ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            suffix = (
                "\n\n<i>✅ زره مصرف شد؛ بازیکن در بازی ماند.</i>"
                if armor_saved
                else "\n\n<i>✅ حذف بازیکن تأیید و ثبت شد.</i>"
            )
            await callback.message.edit_text(
                base + suffix,
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    skip_mid = (
        frozenset({callback.message.message_id})
        if callback.message
        else frozenset()
    )
    await close_mirror_prompt_keyboards(
        bot,
        game,
        _no_host_day1_defense_outcome_ui_key(game, assistant_uid),
        skip_message_ids=skip_mid,
    )
    await close_mirror_prompt_keyboards(
        bot,
        game,
        _no_host_day1_pick_elim_ui_key(game, assistant_uid),
        skip_message_ids=skip_mid,
    )
    if armor_saved:
        from bot.roles.mozakere_armored import day_vote_armor_consumed_announce_line

        broadcast = (
            "<b>📢 اعلام رأی روز</b>\n\n"
            f"{html.escape(day_vote_armor_consumed_announce_line(game, manager, target_uid))}"
        )
    else:
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
    from bot.nam10.no_host_mafia_win import nam10_maybe_end_on_faction_win

    if not armor_saved and await nam10_maybe_end_on_faction_win(
        bot,
        game,
        manager,
        elim_source="day_vote",
        elim_uid=target_uid,
    ):
        return
    from bot.nam10.rebel_day import dispatch_nam10_rebel_activation

    try:
        await dispatch_nam10_rebel_activation(bot, game)
    except Exception:
        logger.exception(
            "rebel daytime activation failed room=%s", game.room_code
        )
    from bot.nam10.no_host_handoff import offer_handoff_day1_after_elim

    if offer_handoff_day1_after_elim(game):
        await push_host_step(bot, game, manager)
    else:
        nam10_day1_after_elim_enter_night(game)
        await on_no_host_entered_night1(bot, game, manager)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_elim_confirmed",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
            eliminated_uid=target_uid,
            host_day=game.nmnd_narrator_host_day,
            night_count=game.nmnd_narrator_night_count,
        )
    except Exception:
        pass

def build_no_host_day1_elim_broadcast_html(
    game: Game, assistant_uid: int, eliminated_uid: int
) -> str:
    from bot.nam10.nmnd_narrator import hunter_vote_elim_names_html_block

    ap = game.players.get(assistant_uid)
    assistant_tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    from bot.nam10.no_host_day_vote import (
        nam10_day_ordinal_fa,
        nam10_upcoming_night_ordinal_fa,
    )

    names_block = hunter_vote_elim_names_html_block(
        game, manager, eliminated_uid
    )
    day_w = nam10_day_ordinal_fa(game.nmnd_narrator_host_day)
    night_w = nam10_upcoming_night_ordinal_fa(game)
    elim_intro = (
        "بازیکنان زیر با اجماع رأی‌گیری از بازی خارج شدند"
        if "\n" in names_block
        else "بازیکن زیر با اجماع رأی‌گیری از بازی خارج شد"
    )
    return (
        f"🌙 <b>پایان روز {day_w}</b>\n\n"
        f"طبق تأیید <b>{assistant_tag}</b>، {elim_intro}:\n\n"
        f"{names_block}\n\n"
        "🌑 فاز شب آغاز می‌شود.\n\n"
        "😴 لطفاً برای چند لحظه بخوابید تا گروه مافیا بیدار شده و "
        "درباره تصمیم امشب خود مشورت کند.\n\n"
        f"پس از پایان مشورت و با تأیید <b>{assistant_tag}</b>، انتخاب تمام "
        "بازیکنان از طریق پیام خصوصی دریافت و ثبت خواهد شد.\n\n"
        "📩 همه بازیکنان باید یکی از گزینه‌هایی را که ربات برایشان "
        "ارسال می‌کند انتخاب کنند.\n\n"
        f"✅ وقتی همه بازیکنان انتخاب خود را انجام دادند، "
        f"<b>{assistant_tag}</b> می‌تواند تأیید کند تا نتیجه شب {night_w} "
        "برای همه ارسال شود."
    )

async def _no_host_day1_defense_confirm_elim_no(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.nam10_day1_defense_phase != "confirm_elim":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    game.nam10_day1_pending_elim_uid = None
    game.nam10_day1_defense_phase = "outcome"
    await callback.answer("بازگشت به انتخاب.")
    await send_no_host_day1_defense_outcome_panel(bot, game)

async def send_no_host_day1_defense_outcome_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    text = build_no_host_day1_defense_outcome_html(game)
    kb = _no_host_day1_defense_outcome_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    ui_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_observer=nam10_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )

def build_no_host_day1_defense_outcome_html(game: Game) -> str:
    if is_mason_scenario(game):
        from bot.mason_day_defense import build_mason_defense_candidates_announcement_html

        return build_mason_defense_candidates_announcement_html(game)
    uids = sorted(day_vote_defender_uids(game))
    protected = _nam10_day_lawyer_protected_uids(game)
    lines: list[str] = []
    idx = 0
    for uid in uids:
        p = game.players.get(uid)
        if not p:
            continue
        idx += 1
        tag = html.escape(manager.format_player_tag(p))
        prev = day_vote_participation_count(game, uid)
        lines.append(
            f"{_fa_digits(idx)}. 👤 {tag} 🗳️ سابقه حضور در رأی‌گیری‌های قبلی: {_fa_digits(prev)}"
        )
        if uid in protected:
            lines.append(
                f"🛡️ {tag} به دلیل حمایت معتبر وکیل در شب گذشته، "
                "وارد دفاعیه نمی‌شود."
            )
    body = "\n".join(lines) if lines else "<i>هیچ بازیکنی انتخاب نشده است.</i>"
    return (
        "⚖️ <b>بررسی بازیکنان انتخاب‌شده برای دفاعیه</b>\n\n"
        "بازیکنان زیر برای دفاعیه انتخاب شده‌اند:\n\n"
        f"{body}"
    )

def _no_host_day1_defense_outcome_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    protected = _nam10_day_lawyer_protected_uids(game)
    pending = game.nam10_day1_pending_elim_uid
    for p in _day1_defense_pool_players(game):
        if p.user_id in protected:
            # Lawyer-protected this day: no elimination option; the
            # candidate itself still keeps the seat.
            continue
        name = html.escape(manager.format_player_tag(p)[:28])
        if mirror:
            cb = PlayerMirrorCb(
                code=game.room_code,
                act="d1el",
                as_uid=assistant_uid,
                tid=p.user_id,
            ).pack()
        else:
            cb = NoHostDay1DefenseCb(
                code=game.room_code, act="d1el", tid=p.user_id
            ).pack()
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"خروج ({name})",
                    callback_data=cb,
                    style="danger" if p.user_id == pending else "primary",
                )
            ]
        )
    if mirror:
        no_cb = PlayerMirrorCb(
            code=game.room_code, act="d1d0", as_uid=assistant_uid
        ).pack()
    else:
        no_cb = NoHostDay1DefenseCb(
            code=game.room_code, act="no_exit"
        ).pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="خروجی نداشتیم. شب کن",
                callback_data=no_cb,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _no_host_day1_defense_confirm(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.nam10_day1_defense_phase != "pick":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    ui_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    picked = {
        u
        for u in day_vote_pick_uids(game)
        if u in game.players and game.players[u].is_alive
    }
    set_day_vote_defender_uids(game, picked)
    set_day_vote_pick_uids(game, set())
    from bot.russian_mafia_flow import note_russian_defense_candidates

    note_russian_defense_candidates(game, picked)
    game.nam10_day1_defense_phase = "outcome"
    from bot.nam10.rebel_day import close_nam10_rebel_window

    try:
        await close_nam10_rebel_window(bot, game)
    except Exception:
        logger.exception(
            "rebel window close failed room=%s", game.room_code
        )
    protected_now = [
        u
        for u in sorted(_nam10_day_lawyer_protected_uids(game))
        if (
            u in picked
            and game.players.get(u) is not None
            and game.players[u].is_alive
        )
    ]
    if protected_now:
        names = " — ".join(
            html.escape(manager.format_player_tag(game.players[u]))
            for u in protected_now
        )
        await callback.answer(
            "ثبت شد.\n\n⚖️ " + names
            + " به دلیل حمایت معتبر وکیل در شب گذشته، "
            "وارد دفاعیه نمی‌شود.",
            show_alert=True,
        )
    else:
        await callback.answer("ثبت شد.")
    pick_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    outcome_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    text = build_no_host_day1_defense_outcome_html(game)
    kb = _no_host_day1_defense_outcome_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    promoted = await promote_mirror_prompt_to_panel(
        bot,
        game,
        from_ui_key=pick_key,
        to_ui_key=outcome_key,
        assistant_uid=assistant_uid,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    if not promoted:
        try:
            if callback.message:
                base = callback.message.html_text or callback.message.text or ""
                await callback.message.edit_text(
                    base + "\n\n<i>✅ انتخاب‌ها ثبت شد.</i>",
                    parse_mode="HTML",
                    reply_markup=None,
                )
        except Exception:
            pass
        await send_no_host_day1_defense_outcome_panel(bot, game)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_confirmed",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
            defender_uids=sorted(picked),
        )
    except Exception:
        pass
    # Valid Lawyer protection skipped a defence: tell every living
    # player once (helper already received the decision popup).
    for _uid in sorted(set(_nam10_day_lawyer_protected_uids(game)) & picked):
        _p = game.players.get(_uid)
        if _p is None or not _p.is_alive:
            continue
        try:
            await announce_nam10_lawyer_defense_skip(bot, game, _uid)
        except Exception:
            logger.exception(
                "lawyer defense-skip announcement failed room=%s uid=%s",
                game.room_code,
                _uid,
            )

def _no_host_day1_defense_actor_may_act(
    game: Game, actor_uid: int, assistant_uid: int
) -> bool:
    if actor_uid == assistant_uid:
        return True
    return (
        game_observer_mirror_active(game)
        and game.observer_user_id == actor_uid
    )

async def send_no_host_day1_defense_pick_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or not game.nam10_day1_defense_active:
        return
    text = build_no_host_day1_defense_pick_html(game)
    kb = day1_defense_pick_keyboard_for(game, assistant_uid)
    pick_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    from bot.observer_delivery import publish_mirror_prompt_pair

    await publish_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        pick_key,
        text,
        kb,
        send_observer=nam10_observer_registered(game),
        observer_same_text=False,
        fresh_observer_copy=True,
        parse_mode="HTML",
    )

async def _process_no_host_day1_show_vote_panel(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.nam10_day1_vote_resolved:
        await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
        return
    if getattr(game, "nmnd_night2_rebel_assassin_used", False) and getattr(
        game, "nam10_assassin_bypass_day", None
    ) == max(1, int(game.nmnd_narrator_host_day or 1)):
        # A committed daytime assassination bypassed today's defence.
        await callback.answer(
            "امروز مرحله دفاعیه برگزار نمی‌شود.", show_alert=True
        )
        return
    from bot.nam10.no_host_day_vote import nam10_day_vote_choice_ui_key

    ui_key = nam10_day_vote_choice_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        err = try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid)
        if err == "already_claimed":
            await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
            return
        if err not in (None, "dup_self") and await _answer_mirror_claim(
            callback, err
        ):
            return
    await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    await callback.answer("پنل رأی‌گیری فعال شد.")
    begin_no_host_day1_defense_pick(game)
    text = build_no_host_day1_defense_pick_html(game)
    kb = day1_defense_pick_keyboard_for(game, assistant_uid)
    pick_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    from bot.observer_delivery import promote_mirror_prompt_to_panel

    promoted = await promote_mirror_prompt_to_panel(
        bot,
        game,
        from_ui_key=ui_key,
        to_ui_key=pick_key,
        assistant_uid=assistant_uid,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    if not promoted:
        await send_no_host_day1_defense_pick_panel(bot, game)
    game.nam10_day1_vote_resolved = True
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_vote_panel_opened",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass

async def _process_no_host_day1_skip_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if getattr(game, "nmnd_night2_rebel_assassin_used", False) and getattr(
        game, "nam10_assassin_bypass_day", None
    ) == max(1, int(game.nmnd_narrator_host_day or 1)):
        # A committed daytime assassination bypassed today's defence;
        # the explicit next-night button is the only entry.
        await callback.answer(
            "برای آغاز شب بعدی از دکمه «🌙 شروع شب بعدی» استفاده کنید.",
            show_alert=True,
        )
        return
    if game.nam10_day1_vote_resolved:
        await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
        return
    from bot.nam10.no_host_day_vote import nam10_day_vote_choice_ui_key

    ui_key = nam10_day_vote_choice_ui_key(game, assistant_uid)
    await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    await callback.answer("ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ به فاز شب می‌رویم (بدون رأی روز).</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    broadcast = build_no_host_day1_skip_vote_broadcast_html(game, assistant_uid)
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    nam10_skip_day1_vote_enter_night(game)
    await on_no_host_entered_night1(bot, game, manager)
    game.nam10_day1_vote_resolved = True
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_vote_skipped",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass

def build_no_host_day1_skip_vote_broadcast_html(
    game: Game, assistant_uid: int
) -> str:
    ap = game.players.get(assistant_uid)
    tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    return (
        f"🌙 <b>{tag}</b> تأیید کرد که رأی‌گیری در این روز لازم نیست.\n\n"
        "😴 لطفاً همه بازیکنان بخوابند تا گروه مافیا بتوانند با هم مشورت کنند."
    )

async def send_no_host_day1_vote_prompt(bot: Bot, game: Game) -> None:
    from bot.nam10.no_host_day_vote import send_no_host_day_vote_prompt

    await send_no_host_day_vote_prompt(bot, game)

def day1_vote_choice_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    from bot.nam10.no_host_day_vote import day_vote_choice_keyboard_for as _kb

    return _kb(game, assistant_uid)

async def _execute_no_host_intro_night_start(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if callback.message is None:
        return
    game.nam10_intro_night_started = True
    from bot.nam10.nmnd_narrator import _mark_day_start_alive_snapshot

    game.nmnd_narrator_host_day = max(1, game.nmnd_narrator_host_day)
    _mark_day_start_alive_snapshot(game)
    ui_key = mirror_ui_claim_key(
        game.room_code, "intro_night_start", assistant_uid
    )
    await apply_mirror_claim_winner(
        bot, game, ui_key, actor_uid, assistant_uid
    )
    await callback.answer("شب معارفه شروع شد.")
    try:
        base = callback.message.html_text or callback.message.text or ""
        await callback.message.edit_text(
            base + "\n\n<i>✅ شب معارفه آغاز شد.</i>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    if is_mason_scenario(game):
        from bot.mason_intro_flow import mason_after_intro_night_started

        await mason_after_intro_night_started(bot, game, manager)
    else:
        await deliver_no_host_intro_night_started_messages(bot, game)
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.intro_night_started",
                assistant_uid=assistant_uid,
                observer_uid=game.observer_user_id,
                observer_prompt_status=game.observer_prompt_status,
                observer_mirror_active=nam10_observer_registered(game),
                per_seat_broadcast_targets=len(game.players) - 1,
            )
        except Exception:
            pass
        await nam10_run_day1_end_vote_flow(bot, game)
        return
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.intro_night_started",
            assistant_uid=assistant_uid,
            observer_uid=game.observer_user_id,
            observer_prompt_status=game.observer_prompt_status,
            observer_mirror_active=nam10_observer_registered(game),
            per_seat_broadcast_targets=len(game.players) - 1,
        )
    except Exception:
        pass

async def deliver_no_host_intro_night_started_messages(
    bot: Bot, game: Game
) -> None:
    """پس از تأیید شب معارفه — پیام جدا برای شهروندان زنده و تیم مافیا."""
    civilian_text = build_no_host_intro_night_civilian_html()
    mafia_text = build_no_host_intro_night_mafia_dm_html(game)
    for uid, p in game.players.items():
        if not p.is_alive:
            continue
        if p.role and is_mafia_team(p.role):
            text = mafia_text
        else:
            text = civilian_text
        if is_synthetic_player_uid(uid):
            # Synthetic Mafia seats (the independent NATO agent in 12/13
            # included) have no Telegram chat: their teammate roster is
            # mirrored to the registered Observer instead, following the
            # same per-seat policy as every other synthetic private
            # panel. Idempotent; never marked delivered when the send
            # failed. Synthetic civilians keep the existing handling
            # (the shared civilian text carries no per-seat information).
            if (
                text is not mafia_text
                or not nam10_observer_registered(game)
                or uid in game.nmnd_intro_night_delivered_uids
            ):
                continue
            from bot.observer_delivery import observer_player_copy_prefix

            sent = await safe_send_message(
                bot,
                game.observer_user_id,
                observer_player_copy_prefix(game, uid) + text,
                parse_mode="HTML",
            )
            if sent:
                game.nmnd_intro_night_delivered_uids.add(uid)
            continue
        await safe_send_message(bot, uid, text, parse_mode="HTML")
    if nam10_observer_registered(game):
        obs_id = game.observer_user_id
        if obs_id is not None:
            await safe_send_message(
                bot, obs_id, civilian_text, parse_mode="HTML"
            )

def build_no_host_intro_night_mafia_dm_html(game: Game) -> str:
    lines = [
        "🌙 <b>شب معارفه آغاز شد.</b>",
        "شما عضو تیم مافیا هستید. اعضای تیم شما عبارت‌اند از:",
        "📋 <b>اعضای تیم مافیا:</b>",
    ]
    for p in _no_host_alive_mafia_for_intro(game):
        tag = html.escape(manager.format_player_tag(p))
        role_txt = html.escape(scenario_role_label_fa(game, p.role))
        lines.append(f"• {tag} — <b>{role_txt}</b>")
    return "\n".join(lines)

def _no_host_alive_mafia_for_intro(game: Game) -> list[Player]:
    mafs = [
        p
        for p in game.players.values()
        if p.is_alive and p.role and is_mafia_team(p.role)
    ]

    def _sort_key(p: Player) -> tuple[int, int, int]:
        if p.role == Role.MAFIA_BOSS:
            return (0, p.seat if p.seat is not None else 999, p.user_id)
        return (1, p.seat if p.seat is not None else 999, p.user_id)

    mafs.sort(key=_sort_key)
    return mafs

def build_no_host_intro_night_civilian_html() -> str:
    return (
        "🌙 <b>شب معارفه آغاز شد</b>\n"
        "اعضای تیم مافیا از طریق پیام ارسالی، هم‌تیمی‌های خود را شناسایی کردند.\n"
        "😴 لطفاً چشم‌های خود را ببندید و بخوابید تا اعضای تیم مافیا "
        "فرصت بیشتری برای آشنایی با یکدیگر داشته باشند."
    )

async def _handle_no_host_intro_night_action(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    act: str,
) -> None:
    if callback.message is None:
        return
    if not nam10_bot_assistant_flow_enabled(game):
        await callback.answer("این مرحله برای این اتاق نیست.", show_alert=True)
        return
    if game.bot_assistant_user_id != assistant_uid:
        await callback.answer("فقط کمک‌کننده ربات.", show_alert=True)
        return
    if game.nam10_intro_night_started:
        await callback.answer("شب معارفه قبلاً شروع شده است.", show_alert=True)
        return
    if act == "go":
        await callback.answer()
        await _refresh_intro_night_prompt_panel(
            bot,
            game,
            assistant_uid,
            phase="confirm",
            callback_message=callback.message,
        )
        return
    if act == "back":
        await callback.answer()
        await _refresh_intro_night_prompt_panel(
            bot,
            game,
            assistant_uid,
            phase="start",
            callback_message=callback.message,
        )
        return
    if act != "ok":
        await callback.answer("نامعتبر.", show_alert=True)
        return
    await _execute_no_host_intro_night_start(
        callback, bot, game, assistant_uid, actor_uid
    )

async def _refresh_intro_night_prompt_panel(
    bot: Bot,
    game: Game,
    assistant_uid: int,
    *,
    phase: str,
    callback_message: Message | None = None,
) -> None:
    if phase == "confirm":
        text = build_no_host_intro_night_confirm_html()
        kb = intro_night_confirm_keyboard_for(game, assistant_uid)
    else:
        text = build_no_host_intro_night_start_html()
        kb = intro_night_start_keyboard_for(game, assistant_uid)
    ui_key = mirror_ui_claim_key(
        game.room_code, "intro_night_start", assistant_uid
    )
    entry = game.mirror_prompt_messages.get(ui_key) or {}
    if entry.get("player") or entry.get("observer"):
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            text,
            kb,
            assistant_uid=assistant_uid,
            parse_mode="HTML",
        )
    elif callback_message is not None:
        try:
            await callback_message.edit_text(
                text, parse_mode="HTML", reply_markup=kb
            )
        except TelegramBadRequest:
            pass

def intro_night_confirm_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_intro_night_confirm_keyboard(game, assistant_uid)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ ادامه",
                    callback_data=NoHostIntroNightStart(
                        code=game.room_code, act="ok"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=NoHostIntroNightStart(
                        code=game.room_code, act="back"
                    ).pack(),
                ),
            ],
        ]
    )

def build_no_host_intro_night_confirm_html() -> str:
    return (
        "🌙 <b>تأیید شروع شب معارفه</b>\n\n"
        "شما در آستانه شروع شب معارفه هستید.\n\n"
        "📨 با ادامه این فرایند، پیامی حاوی معرفی تمامی اعضای تیم مافیا "
        "برای اعضای این تیم ارسال خواهد شد.\n\n"
        "❓ آیا از ادامه این عملیات اطمینان دارید؟"
    )

def build_bazpors_game_end_broadcast_html(game: Game, winner: str) -> str:
    """پیام پایان بازی برای بازیکنان — برنده، نقش‌ها، اتفاقات شب و روز."""
    if winner not in ("mafia", "citizen"):
        winner = "citizen"
    snap = build_post_session_recap_snapshot(game, winner)
    rows_raw = snap.get("rows")
    rows: list[dict[str, object]] = rows_raw if isinstance(rows_raw, list) else []
    scenario_name = str(snap.get("scenario_name") or game.scenario_name or "namayande")
    roster_block = "\n".join(
        _build_session_recap_roster_lines(
            rows,
            scenario_name=scenario_name,
            nam10=True,
        )
    )
    timeline_html = _build_bazpors_timeline_html(snap)
    parts: list[str] = []
    if _bazpors_auto_host_final_report_header(game):
        parts.extend(
            [
                build_game_final_report_header_html(
                    game.room_code, game.scenario_name, game.max_players
                ),
                "",
            ]
        )
    parts.extend(
        [
            _build_bazpors_game_end_winner_html(game, winner),
            "",
            "────────────",
            "",
            "📋 <b>بازیکنان و نقش‌ها</b>",
            roster_block,
        ]
    )
    if timeline_html:
        parts.extend(["", "────────────", "", timeline_html])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Fork callback drivers (hand-written fork seam; mirrors the shared aiogram
# callbacks while reading/writing nam10_* fork state only).
# ---------------------------------------------------------------------------


async def dispatch_nam10_day1_defense_cb(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    callback_data,
) -> None:
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
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
    if not game.nam10_day1_defense_active:
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


async def dispatch_nam10_intro_night_cb(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    callback_data,
) -> None:
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
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


async def close_nam10_defense_for_assassination(bot, game: Game) -> None:
    """Invalidate today's defence workflow after a committed daytime
    Rebel assassination: every live defence keyboard is stripped and all
    further defence callbacks are rejected for the rest of the day
    (historical actions and audits stay intact)."""
    day = max(1, int(game.nmnd_narrator_host_day or 1))
    game.nam10_day1_defense_active = False
    game.nam10_day1_defense_phase = "bypassed"
    game.nam10_day1_pending_elim_uid = None
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    keys = [
        _no_host_day1_defense_pick_ui_key(game, assistant_uid),
        _no_host_day1_defense_outcome_ui_key(game, assistant_uid),
        _no_host_day1_pick_elim_ui_key(game, assistant_uid),
        _no_host_day1_confirm_elim_ui_key(game, assistant_uid),
    ]
    try:
        from bot.nam10.no_host_day_vote import nam10_day_vote_choice_ui_key

        keys.append(nam10_day_vote_choice_ui_key(game, assistant_uid))
    except Exception:
        pass
    from bot.observer_delivery import close_mirror_prompt_keyboards

    for key in keys:
        try:
            await close_mirror_prompt_keyboards(bot, game, key)
        except Exception:
            logger.exception(
                "assassination defence-panel close failed room=%s key=%s",
                game.room_code,
                key,
            )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_bypassed_by_assassination",
            host_day=day,
        )
    except Exception:
        pass
