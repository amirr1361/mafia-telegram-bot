"""شب ۱ — یاکوزایی توسط تیم مافیا (حالت بدون گرداننده)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NS_YAKU_CIV,
    NS_YAKU_SAC,
    _advance_after_mafia_menu_done,
    _alive,
    _find_alive_role,
    _visually_mafia,
    _yaku_civilian_pool,
    _yaku_negotiation_succeeds,
    _yaku_sacrifice_pool,
    push_host_step,
    role_label_fa,
    yakuzai_allowed,
)
from bot.roles import mafia_boss as _boss_role
from bot.roles.night_state import yaku_night_state
from bot.models import Game, Role
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_YAKU,
    _alive_mafia_members,
    _edit_mafia_prompt,
    _mafia_panel_has_uid,
    notify_all_alive_mafia_team,
    sync_mafia_mirror_panel,
)
from bot.game import is_synthetic_player_uid
from bot.observer_delivery import (
    PlayerMirrorCb,
    broadcast_to_alive_non_mafia_players,
    deliver_no_host_player_game_copy,
    no_host_observer_registered,
)

if TYPE_CHECKING:
    from bot.game import GameManager


def resolve_no_host_yaku_boss_uid(game: Game) -> int | None:
    """رییس مافیا — تنها کسی که فدا و هدف یاکوزایی را انتخاب می‌کند."""
    return _boss_role.yaku_boss_uid(game)


def no_host_yaku_boss_actor_may_act(
    game: Game, actor_uid: int, boss_uid: int
) -> bool:
    """فقط رییس مافیا (یا ناظر برای صندلی مصنوعی رییس) می‌تواند یاکوزایی را انجام دهد."""
    return _boss_role.yaku_boss_actor_may_act(game, actor_uid, boss_uid)


async def _notify_non_boss_mafia_yaku_observe(
    bot: Bot, game: Game, boss_uid: int, text: str
) -> None:
    """اعضای مافیا غیر از رییس — فقط مشاهده (بدون دکمه)."""
    for p in _alive_mafia_members(game):
        if p.user_id == boss_uid:
            continue
        await deliver_no_host_player_game_copy(
            bot,
            game,
            p.user_id,
            text,
            is_synthetic_uid=is_synthetic_player_uid,
            parse_mode="HTML",
        )


def build_no_host_yaku_denied_html() -> str:
    return (
        "🌙 <b>شب ۱ — یاکوزایی</b>\n\n"
        "⛔ <b>یاکوزایی مقدور نمی‌باشد.</b>"
    )


def build_no_host_yaku_sac_pick_html() -> str:
    return (
        "🌙 <b>شب ۱ — یاکوزایی</b>\n\n"
        "👑 <b>رییس مافیا</b> — چه کسی را برای فدا انتخاب می‌کنید؟\n\n"
        "از لیست زیر یک عضو تیم مافیا را انتخاب و سپس تأیید کنید."
    )


def build_no_host_yaku_sac_confirm_html(
    game: Game, gm: "GameManager", sac_uid: int
) -> str:
    p = game.players.get(sac_uid)
    tag = html.escape(gm.format_player_tag(p) if p else str(sac_uid))
    return (
        "🌙 <b>شب ۱ — تأیید فدای یاکوزایی</b>\n\n"
        f"🩸 فدا: <b>{tag}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_yaku_civ_pick_html() -> str:
    return (
        "🌙 <b>شب ۱ — یاکوزایی</b>\n\n"
        "👑 <b>رییس مافیا</b> — با چه بازیکنی (غیرمافیا) یاکوزایی انجام شود؟\n\n"
        "از لیست زیر یک نفر را انتخاب و سپس تأیید کنید."
    )


def build_no_host_yaku_civ_confirm_html(
    game: Game, gm: "GameManager", civ_uid: int
) -> str:
    p = game.players.get(civ_uid)
    tag = html.escape(gm.format_player_tag(p) if p else str(civ_uid))
    return (
        "🌙 <b>شب ۱ — تأیید هدف یاکوزایی</b>\n\n"
        f"🎯 هدف: <b>{tag}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_yaku_mafia_wait_html(success: bool, civ_tag: str) -> str:
    if success:
        return (
            "🌙 <b>شب ۱ — یاکوزایی</b>\n\n"
            f"✅ یاکوزایی شما با <b>{html.escape(civ_tag)}</b> موفق بود.\n"
            "و اکنون عضو تیم مافیاست.\n\n"
            "نام تمام اعضای تیم مافیا به شخص یاکوزایی‌شده فرستاده شده است.\n\n"
            "<i>تا پایان فاز شب منتظر بمانید.</i>"
        )
    return (
        "🌙 <b>شب ۱ — یاکوزایی</b>\n\n"
        "⭕ یاکوزایی شما موفق نبود.\n"
        "لطفاً منتظر باشید تا روز شود.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def _yaku_denied_keyboard(game: Game, mafia_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت به مرحله قبل",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="nmb", as_uid=mafia_uid
                    ).pack(),
                )
            ]
        ]
    )


def _confirm_keyboard(game: Game, mafia_uid: int, confirm_act: str, back_act: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔹 بله، تأیید انتخاب",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=confirm_act, as_uid=mafia_uid
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔹 بازگشت و تصحیح انتخاب",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=back_act, as_uid=mafia_uid
                    ).pack(),
                )
            ],
        ]
    )


def _pick_keyboard(
    game: Game,
    mafia_uid: int,
    gm: "GameManager",
    pool: list,
    pick_act: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sorted(
        pool,
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        name = html.escape(gm.format_player_tag(p)[:28])
        cb = PlayerMirrorCb(
            code=game.room_code, act=pick_act, as_uid=mafia_uid, tid=p.user_id
        ).pack()
        row.append(InlineKeyboardButton(text=name, callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_alive_mafia_team_html(
    game: Game,
    gm: "GameManager",
    *,
    exclude_uids: frozenset[int] | None = None,
    with_roles: bool = False,
) -> str:
    skip = exclude_uids or frozenset()
    lines: list[str] = []
    for p in sorted(
        (pl for pl in _alive(game) if _visually_mafia(game, pl)),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        if p.user_id in skip:
            continue
        tag = html.escape(gm.format_player_tag(p))
        if with_roles and p.role:
            role = html.escape(role_label_fa(p.role))
            lines.append(f"• {tag} — <i>{role}</i>")
        else:
            lines.append(f"• {tag}")
    return "\n".join(lines) if lines else "—"


def build_no_host_yaku_converted_player_html(
    game: Game, gm: "GameManager", civ_uid: int
) -> str:
    """پیام یاکوزایی موفق برای بازیکن تبدیل‌شده — نقش اعضا + فدا."""
    sac_uid = yaku_night_state(game).report_sac_uid
    sac_block = ""
    exclude: frozenset[int] = frozenset()
    if sac_uid is not None and sac_uid in game.players:
        sac = game.players[sac_uid]
        sac_tag = html.escape(gm.format_player_tag(sac))
        sac_role = (
            html.escape(role_label_fa(sac.role)) if sac.role else "—"
        )
        sac_block = (
            f"🩸 <b>فدای یاکوزایی:</b> {sac_tag} — <i>{sac_role}</i>\n\n"
        )
        exclude = frozenset({sac_uid})

    mafia_list = _format_alive_mafia_team_html(
        game, gm, exclude_uids=exclude, with_roles=True
    )
    return (
        "✅ <b>یاکوزایی با شما انجام شد و موفقیت‌آصندلی بود.</b>\n\n"
        "شما از این پس عضو <b>تیم مافیا</b> هستید.\n\n"
        f"{sac_block}"
        f"<b>اعضای زنده تیم مافیا:</b>\n{mafia_list}"
    )


async def _broadcast_yaku_wait_to_non_mafia(bot: Bot, game: Game) -> None:
    text = (
        "🌙 <b>شب — یاکوزایی</b>\n\n"
        "🩸 تیم مافیا در حال یاکوزایی است. لطفاً صبر کنید."
    )
    await broadcast_to_alive_non_mafia_players(
        bot,
        game,
        text,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )


async def _notify_converted_player(
    bot: Bot, game: Game, gm: "GameManager", civ_uid: int
) -> None:
    text = build_no_host_yaku_converted_player_html(game, gm, civ_uid)
    await deliver_no_host_player_game_copy(
        bot,
        game,
        civ_uid,
        text,
        is_synthetic_uid=is_synthetic_player_uid,
        parse_mode="HTML",
    )


async def _notify_mafia_outcome(
    bot: Bot, game: Game, gm: "GameManager", *, success: bool, civ_uid: int
) -> None:
    civ = game.players.get(civ_uid)
    civ_tag = gm.format_player_tag(civ) if civ else str(civ_uid)
    text = build_no_host_yaku_mafia_wait_html(success, civ_tag)
    await notify_all_alive_mafia_team(bot, game, text)


def _apply_yaku_outcome(
    game: Game, gm: "GameManager", *, sac_uid: int, civ_uid: int
) -> bool:
    tgt = game.players[civ_uid]
    sac = game.players[sac_uid]
    ok = _yaku_negotiation_succeeds(game, tgt)
    yaku = yaku_night_state(game)
    yaku.commit_outcome(civ_uid=civ_uid, sac_uid=sac_uid, success=ok)
    from bot.roles.doctor import void_night_pick

    void_night_pick(game)
    sac_role = (
        html.escape(role_label_fa(sac.role))
        if sac.role
        else html.escape(gm.format_player_tag(sac))
    )
    tgt_role = (
        html.escape(role_label_fa(tgt.role))
        if tgt.role
        else html.escape(gm.format_player_tag(tgt))
    )
    if ok:
        from bot.game import apply_bazpors_yakuzai_recruit

        apply_bazpors_yakuzai_recruit(game, tgt)
        game.bazpors_night_announce_lines.append(
            f"یاکوزای موفق: {sac_role} فدا شد؛ {tgt_role} به مافیا پیوست."
        )
    else:
        game.bazpors_night_announce_lines.append(
            f"یاکوزای ناموفق: {sac_role} فدا شد؛ {tgt_role} مافیا نشد."
        )
    yaku.mark_used()
    game.bazpors_narrator_pending_uid = None
    gm.check_winner(game)
    return ok


async def start_no_host_mafia_yaku_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if game.bazpors_host_mode != "no_host":
        return
    if game.no_host_mafia_night1_chosen_action != MAFIA_ACTION_YAKU:
        return
    yaku = yaku_night_state(game)
    if yaku.no_host_done or yaku.no_host_flow_active:
        return
    if not yakuzai_allowed(game, gm):
        return

    boss_uid = resolve_no_host_yaku_boss_uid(game)
    if boss_uid is None:
        return

    yaku.start_no_host_flow()

    await _broadcast_yaku_wait_to_non_mafia(bot, game)
    from bot.no_host_detective_night import (
        apply_no_host_detective_yaku_started_reselect_panel,
    )

    await apply_no_host_detective_yaku_started_reselect_panel(bot, game, gm)

    watch_text = (
        "🌙 <b>شب ۱ — یاکوزایی</b>\n\n"
        "👑 <b>رییس مافیا</b> در حال انتخاب فدا و هدف یاکوزایی است.\n"
        "<i>شما فقط مشاهده می‌کنید.</i>"
    )
    await _notify_non_boss_mafia_yaku_observe(bot, game, boss_uid, watch_text)

    sac_pool = _yaku_sacrifice_pool(game)
    text = build_no_host_yaku_sac_pick_html()
    kb = _pick_keyboard(game, boss_uid, gm, sac_pool, "ysp")
    await _edit_mafia_prompt(bot, game, boss_uid, text, kb)
    await sync_mafia_mirror_panel(bot, game, boss_uid, text, kb)

    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night1_mafia_yaku_flow_started",
            boss_uid=boss_uid,
            sac_pool_size=len(sac_pool),
        )
    except Exception:
        pass


async def _finalize_yaku_sac(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    boss_uid: int,
    actor_uid: int,
    sac_uid: int,
) -> None:
    yaku = yaku_night_state(game)
    yaku.finalize_no_host_sac(sac_uid)
    game.bazpors_night_substep = NS_YAKU_CIV

    watch_text = (
        "🌙 <b>شب ۱ — یاکوزایی</b>\n\n"
        "👑 رییس مافیا فدا را تأیید کرد؛ در حال انتخاب هدف یاکوزایی…\n"
        "<i>شما فقط مشاهده می‌کنید.</i>"
    )
    await _notify_non_boss_mafia_yaku_observe(bot, game, boss_uid, watch_text)

    text = build_no_host_yaku_civ_pick_html()
    civ_pool = _yaku_civilian_pool(game)
    kb = _pick_keyboard(game, boss_uid, gm, civ_pool, "ycp")
    await _edit_mafia_prompt(bot, game, boss_uid, text, kb)
    await sync_mafia_mirror_panel(bot, game, boss_uid, text, kb)

    await push_host_step(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night1_mafia_yaku_sac",
            sac_uid=sac_uid,
            boss_uid=boss_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass


async def _finalize_yaku_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    mafia_uid: int,
    actor_uid: int,
    sac_uid: int,
    civ_uid: int,
) -> None:
    yaku = yaku_night_state(game)
    if yaku.no_host_done:
        return
    yaku.finalize_no_host_flow()

    ok = _apply_yaku_outcome(game, gm, sac_uid=sac_uid, civ_uid=civ_uid)

    if ok:
        await _notify_converted_player(bot, game, gm, civ_uid)
    await _notify_mafia_outcome(bot, game, gm, success=ok, civ_uid=civ_uid)
    yaku.clear_sac_uid_after_ack()
    if (
        game.bazpors_night_substep in (NS_YAKU_SAC, NS_YAKU_CIV)
        and not game.no_host_night_parallel_collect_active
    ):
        _advance_after_mafia_menu_done(game)

    from bot.no_host_night_ready import no_host_refresh_after_mafia_sub_action

    await no_host_refresh_after_mafia_sub_action(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night1_mafia_yaku_done",
            success=ok,
            sac_uid=sac_uid,
            civ_uid=civ_uid,
            mafia_uid=mafia_uid,
        )
    except Exception:
        pass


def mafia_yaku_act_active(game: Game, act: str) -> bool:
    return act in ("ysp", "ysc", "ysb", "ycp", "ycc", "ycb")


async def dispatch_no_host_mafia_yaku(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    mafia_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    yaku = yaku_night_state(game)
    if not yaku.no_host_flow_active or yaku.no_host_done:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return

    boss_uid = resolve_no_host_yaku_boss_uid(game)
    if boss_uid is None:
        await callback.answer("رییس مافیا در بازی نیست.", show_alert=True)
        return
    if mafia_uid != boss_uid:
        await callback.answer(
            "انتخاب فدا و هدف یاکوزایی فقط با رییس مافیاست.",
            show_alert=True,
        )
        return
    if not no_host_yaku_boss_actor_may_act(game, actor_uid, boss_uid):
        await callback.answer(
            "فقط رییس مافیا می‌تواند این انتخاب را انجام دهد.",
            show_alert=True,
        )
        return
    if not _mafia_panel_has_uid(game, boss_uid):
        await callback.answer("پنل رییس مافیا فعال نیست.", show_alert=True)
        return

    phase = yaku.no_host_phase

    if act == "ysp" and phase == "sac":
        allowed = {p.user_id for p in _yaku_sacrifice_pool(game)}
        if tid not in allowed:
            await callback.answer("این بازیکن نمی‌تواند فدا شود.", show_alert=True)
            return
        yaku.no_host_pending_sac_uid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        confirm_text = build_no_host_yaku_sac_confirm_html(game, gm, tid)
        confirm_kb = _confirm_keyboard(game, boss_uid, "ysc", "ysb")
        await _edit_mafia_prompt(bot, game, boss_uid, confirm_text, confirm_kb)
        await sync_mafia_mirror_panel(bot, game, boss_uid, confirm_text, confirm_kb)
        return

    if act == "ysb" and phase == "sac":
        yaku.no_host_pending_sac_uid = None
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_yaku_sac_pick_html()
        kb = _pick_keyboard(
            game, boss_uid, gm, _yaku_sacrifice_pool(game), "ysp"
        )
        await _edit_mafia_prompt(bot, game, boss_uid, text, kb)
        await sync_mafia_mirror_panel(bot, game, boss_uid, text, kb)
        return

    if act == "ysc" and phase == "sac":
        sac = yaku.no_host_pending_sac_uid
        allowed = {p.user_id for p in _yaku_sacrifice_pool(game)}
        if sac is None or sac not in allowed:
            await callback.answer("ابتدا فدا را انتخاب کنید.", show_alert=True)
            return
        await callback.answer("تأیید شد.")
        await _finalize_yaku_sac(
            bot, game, gm, boss_uid=boss_uid, actor_uid=actor_uid, sac_uid=sac
        )
        return

    if act == "ycp" and phase == "civ":
        pool_ids = {p.user_id for p in _yaku_civilian_pool(game)}
        if tid not in pool_ids:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        yaku.no_host_pending_civ_uid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        confirm_text = build_no_host_yaku_civ_confirm_html(game, gm, tid)
        confirm_kb = _confirm_keyboard(game, boss_uid, "ycc", "ycb")
        await _edit_mafia_prompt(bot, game, boss_uid, confirm_text, confirm_kb)
        await sync_mafia_mirror_panel(bot, game, boss_uid, confirm_text, confirm_kb)
        return

    if act == "ycb" and phase == "civ":
        yaku.no_host_pending_civ_uid = None
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_yaku_civ_pick_html()
        kb = _pick_keyboard(
            game, boss_uid, gm, _yaku_civilian_pool(game), "ycp"
        )
        await _edit_mafia_prompt(bot, game, boss_uid, text, kb)
        await sync_mafia_mirror_panel(bot, game, boss_uid, text, kb)
        return

    if act == "ycc" and phase == "civ":
        civ = yaku.no_host_pending_civ_uid
        sac = yaku.sac_uid
        pool_ids = {p.user_id for p in _yaku_civilian_pool(game)}
        if civ is None or civ not in pool_ids:
            await callback.answer("ابتدا هدف را انتخاب کنید.", show_alert=True)
            return
        if sac is None or sac not in game.players:
            await callback.answer("خطا: فدا مشخص نیست.", show_alert=True)
            return
        if yaku.no_host_done:
            await callback.answer("یاکوزایی قبلاً ثبت شده است.", show_alert=True)
            return
        await callback.answer("تأیید شد.")
        await _finalize_yaku_flow(
            bot,
            game,
            gm,
            mafia_uid=boss_uid,
            actor_uid=actor_uid,
            sac_uid=sac,
            civ_uid=civ,
        )
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
