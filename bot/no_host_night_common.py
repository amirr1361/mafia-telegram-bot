"""اشتراک منطق فاز شب — مسیر گردانندگی بدون گرداننده."""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import TYPE_CHECKING

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NIGHT_START,
    no_host_assistant_narrator_active,
)
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.game import is_synthetic_player_uid
from bot.models import Game, Role
from bot.room_mode import is_no_host_player_room
from bot.roles.registry import get_role_module, find_alive_role_holder
from bot.observer_delivery import (
    PlayerMirrorCb,
    no_host_observer_registered,
    player_should_receive_game_messages,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)

if TYPE_CHECKING:
    from aiogram import Bot

    from bot.game import GameManager

NIGHT_WAIT_PHASE_STEPS = frozenset({NIGHT_START, NIGHT_ACTIONS})
NIGHT_WAIT_OK_ACT = "nwok"


def no_host_night_wait_phase_active(game: Game) -> bool:
    """بازیکنان می‌توانند در طول فاز شب (شروع یا اجرای نقش‌ها) تأیید/انتخاب کنند."""
    return (
        is_no_host_player_room(game)
        and no_host_assistant_narrator_active(game)
        and game.bazpors_narrator_step in NIGHT_WAIT_PHASE_STEPS
    )


def no_host_should_dispatch_night_entry(game: Game) -> bool:
    return (
        no_host_night_wait_phase_active(game)
        and game.bazpors_narrator_step == NIGHT_START
    )


def no_host_hunter_night1_player_self_serves(game: Game) -> bool:
    """هانتر انسانی (از جمله کمک‌کنندهٔ دارای نقش) — پنل در ورود شب با بقیه."""
    hunter = find_alive_role_holder(game, Role.HUNTER)
    if hunter is None:
        return False
    return not is_synthetic_player_uid(hunter.user_id)


def no_host_mafia_night1_player_self_serves(game: Game) -> bool:
    """حداقل یک دریافت‌کنندهٔ پنل مافیا انسان است — پنل در ورود شب."""
    from bot.no_host_mafia_night1 import resolve_mafia_night1_panel_recipients

    recipients = resolve_mafia_night1_panel_recipients(game)
    return any(
        not is_synthetic_player_uid(p.user_id)
        and player_should_receive_game_messages(game, p.user_id)
        for p in recipients
    )


def no_host_night1_needs_assistant_hunter(game: Game) -> bool:
    if game.no_host_night1_hunter_done:
        return False
    return (
        find_alive_role_holder(game, Role.HUNTER) is not None
        and not no_host_hunter_night1_player_self_serves(game)
    )


def no_host_night1_needs_assistant_mafia(game: Game) -> bool:
    if game.no_host_mafia_night1_done:
        return False
    from bot.no_host_mafia_chooser import (
        _alive_mafia_members,
        _yaku_recruit_panel_fallback,
    )

    if not _alive_mafia_members(game) and not _yaku_recruit_panel_fallback(game):
        return False
    return not no_host_mafia_night1_player_self_serves(game)


def maybe_advance_narrator_at_substep(
    game: Game, expected_substep: str, advance: Callable[[Game], None]
) -> bool:
    """فقط وقتی نریتور روی همان زیرمرحله است پیش ببرد (انتخاب زودهنگام نریتور را جلو نمی‌زند)."""
    if game.bazpors_night_substep != expected_substep:
        return False
    advance(game)
    return True


def no_host_night_wait_ok_keyboard(game: Game, uid: int) -> InlineKeyboardMarkup:
    return no_host_simple_ok_keyboard(game, uid)


def no_host_role_ack_keyboard(game: Game, uid: int, act: str) -> InlineKeyboardMarkup:
    """دکمهٔ اوکی با act اختصاصی نقش (cic، ruc، …) تا همان handler پنل را ببندد."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ اوکی",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=act, as_uid=uid
                    ).pack(),
                )
            ]
        ]
    )


def no_host_simple_ok_keyboard(game: Game, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ اوکی",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=NIGHT_WAIT_OK_ACT, as_uid=uid
                    ).pack(),
                )
            ]
        ]
    )


def format_night_selection_label(
    game: Game,
    gm: "GameManager",
    target_uid: int | None,
    *,
    none_label: str = "انتخابی ندارم",
) -> str:
    if target_uid is None:
        return none_label
    p = game.players.get(target_uid)
    return html.escape(gm.format_player_tag(p) if p else str(target_uid))


async def finalize_no_host_role_pick_message(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    player_uid: int,
    ui_key: str,
    selection_label: str,
) -> None:
    """پس از تأیید انتخاب نقش — همان پیام ویرایش می‌شود؛ بدون دکمه."""
    body = (
        f"✅ انتخاب شما: <b>{selection_label}</b>\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید."
    )
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        body,
        None,
        assistant_uid=player_uid,
        parse_mode="HTML",
    )


async def publish_no_host_night_ack_panel(
    bot: Bot,
    game: Game,
    player_uid: int,
    ui_key: str,
    text: str,
) -> None:
    """یک‌بار در شب — پیام انتظار + دکمهٔ اوکی (شهروند، رویین‌تن، …)."""
    body = _append_night_wait_button_hint(text)
    kb = no_host_simple_ok_keyboard(game, player_uid)
    if is_synthetic_player_uid(player_uid):
        if no_host_observer_registered(game):
            await update_mirror_prompt_pair(
                bot,
                game,
                ui_key,
                body,
                kb,
                assistant_uid=player_uid,
                parse_mode="HTML",
            )
        return
    if not player_should_receive_game_messages(game, player_uid):
        return
    await register_mirror_prompt_pair(
        bot,
        game,
        player_uid,
        ui_key,
        body,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


def arm_no_host_role_pick_flow(
    game: Game,
    *,
    flow_active_attr: str,
    pick_confirmed_attr: str,
    dm_signature_attr: str,
) -> None:
    """اگر پنل قبلاً فرستاده شده ولی flow_active اشتباهاً خاموش شده، دوباره فعال کن."""
    from bot.game_state import NO_HOST_ROLE_PICK_SPECS, arm_no_host_role_pick

    for spec in NO_HOST_ROLE_PICK_SPECS:
        if (
            spec.flow_active == flow_active_attr
            and spec.pick_confirmed == pick_confirmed_attr
            and spec.dm_signature == dm_signature_attr
        ):
            arm_no_host_role_pick(game, spec.role)
            return
    if getattr(game, pick_confirmed_attr):
        return
    if not getattr(game, flow_active_attr) and getattr(game, dm_signature_attr, None):
        setattr(game, flow_active_attr, True)


def _append_night_wait_button_hint(text: str) -> str:
    if "دکمه" in text:
        return text
    return (
        f"{text}\n\n"
        "دکمهٔ زیر را بزنید و تا پایان فاز شب منتظر بمانید."
    )


async def publish_no_host_night_wait_panel(
    bot: Bot,
    game: Game,
    player_uid: int,
    ui_key: str,
    text: str,
    *,
    gm: "GameManager | None" = None,
    selection_uid: int | None = None,
    selection_none_label: str = "انتخابی ندارم",
) -> None:
    """پس از انتخاب+تأیید نقش: فقط متن (بدون دکمه). برای ack با اوکی از publish_no_host_night_ack_panel."""
    if gm is not None:
        label = format_night_selection_label(
            game, gm, selection_uid, none_label=selection_none_label
        )
        await finalize_no_host_role_pick_message(
            bot, game, gm, player_uid, ui_key, label
        )
        return
    await publish_no_host_night_ack_panel(bot, game, player_uid, ui_key, text)


def no_host_night_wait_ok_act_active(game: Game, act: str) -> bool:
    return act == NIGHT_WAIT_OK_ACT


def _night_wait_ok_confirmed_body() -> str:
    return (
        "✅ تأیید شما ثبت شد.\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید."
    )


async def dismiss_no_host_night_wait_panel(
    bot: Bot,
    game: Game,
    as_uid: int,
    *,
    body: str | None = None,
) -> bool:
    """پس از زدن اوکی — همان پیام آینه بدون دکمه ویرایش می‌شود."""
    from bot.observer_delivery import mirror_ui_claim_key

    text = body or _night_wait_ok_confirmed_body()
    prefixes = (
        "no_host_citizen",
        "no_host_ruintan",
        "no_host_sniper",
        "no_host_interrog",
        "no_host_doctor",
        "no_host_detective",
        "no_host_journalist",
        "no_host_shiad",
        "no_host_hunter",
    )
    for prefix in prefixes:
        ui_key = mirror_ui_claim_key(game.room_code, prefix, as_uid)
        if not game.mirror_prompt_messages.get(ui_key):
            continue
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            text,
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )
        return True
    return False


async def dispatch_no_host_night_wait_ok(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    as_uid: int,
    actor_uid: int,
) -> None:
    from bot.observer_delivery import no_host_observer_registered

    if not no_host_night_wait_phase_active(game):
        await callback.answer("این مرحله فعال نیست.", show_alert=True)
        return
    pl = game.players.get(as_uid)
    if pl is None:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    if is_synthetic_player_uid(as_uid):
        if not (
            no_host_observer_registered(game)
            and game.observer_user_id == actor_uid
        ):
            await callback.answer("نامعتبر.", show_alert=True)
            return
    elif actor_uid != as_uid:
        await callback.answer("فقط خود بازیکن می‌تواند تأیید کند.", show_alert=True)
        return

    citizen_mod = get_role_module(Role.CITIZEN)
    if pl.is_alive and citizen_mod is not None and citizen_mod.is_simple_citizen(pl):
        from bot.no_host_citizen_night import (
            _citizen_confirmed,
            _mark_citizen_confirmed,
            build_no_host_citizen_night_html,
            _citizen_ui_key,
        )

        if _citizen_confirmed(game, as_uid):
            await callback.answer("قبلاً تأیید کرده‌اید.")
            return
        _mark_citizen_confirmed(game, as_uid)
        await callback.answer("تأیید ثبت شد.")
        await update_mirror_prompt_pair(
            bot,
            game,
            _citizen_ui_key(game, as_uid),
            build_no_host_citizen_night_html(confirmed=True),
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )
        from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

        await maybe_finish_no_host_parallel_night(bot, game, gm)
        return

    if pl.is_alive and pl.role == Role.RUINTAN:
        from bot.no_host_ruintan_night import (
            build_no_host_ruintan_night_html,
            _ruintan_ui_key,
        )
        
        ru = find_alive_role_holder(game, Role.RUINTAN)
        if ru is None or ru.user_id != as_uid:
            await callback.answer("رویین‌تن در بازی نیست.", show_alert=True)
            return
        if game.no_host_ruintan_night_confirmed:
            await callback.answer("قبلاً تأیید کرده‌اید.")
            return
        game.no_host_ruintan_night_confirmed = True
        await callback.answer("تأیید ثبت شد.")
        await update_mirror_prompt_pair(
            bot,
            game,
            _ruintan_ui_key(game, as_uid),
            build_no_host_ruintan_night_html(confirmed=True),
            None,
            assistant_uid=as_uid,
            parse_mode="HTML",
        )
        from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

        await maybe_finish_no_host_parallel_night(bot, game, gm)
        return

    if await dismiss_no_host_night_wait_panel(bot, game, as_uid):
        await callback.answer("ثبت شد؛ تا پایان فاز شب منتظر بمانید.")
        return

    await callback.answer("قبلاً ثبت شده است.")


async def no_host_after_role_night_pick(
    bot: Bot,
    game: Game,
    gm: GameManager,
    *,
    expected_substep: str | None = None,
    advance: Callable[[Game], None] | None = None,
) -> None:
    """پس از ثبت انتخاب نقش: در جمع‌آوری موازی دروازهٔ پایان شب، وگرنه پیش‌برد نریتور."""
    from bot.bazpors_narrator import push_host_step
    from bot.no_host_night_ready import (
        maybe_finish_no_host_parallel_night,
        no_host_parallel_night_collect_active,
    )
    if no_host_parallel_night_collect_active(game):
        await maybe_finish_no_host_parallel_night(bot, game, gm)
        return
    if (
        expected_substep
        and advance
        and maybe_advance_narrator_at_substep(game, expected_substep, advance)
    ):
        await push_host_step(bot, game, gm)
