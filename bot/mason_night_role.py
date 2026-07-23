"""پنل‌های شبانهٔ نقش‌ها — فقط سناریوی ماسون."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import Game, Player, Role
from bot.mason_multi_select_panels import (
    build_mason_multi_select_keyboard,
    build_mason_multi_select_panel_text,
    mason_multi_select_no_more_button_label,
    mason_multi_select_none_button_label,
)
from bot.no_host_night_common import (
    finalize_no_host_role_pick_message,
    format_night_selection_label,
    no_host_role_ack_keyboard,
)
from bot.no_host_role_pick_common import (
    actor_may_act_on_role_panel,
    build_confirm_cancel_keyboard,
    build_none_pick_row,
    build_pick_keyboard,
    build_single_action_keyboard,
    build_target_button_rows,
    sync_role_mirror_panel,
)
from bot.observer_delivery import (
    PlayerMirrorCb,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)
from bot.room_mode import is_mason_scenario
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_msn
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_guardian as ms_gd
from bot.roles import mason_natasha as ms_nat
from bot.roles import mason_priest as ms_pr
from bot.roles import mason_saboteur as ms_sab
from bot.roles import mason_sniper as ms_sn
from bot.roles.detective import commit_pick as detective_commit_pick, investigation_pool
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager

# Saboteur
MSB_PICK, MSB_CONFIRM, MSB_BACK, MSB_NONE, MSB_OK = "msbp", "msbc", "msbb", "msbn", "msbo"
MASON_SABOTEUR_GUN_SPENT_TEXT = "انتخاب شما لازم نیست. منتظر باشید."
# Doctor
MSD_PICK, MSD_CONFIRM, MSD_BACK, MSD_DONE, MSD_OK = "msdp", "msdc", "msdb", "msdd", "msdo"
# Sniper
MSS_PICK, MSS_CONFIRM, MSS_BACK, MSS_NONE, MSS_OK = "mssp", "mssc", "mssb", "mssn", "msso"
# Gunner
MGN_PICK, MGN_CONFIRM, MGN_BACK, MGN_NONE = "mgnp", "mgnc", "mgnb", "mgnn"
# Guardian
MGD_PICK, MGD_CONFIRM, MGD_BACK, MGD_OK = "mgdp", "mgdc", "mgdb", "mgdo"
MASON_GUARDIAN_APACHE_USED_TEXT = (
    "آپاچی قبلاً از بازی خارج شده است و بنابراین انتخاب شما لازم نیست."
)
MASON_GUARDIAN_APACHE_GONE_TEXT = (
    "آپاچی در بازی نیست و بنابراین انتخاب شما لازم نیست."
)
# Mason recruit
MSM_PICK, MSM_CONFIRM, MSM_BACK, MSM_NONE, MSM_TAILOR = (
    "msmp",
    "msmc",
    "msmb",
    "msmn",
    "msmt",
)
# Detective
MSDT_PICK, MSDT_CONFIRM, MSDT_BACK = "mdtp", "mdtc", "mdtb"
# Commander
MSC_PICK, MSC_CONFIRM, MSC_BACK, MSC_NONE, MSC_DONE, MSC_INFO_OK = (
    "mscp",
    "mscc",
    "mscb",
    "mscn",
    "mscd",
    "msci",
)
MASON_COMMANDER_SNIPER_NO_SHOT_TEXT = "🎯 اسنایپر تصمیم گرفت امشب شلیک نکند."
MASON_NO_NIGHT_PICK_WAIT_TEXT = "شما انتخابی ندارید. منتظر باشید"
MASON_OK_CONFIRMED_PANEL_TEXT = "✅ انتخاب شما ثبت شد."
MASON_NO_PICK_OK_ACK_TEXT = MASON_OK_CONFIRMED_PANEL_TEXT
MASON_NO_PICK_ALREADY_ACK_TEXT = "این انتخاب قبلاً ثبت شده است."
MASON_DEAD_PANEL_INACTIVE_TEXT = "این پنل دیگر فعال نیست."
# Natasha
MSNA_PICK, MSNA_CONFIRM, MSNA_BACK = "mnap", "mnac", "mnab"
# Priest
MSPR_PICK, MSPR_CONFIRM, MSPR_BACK = "mprp", "mprc", "mprb"


def mason_night_role_act_active(game: Game, act: str) -> bool:
    if not is_mason_scenario(game):
        return False
    return act in {
        MSB_PICK, MSB_CONFIRM, MSB_BACK, MSB_NONE, MSB_OK,
        MSD_PICK, MSD_CONFIRM, MSD_BACK, MSD_DONE, MSD_OK,
        MSS_PICK, MSS_CONFIRM, MSS_BACK, MSS_NONE, MSS_OK,
        MGN_PICK, MGN_CONFIRM, MGN_BACK, MGN_NONE,
        MGD_PICK, MGD_CONFIRM, MGD_BACK, MGD_OK,
        MSM_PICK, MSM_CONFIRM, MSM_BACK, MSM_NONE, MSM_TAILOR,
        MSDT_PICK, MSDT_CONFIRM, MSDT_BACK,
        MSC_PICK, MSC_CONFIRM, MSC_BACK, MSC_NONE, MSC_DONE, MSC_INFO_OK,
        MSNA_PICK, MSNA_CONFIRM, MSNA_BACK,
        MSPR_PICK, MSPR_CONFIRM, MSPR_BACK,
    }


def _ui(game: Game, kind: str, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, kind, uid)


def _guardian_no_pick_body(game: Game) -> str:
    from bot.roles.mason_apache import find_alive_mason_apache

    if game.mason_apache_day_action_used:
        return MASON_GUARDIAN_APACHE_USED_TEXT
    if find_alive_mason_apache(game) is None:
        return MASON_GUARDIAN_APACHE_GONE_TEXT
    return MASON_GUARDIAN_APACHE_USED_TEXT


def mason_ok_already_acknowledged(game: Game, confirmed_attr: str) -> bool:
    return bool(getattr(game, confirmed_attr, False))


def build_mason_ok_confirmed_panel_text(
    *, role_html: str | None = None, body: str | None = None
) -> str:
    if role_html:
        if body:
            return f"{role_html}\n\n{body}\n\n{MASON_OK_CONFIRMED_PANEL_TEXT}"
        return f"{role_html}\n\n{MASON_OK_CONFIRMED_PANEL_TEXT}"
    if body:
        return f"{body}\n\n{MASON_OK_CONFIRMED_PANEL_TEXT}"
    return MASON_OK_CONFIRMED_PANEL_TEXT


async def edit_mason_ok_panel_to_confirmed(
    bot: Bot,
    game: Game,
    uid: int,
    *,
    ui_kind: str,
    role_html: str | None = None,
    body: str | None = None,
    parse_mode: str = "HTML",
) -> None:
    text = build_mason_ok_confirmed_panel_text(role_html=role_html, body=body)
    await update_mirror_prompt_pair(
        bot,
        game,
        _ui(game, ui_kind, uid),
        text,
        None,
        assistant_uid=uid,
        parse_mode=parse_mode,
    )


async def process_mason_no_pick_ok_ack(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    as_uid: int,
    confirmed_attr: str,
    ui_kind: str,
    role_html: str | None = None,
    body: str | None = None,
    parse_mode: str = "HTML",
    after_confirmed=None,
) -> bool:
    """ثبت اوکی تک‌بارهٔ پنل بدون انتخاب. True اگر پردازش شد."""
    if mason_ok_already_acknowledged(game, confirmed_attr):
        await callback.answer(MASON_NO_PICK_ALREADY_ACK_TEXT, show_alert=True)
        return False
    setattr(game, confirmed_attr, True)
    await callback.answer("ثبت شد.")
    await edit_mason_ok_panel_to_confirmed(
        bot,
        game,
        as_uid,
        ui_kind=ui_kind,
        role_html=role_html,
        body=body,
        parse_mode=parse_mode,
    )
    if after_confirmed is not None:
        await after_confirmed()
    else:
        from bot.mason_night_ready import maybe_finish_mason_parallel_night

        await maybe_finish_mason_parallel_night(bot, game, gm)
    return True


async def _send_pick_panel(
    bot: Bot,
    game: Game,
    *,
    uid: int,
    ui_kind: str,
    text: str,
    pick_act: str,
    pool,
    none_act: str | None = None,
    none_text: str | None = None,
) -> None:
    kb = build_pick_keyboard(
        game,
        uid,
        pick_act=pick_act,
        players=pool,
        none_act=none_act,
        none_text=none_text,
    )
    await register_mirror_prompt_pair(
        bot,
        game,
        uid,
        _ui(game, ui_kind, uid),
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def _show_mason_sniper_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    uid: int,
    *,
    initial: bool = False,
) -> None:
    selected = ms_sn.mason_sniper_night_selected_uids(game)
    max_allowed = ms_sn.mason_sniper_max_targets_this_night(game)
    header = (
        f"🎯 <b>اسنایپر</b>\n\n"
        f"{ms_sn.build_mason_sniper_remaining_bullets_line(game)}\n\n"
        f"{ms_sn.build_mason_sniper_shoot_instructions(game)}"
    )
    text = build_mason_multi_select_panel_text(
        header, game, gm, selected, max_allowed
    )
    none_label = mason_multi_select_none_button_label(
        len(selected), first_step_label="بدون شلیک"
    )
    kb = build_mason_multi_select_keyboard(
        game,
        uid,
        pick_act=MSS_PICK,
        players=ms_sn.mason_sniper_available_shot_pool(game),
        none_act=MSS_NONE,
        none_text=f"⭕ {none_label}",
    )
    ui = _ui(game, "mason_sniper", uid)
    if initial:
        await register_mirror_prompt_pair(
            bot,
            game,
            uid,
            ui,
            text,
            kb,
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
    else:
        await sync_role_mirror_panel(bot, game, ui, uid, text, kb)


async def _show_mason_doctor_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    uid: int,
    *,
    initial: bool = False,
) -> None:
    cap = ms_doc.mason_doctor_save_capacity(game)
    saved = ms_doc.mason_doctor_night_save_uids(game)
    self_save_line = ms_doc.build_mason_doctor_self_save_usage_line(game)
    header = (
        f"🩺 <b>پزشک</b>\n\n"
        f"{self_save_line}\n\n"
        f"تا {cap} نجات در این شب. بازیکنان را انتخاب کنید."
    )
    text = build_mason_multi_select_panel_text(header, game, gm, saved, cap)
    none_label = mason_multi_select_none_button_label(
        len(saved), first_step_label="انتخابی ندارم"
    )
    kb = build_mason_multi_select_keyboard(
        game,
        uid,
        pick_act=MSD_PICK,
        players=ms_doc.mason_doctor_save_pool(game),
        none_act=MSD_DONE,
        none_text=f"⭕ {none_label}",
    )
    ui = _ui(game, "mason_doctor", uid)
    if initial:
        await register_mirror_prompt_pair(
            bot,
            game,
            uid,
            ui,
            text,
            kb,
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
    else:
        await sync_role_mirror_panel(bot, game, ui, uid, text, kb)


async def apply_mason_doctor_nato_void_panel(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از شروع ناتویی — باطل کردن انتخاب پزشک و جایگزینی پنل."""
    ms_doc.void_mason_doctor_night_after_nato(game)
    doc = ms_doc.find_alive_mason_doctor(game)
    from bot.mason_night_ready import maybe_finish_mason_parallel_night

    if doc is None:
        await maybe_finish_mason_parallel_night(bot, game, gm)
        return
    text = ms_doc.MASON_DOCTOR_NATO_VOID_TEXT
    kb = no_host_role_ack_keyboard(game, doc.user_id, MSD_OK)
    ui = _ui(game, "mason_doctor", doc.user_id)
    await register_mirror_prompt_pair(
        bot,
        game,
        doc.user_id,
        ui,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode=None,
    )
    await maybe_finish_mason_parallel_night(bot, game, gm)


async def _show_mason_commander_panel(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    uid: int,
    *,
    initial: bool = False,
) -> None:
    from bot.roles import mason_commander as ms_cmd

    if ms_cmd.mason_commander_inherits_sniper_shooting(game):
        selected = ms_sn.mason_sniper_night_selected_uids(game)
        max_allowed = ms_sn.mason_sniper_max_targets_this_night(game)
        header = (
            f"⭐ <b>فرمانده</b>\n\n"
            f"{ms_sn.build_mason_sniper_remaining_bullets_line(game)}\n\n"
            "اسنایپر نیست — مستقیماً اهداف را انتخاب کنید."
        )
        text = build_mason_multi_select_panel_text(
            header, game, gm, selected, max_allowed
        )
        none_label = mason_multi_select_none_button_label(
            len(selected), first_step_label="بدون شلیک"
        )
        kb = build_mason_multi_select_keyboard(
            game,
            uid,
            pick_act=MSC_PICK,
            players=ms_cmd.mason_commander_direct_available_pool(game),
            none_act=MSC_NONE,
            none_text=f"⭕ {none_label}",
        )
    else:
        sn_selected = ms_sn.mason_sniper_night_selected_uids(game)
        approved = ms_cmd.mason_commander_approved_shot_uids(game)
        sn_names = ", ".join(
            html.escape(gm.format_player_tag(game.players[u]))
            for u in sn_selected
            if u in game.players
        )
        header = (
            f"⭐ <b>فرمانده</b>\n\n"
            f"اهداف پیشنهادی اسنایپر: {sn_names}\n"
            "اهداف تأییدشده را انتخاب کنید."
        )
        max_allowed = max(len(sn_selected), 1)
        text = build_mason_multi_select_panel_text(
            header,
            game,
            gm,
            approved,
            max_allowed,
            line_prefix="تأیید",
        )
        none_act = MSC_NONE if not approved else None
        none_text = "❌ رد همه" if not approved else None
        done_act = None
        done_text = None
        if approved and ms_cmd.mason_commander_can_add_approval(game):
            done_act = MSC_DONE
            done_text = (
                f"⭕ {mason_multi_select_no_more_button_label(len(approved) + 1)}"
            )
        kb = build_mason_multi_select_keyboard(
            game,
            uid,
            pick_act=MSC_PICK,
            players=ms_cmd.mason_commander_approval_pool(game),
            none_act=none_act,
            none_text=none_text,
            done_act=done_act,
            done_text=done_text,
        )
    ui = _ui(game, "mason_commander", uid)
    if initial:
        await register_mirror_prompt_pair(
            bot,
            game,
            uid,
            ui,
            text,
            kb,
            send_player=True,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
    else:
        await sync_role_mirror_panel(bot, game, ui, uid, text, kb)


async def _send_saboteur_no_pick_ok_panel(
    bot: Bot, game: Game, uid: int
) -> None:
    text = f"🔧 <b>خرابکار</b>\n\n{MASON_SABOTEUR_GUN_SPENT_TEXT}"
    kb = no_host_role_ack_keyboard(game, uid, MSB_OK)
    await register_mirror_prompt_pair(
        bot,
        game,
        uid,
        _ui(game, "mason_saboteur", uid),
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def _send_commander_sniper_no_shot_info_panel(
    bot: Bot, game: Game, uid: int
) -> None:
    text = MASON_COMMANDER_SNIPER_NO_SHOT_TEXT
    kb = no_host_role_ack_keyboard(game, uid, MSC_INFO_OK)
    await register_mirror_prompt_pair(
        bot,
        game,
        uid,
        _ui(game, "mason_commander", uid),
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def _finalize_mason_no_pick_ok_panel(
    bot: Bot,
    game: Game,
    uid: int,
    *,
    ui_kind: str,
    role_html: str,
) -> None:
    await edit_mason_ok_panel_to_confirmed(
        bot,
        game,
        uid,
        ui_kind=ui_kind,
        role_html=role_html,
    )


async def _send_mason_no_pick_wait_panel(
    bot: Bot,
    game: Game,
    uid: int,
    *,
    role_html: str,
    ui_kind: str,
    ok_act: str,
) -> None:
    """گلوله/اقدام باقی نمانده — پیام انتظار + اوکی (شامل ناظر و بازیکن مصنوعی)."""
    text = f"{role_html}\n\n{MASON_NO_NIGHT_PICK_WAIT_TEXT}"
    kb = no_host_role_ack_keyboard(game, uid, ok_act)
    await register_mirror_prompt_pair(
        bot,
        game,
        uid,
        _ui(game, ui_kind, uid),
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def dispatch_mason_saboteur_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    sab = ms_sab.find_alive_mason_saboteur(game)
    if sab is None:
        game.mason_night_saboteur_confirmed = True
        return
    if not ms_sab.mason_saboteur_needs_night_pick(game):
        await _send_saboteur_no_pick_ok_panel(bot, game, sab.user_id)
        return
    await _send_pick_panel(
        bot,
        game,
        uid=sab.user_id,
        ui_kind="mason_saboteur",
        text="🔧 <b>خرابکار</b>\n\nیک بازیکن زنده را برای خرابکاری انتخاب کنید.",
        pick_act=MSB_PICK,
        pool=ms_sab.mason_saboteur_night_target_pool(game),
        none_act=MSB_NONE,
        none_text="انتخابی ندارم",
    )


async def dispatch_mason_doctor_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    doc = ms_doc.find_alive_mason_doctor(game)
    if doc is None:
        game.mason_night_doctor_confirmed = True
        return
    ms_doc.snapshot_mason_doctor_night_baseline(game)
    await _show_mason_doctor_panel(bot, game, gm, doc.user_id, initial=True)


async def _maybe_finish_after_mason_commander_dispatch(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not game.mason_night_commander_confirmed:
        return
    from bot.mason_night_ready import maybe_finish_mason_parallel_night

    await maybe_finish_mason_parallel_night(bot, game, gm)


async def dispatch_mason_sniper_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    from bot.roles import mason_commander as ms_cmd

    sn = ms_sn.find_alive_mason_sniper(game)
    if sn is None:
        game.mason_night_sniper_confirmed = True
        await dispatch_mason_commander_panel(bot, game, gm)
        return
    if not ms_sn.mason_sniper_needs_night_pick(game):
        cmd = ms_cmd.find_alive_mason_commander(game)
        commander_dealt = any(p.role == Role.COMMANDER for p in game.players.values())
        if cmd is None and commander_dealt:
            # فرمانده مرده — زنجیرهٔ تأیید لازم نیست (Room 68).
            game.mason_night_sniper_confirmed = True
        else:
            await _send_mason_no_pick_wait_panel(
                bot,
                game,
                sn.user_id,
                role_html="🎯 <b>اسنایپر</b>",
                ui_kind="mason_sniper",
                ok_act=MSS_OK,
            )
        await dispatch_mason_commander_panel(bot, game, gm)
        return
    await _show_mason_sniper_panel(bot, game, gm, sn.user_id, initial=True)


async def dispatch_mason_commander_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    from bot.roles import mason_commander as ms_cmd

    cmd = ms_cmd.find_alive_mason_commander(game)
    if cmd is None:
        ms_cmd.auto_approve_sniper_shots_when_no_commander(game)
        game.mason_night_commander_confirmed = True
        await _maybe_finish_after_mason_commander_dispatch(bot, game, gm)
        return
    if game.mason_night_commander_panel_sent:
        return
    game.mason_night_commander_panel_sent = True
    if ms_cmd.mason_commander_inherits_sniper_shooting(game):
        if ms_cmd.mason_commander_needs_no_pick_wait_panel(game):
            await _send_mason_no_pick_wait_panel(
                bot,
                game,
                cmd.user_id,
                role_html="🎖️ <b>فرمانده</b>",
                ui_kind="mason_commander",
                ok_act=MSC_INFO_OK,
            )
            await _maybe_finish_after_mason_commander_dispatch(bot, game, gm)
            return
    if not ms_cmd.mason_commander_inherits_sniper_shooting(game):
        if ms_cmd.mason_commander_needs_sniper_no_shot_info_panel(game):
            await _send_commander_sniper_no_shot_info_panel(bot, game, cmd.user_id)
            return
    await _show_mason_commander_panel(bot, game, gm, cmd.user_id, initial=True)


async def dispatch_mason_gunner_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    gun = ms_gn.find_alive_mason_gunner(game)
    if gun is None or not ms_gn.mason_gunner_can_give_gun(game):
        game.mason_night_gunner_confirmed = True
        return
    await _send_pick_panel(
        bot,
        game,
        uid=gun.user_id,
        ui_kind="mason_gunner",
        text="🔫 <b>تفنگدار</b>\n\nیک بازیکن را برای دریافت اسلحهٔ فردا انتخاب کنید.",
        pick_act=MGN_PICK,
        pool=ms_gn.mason_gunner_night_target_pool(game),
        none_act=MGN_NONE,
        none_text="انتخابی ندارم",
    )


async def _send_guardian_no_pick_ok_panel(
    bot: Bot, game: Game, uid: int, *, text_body: str | None = None
) -> None:
    body = text_body or MASON_GUARDIAN_APACHE_USED_TEXT
    text = f"🛡️ <b>محافظ</b>\n\n{body}"
    kb = no_host_role_ack_keyboard(game, uid, MGD_OK)
    await register_mirror_prompt_pair(
        bot,
        game,
        uid,
        _ui(game, "mason_guardian", uid),
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def dispatch_mason_guardian_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    gd = ms_gd.find_alive_mason_guardian(game)
    if gd is None:
        game.mason_night_guardian_confirmed = True
        return
    if not ms_gd.mason_guardian_needs_night_pick(game):
        await _send_guardian_no_pick_ok_panel(
            bot, game, gd.user_id, text_body=_guardian_no_pick_body(game)
        )
        return
    await _send_pick_panel(
        bot,
        game,
        uid=gd.user_id,
        ui_kind="mason_guardian",
        text="🛡️ <b>محافظ</b>\n\nیک بازیکن را برای محافظت در برابر آپاچی انتخاب کنید.",
        pick_act=MGD_PICK,
        pool=ms_gd.mason_guardian_night_target_pool(game),
    )


def _build_mason_recruit_keyboard(
    game: Game,
    mason: Player,
    pool: list[Player],
) -> InlineKeyboardMarkup:
    rows = build_target_button_rows(
        game,
        as_uid=mason.user_id,
        pick_act=MSM_PICK,
        players=pool,
    )
    if ms_msn.mason_show_tailor_recruit_button(game, mason):
        tailor = ms_msn.find_mason_tailor(game)
        rows.append(
            [
                InlineKeyboardButton(
                    text=ms_msn.MASON_TAILOR_RECRUIT_LABEL,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act=MSM_TAILOR,
                        as_uid=mason.user_id,
                        tid=tailor.user_id if tailor is not None else 0,
                    ).pack(),
                )
            ]
        )
    rows.append(
        build_none_pick_row(
            game,
            mason.user_id,
            none_act=MSM_NONE,
            none_text=ms_msn.MASON_NO_RECRUIT_LABEL,
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def dispatch_mason_mason_recruit_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    mason = ms_msn.find_alive_mason_role_holder(game)
    if mason is None:
        game.mason_night_mason_confirmed = True
        return
    pool = ms_msn.mason_recruit_target_pool(game, mason)
    kb = _build_mason_recruit_keyboard(game, mason, pool)
    await register_mirror_prompt_pair(
        bot,
        game,
        mason.user_id,
        _ui(game, "mason_recruit", mason.user_id),
        ms_msn.build_mason_recruit_panel_html(game),
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def dispatch_mason_detective_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    det = find_alive_role_holder(game, Role.DETECTIVE)
    if det is None:
        game.mason_night_detective_confirmed = True
        return
    await _send_pick_panel(
        bot,
        game,
        uid=det.user_id,
        ui_kind="mason_detective",
        text="🔍 <b>کارآگاه</b>\n\nیک بازیکن را برای استعلام انتخاب کنید.",
        pick_act=MSDT_PICK,
        pool=investigation_pool(game),
    )


async def dispatch_mason_natasha_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    nat = ms_nat.find_alive_mason_natasha(game)
    if nat is None:
        game.mason_night_natasha_confirmed = True
        return
    await _send_pick_panel(
        bot,
        game,
        uid=nat.user_id,
        ui_kind="mason_natasha",
        text="🤐 <b>ناتاشا</b>\n\nیک بازیکن را برای سکوت فردا انتخاب کنید.",
        pick_act=MSNA_PICK,
        pool=ms_nat.mason_natasha_night_target_pool(game),
    )


async def dispatch_mason_priest_panel(bot: Bot, game: Game, gm: "GameManager") -> None:
    pr = ms_pr.find_alive_mason_priest(game)
    if pr is None:
        game.mason_night_priest_confirmed = True
        return
    await _send_pick_panel(
        bot,
        game,
        uid=pr.user_id,
        ui_kind="mason_priest",
        text="⛪ <b>کشیش</b>\n\nیک بازیکن را برای خنثی‌سازی سکوت ناتاشا انتخاب کنید.",
        pick_act=MSPR_PICK,
        pool=ms_pr.mason_priest_night_target_pool(game),
    )


def build_mason_night_finalized_selection_label(
    game: Game,
    gm: "GameManager",
    ui_kind: str,
) -> str:
    """برچسب «انتخاب شما» پس از تأیید — از state واقعی نقش ماسون."""
    from bot.roles.detective import committed_target_uid

    def _one(uid: int | None, *, none: str = "انتخابی ندارم") -> str:
        return format_night_selection_label(game, gm, uid, none_label=none)

    def _many(uids: list[int], *, none: str = "انتخابی ندارم") -> str:
        if not uids:
            return none
        return "، ".join(_one(u) for u in uids)

    if ui_kind == "mason_saboteur":
        if game.mason_saboteur_night_no_sabotage:
            return "انتخابی ندارم"
        return _one(game.mason_saboteur_night_target_uid)
    if ui_kind == "mason_doctor":
        return _many(ms_doc.mason_doctor_night_save_uids(game))
    if ui_kind == "mason_sniper":
        return _many(
            ms_sn.mason_sniper_night_selected_uids(game),
            none="بدون شلیک",
        )
    if ui_kind == "mason_commander":
        from bot.roles import mason_commander as ms_cmd

        return _many(
            ms_cmd.mason_commander_approved_shot_uids(game),
            none="رد همه",
        )
    if ui_kind == "mason_gunner":
        if game.mason_gunner_night_no_give:
            return "انتخابی ندارم"
        return _one(game.mason_gunner_night_target_uid)
    if ui_kind == "mason_guardian":
        return _one(game.mason_guardian_night_target_uid)
    if ui_kind == "mason_recruit":
        if game.mason_mason_night_no_recruit:
            return "انتخابی ندارم"
        return _one(game.mason_pending_recruit_uid)
    if ui_kind == "mason_detective":
        return _one(committed_target_uid(game))
    if ui_kind == "mason_natasha":
        return _one(game.mason_natasha_target_uid)
    if ui_kind == "mason_priest":
        return _one(game.mason_priest_target_uid)
    return "انتخابی ندارم"


async def _after_role_confirmed(
    bot: Bot, game: Game, gm: "GameManager", uid: int, ui_kind: str, label: str
) -> None:
    selection_label = build_mason_night_finalized_selection_label(game, gm, ui_kind)
    await finalize_no_host_role_pick_message(
        bot,
        game,
        gm,
        uid,
        _ui(game, ui_kind, uid),
        selection_label,
    )
    from bot.mason_night_ready import maybe_finish_mason_parallel_night

    await maybe_finish_mason_parallel_night(bot, game, gm)


async def dispatch_mason_night_role(
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
    from bot.mason_force_finish_night import (
        MASON_NIGHT_PHASE_ENDED_TEXT,
        mason_night_player_actions_closed,
    )

    if mason_night_player_actions_closed(game):
        await callback.answer(MASON_NIGHT_PHASE_ENDED_TEXT, show_alert=True)
        return
    holder = game.players.get(as_uid)
    if holder is not None and not holder.is_alive:
        await callback.answer(MASON_DEAD_PANEL_INACTIVE_TEXT, show_alert=True)
        return
    if not actor_may_act_on_role_panel(game, actor_uid, as_uid):
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return

    # --- Saboteur ---
    if act in (MSB_PICK, MSB_CONFIRM, MSB_BACK, MSB_NONE, MSB_OK):
        sab = ms_sab.find_alive_mason_saboteur(game)
        if sab is None or sab.user_id != as_uid:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MSB_OK:
            if not actor_may_act_on_role_panel(game, actor_uid, as_uid):
                await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
                return
            if ms_sab.mason_saboteur_needs_night_pick(game):
                await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
                return
            await process_mason_no_pick_ok_ack(
                callback,
                bot,
                game,
                gm,
                as_uid=as_uid,
                confirmed_attr="mason_night_saboteur_confirmed",
                ui_kind="mason_saboteur",
                role_html="🔧 <b>خرابکار</b>",
                body=MASON_SABOTEUR_GUN_SPENT_TEXT,
            )
            return
        if game.mason_night_saboteur_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        ui = _ui(game, "mason_saboteur", as_uid)
        if act == MSB_NONE:
            if not ms_sab.commit_mason_saboteur_no_sabotage(game):
                await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
                return
            game.mason_night_saboteur_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_saboteur", "خرابکار")
            return
        if act == MSB_PICK:
            tgt = game.players.get(tid)
            if tgt is None or not ms_sab.commit_mason_saboteur_target(game, sab, tgt):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            await callback.answer("انتخاب شد.")
            kb = build_confirm_cancel_keyboard(
                game, as_uid,
                confirm_act=MSB_CONFIRM, back_act=MSB_BACK,
                confirm_text="✅ تأیید", back_text="↩️ بازگشت",
            )
            await sync_role_mirror_panel(bot, game, ui, as_uid, "تأیید خرابکار", kb)
            return
        if act == MSB_BACK:
            await callback.answer("بازگشت.")
            await dispatch_mason_saboteur_panel(bot, game, gm)
            return
        if act == MSB_CONFIRM:
            if game.mason_saboteur_night_target_uid is None:
                await callback.answer("ابتدا هدف را انتخاب کنید.", show_alert=True)
                return
            game.mason_night_saboteur_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_saboteur", "خرابکار")
        return

    # --- Doctor ---
    if act in (MSD_PICK, MSD_CONFIRM, MSD_BACK, MSD_DONE, MSD_OK):
        doc = ms_doc.find_alive_mason_doctor(game)
        if act == MSD_OK:
            if doc is None or doc.user_id != as_uid:
                await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
                return
            if mason_ok_already_acknowledged(game, "mason_night_doctor_confirmed"):
                await callback.answer(MASON_NO_PICK_ALREADY_ACK_TEXT, show_alert=True)
                return
            if not game.mason_night_doctor_nato_void_pending:
                await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
                return
            await process_mason_no_pick_ok_ack(
                callback,
                bot,
                game,
                gm,
                as_uid=as_uid,
                confirmed_attr="mason_night_doctor_confirmed",
                ui_kind="mason_doctor",
                body=ms_doc.MASON_DOCTOR_NATO_VOID_TEXT,
                parse_mode=None,
            )
            game.mason_night_doctor_nato_void_pending = False
            return
        if doc is None or doc.user_id != as_uid or game.mason_night_doctor_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        ui = _ui(game, "mason_doctor", as_uid)
        if act == MSD_PICK:
            if not ms_doc.commit_mason_doctor_save(game, tid):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            await callback.answer("نجات ثبت شد.")
            if not ms_doc.can_add_mason_doctor_save(game):
                game.mason_night_doctor_confirmed = True
                await _after_role_confirmed(bot, game, gm, as_uid, "mason_doctor", "پزشک")
            else:
                await _show_mason_doctor_panel(bot, game, gm, as_uid)
            return
        if act == MSD_DONE:
            game.mason_night_doctor_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_doctor", "پزشک")
        return

    # --- Sniper ---
    if act in (MSS_PICK, MSS_CONFIRM, MSS_BACK, MSS_NONE, MSS_OK):
        sn = ms_sn.find_alive_mason_sniper(game)
        if act == MSS_OK:
            if sn is None or sn.user_id != as_uid:
                await callback.answer(MASON_DEAD_PANEL_INACTIVE_TEXT, show_alert=True)
                return
            if ms_sn.mason_sniper_needs_night_pick(game):
                await callback.answer(MASON_DEAD_PANEL_INACTIVE_TEXT, show_alert=True)
                return
            await process_mason_no_pick_ok_ack(
                callback,
                bot,
                game,
                gm,
                as_uid=as_uid,
                confirmed_attr="mason_night_sniper_confirmed",
                ui_kind="mason_sniper",
                role_html="🎯 <b>اسنایپر</b>",
                body=MASON_NO_NIGHT_PICK_WAIT_TEXT,
                after_confirmed=lambda: dispatch_mason_commander_panel(
                    bot, game, gm
                ),
            )
            return
        if (
            sn is None
            or sn.user_id != as_uid
            or game.mason_night_sniper_confirmed
            or not ms_sn.mason_sniper_needs_night_pick(game)
        ):
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MSS_NONE:
            if not ms_sn.mason_sniper_night_selected_uids(game):
                ms_sn.clear_mason_sniper_night_selection(game)
            game.mason_night_sniper_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_sniper", "اسنایپر")
            await dispatch_mason_commander_panel(bot, game, gm)
            return
        if act == MSS_PICK:
            selected = list(ms_sn.mason_sniper_night_selected_uids(game))
            if tid in selected:
                await callback.answer("این بازیکن قبلاً انتخاب شده.", show_alert=True)
                return
            max_targets = ms_sn.mason_sniper_max_targets_this_night(game)
            if len(selected) >= max_targets:
                await callback.answer("حداکثر تعداد اهداف انتخاب شده.", show_alert=True)
                return
            selected.append(tid)
            if not ms_sn.commit_mason_sniper_night_selection(game, selected):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            await callback.answer("انتخاب شد.")
            if len(selected) >= max_targets:
                game.mason_night_sniper_confirmed = True
                await _after_role_confirmed(bot, game, gm, as_uid, "mason_sniper", "اسنایپر")
                await dispatch_mason_commander_panel(bot, game, gm)
            else:
                await _show_mason_sniper_panel(bot, game, gm, as_uid)
            return
        return

    # --- Commander ---
    if act in (MSC_PICK, MSC_CONFIRM, MSC_BACK, MSC_NONE, MSC_DONE, MSC_INFO_OK):
        from bot.roles import mason_commander as ms_cmd

        cmd = ms_cmd.find_alive_mason_commander(game)
        if cmd is None or cmd.user_id != as_uid:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MSC_INFO_OK:
            if ms_cmd.mason_commander_needs_no_pick_wait_panel(game):
                body = MASON_NO_NIGHT_PICK_WAIT_TEXT
                role_html: str | None = "🎖️ <b>فرمانده</b>"
            else:
                body = MASON_COMMANDER_SNIPER_NO_SHOT_TEXT
                role_html = None
            await process_mason_no_pick_ok_ack(
                callback,
                bot,
                game,
                gm,
                as_uid=as_uid,
                confirmed_attr="mason_night_commander_confirmed",
                ui_kind="mason_commander",
                role_html=role_html,
                body=body,
                after_confirmed=lambda: _maybe_finish_after_mason_commander_dispatch(
                    bot, game, gm
                ),
            )
            return
        if game.mason_night_commander_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MSC_NONE:
            if ms_cmd.mason_commander_inherits_sniper_shooting(game):
                if ms_sn.mason_sniper_night_selected_uids(game):
                    ms_cmd.finalize_mason_commander_direct_shots(game)
                else:
                    ms_cmd.mason_commander_rejects_all_shots(game)
            else:
                ms_cmd.mason_commander_rejects_all_shots(game)
            game.mason_night_commander_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_commander", "فرمانده")
            return
        if act == MSC_DONE:
            game.mason_night_commander_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_commander", "فرمانده")
            return
        if act == MSC_PICK:
            if ms_cmd.mason_commander_inherits_sniper_shooting(game):
                selected = list(ms_sn.mason_sniper_night_selected_uids(game))
                if tid in selected:
                    await callback.answer("این بازیکن قبلاً انتخاب شده.", show_alert=True)
                    return
                max_targets = ms_sn.mason_sniper_max_targets_this_night(game)
                if len(selected) >= max_targets:
                    await callback.answer("حداکثر تعداد اهداف انتخاب شده.", show_alert=True)
                    return
                if not ms_cmd.add_mason_commander_direct_shot(game, tid):
                    await callback.answer("انتخاب نامعتبر.", show_alert=True)
                    return
                await callback.answer("انتخاب شد.")
                selected = ms_sn.mason_sniper_night_selected_uids(game)
                if len(selected) >= max_targets:
                    ms_cmd.finalize_mason_commander_direct_shots(game)
                    game.mason_night_commander_confirmed = True
                    await _after_role_confirmed(
                        bot, game, gm, as_uid, "mason_commander", "فرمانده"
                    )
                else:
                    await _show_mason_commander_panel(bot, game, gm, as_uid)
            else:
                if not ms_cmd.add_mason_commander_approval(game, tid):
                    await callback.answer("انتخاب نامعتبر.", show_alert=True)
                    return
                await callback.answer("تأیید شد.")
                approved = ms_cmd.mason_commander_approved_shot_uids(game)
                sn_selected = ms_sn.mason_sniper_night_selected_uids(game)
                if len(approved) >= len(sn_selected) or not ms_cmd.mason_commander_can_add_approval(game):
                    game.mason_night_commander_confirmed = True
                    await _after_role_confirmed(
                        bot, game, gm, as_uid, "mason_commander", "فرمانده"
                    )
                else:
                    await _show_mason_commander_panel(bot, game, gm, as_uid)
            return
        return

    # --- Gunner ---
    if act in (MGN_PICK, MGN_CONFIRM, MGN_BACK, MGN_NONE):
        gun = ms_gn.find_alive_mason_gunner(game)
        if (
            gun is None
            or gun.user_id != as_uid
            or game.mason_night_gunner_confirmed
            or not ms_gn.mason_gunner_can_give_gun(game)
        ):
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MGN_NONE:
            if not ms_gn.commit_mason_gunner_no_give(game):
                await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
                return
            game.mason_night_gunner_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_gunner", "تفنگدار")
            return
        tgt = game.players.get(tid)
        if act == MGN_PICK and tgt and ms_gn.commit_mason_gunner_target(game, gun, tgt):
            game.mason_night_gunner_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_gunner", "تفنگدار")
        else:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
        return

    # --- Guardian ---
    if act in (MGD_PICK, MGD_CONFIRM, MGD_BACK, MGD_OK):
        gd = ms_gd.find_alive_mason_guardian(game)
        if gd is None or gd.user_id != as_uid:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MGD_OK:
            if not actor_may_act_on_role_panel(game, actor_uid, as_uid):
                await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
                return
            if ms_gd.mason_guardian_needs_night_pick(game):
                await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
                return
            await process_mason_no_pick_ok_ack(
                callback,
                bot,
                game,
                gm,
                as_uid=as_uid,
                confirmed_attr="mason_night_guardian_confirmed",
                ui_kind="mason_guardian",
                role_html="🛡️ <b>محافظ</b>",
                body=_guardian_no_pick_body(game),
            )
            return
        if game.mason_night_guardian_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MGD_PICK:
            if not ms_gd.commit_mason_guardian_night_pick(game, tid):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            game.mason_night_guardian_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_guardian", "محافظ")
        return

    # --- Mason recruit ---
    if act in (MSM_PICK, MSM_CONFIRM, MSM_BACK, MSM_NONE, MSM_TAILOR):
        mason = ms_msn.find_alive_mason_role_holder(game)
        if mason is None or mason.user_id != as_uid or game.mason_night_mason_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MSM_NONE:
            ms_msn.commit_mason_recruit(game, mason, None)
            game.mason_night_mason_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_recruit", "ماسون")
            return
        if act == MSM_TAILOR:
            if ms_msn.mason_is_dead_tailor_recruit_button(game, mason):
                if not ms_msn.commit_mason_recruit_dead_tailor(game, mason):
                    await callback.answer("انتخاب نامعتبر.", show_alert=True)
                    return
                game.mason_night_mason_confirmed = True
                await callback.answer("ثبت شد.")
                await finalize_no_host_role_pick_message(
                    bot,
                    game,
                    gm,
                    as_uid,
                    _ui(game, "mason_recruit", as_uid),
                    ms_msn.MASON_DEAD_TAILOR_UNAVAILABLE_TEXT,
                )
                from bot.mason_night_ready import maybe_finish_mason_parallel_night

                await maybe_finish_mason_parallel_night(bot, game, gm)
                return
            if not ms_msn.mason_show_alive_tailor_recruit_button(game, mason):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            welcome = ms_msn.commit_mason_recruit_tailor(game, mason)
            if welcome is None:
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            recruit_uid = game.mason_pending_recruit_uid
            if recruit_uid is not None:
                from bot.mason_recruit_delivery import (
                    deliver_mason_recruit_membership_message,
                )

                await deliver_mason_recruit_membership_message(
                    bot, game, recruit_uid, welcome
                )
            game.mason_night_mason_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_recruit", "ماسون")
            return
        if act == MSM_PICK:
            tgt = game.players.get(tid)
            if tgt is None or not ms_msn.mason_can_recruit_target(game, mason, tgt):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            welcome = ms_msn.commit_mason_recruit(game, mason, tgt)
            if welcome:
                from bot.mason_recruit_delivery import (
                    deliver_mason_recruit_membership_message,
                )

                await deliver_mason_recruit_membership_message(
                    bot, game, tgt.user_id, welcome
                )
            game.mason_night_mason_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_recruit", "ماسون")
        return

    # --- Detective ---
    if act in (MSDT_PICK, MSDT_CONFIRM, MSDT_BACK):
        det = find_alive_role_holder(game, Role.DETECTIVE)
        if det is None or det.user_id != as_uid or game.mason_night_detective_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        if act == MSDT_PICK:
            if not detective_commit_pick(game, tid):
                await callback.answer("انتخاب نامعتبر.", show_alert=True)
                return
            game.mason_night_detective_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_detective", "کارآگاه")
        return

    # --- Natasha ---
    if act in (MSNA_PICK, MSNA_CONFIRM, MSNA_BACK):
        nat = ms_nat.find_alive_mason_natasha(game)
        if nat is None or nat.user_id != as_uid or game.mason_night_natasha_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        tgt = game.players.get(tid)
        if act == MSNA_PICK and tgt and ms_nat.commit_mason_natasha_target(game, nat, tgt, confirmed=True):
            game.mason_night_natasha_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_natasha", "ناتاشا")
        else:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
        return

    # --- Priest ---
    if act in (MSPR_PICK, MSPR_CONFIRM, MSPR_BACK):
        pr = ms_pr.find_alive_mason_priest(game)
        if pr is None or pr.user_id != as_uid or game.mason_night_priest_confirmed:
            await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
            return
        tgt = game.players.get(tid)
        if act == MSPR_PICK and tgt and ms_pr.commit_mason_priest_target(game, pr, tgt, confirmed=True):
            game.mason_night_priest_confirmed = True
            await callback.answer("ثبت شد.")
            await _after_role_confirmed(bot, game, gm, as_uid, "mason_priest", "کشیش")
        else:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
