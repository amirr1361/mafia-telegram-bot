"""درگاه «همهٔ بازیکنان آماده شدند» قبل از محاسبات شب (no_host)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NIGHT_START,
    Role,
    _bazpors_sniper_nights_enabled,
    _goto_discipline_ask,
    _role_eliminated_from_game,
    _sniper_can_shoot,
    no_host_assistant_narrator_active,
    push_host_step,
)
from bot.models import Game
from bot.game import is_mafia_team
from bot.room_mode import is_no_host_player_room
from bot.roles.night_state import yaku_night_state
from bot.roles.registry import find_alive_player, get_role_module, find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager


def no_host_parallel_night_collect_active(game: Game) -> bool:
    return bool(
        is_no_host_player_room(game)
        and no_host_assistant_narrator_active(game)
        and game.no_host_night_parallel_collect_active
        and game.bazpors_narrator_step in (NIGHT_START, NIGHT_ACTIONS)
    )


def _alive_citizen_uids(game: Game) -> list[int]:
    mod = get_role_module(Role.CITIZEN)
    assert mod is not None
    return mod.alive_simple_citizen_uids(game)


def _citizens_ready(game: Game) -> bool:
    need = _alive_citizen_uids(game)
    if not need:
        return True
    done = set(game.no_host_citizen_night_confirmed_uids)
    return all(uid in done for uid in need)


def _ruintan_ready(game: Game) -> bool:
    if find_alive_player(game, Role.RUINTAN) is None:
        return True
    return game.no_host_ruintan_night_confirmed


def _hunter_night1_ready(game: Game) -> bool:
    if find_alive_player(game, Role.HUNTER) is None:
        return True
    return game.no_host_night1_hunter_done


def _mafia_night1_parallel_ready(game: Game) -> bool:
    """منوی تیم مافیا (شات / ناتو / یاکوزا) — هر شب."""
    mod = get_role_module(Role.MAFIA_BASIC)
    if mod is None or not mod.has_mafia_team_member_alive(game):
        return True
    if not game.no_host_mafia_night1_done:
        return False
    from bot.no_host_mafia_night1 import (
        MAFIA_ACTION_NATO,
        MAFIA_ACTION_NEGOTIATE,
        MAFIA_ACTION_SHOT,
        MAFIA_ACTION_YAKU,
    )
    from bot.roles.mozakere_negotiator import find_alive_negotiator

    action = game.no_host_mafia_night1_chosen_action
    if action == MAFIA_ACTION_SHOT:
        return bool(
            game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
        )
    if action == MAFIA_ACTION_YAKU:
        return yaku_night_state(game).no_host_done
    if action == MAFIA_ACTION_NATO:
        return game.no_host_mafia_nato_done
    if action == MAFIA_ACTION_NEGOTIATE:
        if find_alive_negotiator(game) is None:
            return True
        return game.no_host_negotiator_pick_confirmed
    return True


def _mafia_shot_parallel_ready(game: Game) -> bool:
    """شات زیرمجموعهٔ منوی مافیا است — در _mafia_night1_parallel_ready بررسی می‌شود."""
    return True


def _mafia_night1_ready(game: Game) -> bool:
    has_mafia = any(
        p.is_alive and p.role and is_mafia_team(p.role)
        for p in game.players.values()
    )
    if not has_mafia:
        return True
    if not game.no_host_mafia_night1_done:
        return False
    from bot.no_host_mafia_night1 import (
        MAFIA_ACTION_NATO,
        MAFIA_ACTION_NEGOTIATE,
        MAFIA_ACTION_SHOT,
        MAFIA_ACTION_YAKU,
    )
    from bot.roles.mozakere_negotiator import find_alive_negotiator

    action = game.no_host_mafia_night1_chosen_action
    if action == MAFIA_ACTION_SHOT:
        return bool(
            game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
        )
    if action == MAFIA_ACTION_YAKU:
        return yaku_night_state(game).no_host_done
    if action == MAFIA_ACTION_NATO:
        return game.no_host_mafia_nato_done
    if action == MAFIA_ACTION_NEGOTIATE:
        if find_alive_negotiator(game) is None:
            return True
        return game.no_host_negotiator_pick_confirmed
    return True


def _detective_ready(game: Game) -> bool:
    from bot.room_mode import is_mozakere_scenario

    if find_alive_role_holder(game, Role.DETECTIVE) is None:
        return True
    if is_mozakere_scenario(game) and game.bazpors_detective_blocked:
        return game.no_host_detective_pick_confirmed
    return _role_pick_ready(game, Role.DETECTIVE, "no_host_detective_pick_confirmed")


def _sniper_ready(game: Game) -> bool:
    if not _bazpors_sniper_nights_enabled(game):
        return True
    sn = find_alive_role_holder(game, Role.SNIPER)
    if sn is None:
        return True
    if not _sniper_can_shoot(game):
        return True
    return game.no_host_sniper_pick_confirmed


def _interrogator_ready(game: Game) -> bool:
    if find_alive_role_holder(game, Role.INTERROGATOR) is None:
        return True
    if game.bazpors_interrog_night_finished:
        return True
    return game.no_host_interrog_pick_confirmed


def _journalist_ready(game: Game) -> bool:
    from bot.room_mode import is_mozakere_scenario

    if not is_mozakere_scenario(game):
        return True
    if find_alive_role_holder(game, Role.JOURNALIST) is None:
        return True
    from bot.roles.mozakere_journalist import mozakere_journalist_active

    if mozakere_journalist_active(game):
        return game.no_host_journalist_pick_confirmed
    return game.no_host_journalist_idle_confirmed


def _role_pick_ready(game: Game, role: Role, confirmed_attr: str) -> bool:
    if find_alive_role_holder(game, role) is None:
        return True
    return bool(getattr(game, confirmed_attr))


def _doctor_ready(game: Game) -> bool:
    if find_alive_role_holder(game, Role.DOCTOR) is None:
        return True
    if game.bazpors_nato_action_registered:
        return game.no_host_doctor_pick_confirmed
    return _role_pick_ready(game, Role.DOCTOR, "no_host_doctor_pick_confirmed")


def all_no_host_parallel_night_ready(game: Game) -> bool:
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.mason_night_ready import all_mason_parallel_night_ready

        return all_mason_parallel_night_ready(game)
    if not no_host_parallel_night_collect_active(game):
        return False
    checks = (
        _citizens_ready(game),
        _ruintan_ready(game),
        _hunter_night1_ready(game),
        _mafia_night1_parallel_ready(game),
        _mafia_shot_parallel_ready(game),
        _role_pick_ready(game, Role.SHIAD, "no_host_shiad_pick_confirmed"),
        _detective_ready(game),
        _doctor_ready(game),
        _sniper_ready(game),
        _interrogator_ready(game),
        _journalist_ready(game),
    )
    return all(checks)


def pending_no_host_night_actor_labels(game: Game) -> list[str]:
    """برچسب‌های فارسی برای نمایش در پنل دستیار (چه کسی مانده)."""
    pending: list[str] = []
    if not _citizens_ready(game):
        pending.append("شهروندان ساده")
    if not _ruintan_ready(game):
        pending.append("رویین‌تن")
    if not _hunter_night1_ready(game):
        pending.append("هانتر")
    if not _mafia_night1_parallel_ready(game):
        pending.append("تیم مافیا")
    if not _mafia_shot_parallel_ready(game):
        pending.append("شات مافیا")
    if not _role_pick_ready(game, Role.SHIAD, "no_host_shiad_pick_confirmed"):
        pending.append("شیاد")
    if not _detective_ready(game):
        pending.append("کارآگاه")
    if not _doctor_ready(game):
        pending.append("پزشک")
    if not _sniper_ready(game):
        pending.append("اسنایپر")
    if not _interrogator_ready(game):
        pending.append("بازپرس")
    if not _journalist_ready(game):
        pending.append("خبرنگار")
    return pending


def defer_no_host_faction_win_until_night_complete(game: Game) -> bool:
    """تا وقتی همهٔ بازیکنان فاز شب را تمام نکرده‌اند، برد/باخت اعلام نشود."""
    return no_host_parallel_night_collect_active(game)


async def no_host_refresh_after_mafia_sub_action(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if no_host_parallel_night_collect_active(game):
        await maybe_finish_no_host_parallel_night(bot, game, gm)
    else:
        await push_host_step(bot, game, gm)


async def maybe_finish_no_host_parallel_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> bool:
    """اگر همه آماده‌اند، وارد انضباط/محاسبه شب شو. True یعنی پایان جمع‌آوری انجام شد."""
    if not all_no_host_parallel_night_ready(game):
        return False
    await finish_no_host_parallel_night_collect(bot, game, gm)
    return True


def arm_all_pending_no_host_role_pick_flows(game: Game) -> None:
    """اگر پنل شبانه فرستاده شده ولی flow_active خاموش است، دوباره فعال کن."""
    from bot.game_state import NO_HOST_ROLE_PICK_SPECS, arm_no_host_role_pick

    for spec in NO_HOST_ROLE_PICK_SPECS:
        arm_no_host_role_pick(game, spec.role)


def _bazpors_role_pick_blocker_detail(
    game: Game, gm: "GameManager", role: Role, *, label: str, field: str, callbacks: str
) -> str:
    holder = find_alive_role_holder(game, role)
    confirmed = bool(getattr(game, field))
    if holder is None:
        if confirmed:
            return f"{label}: no alive holder (skipped)"
        return f"{label}: holder dead/absent but {field}=False — unexpected"
    panel_sent = bool(getattr(game, field.replace("_pick_confirmed", "_dm_signature"), None))
    flow_attr = field.replace("_pick_confirmed", "_flow_active")
    flow_active = bool(getattr(game, flow_attr, False))
    tag = gm.format_player_tag(holder)
    seat = holder.seat or "?"
    parts = [
        f"{label}: seat {seat} {tag}",
        f"{field}=False",
        f"panel_sent={panel_sent}",
        f"flow_active={flow_active}",
        f"expected callbacks: {callbacks}",
    ]
    if panel_sent and not flow_active:
        parts.append("stale flow_active — panel sent but flow disarmed")
    return "; ".join(parts)


def explain_bazpors_night_stuck(game: Game, gm: "GameManager") -> str:
    """گزارش دیباگ — چرا شب بازپرس (no_host) جلو نمی‌رود؟"""
    from bot.room_mode import is_mason_scenario, is_mozakere_scenario

    if is_mason_scenario(game):
        from bot.mason_night_ready import explain_mason_night_stuck

        return explain_mason_night_stuck(game, gm)

    phase = game.bazpors_narrator_step or "unknown"
    night = game.bazpors_narrator_night_count
    collect_active = no_host_parallel_night_collect_active(game)
    lines: list[str] = [
        f"Phase: {phase} (night {night})",
        f"Parallel night collect active: {collect_active}",
        "",
    ]

    if all_no_host_parallel_night_ready(game):
        lines.append("Night readiness complete — game should advance.")
        return "\n".join(lines)

    pending = pending_no_host_night_actor_labels(game)
    state_fields: list[str] = []
    blocker_details: list[str] = []

    if not _citizens_ready(game):
        state_fields.append("citizens_ready=False")
        need = _alive_citizen_uids(game)
        done = set(game.no_host_citizen_night_confirmed_uids)
        for uid in need:
            if uid in done:
                continue
            pl = game.players.get(uid)
            tag = gm.format_player_tag(pl) if pl else str(uid)
            seat = pl.seat if pl and pl.seat else "?"
            blocker_details.append(
                f"Citizen: seat {seat} {tag}; panel_sent=unknown; "
                "expected callback: night wait OK"
            )
    if not _ruintan_ready(game):
        state_fields.append("no_host_ruintan_night_confirmed=False")
        ru = find_alive_role_holder(game, Role.RUINTAN)
        if ru:
            blocker_details.append(
                f"Ruintan: seat {ru.seat or '?'} {gm.format_player_tag(ru)}; "
                "expected callback: night wait OK"
            )
    if not _hunter_night1_ready(game):
        state_fields.append("no_host_night1_hunter_done=False")
        hun = find_alive_role_holder(game, Role.HUNTER)
        if hun:
            blocker_details.append(
                f"Hunter: seat {hun.seat or '?'} {gm.format_player_tag(hun)}; "
                "expected callbacks: hnp/hnc/hns/hnb"
            )
    if not _mafia_night1_parallel_ready(game):
        state_fields.append("mafia_night1_parallel_ready=False")
        if not game.no_host_mafia_night1_done:
            state_fields.append("no_host_mafia_night1_done=False")
        else:
            action = game.no_host_mafia_night1_chosen_action
            state_fields.append(f"mafia_action={action!r}")
            if action == "shot" and not (
                game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
            ):
                state_fields.append("no_host_mafia_shot_done=False")
    if not _role_pick_ready(game, Role.SHIAD, "no_host_shiad_pick_confirmed"):
        state_fields.append("no_host_shiad_pick_confirmed=False")
        blocker_details.append(
            _bazpors_role_pick_blocker_detail(
                game,
                gm,
                Role.SHIAD,
                label="Shiad",
                field="no_host_shiad_pick_confirmed",
                callbacks="sgt → sgc (or sgb back)",
            )
        )
    if not _detective_ready(game):
        state_fields.append("detective_ready=False")
        blocker_details.append(
            _bazpors_role_pick_blocker_detail(
                game,
                gm,
                Role.DETECTIVE,
                label="Detective",
                field="no_host_detective_pick_confirmed",
                callbacks="det pick/confirm",
            )
        )
    if not _doctor_ready(game):
        state_fields.append("doctor_ready=False")
        blocker_details.append(
            _bazpors_role_pick_blocker_detail(
                game,
                gm,
                Role.DOCTOR,
                label="Doctor",
                field="no_host_doctor_pick_confirmed",
                callbacks="doc pick/confirm",
            )
        )
    if not _sniper_ready(game):
        state_fields.append("sniper_ready=False")
        blocker_details.append(
            _bazpors_role_pick_blocker_detail(
                game,
                gm,
                Role.SNIPER,
                label="Sniper",
                field="no_host_sniper_pick_confirmed",
                callbacks="sniper pick/confirm or skip",
            )
        )
    if not _interrogator_ready(game):
        state_fields.append("no_host_interrog_pick_confirmed=False")
        phase = game.no_host_interrog_ui_phase or "int1"
        blocker_details.append(
            _bazpors_role_pick_blocker_detail(
                game,
                gm,
                Role.INTERROGATOR,
                label="Interrogator",
                field="no_host_interrog_pick_confirmed",
                callbacks=f"nii1/nii1s/nii2/niisk (phase={phase})",
            )
        )
    if is_mozakere_scenario(game) and not _journalist_ready(game):
        state_fields.append("journalist_ready=False")
        blocker_details.append(
            _bazpors_role_pick_blocker_detail(
                game,
                gm,
                Role.JOURNALIST,
                label="Journalist",
                field="no_host_journalist_pick_confirmed",
                callbacks="journalist night",
            )
        )

    if not collect_active:
        state_fields.insert(0, "no_host_night_parallel_collect_active=False")

    lines.extend(["Waiting for:", *[f"- {x}" for x in pending]])
    if state_fields:
        lines.extend(["", "Waiting because:", *[f"- {x}" for x in state_fields]])
    if blocker_details:
        lines.extend(["", "Blocker details:", *[f"- {x}" for x in blocker_details]])
    return "\n".join(lines)


async def finish_no_host_parallel_night_collect(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.mason_game_flow import mason_finish_parallel_night_collect

        await mason_finish_parallel_night_collect(bot, game, gm)
        return

    game.no_host_night_parallel_collect_active = False
    # نجات خود پزشک فقط در پایان شب ثبت می‌شود (پس از ناتو/یاکوزا در _finalize_no_host_night_state).
    game.bazpors_narrator_step = NIGHT_ACTIONS
    _goto_discipline_ask(game)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.parallel_night_collect_finished",
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass
    await push_host_step(bot, game, gm)
