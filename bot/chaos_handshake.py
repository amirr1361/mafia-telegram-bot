"""فاز آشوب — دست دادن سه‌نفره (۱ مافیا + ۲ شهروند)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    CHAOS_DAY_HANDSHAKE,
    CHAOS_PHASE_LABEL,
    _ki_as_counts_met,
    _sync_ki_as_today,
    push_host_step,
)
from bot.game import bazpors_counts_as_mafia_faction, is_synthetic_player_uid
from bot.models import Game, Player
from bot.observer_delivery import (
    PlayerMirrorCb,
    broadcast_to_alive_players,
    mirror_ui_claim_key,
    no_host_observer_registered,
    player_should_receive_game_messages,
    send_to_bot_assistant,
    send_to_player,
    update_mirror_prompt_pair,
)
from bot.tg_send import safe_callback_answer

if TYPE_CHECKING:
    from bot.game import GameManager

CHAOS_HANDSHAKE_PROMPT_HTML = (
    "🤝 <b>تصمیم آخر</b>\n\n"
    "فقط ۳ بازیکن در بازی باقی مانده‌اند.\n"
    "لطفاً انتخاب کنید با کدام بازیکن می‌خواهید دست بدهید.\n\n"
    "⚠️ دست دادن فقط زمانی معتبر است که هر دو نفر همدیگر را انتخاب کرده باشند."
)

CHAOS_HANDSHAKE_WAITING_HTML = (
    "🤝 <b>تصمیم آخر</b>\n\n"
    "✅ انتخاب شما ثبت شد.\n\n"
    "<i>منتظر انتخاب دو بازیکن دیگر بمانید.</i>"
)

CHAOS_RETRY_BROADCAST_HTML = (
    "⚠️ هیچ دست دادن دوطرفه‌ای ثبت نشد.\n"
    "بازیکنان باید دوباره انتخاب کنند."
)

RESULT_CITIZENS_HTML = (
    "🏆 <b>شهروندها برنده شدند.</b>\n\n"
    "🤝 دست دادن نهایی بین دو شهروند انجام شد."
)

RESULT_MAFIA_HTML = (
    "🏆 <b>تیم مافیا برنده شد.</b>\n\n"
    "🤝 دست دادن نهایی بین مافیا و شهروند انجام شد."
)


class ChaosHandshakeCb(CallbackData, prefix="chs"):
    """chaos_handshake:{code}:{round}:{chooser}:{target} — بستهٔ aiogram."""

    code: str
    rnd: int
    ch: int
    tgt: int


def chaos_handshake_mirror_act_active(game: Game, act: str) -> bool:
    return (
        act == "chs"
        and game.bazpors_narrator_step == CHAOS_DAY_HANDSHAKE
    )


def reset_chaos_handshake_state(game: Game) -> None:
    game.bazpors_chaos_handshake_round = 0
    game.bazpors_chaos_choices.clear()


def chaos_handshake_phase_active(game: Game) -> bool:
    return game.bazpors_narrator_step == CHAOS_DAY_HANDSHAKE


def find_valid_handshake(chaos_choices: dict[int, int]) -> tuple[int, int] | None:
    seen: set[tuple[int, int]] = set()
    for chooser_id, target_id in chaos_choices.items():
        if chaos_choices.get(target_id) == chooser_id:
            pair = tuple(sorted((chooser_id, target_id)))
            if pair not in seen:
                return pair
            seen.add(pair)
    return None


def _player_team(game: Game, uid: int) -> str:
    p = game.players.get(uid)
    if p is None:
        return "unknown"
    return (
        "mafia"
        if bazpors_counts_as_mafia_faction(game, p)
        else "citizen"
    )


def decide_chaos_winner(
    game: Game, chaos_choices: dict[int, int]
) -> dict[str, Any]:
    pair = find_valid_handshake(chaos_choices)
    if not pair:
        return {"winner": "no_valid_handshake", "pair": None}

    p1_id, p2_id = pair
    p1_team = _player_team(game, p1_id)
    p2_team = _player_team(game, p2_id)

    if p1_team == "citizen" and p2_team == "citizen":
        return {"winner": "citizens", "pair": pair}

    if "mafia" in {p1_team, p2_team}:
        return {"winner": "mafia", "pair": pair}

    return {"winner": "unknown", "pair": pair}


def _chaos_ui_key(game: Game, player_uid: int) -> str:
    rnd = max(1, game.bazpors_chaos_handshake_round)
    return mirror_ui_claim_key(game.room_code, f"chaos_hs_{rnd}", player_uid)


def _handshake_keyboard(
    game: Game, gm: "GameManager", chooser: Player, *, mirror: bool
) -> InlineKeyboardMarkup:
    rnd = game.bazpors_chaos_handshake_round
    code = game.room_code
    rows: list[list[InlineKeyboardButton]] = []
    for target in sorted(
        (p for p in game.players.values() if p.is_alive and p.user_id != chooser.user_id),
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    ):
        label = html.escape(gm.format_player_tag(target)[:28])
        if mirror:
            cb = PlayerMirrorCb(
                code=code,
                act="chs",
                as_uid=chooser.user_id,
                tid=target.user_id,
                rid=str(rnd),
            ).pack()
        else:
            cb = ChaosHandshakeCb(
                code=code, rnd=rnd, ch=chooser.user_id, tgt=target.user_id
            ).pack()
        rows.append(
            [InlineKeyboardButton(text=f"🤝 دست دادن با {label}", callback_data=cb)]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_chaos_assistant_panel_html(game: Game, gm: "GameManager") -> str:
    alive = [p for p in game.players.values() if p.is_alive]
    n_chosen = len(game.bazpors_chaos_choices)
    rnd = max(1, game.bazpors_chaos_handshake_round)
    lines = [
        f"🤝 <b>{CHAOS_PHASE_LABEL}</b>",
        f"دور دست دادن: <b>{rnd}</b>",
        "",
        f"انتخاب ثبت‌شده: <b>{n_chosen}</b> از <b>{len(alive)}</b>",
        "",
        "به هر بازیکن زنده در همان چت ربات پیام با دو دکمه فرستاده شده است.",
        "پس از ثبت هر سه انتخاب، نتیجهٔ دست دوطرفه محاسبه می‌شود.",
    ]
    if n_chosen >= len(alive) and len(alive) == 3:
        lines.append("")
        lines.append("<i>در حال محاسبهٔ نتیجه…</i>")
    return "\n".join(lines)


def _actor_may_submit_choice(
    game: Game, chooser_uid: int, actor_uid: int
) -> bool:
    if chooser_uid in game.bazpors_chaos_choices:
        return False
    if not is_synthetic_player_uid(chooser_uid):
        return actor_uid == chooser_uid
    return (
        no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


async def start_chaos_handshake_round(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """دور جدید — پاک‌سازی انتخاب‌ها و ارسال پنل دست دادن به ۳ نفر (همان مسیر send_to_player)."""
    alive = [p for p in game.players.values() if p.is_alive]
    if len(alive) != 3 or not _ki_as_counts_met(game, gm):
        return

    game.bazpors_chaos_handshake_round += 1
    game.bazpors_chaos_choices.clear()

    for player in alive:
        uid = player.user_id
        if not player_should_receive_game_messages(game, uid):
            continue
        mirror = is_synthetic_player_uid(uid)
        kb = _handshake_keyboard(game, gm, player, mirror=mirror)
        ui_key = _chaos_ui_key(game, uid)
        await send_to_player(
            bot,
            game,
            uid,
            CHAOS_HANDSHAKE_PROMPT_HTML,
            mirror_reply_markup=kb,
            mirror_ui_key=ui_key,
            parse_mode="HTML",
        )

    await send_to_bot_assistant(
        bot,
        game,
        build_chaos_assistant_panel_html(game, gm),
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "chaos_handshake.round_started",
            round=game.bazpors_chaos_handshake_round,
            host_day=game.bazpors_narrator_host_day,
            alive_uids=sorted(p.user_id for p in alive),
        )
    except Exception:
        pass


async def ensure_chaos_handshake_started(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if game.bazpors_host_mode == "semi_auto":
        return
    if chaos_handshake_phase_active(game):
        return
    _sync_ki_as_today(game, gm)
    if not game.bazpors_ki_as_today or gm.check_winner(game):
        return
    if not _ki_as_counts_met(game, gm):
        return
    game.bazpors_narrator_step = CHAOS_DAY_HANDSHAKE
    await start_chaos_handshake_round(bot, game, gm)
    await push_host_step(bot, game, gm)


async def handle_chaos_handshake_pick(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    chooser_uid: int,
    target_uid: int,
    round_no: int,
    actor_uid: int,
    callback: CallbackQuery | None = None,
) -> None:
    if not chaos_handshake_phase_active(game):
        if callback:
            await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return
    if round_no != game.bazpors_chaos_handshake_round:
        if callback:
            await safe_callback_answer(
                callback,
                "این دکمه از دور قبل است — از پیام جدید انتخاب کنید.",
                show_alert=True,
            )
        return
    if chooser_uid not in game.players or target_uid not in game.players:
        if callback:
            await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return
    chooser = game.players[chooser_uid]
    target = game.players[target_uid]
    if not chooser.is_alive or not target.is_alive:
        if callback:
            await safe_callback_answer(callback, "بازیکن زنده نیست.", show_alert=True)
        return
    if chooser_uid == target_uid:
        if callback:
            await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return
    if chooser_uid in game.bazpors_chaos_choices:
        if callback:
            await safe_callback_answer(
                callback, "انتخاب شما قبلاً ثبت شده است.", show_alert=True
            )
        return
    if not _actor_may_submit_choice(game, chooser_uid, actor_uid):
        if callback:
            await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return

    game.bazpors_chaos_choices[chooser_uid] = target_uid
    if callback:
        await safe_callback_answer(callback, "✅ انتخاب شما ثبت شد.")

    await update_mirror_prompt_pair(
        bot,
        game,
        _chaos_ui_key(game, chooser_uid),
        CHAOS_HANDSHAKE_WAITING_HTML,
        None,
        assistant_uid=chooser_uid,
        fresh_observer_copy=False,
        parse_mode="HTML",
    )

    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "chaos_handshake.choice",
            round=round_no,
            host_day=game.bazpors_narrator_host_day,
            chooser_uid=chooser_uid,
            target_uid=target_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass

    await send_to_bot_assistant(
        bot,
        game,
        build_chaos_assistant_panel_html(game, gm),
        parse_mode="HTML",
    )
    await push_host_step(bot, game, gm)

    alive_count = sum(1 for p in game.players.values() if p.is_alive)
    if len(game.bazpors_chaos_choices) >= alive_count:
        await resolve_chaos_handshake_round(bot, game, gm)


async def resolve_chaos_handshake_round(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    outcome = decide_chaos_winner(game, game.bazpors_chaos_choices)
    winner_kind = outcome["winner"]

    if winner_kind == "no_valid_handshake":
        await broadcast_to_alive_players(
            bot,
            game,
            CHAOS_RETRY_BROADCAST_HTML,
            parse_mode="HTML",
            is_synthetic_uid=is_synthetic_player_uid,
        )
        await send_to_bot_assistant(
            bot,
            game,
            CHAOS_RETRY_BROADCAST_HTML,
            parse_mode="HTML",
        )
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "chaos_handshake.no_pair_retry",
                round=game.bazpors_chaos_handshake_round,
                host_day=game.bazpors_narrator_host_day,
                choices=dict(game.bazpors_chaos_choices),
            )
        except Exception:
            pass
        await start_chaos_handshake_round(bot, game, gm)
        await push_host_step(bot, game, gm)
        return

    if winner_kind == "citizens":
        public_html = RESULT_CITIZENS_HTML
        finalize_winner = "citizen"
    elif winner_kind == "mafia":
        public_html = RESULT_MAFIA_HTML
        finalize_winner = "mafia"
        game.bazpors_mafia_win_via_chaos = True
    else:
        await send_to_bot_assistant(
            bot,
            game,
            "⚠️ نتیجهٔ دست نامشخص — با /endgame برنده را ثبت کنید.",
            parse_mode="HTML",
        )
        return

    await broadcast_to_alive_players(
        bot,
        game,
        public_html,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await send_to_bot_assistant(bot, game, public_html, parse_mode="HTML")

    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "chaos_handshake.resolved",
            round=game.bazpors_chaos_handshake_round,
            host_day=game.bazpors_narrator_host_day,
            winner=winner_kind,
            pair=outcome.get("pair"),
            choices=dict(game.bazpors_chaos_choices),
        )
    except Exception:
        pass

    game.bazpors_ki_as_today = False
    reset_chaos_handshake_state(game)

    from bot.post_game_flow import (
        broadcast_bazpors_game_end_to_players,
        finalize_game_winner,
    )

    await broadcast_bazpors_game_end_to_players(bot, game, finalize_winner)
    picker = game.bot_assistant_user_id or game.host_id
    await finalize_game_winner(bot, game, finalize_winner, picker)


async def dispatch_chaos_handshake_mirror(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    chooser_uid: int,
    actor_uid: int,
    target_uid: int,
    round_raw: str,
) -> None:
    round_no = game.bazpors_chaos_handshake_round
    if round_raw:
        try:
            round_no = int(round_raw)
        except ValueError:
            await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
            return
    await handle_chaos_handshake_pick(
        bot,
        game,
        gm,
        chooser_uid=chooser_uid,
        target_uid=target_uid,
        round_no=round_no,
        actor_uid=actor_uid,
        callback=callback,
    )
