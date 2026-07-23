"""پنل‌های روزانهٔ آپاچی و کابوی — فقط سناریوی ماسون."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import eliminate_player_from_game
from bot.game import is_mafia_team, is_synthetic_player_uid
from bot.models import Game, Role
from bot.no_host_role_pick_common import (
    actor_may_act_on_role_panel,
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
    sync_role_mirror_panel,
)
from bot.observer_delivery import (
    broadcast_to_alive_players,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
)
from bot.room_mode import is_mason_scenario
from bot.roles import mason_apache as ms_ap
from bot.roles import mason_cowboy as ms_cw
from bot.roles.mason_guardian import guardian_blocks_apache

if TYPE_CHECKING:
    from bot.game import GameManager


def _log_mason_day_timeline_event(game: Game, event: str, **fields: object) -> None:
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            event,
            host_day=game.bazpors_narrator_host_day,
            night_count=game.bazpors_narrator_night_count,
            **fields,
        )
    except Exception:
        pass

MASON_APACHE_PICK_ACT = "map"
MASON_APACHE_CONFIRM_ACT = "mac"
MASON_APACHE_BACK_ACT = "mab"
MASON_COWBOY_PICK_ACT = "mcp"
MASON_COWBOY_CONFIRM_ACT = "mcc"
MASON_COWBOY_BACK_ACT = "mcb"
MASON_DAY_GUN_PICK_ACT = "mdgp"
MASON_DAY_GUN_CONFIRM_ACT = "mdgc"
MASON_DAY_GUN_BACK_ACT = "mdgb"
MASON_DAY_DEAD_PLAYER_ALERT_FA = "این بازیکن دیگر در بازی نیست."
MASON_DAY_PANEL_INACTIVE_FA = "این پنل دیگر فعال نیست."
MASON_DAY_PANEL_INACTIVE_ALERT_FA = "این پنل دیگر فعال نیست."
MASON_DAY_ABILITY_USED_PANEL_FA = "✅ عملیات شما ثبت شد."
MASON_DAY_ABILITY_REVOKED_PANEL_FA = "⛔ این قابلیت روزانه دیگر فعال نیست."
MASON_DAY_GUN_EXPIRED_PANEL_FA = "مهلت استفاده از تفنگ به پایان رسید."
MASON_DAY_GUN_EXPIRED_ALERT_FA = "مهلت استفاده از تفنگ به پایان رسیده است."


def _apache_ui_key(game: Game, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "mason_apache_day", uid)


def _cowboy_ui_key(game: Game, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "mason_cowboy_day", uid)


def _day_gun_ui_key(game: Game, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "mason_day_gun", uid)


def mason_day_ability_act_active(game: Game, act: str) -> bool:
    if not is_mason_scenario(game):
        return False
    return act in (
        MASON_APACHE_PICK_ACT,
        MASON_APACHE_CONFIRM_ACT,
        MASON_APACHE_BACK_ACT,
        MASON_COWBOY_PICK_ACT,
        MASON_COWBOY_CONFIRM_ACT,
        MASON_COWBOY_BACK_ACT,
        MASON_DAY_GUN_PICK_ACT,
        MASON_DAY_GUN_CONFIRM_ACT,
        MASON_DAY_GUN_BACK_ACT,
    )


def _day_panel_ui_keys(game: Game, uid: int) -> list[str]:
    return [
        _apache_ui_key(game, uid),
        _cowboy_ui_key(game, uid),
        _day_gun_ui_key(game, uid),
    ]


def _player_has_registered_day_panel(game: Game, uid: int) -> bool:
    return any(
        key in game.mirror_prompt_messages for key in _day_panel_ui_keys(game, uid)
    )


async def dismiss_mason_day_ability_panel_for_eliminated(
    bot: Bot, game: Game, uid: int
) -> None:
    """غیرفعال کردن پنل روزانهٔ بازیکن حذف‌شده در طول روز."""
    if not is_mason_scenario(game):
        return
    if not game.mason_intro_day_ability_open or game.mason_intro_day_ability_locked:
        return
    if not _player_has_registered_day_panel(game, uid):
        return
    for ui_key in _day_panel_ui_keys(game, uid):
        if ui_key not in game.mirror_prompt_messages:
            continue
        await sync_role_mirror_panel(
            bot, game, ui_key, uid, MASON_DAY_PANEL_INACTIVE_FA, None
        )
    pl = game.players.get(uid)
    if pl is None:
        return
    if pl.role == Role.APACHE:
        game.mason_apache_day_flow_active = False
        game.mason_apache_day_pending_uid = None
        ms_ap.clear_mason_apache_day_pick(game)
    if pl.role == Role.COWBOY:
        game.mason_cowboy_day_flow_active = False
        game.mason_cowboy_day_pending_uid = None
        ms_cw.clear_mason_cowboy_day_pick(game)
    from bot.roles import mason_gunner as ms_gn

    if ms_gn.mason_day_gun_holder_uid(game) == uid:
        ms_gn.refresh_mason_day_gun_holder_if_eliminated(game)


def mason_day_ability_panels_open(game: Game) -> bool:
    return (
        is_mason_scenario(game)
        and game.mason_intro_day_ability_open
        and not game.mason_intro_day_ability_locked
    )


def build_mason_apache_day_pick_html(game: Game) -> str:
    return (
        "🎭 <b>آپاچی</b>\n\n"
        "یک بازیکن زنده را انتخاب کنید.\n\n"
        "اگر محافظت نشده باشد، او و شما از بازی خارج می‌شوید.\n"
        "اگر محافظت شده باشد، فقط شما از بازی خارج می‌شوید."
    )


def build_mason_cowboy_day_pick_html(game: Game) -> str:
    return (
        "🤠 <b>کابوی</b>\n\n"
        "یک بازیکن زنده را انتخاب کنید.\n\n"
        "پس از تأیید، آن بازیکن به همراه شما از بازی خارج خواهد شد."
    )


def build_mason_day_gun_pick_html(game: Game) -> str:
    return (
        "🔫 <b>تفنگ روز</b>\n\n"
        "یک بازیکن زنده را برای شلیک انتخاب کنید.\n\n"
        "پس از تأیید، نتیجهٔ شلیک اعمال می‌شود."
    )


def _build_confirm_html(game: Game, gm: "GameManager", target_uid: int, *, role: str) -> str:
    tgt = game.players.get(target_uid)
    tag = html.escape(gm.format_player_tag(tgt) if tgt else str(target_uid))
    return (
        f"{role}\n\n"
        f"آیا از انتخاب <b>{tag}</b> مطمئن هستید؟\n"
        "پس از تأیید، شما و این بازیکن فوراً از بازی خارج می‌شوید."
    )


def mason_eliminated_team_line_fa(game: Game, uid: int) -> str:
    pl = game.players.get(uid)
    if pl is None or pl.role is None:
        return "🟢 بازیکن حذف‌شده عضو تیم شهروندان بود."
    if is_mafia_team(pl.role):
        return "🔴 بازیکن حذف‌شده عضو تیم مافیا بود."
    return "🟢 بازیکن حذف‌شده عضو تیم شهروندان بود."


def build_mason_apache_elim_broadcast_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    tgt = game.players.get(target_uid)
    name = html.escape(gm.format_player_tag(tgt) if tgt else str(target_uid))
    team = mason_eliminated_team_line_fa(game, target_uid)
    return f"💥 {name} به همراه آپاچی از بازی خارج شدند.\n\n{team}"


MASON_APACHE_SOLO_ELIM_BROADCAST_FA = "آپاچی به تنهایی از بازی خارج می‌شود."


def build_mason_apache_solo_elim_broadcast_html() -> str:
    return MASON_APACHE_SOLO_ELIM_BROADCAST_FA


def build_mason_cowboy_elim_broadcast_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    tgt = game.players.get(target_uid)
    name = html.escape(gm.format_player_tag(tgt) if tgt else str(target_uid))
    team = mason_eliminated_team_line_fa(game, target_uid)
    return f"🤠 {name} به همراه کابوی از بازی خارج شدند.\n\n{team}"


def build_mason_day_gun_normal_shot_broadcast_html(
    game: Game, gm: "GameManager", eliminated_uid: int
) -> str:
    from bot.roles import mason_gunner as ms_gn

    tgt = game.players.get(eliminated_uid)
    name = html.escape(gm.format_player_tag(tgt) if tgt else str(eliminated_uid))
    side = ms_gn.mason_faction_side_label_fa(game, eliminated_uid)
    return f"{name} با شلیک تفنگدار از بازی خارج شد.\n\nساید: {side}"


def build_mason_day_gun_sabotaged_broadcast_html(
    game: Game, gm: "GameManager", holder_uid: int
) -> str:
    from bot.roles import mason_gunner as ms_gn

    holder = game.players.get(holder_uid)
    name = html.escape(gm.format_player_tag(holder) if holder else str(holder_uid))
    side = ms_gn.mason_faction_side_label_fa(game, holder_uid)
    return (
        f"تفنگ {name} خرابکاری شده بود و بنابراین خودش از بازی خارج می‌شود.\n\n"
        f"ساید: {side}"
    )


async def _lock_day_ability_panel(
    bot: Bot, game: Game, uid: int, ui_key: str, *, done_text: str
) -> None:
    await sync_role_mirror_panel(
        bot, game, ui_key, uid, done_text, None
    )


async def _disable_mason_apache_day_panel(
    bot: Bot,
    game: Game,
    uid: int,
    *,
    done_text: str = MASON_DAY_ABILITY_USED_PANEL_FA,
) -> None:
    await _lock_day_ability_panel(
        bot, game, uid, _apache_ui_key(game, uid), done_text=done_text
    )
    game.mason_apache_day_flow_active = False
    game.mason_apache_day_pending_uid = None
    ms_ap.clear_mason_apache_day_pick(game)


async def _disable_mason_cowboy_day_panel(
    bot: Bot,
    game: Game,
    uid: int,
    *,
    done_text: str = MASON_DAY_ABILITY_USED_PANEL_FA,
) -> None:
    await _lock_day_ability_panel(
        bot, game, uid, _cowboy_ui_key(game, uid), done_text=done_text
    )
    game.mason_cowboy_day_flow_active = False
    game.mason_cowboy_day_pending_uid = None
    ms_cw.clear_mason_cowboy_day_pick(game)


def _day_ability_actor_alive(game: Game, as_uid: int) -> bool:
    pl = game.players.get(as_uid)
    return pl is not None and pl.is_alive


def lock_mason_day_ability_panels(game: Game) -> None:
    game.mason_intro_day_ability_locked = True
    game.mason_apache_day_flow_active = False
    game.mason_cowboy_day_flow_active = False


async def dismiss_mason_day_ability_panels(bot: Bot, game: Game) -> None:
    """پس از شروع رأی‌گیری — پنل‌های آپاچی/کابوی/تفنگ روز غیرفعال."""
    lock_mason_day_ability_panels(game)
    await expire_mason_day_gun_panel_at_vote_start(bot, game)
    for uid, p in game.players.items():
        if p.role == Role.APACHE and p.is_alive:
            await _lock_day_ability_panel(
                bot,
                game,
                uid,
                _apache_ui_key(game, uid),
                done_text="⛔ قابلیت روزانهٔ آپاچی در این روز دیگر فعال نیست.",
            )
        if p.role == Role.COWBOY and p.is_alive:
            await _lock_day_ability_panel(
                bot,
                game,
                uid,
                _cowboy_ui_key(game, uid),
                done_text="⛔ قابلیت روزانهٔ کابوی در این روز دیگر فعال نیست.",
            )


async def expire_mason_day_gun_panel_at_vote_start(bot: Bot, game: Game) -> None:
    """پایان مهلت تفنگ روز هنگام شروع رأی‌گیری — فقط اگر هنوز استفاده نشده باشد."""
    from bot.roles import mason_gunner as ms_gn

    holder_uid = ms_gn.expire_mason_day_gun_for_vote_start(game)
    if holder_uid is None:
        return
    await _lock_day_ability_panel(
        bot,
        game,
        holder_uid,
        _day_gun_ui_key(game, holder_uid),
        done_text=MASON_DAY_GUN_EXPIRED_PANEL_FA,
    )


async def _eliminate_apache_and_target(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    apache_uid: int,
    target_uid: int,
) -> None:
    target = game.players.get(target_uid)
    if guardian_blocks_apache(game, target_uid):
        _log_mason_day_timeline_event(
            game,
            "no_host.mason_apache_day",
            target_uid=target_uid,
            apache_solo_elim=True,
        )
        eliminate_player_from_game(
            game, gm, apache_uid, hunter_chain=False, elim_source="mason_apache_day"
        )
        gm.check_winner(game)
        await broadcast_to_alive_players(
            bot,
            game,
            build_mason_apache_solo_elim_broadcast_html(),
            parse_mode="HTML",
            is_synthetic_uid=is_synthetic_player_uid,
        )
        await _disable_mason_apache_day_panel(bot, game, apache_uid)
        await dismiss_mason_day_ability_panel_for_eliminated(bot, game, apache_uid)
        from bot.mason_game_flow import mason_auto_continue_after_apache_result

        await mason_auto_continue_after_apache_result(bot, game, gm)
        return
    _log_mason_day_timeline_event(
        game,
        "no_host.mason_apache_day",
        target_uid=target_uid,
        apache_uid=apache_uid,
    )
    broadcast = build_mason_apache_elim_broadcast_html(game, gm, target_uid)
    eliminate_player_from_game(
        game, gm, target_uid, hunter_chain=False, elim_source="mason_apache_day"
    )
    eliminate_player_from_game(
        game, gm, apache_uid, hunter_chain=False, elim_source="mason_apache_day"
    )
    gm.check_winner(game)
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await _disable_mason_apache_day_panel(bot, game, apache_uid)
    await dismiss_mason_day_ability_panel_for_eliminated(bot, game, apache_uid)
    await dismiss_mason_day_ability_panel_for_eliminated(bot, game, target_uid)
    if target is not None and target.role == Role.COWBOY:
        await _disable_mason_cowboy_day_panel(
            bot,
            game,
            target_uid,
            done_text=MASON_DAY_ABILITY_REVOKED_PANEL_FA,
        )
    from bot.mason_game_flow import mason_auto_continue_after_apache_result

    await mason_auto_continue_after_apache_result(bot, game, gm)


async def _eliminate_cowboy_and_target(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    cowboy_uid: int,
    target_uid: int,
) -> None:
    target = game.players.get(target_uid)
    _log_mason_day_timeline_event(
        game,
        "no_host.mason_cowboy_day",
        target_uid=target_uid,
        cowboy_uid=cowboy_uid,
    )
    broadcast = build_mason_cowboy_elim_broadcast_html(game, gm, target_uid)
    eliminate_player_from_game(
        game, gm, target_uid, hunter_chain=False, elim_source="mason_cowboy_day"
    )
    eliminate_player_from_game(
        game, gm, cowboy_uid, hunter_chain=False, elim_source="mason_cowboy_day"
    )
    gm.check_winner(game)
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await _disable_mason_cowboy_day_panel(bot, game, cowboy_uid)
    await dismiss_mason_day_ability_panel_for_eliminated(bot, game, cowboy_uid)
    await dismiss_mason_day_ability_panel_for_eliminated(bot, game, target_uid)
    if target is not None and target.role == Role.APACHE:
        await _disable_mason_apache_day_panel(
            bot,
            game,
            target_uid,
            done_text=MASON_DAY_ABILITY_REVOKED_PANEL_FA,
        )


async def dispatch_mason_intro_day_ability_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    await _dispatch_mason_apache_cowboy_panels(bot, game, gm)


async def dispatch_mason_day_start_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """شروع هر روز — آپاچی، کابوی، تفنگ روز."""
    await _dispatch_mason_apache_cowboy_panels(bot, game, gm)
    await _dispatch_mason_day_gun_panel(bot, game, gm)


async def _dispatch_mason_apache_cowboy_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    apache = ms_ap.find_alive_mason_apache(game)
    if apache is not None:
        game.mason_apache_day_flow_active = True
        text = build_mason_apache_day_pick_html(game)
        kb = build_pick_keyboard(
            game,
            apache.user_id,
            pick_act=MASON_APACHE_PICK_ACT,
            players=ms_ap.mason_apache_day_target_pool(game),
            columns=2,
        )
        await register_mirror_prompt_pair(
            bot,
            game,
            apache.user_id,
            _apache_ui_key(game, apache.user_id),
            text,
            kb,
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
    cowboy = ms_cw.find_alive_mason_cowboy(game)
    if cowboy is not None:
        game.mason_cowboy_day_flow_active = True
        text = build_mason_cowboy_day_pick_html(game)
        kb = build_pick_keyboard(
            game,
            cowboy.user_id,
            pick_act=MASON_COWBOY_PICK_ACT,
            players=ms_cw.mason_cowboy_day_target_pool(game),
            columns=2,
        )
        await register_mirror_prompt_pair(
            bot,
            game,
            cowboy.user_id,
            _cowboy_ui_key(game, cowboy.user_id),
            text,
            kb,
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )


async def _dispatch_mason_day_gun_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.roles import mason_gunner as ms_gn

    holder_uid = ms_gn.mason_day_gun_holder_uid(game)
    if holder_uid is None or not ms_gn.mason_day_gun_available(game):
        return
    holder = game.players.get(holder_uid)
    if holder is None or not holder.is_alive:
        return
    text = build_mason_day_gun_pick_html(game)
    kb = build_pick_keyboard(
        game,
        holder_uid,
        pick_act=MASON_DAY_GUN_PICK_ACT,
        players=ms_gn.mason_day_gun_shot_pool(game, holder_uid),
        columns=2,
    )
    await register_mirror_prompt_pair(
        bot,
        game,
        holder_uid,
        _day_gun_ui_key(game, holder_uid),
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    ms_gn.mark_mason_gun_delivered_to_holder(game)


async def _eliminate_day_gun_shot(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    holder_uid: int,
    target_uid: int,
) -> None:
    from bot.roles import mason_gunner as ms_gn

    holder = game.players[holder_uid]
    target = game.players[target_uid]
    result = ms_gn.resolve_mason_day_gun_shot(game, holder, target)
    if result is None:
        return
    _log_mason_day_timeline_event(
        game,
        "no_host.mason_day_gun_shot",
        target_uid=result.eliminated_uid,
        holder_uid=holder_uid,
        sabotaged=result.sabotaged,
    )
    if result.sabotaged:
        broadcast = build_mason_day_gun_sabotaged_broadcast_html(
            game, gm, result.eliminated_uid
        )
    else:
        broadcast = build_mason_day_gun_normal_shot_broadcast_html(
            game, gm, result.eliminated_uid
        )
    eliminate_player_from_game(
        game,
        gm,
        result.eliminated_uid,
        hunter_chain=False,
        elim_source="mason_day_gun",
    )
    gm.check_winner(game)
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await _lock_day_ability_panel(
        bot,
        game,
        holder_uid,
        _day_gun_ui_key(game, holder_uid),
        done_text="✅ شلیک ثبت شد.",
    )
    await dismiss_mason_day_ability_panel_for_eliminated(
        bot, game, result.eliminated_uid
    )


async def dispatch_mason_day_ability(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    as_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    day_gun_act = act in (
        MASON_DAY_GUN_PICK_ACT,
        MASON_DAY_GUN_CONFIRM_ACT,
        MASON_DAY_GUN_BACK_ACT,
    )
    if not day_gun_act and not mason_day_ability_panels_open(game):
        await callback.answer(MASON_DAY_PANEL_INACTIVE_ALERT_FA, show_alert=True)
        return
    if not actor_may_act_on_role_panel(game, actor_uid, as_uid):
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return
    if not _day_ability_actor_alive(game, as_uid):
        await callback.answer(MASON_DAY_PANEL_INACTIVE_ALERT_FA, show_alert=True)
        return

    if act in (MASON_APACHE_PICK_ACT, MASON_APACHE_CONFIRM_ACT, MASON_APACHE_BACK_ACT):
        apache = ms_ap.find_alive_mason_apache(game)
        if apache is None or apache.user_id != as_uid:
            await callback.answer("آپاچی در بازی نیست.", show_alert=True)
            return
        ui_key = _apache_ui_key(game, as_uid)
        if act == MASON_APACHE_PICK_ACT:
            if not ms_ap.mason_apache_day_target_valid(game, tid):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            game.mason_apache_day_pending_uid = tid
            await callback.answer("انتخاب شد؛ تأیید کنید.")
            confirm_kb = build_confirm_cancel_keyboard(
                game,
                as_uid,
                confirm_act=MASON_APACHE_CONFIRM_ACT,
                back_act=MASON_APACHE_BACK_ACT,
                confirm_text="✅ تأیید",
                back_text="↩️ بازگشت",
            )
            await sync_role_mirror_panel(
                bot,
                game,
                ui_key,
                as_uid,
                _build_confirm_html(game, gm, tid, role="🎭 <b>آپاچی</b>"),
                confirm_kb,
            )
            return
        if act == MASON_APACHE_BACK_ACT:
            game.mason_apache_day_pending_uid = None
            await callback.answer("بازگشت.")
            kb = build_pick_keyboard(
                game,
                as_uid,
                pick_act=MASON_APACHE_PICK_ACT,
                players=ms_ap.mason_apache_day_target_pool(game),
            )
            await sync_role_mirror_panel(
                bot, game, ui_key, as_uid, build_mason_apache_day_pick_html(game), kb
            )
            return
        if act == MASON_APACHE_CONFIRM_ACT:
            pending = game.mason_apache_day_pending_uid
            if pending is None or not ms_ap.mason_apache_day_target_valid(game, pending):
                await callback.answer("ابتدا هدف را انتخاب کنید.", show_alert=True)
                return
            ms_ap.commit_mason_apache_day_pick(game, pending, confirmed=True)
            ms_ap.mark_mason_apache_day_action_used(game)
            await callback.answer("ثبت شد.")
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=as_uid, target_uid=pending
            )
        return

    if act in (MASON_COWBOY_PICK_ACT, MASON_COWBOY_CONFIRM_ACT, MASON_COWBOY_BACK_ACT):
        if not _day_ability_actor_alive(game, as_uid):
            await callback.answer(MASON_DAY_PANEL_INACTIVE_ALERT_FA, show_alert=True)
            return
        cowboy = ms_cw.find_alive_mason_cowboy(game)
        if cowboy is None or cowboy.user_id != as_uid:
            await callback.answer("کابوی در بازی نیست.", show_alert=True)
            return
        ui_key = _cowboy_ui_key(game, as_uid)
        if act == MASON_COWBOY_PICK_ACT:
            if not ms_cw.mason_cowboy_day_target_valid(game, tid):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            game.mason_cowboy_day_pending_uid = tid
            await callback.answer("انتخاب شد؛ تأیید کنید.")
            confirm_kb = build_confirm_cancel_keyboard(
                game,
                as_uid,
                confirm_act=MASON_COWBOY_CONFIRM_ACT,
                back_act=MASON_COWBOY_BACK_ACT,
                confirm_text="✅ تأیید",
                back_text="↩️ بازگشت",
            )
            await sync_role_mirror_panel(
                bot,
                game,
                ui_key,
                as_uid,
                _build_confirm_html(game, gm, tid, role="🤠 <b>کابوی</b>"),
                confirm_kb,
            )
            return
        if act == MASON_COWBOY_BACK_ACT:
            game.mason_cowboy_day_pending_uid = None
            await callback.answer("بازگشت.")
            kb = build_pick_keyboard(
                game,
                as_uid,
                pick_act=MASON_COWBOY_PICK_ACT,
                players=ms_cw.mason_cowboy_day_target_pool(game),
            )
            await sync_role_mirror_panel(
                bot, game, ui_key, as_uid, build_mason_cowboy_day_pick_html(game), kb
            )
            return
        if act == MASON_COWBOY_CONFIRM_ACT:
            pending = game.mason_cowboy_day_pending_uid
            if pending is None or not ms_cw.mason_cowboy_day_target_valid(game, pending):
                await callback.answer("ابتدا هدف را انتخاب کنید.", show_alert=True)
                return
            ms_cw.commit_mason_cowboy_day_pick(game, pending, confirmed=True)
            await callback.answer("ثبت شد.")
            await _eliminate_cowboy_and_target(
                bot, game, gm, cowboy_uid=as_uid, target_uid=pending
            )
        return

    if act in (MASON_DAY_GUN_PICK_ACT, MASON_DAY_GUN_CONFIRM_ACT, MASON_DAY_GUN_BACK_ACT):
        from bot.roles import mason_gunner as ms_gn

        if game.mason_intro_day_ability_locked or not ms_gn.mason_day_gun_available(game):
            await callback.answer(MASON_DAY_GUN_EXPIRED_ALERT_FA, show_alert=True)
            return
        holder_uid = ms_gn.mason_day_gun_holder_uid(game)
        if holder_uid is None or holder_uid != as_uid:
            await callback.answer("تفنگ روز برای شما فعال نیست.", show_alert=True)
            return
        holder = game.players.get(as_uid)
        if holder is None or not holder.is_alive:
            await callback.answer("بازیکن در بازی نیست.", show_alert=True)
            return
        ui_key = _day_gun_ui_key(game, as_uid)
        if act == MASON_DAY_GUN_PICK_ACT:
            target = game.players.get(tid)
            if target is None or not ms_gn.mason_day_gun_holder_can_shoot(
                game, holder, target
            ):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            game.mason_day_gun_shot_target_uid = tid
            await callback.answer("انتخاب شد؛ تأیید کنید.")
            confirm_kb = build_confirm_cancel_keyboard(
                game,
                as_uid,
                confirm_act=MASON_DAY_GUN_CONFIRM_ACT,
                back_act=MASON_DAY_GUN_BACK_ACT,
                confirm_text="✅ تأیید",
                back_text="↩️ بازگشت",
            )
            await sync_role_mirror_panel(
                bot,
                game,
                ui_key,
                as_uid,
                _build_confirm_html(game, gm, tid, role="🔫 <b>تفنگ روز</b>"),
                confirm_kb,
            )
            return
        if act == MASON_DAY_GUN_BACK_ACT:
            game.mason_day_gun_shot_target_uid = None
            await callback.answer("بازگشت.")
            kb = build_pick_keyboard(
                game,
                as_uid,
                pick_act=MASON_DAY_GUN_PICK_ACT,
                players=ms_gn.mason_day_gun_shot_pool(game, as_uid),
            )
            await sync_role_mirror_panel(
                bot, game, ui_key, as_uid, build_mason_day_gun_pick_html(game), kb
            )
            return
        if act == MASON_DAY_GUN_CONFIRM_ACT:
            pending = game.mason_day_gun_shot_target_uid
            target = game.players.get(pending) if pending is not None else None
            if target is None or not ms_gn.mason_day_gun_holder_can_shoot(
                game, holder, target
            ):
                await callback.answer("ابتدا هدف را انتخاب کنید.", show_alert=True)
                return
            await callback.answer("ثبت شد.")
            await _eliminate_day_gun_shot(
                bot, game, gm, holder_uid=as_uid, target_uid=pending
            )
        return
