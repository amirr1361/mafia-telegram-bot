"""شب ۱ — ناتویی توسط بازیکن ناتو (حالت بدون گرداننده)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NS_NATO_ROLE,
    _advance_after_mafia_menu_done,
    nato_denied_message,
    push_host_step,
    role_label_fa,
)
from bot.game import is_synthetic_player_uid
from bot.models import Game, Player, Role
from bot.roles.registry import find_alive_role_holder, require_role_module

_nato_role = require_role_module(Role.NATO)
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_NATO,
    notify_all_alive_mafia_team,
)
from bot.no_host_role_pick_common import (
    append_pending_selection_line,
    apply_bazpors_panel_styles,
    with_inline_confirm_row,
)
from bot.observer_delivery import (
    PlayerMirrorCb,
    apply_mirror_claim_winner,
    broadcast_to_alive_players,
    mirror_ui_claim_key,
    no_host_observer_registered,
    player_should_receive_game_messages,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)
from bot.room_mode import is_mason_scenario
from bot.tg_send import safe_send_message

if TYPE_CHECKING:
    from bot.game import GameManager


def no_host_nato_allowed(game: Game) -> bool:
    if is_mason_scenario(game):
        from bot.roles.mason_godfather import mason_nato_can_register

        return mason_nato_can_register(game)
    return _nato_role.can_register(game)


def build_no_host_nato_denied_html(game: Game) -> str:
    return (
        "🌙 <b>شب ۱ — ناتویی</b>\n\n"
        f"⛔ {html.escape(nato_denied_message(game))}"
    )


def build_no_host_nato_role_pick_html() -> str:
    return (
        "🌙 <b>شب ۱ — ناتویی</b>\n\n"
        "🎭 چه <b>نقشی</b> را می‌خواهید حدس بزنید؟\n\n"
        "فقط نقش‌های شهروندِ دارای قابلیت (غیر از شهروند ساده) که در این اتاق "
        "ثبت شده‌اند (زنده یا از بازی‌رفته) در لیست هستند.\n\n"
        "حداقل و حداکثر یک نقش را انتخاب کنید."
    )


def build_no_host_nato_role_confirm_html(role: Role) -> str:
    label = html.escape(role_label_fa(role))
    return (
        "🌙 <b>شب ۱ — تأیید نقش حدس‌زده</b>\n\n"
        f"🎭 نقش انتخابی: <b>{label}</b>\n\n"
        "آیا این نقش را تأیید می‌کنید؟"
    )


def build_no_host_nato_player_pick_html(role: Role) -> str:
    label = html.escape(role_label_fa(role))
    return (
        "🌙 <b>شب ۱ — ناتویی</b>\n\n"
        f"🎭 نقش حدس‌زده: <b>{label}</b>\n\n"
        "فکر می‌کنید این نقش متعلق به کدام بازیکن زنده است؟\n\n"
        "از لیست زیر یک نام را انتخاب و سپس تأیید کنید."
    )


def build_no_host_nato_player_confirm_html(
    game: Game, gm: "GameManager", target_uid: int
) -> str:
    p = game.players.get(target_uid)
    tag = html.escape(gm.format_player_tag(p) if p else str(target_uid))
    return (
        "🌙 <b>شب ۱ — تأیید هدف ناتویی</b>\n\n"
        f"👤 بازیکن انتخابی: <b>{tag}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_nato_nato_waiting_html() -> str:
    return (
        "🌙 <b>شب ۱ — ناتویی</b>\n\n"
        "✅ انتخاب شما ثبت شد.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def build_mason_nato_role_pick_html() -> str:
    return "چه نقشی را برای ناتویی انتخاب می‌کنید؟"


def build_mason_nato_player_pick_html() -> str:
    return "فکر می‌کنید این نقش متعلق به چه کسی است؟"


def build_mason_nato_wait_broadcast_html() -> str:
    return "تیم مافیا در حال ناتویی..."


def build_no_host_nato_wait_broadcast_html() -> str:
    return (
        "🌙 <b>شب — ناتویی</b>\n\n"
        "🎭 تیم مافیا در حال ناتویی است. لطفاً منتظر باشید."
    )


def _nato_role_pick_html(game: Game) -> str:
    if is_mason_scenario(game):
        return build_mason_nato_role_pick_html()
    return build_no_host_nato_role_pick_html()


def _nato_player_pick_html(game: Game, role: Role) -> str:
    if is_mason_scenario(game):
        return build_mason_nato_player_pick_html()
    return build_no_host_nato_player_pick_html(role)


def build_no_host_nato_done_broadcast_html() -> str:
    return (
        "🌙 <b>شب — ناتویی</b>\n\n"
        "🎭 انتخاب ناتو ثبت شد. لطفاً تا پایان فاز شب صبر کنید."
    )


def build_no_host_nato_mafia_summary_html(
    game: Game, gm: "GameManager", *, role: Role, target_uid: int
) -> str:
    p = game.players.get(target_uid)
    role_txt = html.escape(role_label_fa(role))
    name_txt = html.escape(gm.format_player_tag(p) if p else str(target_uid))
    return (
        "🌙 <b>شب ۱ — ناتویی</b>\n\n"
        f"🎭 ناتو نقش <b>{role_txt}</b> را حدس زده و "
        f"بازیکن <b>{name_txt}</b> را به‌عنوان هدف ناتویی انتخاب کرده است.\n\n"
        "<i>منتظر بمانید تا پایان فاز شب.</i>"
    )


def _nato_denied_keyboard(game: Game, mafia_uid: int) -> InlineKeyboardMarkup:
    return apply_bazpors_panel_styles(
        game,
        InlineKeyboardMarkup(
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
        ),
        ok_acts={"nmb"},
    )


def _nato_ui_key(game: Game, nato_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "night1_nato", nato_uid)


def _nato_role_confirm_claim_key(game: Game) -> str:
    return mirror_ui_claim_key(game.room_code, "night1_nato_role_confirm", 0)


def _nato_player_confirm_claim_key(game: Game) -> str:
    return mirror_ui_claim_key(game.room_code, "night1_nato_player_confirm", 0)


def _non_mafia_roles_in_room(game: Game) -> list[Role]:
    return _nato_role.non_mafia_roles_in_room(game)


def _nato_guess_roles_in_room(game: Game) -> list[Role]:
    if is_mason_scenario(game):
        from bot.roles.mason_nato import mason_nato_guess_roles_in_room

        return mason_nato_guess_roles_in_room(game)
    return _nato_role.guess_roles_in_room(game)


def _nato_player_pool(game: Game) -> list[Player]:
    if is_mason_scenario(game):
        from bot.roles.mason_nato import mason_nato_target_pool

        return mason_nato_target_pool(game)
    return _nato_role.target_pool(game)


def _parse_nato_role_act(act: str) -> str | None:
    if act.startswith("n1r-"):
        return act[4:]
    return None


def _confirm_keyboard(
    game: Game, nato_uid: int, confirm_act: str, back_act: str
) -> InlineKeyboardMarkup:
    return apply_bazpors_panel_styles(
        game,
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔹 بله، تأیید انتخاب",
                        callback_data=PlayerMirrorCb(
                            code=game.room_code, act=confirm_act, as_uid=nato_uid
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔹 بازگشت و تصحیح انتخاب",
                        callback_data=PlayerMirrorCb(
                            code=game.room_code, act=back_act, as_uid=nato_uid
                        ).pack(),
                    )
                ],
            ]
        ),
        ok_acts={confirm_act, back_act},
    )


def _nato_role_pending_line(game: Game) -> str:
    role_val = game.no_host_mafia_nato_pending_role
    if role_val:
        try:
            return (
                "🎭 انتخاب فعلی: <b>"
                + html.escape(role_label_fa(Role(role_val)))
                + "</b>"
            )
        except ValueError:
            pass
    return "🎭 انتخاب فعلی: <i>هنوز انتخابی ثبت نشده است</i>"


def _nato_player_pending_line(game: Game, gm: "GameManager") -> str:
    tid = game.no_host_mafia_nato_pending_target_uid
    if tid is not None:
        p = game.players.get(tid)
        tag = html.escape(gm.format_player_tag(p) if p else str(tid))
        return f"👤 انتخاب فعلی: <b>{tag}</b>"
    return "👤 انتخاب فعلی: <i>هنوز انتخابی ثبت نشده است</i>"


def _role_pick_keyboard(game: Game, nato_uid: int) -> InlineKeyboardMarkup:
    guess_roles = _nato_guess_roles_in_room(game)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for role in guess_roles:
        label = role_label_fa(role)[:28]
        cb = PlayerMirrorCb(
            code=game.room_code,
            act=f"n1r-{role.value}",
            as_uid=nato_uid,
        ).pack()
        row.append(InlineKeyboardButton(text=label, callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    ok_acts = {f"n1r-{role.value}" for role in guess_roles}
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if game.scenario_name == "bazpors":
        # بازپرس — نقش انتخابی قرمز، بقیه آبی + تأیید سبز از رندر اولیه.
        pending = game.no_host_mafia_nato_pending_role
        kb = apply_bazpors_panel_styles(
            game,
            kb,
            ok_acts=ok_acts,
            selected_acts={f"n1r-{pending}"} if pending else set(),
        )
        kb = with_inline_confirm_row(game, nato_uid, kb, confirm_act="n1c")
        return kb
    return apply_bazpors_panel_styles(game, kb, ok_acts=ok_acts)


def _player_pick_keyboard(
    game: Game, nato_uid: int, gm: "GameManager"
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sorted(
        _nato_player_pool(game),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        name = html.escape(gm.format_player_tag(p)[:28])
        cb = PlayerMirrorCb(
            code=game.room_code, act="n2p", as_uid=nato_uid, tid=p.user_id
        ).pack()
        row.append(InlineKeyboardButton(text=name, callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    pending_target = game.no_host_mafia_nato_pending_target_uid
    kb = apply_bazpors_panel_styles(
        game,
        InlineKeyboardMarkup(inline_keyboard=rows),
        pick_acts={"n2p"},
        selected_uids=[pending_target] if pending_target is not None else [],
    )
    if game.scenario_name == "bazpors":
        # تأیید سبز از رندر اولیه — مرحلهٔ انتخاب بازیکن با تأیید نهایی می‌بندد.
        kb = with_inline_confirm_row(game, nato_uid, kb, confirm_act="n2c")
    return kb


def _nato_pending_role_val(game: Game) -> str:
    """نقش تأییدشدهٔ مرحلهٔ اول ناتو — برای بازسازی متن دکمه‌ها."""
    if is_mason_scenario(game):
        return game.mason_nato_pending_role or ""
    return game.no_host_mafia_nato_pending_role or game.bazpors_nato_guess_role or ""


def _actor_may_use_nato_panel(game: Game, actor_uid: int, nato_uid: int) -> bool:
    if game.no_host_mafia_nato_player_uid is None:
        return False
    if nato_uid != game.no_host_mafia_nato_player_uid:
        return False
    if actor_uid == nato_uid:
        return True
    return (
        no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


def _apply_nato_guess_to_game(
    game: Game, gm: "GameManager", *, guess_role: Role, target_uid: int
) -> None:
    if is_mason_scenario(game):
        from bot.roles.mason_nato import commit_mason_nato_guess

        commit_mason_nato_guess(game, guess_role, target_uid)
        return
    _nato_role.commit_guess(
        game, guess_role, target_uid, gm=gm, announce=True
    )


async def _broadcast_nato_wait_to_alive(bot: Bot, game: Game, gm: "GameManager | None" = None) -> None:
    """همگانی به همهٔ بازیکنان زنده — شامل آپاچی در ماسون."""
    text = (
        build_mason_nato_wait_broadcast_html()
        if is_mason_scenario(game)
        else build_no_host_nato_wait_broadcast_html()
    )
    await broadcast_to_alive_players(
        bot,
        game,
        text,
        parse_mode="HTML" if not is_mason_scenario(game) else None,
        is_synthetic_uid=is_synthetic_player_uid,
    )
    if is_mason_scenario(game) and gm is not None:
        from bot.mason_night_role import apply_mason_doctor_nato_void_panel

        await apply_mason_doctor_nato_void_panel(bot, game, gm)


async def _broadcast_nato_done_to_alive(bot: Bot, game: Game) -> None:
    await broadcast_to_alive_players(
        bot,
        game,
        build_no_host_nato_done_broadcast_html(),
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )


async def _notify_mafia_nato_summary(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    role: Role,
    target_uid: int,
) -> None:
    text = build_no_host_nato_mafia_summary_html(
        game, gm, role=role, target_uid=target_uid
    )
    await notify_all_alive_mafia_team(bot, game, text)


async def start_no_host_mafia_nato_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if game.bazpors_host_mode != "no_host":
        return
    if game.no_host_mafia_night1_chosen_action != MAFIA_ACTION_NATO:
        return
    if game.no_host_mafia_nato_done or game.no_host_mafia_nato_flow_active:
        return

    nato = find_alive_role_holder(game, Role.NATO)
    if nato is None:
        return

    roles = _nato_guess_roles_in_room(game)
    if not roles:
        return

    game.no_host_mafia_nato_flow_active = True
    game.no_host_mafia_nato_phase = "role"
    game.no_host_mafia_nato_player_uid = nato.user_id
    game.no_host_mafia_nato_pending_role = None
    game.no_host_mafia_nato_pending_target_uid = None

    await _broadcast_nato_wait_to_alive(bot, game, gm)

    text = _nato_role_pick_html(game)
    kb = _role_pick_keyboard(game, nato.user_id)
    ui_key = _nato_ui_key(game, nato.user_id)
    await register_mirror_prompt_pair(
        bot,
        game,
        nato.user_id,
        ui_key,
        text,
        kb,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def _finalize_nato_flow(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    nato_uid: int,
    guess_role: Role,
    target_uid: int,
) -> None:
    if game.no_host_mafia_nato_done:
        return
    game.no_host_mafia_nato_flow_active = False
    game.no_host_mafia_nato_done = True
    game.no_host_mafia_nato_phase = None
    game.no_host_mafia_nato_pending_role = None
    game.no_host_mafia_nato_pending_target_uid = None

    _apply_nato_guess_to_game(game, gm, guess_role=guess_role, target_uid=target_uid)

    ui_key = _nato_ui_key(game, nato_uid)
    wait_text = build_no_host_nato_nato_waiting_html()
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        wait_text,
        None,
        assistant_uid=nato_uid,
        parse_mode="HTML",
    )

    if not is_mason_scenario(game):
        await _notify_mafia_nato_summary(
            bot, game, gm, role=guess_role, target_uid=target_uid
        )
        await _broadcast_nato_done_to_alive(bot, game)

        from bot.no_host_doctor_night import apply_no_host_doctor_nato_blocked_panel

        await apply_no_host_doctor_nato_blocked_panel(bot, game, gm)

    if (
        game.bazpors_night_substep == NS_NATO_ROLE
        and not game.no_host_night_parallel_collect_active
    ):
        _advance_after_mafia_menu_done(game)

    from bot.no_host_night_ready import no_host_refresh_after_mafia_sub_action

    await no_host_refresh_after_mafia_sub_action(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night1_mafia_nato_done",
            nato_uid=nato_uid,
            guess_role=guess_role.value,
            target_uid=target_uid,
            success=(
                None
                if is_mason_scenario(game)
                else game.bazpors_nato_success
            ),
        )
    except Exception:
        pass


def mafia_nato_act_active(game: Game, act: str) -> bool:
    if act in ("n1c", "n1b", "n2p", "n2c", "n2b"):
        return True
    return _parse_nato_role_act(act) is not None


async def dispatch_no_host_mafia_nato(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    nato_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    from bot.mason_force_finish_night import reject_mason_night_callback_if_closed

    if await reject_mason_night_callback_if_closed(callback, game):
        return
    if not game.no_host_mafia_nato_flow_active or game.no_host_mafia_nato_done:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    if not _actor_may_use_nato_panel(game, actor_uid, nato_uid):
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return

    ui_key = _nato_ui_key(game, nato_uid)
    phase = game.no_host_mafia_nato_phase

    role_val = _parse_nato_role_act(act)
    if role_val is not None and phase == "role":
        try:
            guess_role = Role(role_val)
        except ValueError:
            await callback.answer("نقش نامعتبر.", show_alert=True)
            return
        if guess_role not in _nato_guess_roles_in_room(game):
            await callback.answer("این نقش در اتاق نیست.", show_alert=True)
            return
        game.no_host_mafia_nato_pending_role = role_val
        if game.scenario_name == "bazpors":
            # بازپرس — پنل نقش‌ها با نقش انتخابی قرمز + تأیید سبز در همان صفحه.
            await callback.answer("انتخاب شد؛ تأیید کنید.")
            text = append_pending_selection_line(
                _nato_role_pick_html(game),
                [_nato_role_pending_line(game)],
            )
            kb = _role_pick_keyboard(game, nato_uid)
            await update_mirror_prompt_pair(
                bot,
                game,
                ui_key,
                text,
                kb,
                assistant_uid=nato_uid,
                parse_mode="HTML",
            )
            return
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        confirm_text = build_no_host_nato_role_confirm_html(guess_role)
        confirm_kb = _confirm_keyboard(game, nato_uid, "n1c", "n1b")
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            confirm_text,
            confirm_kb,
            assistant_uid=nato_uid,
            parse_mode="HTML",
        )
        return

    if act == "n1b" and phase == "role":
        game.no_host_mafia_nato_pending_role = None
        await callback.answer("بازگشت به لیست نقش‌ها.")
        text = _nato_role_pick_html(game)
        kb = _role_pick_keyboard(game, nato_uid)
        await update_mirror_prompt_pair(
            bot, game, ui_key, text, kb, assistant_uid=nato_uid, parse_mode="HTML"
        )
        return

    if act == "n1c" and phase == "role":
        role_val = game.no_host_mafia_nato_pending_role
        if not role_val:
            await callback.answer("ابتدا یک نقش انتخاب کنید.", show_alert=True)
            return
        try:
            guess_role = Role(role_val)
        except ValueError:
            await callback.answer("نقش نامعتبر.", show_alert=True)
            return
        claim_key = _nato_role_confirm_claim_key(game)
        existing = game.mirror_action_claims.get(claim_key)
        if existing is not None and existing != actor_uid:
            await callback.answer("این مرحله قبلاً تأیید شده است.", show_alert=True)
            return
        if existing is None:
            game.mirror_action_claims[claim_key] = actor_uid
            if no_host_observer_registered(game):
                await apply_mirror_claim_winner(
                    bot, game, ui_key, actor_uid, nato_uid
                )
        game.no_host_mafia_nato_phase = "player"
        if not is_mason_scenario(game):
            game.bazpors_nato_guess_role = role_val
            game.bazpors_night_substep = NS_NATO_ROLE
        else:
            game.mason_nato_pending_role = role_val
        await callback.answer("تأیید شد.")
        pick_text = _nato_player_pick_html(game, guess_role)
        pick_kb = _player_pick_keyboard(game, nato_uid, gm)
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            pick_text,
            pick_kb,
            assistant_uid=nato_uid,
            parse_mode="HTML",
        )
        return

    if act == "n2p" and phase == "player":
        pool_ids = {p.user_id for p in _nato_player_pool(game)}
        if tid not in pool_ids:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        if game.scenario_name == "bazpors":
            if game.no_host_mafia_nato_pending_target_uid == tid:
                # زدن دوباره روی انتخاب فعلی = لغو انتخاب (بازگشت به لیست).
                game.no_host_mafia_nato_pending_target_uid = None
                await callback.answer("انتخاب لغو شد.")
            else:
                game.no_host_mafia_nato_pending_target_uid = tid
                await callback.answer("انتخاب شد؛ تأیید کنید.")
            # بازپرس — پنل بازیکن‌ها با هدف قرمز + تأیید سبز در همان صفحه.
            text = append_pending_selection_line(
                _nato_player_pick_html(game, Role(_nato_pending_role_val(game))),
                [_nato_player_pending_line(game, gm)],
            )
            kb = _player_pick_keyboard(game, nato_uid, gm)
            await update_mirror_prompt_pair(
                bot,
                game,
                ui_key,
                text,
                kb,
                assistant_uid=nato_uid,
                parse_mode="HTML",
            )
            return
        game.no_host_mafia_nato_pending_target_uid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        confirm_text = build_no_host_nato_player_confirm_html(game, gm, tid)
        confirm_kb = _confirm_keyboard(game, nato_uid, "n2c", "n2b")
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            confirm_text,
            confirm_kb,
            assistant_uid=nato_uid,
            parse_mode="HTML",
        )
        return

    if act == "n2b" and phase == "player":
        game.no_host_mafia_nato_pending_target_uid = None
        role_val = (
            game.mason_nato_pending_role
            if is_mason_scenario(game)
            else (game.no_host_mafia_nato_pending_role or game.bazpors_nato_guess_role)
        )
        if not role_val:
            await callback.answer("خطا.", show_alert=True)
            return
        guess_role = Role(role_val)
        await callback.answer("بازگشت به لیست بازیکنان.")
        pick_text = _nato_player_pick_html(game, guess_role)
        pick_kb = _player_pick_keyboard(game, nato_uid, gm)
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            pick_text,
            pick_kb,
            assistant_uid=nato_uid,
            parse_mode="HTML",
        )
        return

    if act == "n2c" and phase == "player":
        target_uid = game.no_host_mafia_nato_pending_target_uid
        role_val = (
            game.mason_nato_pending_role
            if is_mason_scenario(game)
            else (game.no_host_mafia_nato_pending_role or game.bazpors_nato_guess_role)
        )
        pool_ids = {p.user_id for p in _nato_player_pool(game)}
        if target_uid is None or target_uid not in pool_ids:
            await callback.answer("ابتدا یک بازیکن انتخاب کنید.", show_alert=True)
            return
        if not role_val:
            await callback.answer("خطا: نقش حدس‌زده مشخص نیست.", show_alert=True)
            return
        try:
            guess_role = Role(role_val)
        except ValueError:
            await callback.answer("خطا.", show_alert=True)
            return
        claim_key = _nato_player_confirm_claim_key(game)
        existing = game.mirror_action_claims.get(claim_key)
        if existing is not None and existing != actor_uid:
            await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
            return
        if existing is None:
            game.mirror_action_claims[claim_key] = actor_uid
            if no_host_observer_registered(game):
                await apply_mirror_claim_winner(
                    bot, game, ui_key, actor_uid, nato_uid
                )
        if game.no_host_mafia_nato_done:
            await callback.answer("ناتویی قبلاً ثبت شده است.", show_alert=True)
            return
        await callback.answer("ثبت شد.")
        await _finalize_nato_flow(
            bot,
            game,
            gm,
            nato_uid=nato_uid,
            guess_role=guess_role,
            target_uid=target_uid,
        )
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
