"""محاسبات پایان شب و اعلان همگانی — مسیر گردانندگی بدون گرداننده."""

from __future__ import annotations

from bot.nam10.role_labels import nam10_role_label_fa

import html
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.nam10.roles_detective import load_result as load_detective_inquiry_result
from bot.nam10 import roles_ruintan as _ruintan_role
from bot.nam10.roles_night_state import yaku_night_state
from bot.nam10.nmnd_narrator import (
    ASK_NIGHT_EXTRA,
    CITIZEN_WIN_GATE,
    DAY_DISCUSS,
    MAFIA_TIE_GATE,
    Role,
    role_label_fa,
    _apply_interrog_cancel_if_nominee_died,
    _apply_sniper_night_resolution,
    _commit_night_pending_state,
    _compose_full_night_report,
    _discipline_kick_uids,
    _eliminate_player,
    _evaluate_post_night_host_state,
    _find_alive_role,
    _mark_day_start_alive_snapshot,
    _night_report_day_farewell_uids,
    _refresh_interrog_ready_for_day,
    _seat_fa,
    _sync_ki_as_today,
    _night_report_outcome_section,
    deliver_observer_night_end_report,
    nam10_assistant_narrator_active,
    push_host_step,
)
from bot.nam10.roles_doctor import save_uid_set as _doctor_save_uid_set
from bot.nam10.no_host_mafia_win import nam10_maybe_end_on_faction_win
from bot.nam10.engine import is_synthetic_player_uid, synthetic_player_base_name
from bot.models import Game
from bot.observer_delivery import (
    broadcast_to_alive_players,
    deliver_no_host_player_game_copy,
    mirror_per_player_to_observer,
    no_host_observer_registered as nam10_observer_registered,
)
from bot.tg_send import safe_send_message

if TYPE_CHECKING:
    from bot.nam10.engine import GameManager


def build_no_host_day_started_broadcast_html(
    game: Game, gm: "GameManager | None" = None
) -> str:
    from bot.nam10.nmnd_narrator import _day_start_title_fa

    day_num = max(1, game.nmnd_narrator_host_day)
    ki_as = bool(game.nmnd_ki_as_today)
    if gm is not None and not ki_as:
        from bot.nam10.nmnd_narrator import _sync_ki_as_today

        _sync_ki_as_today(game, gm)
        ki_as = bool(game.nmnd_ki_as_today)
        if not ki_as:
            from bot.nam10.mode import is_mason_scenario

            if is_mason_scenario(game):
                from bot.mason_chaos import sync_mason_chaos_today

                sync_mason_chaos_today(game, gm)
                ki_as = bool(game.nmnd_ki_as_today)
    title = _day_start_title_fa(day_num, ki_as=ki_as)
    return title.replace("☀️ ", "", 1) if title.startswith("☀️ ") else title


async def nam10_begin_day_after_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """ورود به فاز روز پس از اعلام نتایج شب — بدون دکمه برای بازیکنان."""
    game.nmnd_narrator_host_day += 1
    _mark_day_start_alive_snapshot(game)
    _sync_ki_as_today(game, gm)
    game.nmnd_interrog_ready_for_day = False
    game.nmnd_interrog_cancel_next_day = False
    game.nmnd_narrator_step = DAY_DISCUSS
    exclude = game.bot_assistant_user_id
    await broadcast_to_alive_players(
        bot,
        game,
        build_no_host_day_started_broadcast_html(game),
        exclude=exclude,
        is_synthetic_uid=is_synthetic_player_uid,
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day_started_after_night",
            host_day=game.nmnd_narrator_host_day,
            night_count=game.nmnd_narrator_night_count,
        )
    except Exception:
        pass


def _assistant_tag(game: Game, gm: "GameManager") -> str:
    uid = game.bot_assistant_user_id
    if uid is not None and uid in game.players:
        return gm.format_player_tag(game.players[uid])
    return "کمک‌کننده ربات"


def _player_seat_label(game: Game, gm: "GameManager", uid: int) -> str:
    p = game.players[uid]
    seat = _seat_fa(p.seat) if p.seat is not None else "؟"
    name = html.escape(gm.format_player_tag(p))
    return f"صندلی {seat} — {name}"


def _broadcast_plain_name(game: Game, gm: "GameManager", uid: int) -> str:
    """نام بازیکن برای اعلام عمومی — بدون برچسب نقش."""
    p = game.players[uid]
    label = gm.user_display_names.get(uid) or p.full_name
    if is_synthetic_player_uid(uid):
        label = synthetic_player_base_name(p.full_name)
        if label == p.full_name and p.role is not None:
            suffix = f"-{nam10_role_label_fa(p.role)}"
            if p.full_name.endswith(suffix):
                label = p.full_name[: -len(suffix)]
    if p.username:
        return html.escape(f"{label} (@{p.username})")
    return html.escape(label)


def _join_fa_names(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} و {names[1]}"
    return "، ".join(names[:-1]) + f" و {names[-1]}"


async def _broadcast_discipline_no(bot: Bot, game: Game, gm: "GameManager") -> None:
    tag = html.escape(_assistant_tag(game, gm))
    text = f"👢 <b>{tag}</b> اعلام کرد که در این شب اخراج انضباطی نداریم."
    await broadcast_to_alive_players(
        bot,
        game,
        text,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )


async def _broadcast_discipline_kick(
    bot: Bot, game: Game, gm: "GameManager", kicked_uid: int
) -> None:
    if kicked_uid not in game.players:
        return
    tag = html.escape(_assistant_tag(game, gm))
    seat_name = _player_seat_label(game, gm, kicked_uid)
    text = (
        f"👢 <b>{tag}</b> بازیکن {seat_name} را از بازی اخراج کرد."
    )
    await broadcast_to_alive_players(
        bot,
        game,
        text,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )


def _apply_no_host_night_resolution(game: Game, gm: "GameManager") -> None:
    """اعمال مرگ‌های شب بدون پیام میانی (ترتیب طبق قوانین سناریو)."""
    game.nmnd_host_flush_note = None
    game.nmnd_night_announce_lines.clear()

    from bot.nam10.mode import is_mason_scenario

    if is_mason_scenario(game):
        if game.mason_night_resolution_applied:
            return
        from bot.mason_night_resolve import apply_mason_night_resolution

        apply_mason_night_resolution(game, gm)
        return

    from bot.nam10.night2 import nam10_night2_mode

    if nam10_night2_mode(game):
        # Night v2 applies every deterministic elimination
        # internally during the resolution; the legacy pending-state
        # path has nothing to re-apply here (double registrations
        # would otherwise be created).
        return

    yaku = yaku_night_state(game)
    if yaku.successful_recruit_pending:
        civ_uid = yaku.night_civilian_uid
        assert civ_uid is not None
        civ = game.players.get(civ_uid)
        if civ is not None and civ.is_alive:
            from bot.nam10.engine import apply_bazpors_yakuzai_recruit

            apply_bazpors_yakuzai_recruit(game, civ)

    t = game.actions.mafia_target
    saves = _doctor_save_uid_set(game)
    if game.nmnd_mafia_shot_registered and t is not None and t in game.players:
        pl = game.players[t]
        if pl.is_alive and t not in saves:
            from bot.nam10.mode import is_mozakere_scenario

            survived_shot = False
            if is_mozakere_scenario(game):
                from bot.roles.mozakere_armored import mafia_shot_blocked_by_armor

                if mafia_shot_blocked_by_armor(game, pl):
                    survived_shot = True
            if not survived_shot and _ruintan_role.mafia_shot_survives(pl):
                pass
            elif not survived_shot:
                _eliminate_player(
                    game, gm, t, elim_source="night_resolve"
                )

    if game.nmnd_nato_success and game.nmnd_nato_kill_target_uid is not None:
        u = game.nmnd_nato_kill_target_uid
        if u in game.players and game.players[u].is_alive:
            _eliminate_player(game, gm, u, elim_source="night_resolve")

    su = yaku.sacrifice_elimination_uid()
    if su is not None:
        sac = game.players[su]
        if sac.is_alive:
            _eliminate_player(game, gm, su, elim_source="night_resolve")

    _apply_sniper_night_resolution(game, gm)


async def _send_detective_inquiry_dm(bot: Bot, game: Game, gm: "GameManager") -> None:
    result = load_detective_inquiry_result(game)
    if result is None:
        return
    snap = game.nmnd_alive_at_night_start or {}
    det_uid = None
    for uid, pl in game.players.items():
        if pl.role == Role.DETECTIVE and snap.get(uid, pl.is_alive):
            det_uid = uid
            break
    if det_uid is None:
        return
    tgt = game.players.get(result.target_uid)
    name = html.escape(gm.format_player_tag(tgt) if tgt else str(result.target_uid))
    text = result.private_line_fa(name)
    await deliver_no_host_player_game_copy(
        bot,
        game,
        det_uid,
        text,
        is_synthetic_uid=is_synthetic_player_uid,
        parse_mode="HTML",
    )


async def _send_journalist_inquiry_dm(bot: Bot, game: Game, gm: "GameManager") -> None:
    from bot.nam10.mode import is_mozakere_scenario
    from bot.roles.mozakere_journalist import load_result as load_journalist_result

    if not is_mozakere_scenario(game):
        return
    if not game.nam10_journalist_pick_confirmed:
        return
    result = load_journalist_result(game)
    if result is None:
        return
    snap = game.nmnd_alive_at_night_start or {}
    jr_uid = None
    for uid, pl in game.players.items():
        if pl.role == Role.JOURNALIST and snap.get(uid, pl.is_alive):
            jr_uid = uid
            break
    if jr_uid is None:
        return
    tgt = game.players.get(result.target_uid)
    name = html.escape(gm.format_player_tag(tgt) if tgt else str(result.target_uid))
    text = result.private_line_fa(name)
    await deliver_no_host_player_game_copy(
        bot,
        game,
        jr_uid,
        text,
        is_synthetic_uid=is_synthetic_player_uid,
        parse_mode="HTML",
    )


def uids_eliminated_during_this_night(game: Game) -> list[int]:
    """بازیکنانی که از شروع این شب زنده بودند و تا قبل از اعلام نتایج مرده‌اند."""
    snap = game.nmnd_alive_at_night_start or {
        uid: p.is_alive for uid, p in game.players.items()
    }
    out: list[int] = []
    for uid, p in sorted(game.players.items(), key=lambda x: x[0]):
        if p.role == Role.OBSERVER:
            continue
        if snap.get(uid, True) and not p.is_alive:
            out.append(uid)
    return out


async def deliver_night_results_to_eliminated_from_night(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    results_html: str,
) -> None:
    """خلاصهٔ شب برای کسانی که همین شب از بازی خارج شدند — قبل از پیام حذف."""
    if not results_html.strip():
        return
    for uid in uids_eliminated_during_this_night(game):
        if is_synthetic_player_uid(uid):
            if nam10_observer_registered(game):
                await mirror_per_player_to_observer(
                    bot,
                    game,
                    uid,
                    results_html,
                    parse_mode="HTML",
                )
            continue
        if game.observer_user_id is not None and uid == game.observer_user_id:
            continue
        await safe_send_message(
            bot, uid, results_html, parse_mode="HTML"
        )
        if nam10_observer_registered(game):
            await mirror_per_player_to_observer(
                bot,
                game,
                uid,
                results_html,
                parse_mode="HTML",
            )


def build_no_host_night_results_broadcast_html(
    game: Game,
    gm: "GameManager",
    *,
    exclude_discipline_kick_uid: int | None = None,
) -> str:
    """همان بلوک «نتیجه نهایی شب و روز گذشته» که ناظر/گرداننده می‌بیند."""
    del exclude_discipline_kick_uid  # انضباط در _night_report_outcome_section
    snap = game.nmnd_alive_at_night_start or {
        uid: p.is_alive for uid, p in game.players.items()
    }
    # Player-facing summary: eliminated players by name only — no
    # roles, no team affiliations.
    return "\n".join(
        _night_report_outcome_section(game, gm, snap, public=True)
    )


def _finalize_no_host_night_state(game: Game, gm: "GameManager") -> None:
    from bot.nam10.roles_doctor import void_night_pick

    snap = game.nmnd_alive_at_night_start or {
        uid: p.is_alive for uid, p in game.players.items()
    }
    void_night_pick(game)
    _commit_night_pending_state(game)
    _apply_interrog_cancel_if_nominee_died(game, snap)
    _refresh_interrog_ready_for_day(game)
    game.nmnd_night_report_html = _compose_full_night_report(game, gm, snap)
    from bot.nam10.night2 import nam10_night2_mode

    if nam10_night2_mode(game):
        from bot.nam10.night2_publish import (
            night2_night_report_extra_section,
        )

        extra = night2_night_report_extra_section(game, gm)
        if extra:
            game.nmnd_night_report_html = (
                game.nmnd_night_report_html + "\n" + extra
            )
    game.nmnd_host_flush_note = None
    game.nmnd_night_substep = None
    game.nam10_detective_result_pending = False
    game.nam10_sniper_result_pending = False
    game.nam10_shiad_result_pending = False
    game.nam10_journalist_result_pending = False
    gm.check_winner(game)
    from bot.nam10.no_host_interrog_day import should_enter_no_host_interrog_day

    if should_enter_no_host_interrog_day(game):
        game.nam10_interrog_night_gate_pending = True
    elif not nam10_assistant_narrator_active(game):
        game.nmnd_narrator_step = ASK_NIGHT_EXTRA
    _evaluate_post_night_host_state(game, gm)
    try:
        from bot.game_audit_log import log_night_resolved

        log_night_resolved(game, gm)
    except Exception:
        pass


async def _notify_observer_night_end_report(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    await deliver_observer_night_end_report(bot, game, gm)


async def nam10_complete_discipline_and_resolve(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    kicked_uid: int | None = None,
    send_discipline_broadcast: bool = True,
) -> bool:
    """پس از انضباط: اعلان → محاسبهٔ خاموش شب → اعلان نتایج.

    True = پنل کمک‌کننده همین‌جا ارسال شد (refresh بعد از callback لازم نیست).
    """
    if not nam10_assistant_narrator_active(game):
        return False

    discipline_kick = kicked_uid if kicked_uid is not None else game.nmnd_night_discipline_kick_uid

    if send_discipline_broadcast:
        if discipline_kick is None:
            await _broadcast_discipline_no(bot, game, gm)
        else:
            await _broadcast_discipline_kick(bot, game, gm, discipline_kick)

    _apply_no_host_night_resolution(game, gm)
    from bot.nam10.nmnd_night_panel_purge import purge_stale_night_and_day_panel_messages

    await purge_stale_night_and_day_panel_messages(bot, game)
    await _send_detective_inquiry_dm(bot, game, gm)
    await _send_journalist_inquiry_dm(bot, game, gm)
    _finalize_no_host_night_state(game, gm)
    await _notify_observer_night_end_report(bot, game, gm)
    # Publication is now settled: the full night report is composed, the
    # observer report is out and the room is being handed to the pre-day
    # gate. Clear the sticky publication latch here — daylight flows read
    # it afterwards (notably the Rebel assassination daytime window), and
    # a latch that stays True until the next night's entry reset silently
    # blocks every post-night day (Room 31 defect: the synthetic Rebel
    # never received its assassination entry panel on Day 3).
    game.nmnd_night2_publication_pending = False
    game.nmnd_night2_publication_stage = None

    results = build_no_host_night_results_broadcast_html(
        game,
        gm,
        exclude_discipline_kick_uid=discipline_kick,
    )
    await broadcast_to_alive_players(
        bot,
        game,
        results,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await deliver_night_results_to_eliminated_from_night(
        bot, game, gm, results
    )
    if await nam10_maybe_end_on_faction_win(
        bot, game, gm, elim_source="night_resolve"
    ):
        return True

    from bot.nam10.nmnd_narrator import push_host_step
    from bot.nam10.no_host_table_inquiry import (
        nam10_enter_table_inquiry_before_day,
        nam10_prompt_table_inquiry_before_day,
    )

    if game.nmnd_narrator_step not in (
        CITIZEN_WIN_GATE,
        MAFIA_TIE_GATE,
    ):
        if game.nam10_interrog_night_gate_pending:
            await nam10_prompt_table_inquiry_before_day(bot, game, gm)
        else:
            await nam10_enter_table_inquiry_before_day(bot, game, gm)
            await push_host_step(bot, game, gm, force_new_host_message=True)

    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night_resolved_and_announced",
            night_count=game.nmnd_narrator_night_count,
            discipline_kick_uid=discipline_kick,
            interrog_ready=game.nmnd_interrog_ready_for_day,
            table_inquiry_before_interrog=game.nam10_interrog_night_gate_pending,
        )
    except Exception:
        pass
    return True
