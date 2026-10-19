"""درگاه آمادگی شب — فقط سناریوی ماسون."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.models import Game, Role
from bot.no_host_night_ready import no_host_parallel_night_collect_active
from bot.room_mode import is_mason_scenario
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager


def _mafia_ready(game: Game) -> bool:
    from bot.no_host_mafia_night1 import (
        MAFIA_ACTION_NATO,
        MAFIA_ACTION_SHOT,
    )

    if not game.no_host_mafia_night1_done:
        if is_mason_scenario(game):
            shot_complete = bool(
                game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
            )
            if shot_complete and game.no_host_mafia_night1_chosen_action in (
                MAFIA_ACTION_SHOT,
                None,
            ):
                return True
        return False

    action = game.no_host_mafia_night1_chosen_action
    if action == MAFIA_ACTION_SHOT:
        return bool(game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered)
    if action == MAFIA_ACTION_NATO:
        return game.no_host_mafia_nato_done
    return True


def _mafia_ready_reason(game: Game) -> str | None:
    if not game.no_host_mafia_night1_done:
        return "منوی تیم مافیا تمام نشده"
    from bot.no_host_mafia_night1 import (
        MAFIA_ACTION_NATO,
        MAFIA_ACTION_SHOT,
    )

    action = game.no_host_mafia_night1_chosen_action
    if action == MAFIA_ACTION_SHOT and not (
        game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
    ):
        return "شات مافیا ثبت نشده"
    if action == MAFIA_ACTION_NATO and not game.no_host_mafia_nato_done:
        return "عملیات ناتو تمام نشده"
    return None


def _mafia_shot_target_label(game: Game, gm: "GameManager") -> str | None:
    from bot.roles.night_state import mafia_night_state

    uid = mafia_night_state(game).target_uid
    if uid is None:
        uid = game.actions.mafia_target
    if uid is None or uid not in game.players:
        return None
    from bot.no_host_night_common import format_night_selection_label

    return format_night_selection_label(game, gm, uid)


def _mason_role_panel_sent(game: Game, role: Role, uid: int) -> bool:
    from bot.observer_delivery import mirror_ui_claim_key

    ui_kind_by_role = {
        Role.SABOTEUR: "mason_saboteur",
        Role.DOCTOR: "mason_doctor",
        Role.SNIPER: "mason_sniper",
        Role.COMMANDER: "mason_commander",
        Role.GUNMAN: "mason_gunner",
        Role.BODYGUARD: "mason_guardian",
        Role.MASON: "mason_recruit",
        Role.DETECTIVE: "mason_detective",
        Role.NATASHA: "mason_natasha",
        Role.PRIEST: "mason_priest",
    }
    kind = ui_kind_by_role.get(role)
    if kind is None:
        return False
    key = mirror_ui_claim_key(game.room_code, kind, uid)
    entry = game.mirror_prompt_messages.get(key, {})
    return bool(entry.get("player") or entry.get("observer"))


def _describe_mason_mafia_action_complete_summary(
    game: Game, gm: "GameManager"
) -> str | None:
    if not _mafia_ready(game):
        shot_done = bool(
            game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
        )
        if shot_done and not game.no_host_mafia_night1_done:
            target = _mafia_shot_target_label(game, gm) or "unknown"
            return (
                "Mafia shot flags inconsistent: no_host_mafia_shot_done=True but "
                f"no_host_mafia_night1_done=False (target={target}). "
                "maybe_finish was not satisfied."
            )
        return None

    from bot.no_host_mafia_night1 import MAFIA_ACTION_NATO, MAFIA_ACTION_SHOT
    from bot.roles.mason_godfather import resolve_mason_mafia_action_holder_label

    chooser_uid = game.no_host_mafia_night1_chooser_uid
    player = game.players.get(chooser_uid) if chooser_uid is not None else None
    if player is None:
        from bot.no_host_mafia_chooser import resolve_mafia_shot_chooser

        player = resolve_mafia_shot_chooser(game)
    tag = gm.format_player_tag(player) if player is not None else "unknown"
    holder_label = resolve_mason_mafia_action_holder_label(game)
    action = game.no_host_mafia_night1_chosen_action
    if action in (MAFIA_ACTION_SHOT, None):
        target = _mafia_shot_target_label(game, gm)
        if target:
            return f"Mafia action complete: {tag} ({holder_label}) shot {target}."
        return f"Mafia action complete: {tag} ({holder_label}) shot confirmed."
    if action == MAFIA_ACTION_NATO:
        return f"Mafia action complete: {tag} ({holder_label}) chose NATO."
    return f"Mafia action complete: {tag} ({holder_label})."


def _describe_mason_next_role_blocker(
    game: Game, gm: "GameManager"
) -> str | None:
    """اولین نقش غیرمافیا که هنوز آماده نیست."""
    role_gates = (
        (Role.SABOTEUR, "Saboteur", _saboteur_ready, "mason_night_saboteur_confirmed"),
        (Role.DOCTOR, "Doctor", _doctor_ready, "mason_night_doctor_confirmed"),
        (Role.SNIPER, "Sniper", _sniper_ready, "mason_night_sniper_confirmed"),
        (Role.COMMANDER, "Commander", _commander_ready, "mason_night_commander_confirmed"),
        (Role.GUNMAN, "Gunner", _gunner_ready, "mason_night_gunner_confirmed"),
        (Role.BODYGUARD, "Guardian", _guardian_ready, "mason_night_guardian_confirmed"),
        (Role.MASON, "Mason", _mason_recruit_ready, "mason_night_mason_confirmed"),
        (Role.DETECTIVE, "Detective", _detective_ready, "mason_night_detective_confirmed"),
        (Role.NATASHA, "Natasha", _natasha_ready, "mason_night_natasha_confirmed"),
        (Role.PRIEST, "Priest", _priest_ready, "mason_night_priest_confirmed"),
    )
    for role, label, ready_fn, field in role_gates:
        if ready_fn(game):
            continue
        holder = find_alive_role_holder(game, role)
        if holder is None:
            continue
        tag = gm.format_player_tag(holder)
        panel_sent = _mason_role_panel_sent(game, role, holder.user_id)
        ok_panel = _mason_no_pick_ok_panel_kind(game, role)
        if ok_panel:
            return (
                f"Waiting for {label} OK: player={tag}, alive=True, "
                f"panel_sent={panel_sent}, field={field}=False"
            )
        return (
            f"Waiting for {label}: player={tag}, alive=True, "
            f"panel_sent={panel_sent}, field={field}=False"
        )

    if not _waiters_ready(game):
        holders = _night_wait_ok_holder_uids(game)
        done = set(game.mason_night_wait_ok_uids)
        for p in game.players.values():
            if not p.is_alive or p.user_id in holders or p.user_id in done:
                continue
            if _player_auto_satisfied_wait_ok(game, p):
                continue
            from bot.mason_night_entry import _wait_ui_key

            tag = gm.format_player_tag(p)
            key = _wait_ui_key(game, p.user_id)
            entry = game.mirror_prompt_messages.get(key, {})
            panel_sent = bool(entry.get("player") or entry.get("observer"))
            return (
                f"Waiting for no-action OK: player={tag}, alive=True, "
                f"panel_sent={panel_sent}, field=mason_night_wait_ok_uids"
            )
    if _mafia_ready(game) and not all_mason_parallel_night_ready(game):
        return (
            "Mafia action complete. No role blocker found but "
            "maybe_finish was not called after shot confirmation."
        )
    return None


def _describe_mason_mafia_night_blocker(
    game: Game, gm: "GameManager"
) -> str | None:
    """گزارش دقیق بلاکر اقدام مافیا — فقط سناریوی ماسون."""
    if not is_mason_scenario(game) or _mafia_ready(game):
        return None

    from bot.no_host_mafia_night1 import (
        MAFIA_ACTION_NATO,
        MAFIA_ACTION_SHOT,
        mafia_night1_expected_panel_uids,
        mafia_night1_panel_delivered,
    )
    from bot.roles.mason_godfather import resolve_mason_mafia_action_holder_label

    holder_label = resolve_mason_mafia_action_holder_label(game)
    expected_uids = mafia_night1_expected_panel_uids(game)
    holder = None
    if expected_uids:
        holder = game.players.get(expected_uids[0])

    if not game.no_host_mafia_night1_done:
        shot_done = bool(
            game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
        )
        if shot_done:
            target = _mafia_shot_target_label(game, gm) or "unknown"
            return (
                "Waiting for Mafia menu flag: shot already confirmed but "
                f"no_host_mafia_night1_done=False (target={target})"
            )
        if holder is None:
            return (
                "Waiting for Mafia action: holder=none, player=none, "
                "alive=False, panel_sent=False, field=no_host_mafia_night1_done=False"
            )
        tag = gm.format_player_tag(holder)
        panel_sent = mafia_night1_panel_delivered(game, holder.user_id)
        return (
            f"Waiting for Mafia action: holder={holder_label}, player={tag}, "
            f"alive={holder.is_alive}, panel_sent={panel_sent}, "
            f"field=no_host_mafia_night1_done=False"
        )

    action = game.no_host_mafia_night1_chosen_action
    actor_uid = game.no_host_mafia_night1_chooser_uid or (
        holder.user_id if holder is not None else None
    )
    actor = game.players.get(actor_uid) if actor_uid is not None else holder
    if actor is None and holder is not None:
        actor = holder
    tag = gm.format_player_tag(actor) if actor is not None else "none"
    alive = actor.is_alive if actor is not None else False
    panel_uid = actor_uid if actor_uid is not None else -1
    panel_sent = mafia_night1_panel_delivered(game, panel_uid) if panel_uid > 0 else False

    if action == MAFIA_ACTION_SHOT and not (
        game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
    ):
        return (
            f"Waiting for Mafia shot: holder={holder_label}, player={tag}, "
            f"alive={alive}, panel_sent={panel_sent}, "
            f"field=no_host_mafia_shot_done=False"
        )
    if action == MAFIA_ACTION_NATO and not game.no_host_mafia_nato_done:
        nato = find_alive_role_holder(game, Role.NATO)
        nato_tag = gm.format_player_tag(nato) if nato is not None else tag
        nato_alive = nato.is_alive if nato is not None else alive
        nato_uid = nato.user_id if nato is not None else panel_uid
        from bot.no_host_mafia_nato import _nato_ui_key

        nato_panel_sent = bool(
            game.mirror_prompt_messages.get(_nato_ui_key(game, nato_uid), {}).get(
                "player"
            )
            or game.mirror_prompt_messages.get(_nato_ui_key(game, nato_uid), {}).get(
                "observer"
            )
        ) if nato_uid > 0 else False
        return (
            f"Waiting for NATO sub-flow: holder={holder_label}, player={nato_tag}, "
            f"alive={nato_alive}, panel_sent={nato_panel_sent}, "
            f"field=no_host_mafia_nato_done=False"
        )
    return None


def _role_was_dealt(game: Game, role: Role) -> bool:
    return any(p.role == role for p in game.players.values())


def _holder_dead_or_absent_ready(game: Game, role: Role) -> bool:
    if not _role_was_dealt(game, role):
        return True
    return find_alive_role_holder(game, role) is None


def _confirmed_if_alive(game: Game, role: Role, attr: str) -> bool:
    if _holder_dead_or_absent_ready(game, role):
        return True
    return bool(getattr(game, attr))


def _saboteur_ready(game: Game) -> bool:
    if _holder_dead_or_absent_ready(game, Role.SABOTEUR):
        return True
    return game.mason_night_saboteur_confirmed


def _saboteur_ready_reason(game: Game) -> str | None:
    from bot.roles import mason_saboteur as ms_sb

    if _holder_dead_or_absent_ready(game, Role.SABOTEUR):
        return None
    if not ms_sb.mason_saboteur_needs_night_pick(game):
        if not game.mason_night_saboteur_confirmed:
            return "تأیید خرابکار (اوکی) ثبت نشده"
        return None
    if not game.mason_night_saboteur_confirmed:
        return "اقدام خرابکار تمام نشده"
    return None


def _doctor_ready(game: Game) -> bool:
    return _confirmed_if_alive(game, Role.DOCTOR, "mason_night_doctor_confirmed")


def _doctor_ready_reason(game: Game) -> str | None:
    if _doctor_ready(game):
        return None
    return "اقدام پزشک تمام نشده"


def _gunner_ready(game: Game) -> bool:
    from bot.roles import mason_gunner as ms_gn

    if _holder_dead_or_absent_ready(game, Role.GUNMAN):
        return True
    if not ms_gn.mason_gunner_can_give_gun(game):
        return True
    return game.mason_night_gunner_confirmed


def _gunner_ready_reason(game: Game) -> str | None:
    from bot.roles import mason_gunner as ms_gn

    if _holder_dead_or_absent_ready(game, Role.GUNMAN):
        return None
    if not ms_gn.mason_gunner_can_give_gun(game):
        return None
    if not game.mason_night_gunner_confirmed:
        return "اقدام تفنگدار تمام نشده"
    return None


def _guardian_ready(game: Game) -> bool:
    if _holder_dead_or_absent_ready(game, Role.BODYGUARD):
        return True
    return game.mason_night_guardian_confirmed


def _guardian_ready_reason(game: Game) -> str | None:
    from bot.roles import mason_guardian as ms_gd

    if _holder_dead_or_absent_ready(game, Role.BODYGUARD):
        return None
    if not ms_gd.mason_guardian_needs_night_pick(game):
        if not game.mason_night_guardian_confirmed:
            return "تأیید محافظ (اوکی) ثبت نشده"
        return None
    if not game.mason_night_guardian_confirmed:
        return "اقدام محافظ تمام نشده"
    return None


def _mason_recruit_ready(game: Game) -> bool:
    return _confirmed_if_alive(game, Role.MASON, "mason_night_mason_confirmed")


def _mason_recruit_ready_reason(game: Game) -> str | None:
    if _mason_recruit_ready(game):
        return None
    return "اقدام ماسون تمام نشده"


def _detective_ready(game: Game) -> bool:
    return _confirmed_if_alive(game, Role.DETECTIVE, "mason_night_detective_confirmed")


def _detective_ready_reason(game: Game) -> str | None:
    if _detective_ready(game):
        return None
    return "اقدام کارآگاه تمام نشده"


def _natasha_ready(game: Game) -> bool:
    return _confirmed_if_alive(game, Role.NATASHA, "mason_night_natasha_confirmed")


def _natasha_ready_reason(game: Game) -> str | None:
    if _natasha_ready(game):
        return None
    return "اقدام ناتاشا تمام نشده"


def _priest_ready(game: Game) -> bool:
    return _confirmed_if_alive(game, Role.PRIEST, "mason_night_priest_confirmed")


def _priest_ready_reason(game: Game) -> str | None:
    if _priest_ready(game):
        return None
    return "اقدام کشیش تمام نشده"


def _sniper_ready(game: Game) -> bool:
    if _holder_dead_or_absent_ready(game, Role.SNIPER):
        return True
    return game.mason_night_sniper_confirmed


def _sniper_ready_reason(game: Game) -> str | None:
    from bot.roles import mason_sniper as ms_sn

    if _holder_dead_or_absent_ready(game, Role.SNIPER):
        return None
    if not ms_sn.mason_sniper_needs_night_pick(game):
        if not game.mason_night_sniper_confirmed:
            return "تأیید اسنایپر (اوکی) ثبت نشده"
        return None
    if not game.mason_night_sniper_confirmed:
        return "اقدام اسنایپر تمام نشده"
    return None


def _commander_ready(game: Game) -> bool:
    from bot.roles import mason_commander as ms_cmd
    from bot.roles import mason_sniper as ms_sn

    cmd = find_alive_role_holder(game, Role.COMMANDER)
    sn = find_alive_role_holder(game, Role.SNIPER)
    if cmd is None:
        return True
    if sn is None:
        if (
            ms_cmd.mason_commander_inherits_sniper_shooting(game)
            and ms_sn.mason_sniper_bullets_remaining(game) <= 0
        ):
            return game.mason_night_commander_confirmed
        return game.mason_night_commander_confirmed
    if not _sniper_ready(game):
        return False
    return game.mason_night_commander_confirmed


def _commander_ready_reason(game: Game) -> str | None:
    from bot.roles import mason_commander as ms_cmd
    from bot.roles import mason_sniper as ms_sn

    cmd = find_alive_role_holder(game, Role.COMMANDER)
    sn = find_alive_role_holder(game, Role.SNIPER)
    if cmd is None:
        return None
    if sn is None and (
        ms_cmd.mason_commander_inherits_sniper_shooting(game)
        and ms_sn.mason_sniper_bullets_remaining(game) <= 0
    ):
        if not game.mason_night_commander_confirmed:
            return "تأیید فرمانده (اوکی) ثبت نشده"
        return None
    sniper_reason = _sniper_ready_reason(game)
    if sn is not None and sniper_reason:
        return sniper_reason
    if not game.mason_night_commander_confirmed:
        if game.mason_night_commander_panel_sent:
            return "پنل فرمانده باز است"
        return "پنل فرمانده ارسال نشده"
    return None


def _waiters_ready(game: Game) -> bool:
    holders = _night_wait_ok_holder_uids(game)
    done = set(game.mason_night_wait_ok_uids)
    for p in game.players.values():
        if not p.is_alive:
            continue
        if p.user_id in holders:
            continue
        if p.user_id in done:
            continue
        if _player_auto_satisfied_wait_ok(game, p):
            continue
        return False
    return True


def _night_wait_ok_holder_uids(game: Game) -> set[int]:
    """همان مجموعهٔ night_action_holder_uids به‌علاوهٔ فرمانده وقتی اسنایپر زنده است."""
    from bot.mason_night_entry import night_action_holder_uids

    holders = set(night_action_holder_uids(game))
    cmd = find_alive_role_holder(game, Role.COMMANDER)
    sn = find_alive_role_holder(game, Role.SNIPER)
    if cmd is not None and sn is not None:
        holders.add(cmd.user_id)
    return holders


def _player_auto_satisfied_wait_ok(game: Game, player: Player) -> bool:
    """بازیکنانی که پنل اوکی عمومی «منتظر شب» لازم ندارند."""
    if player.role == Role.GUNMAN:
        from bot.roles import mason_gunner as ms_gn

        if not ms_gn.mason_gunner_can_give_gun(game):
            return True
    if player.role == Role.SNIPER:
        from bot.roles import mason_sniper as ms_sn

        if not ms_sn.mason_sniper_needs_night_pick(game):
            return True
    if player.role == Role.COMMANDER:
        from bot.roles import mason_commander as ms_cmd
        from bot.roles import mason_sniper as ms_sn

        if (
            ms_cmd.mason_commander_inherits_sniper_shooting(game)
            and ms_sn.mason_sniper_bullets_remaining(game) <= 0
        ):
            return True
    return False


def _role_confirmed_attr(role: Role) -> str | None:
    return {
        Role.SABOTEUR: "mason_night_saboteur_confirmed",
        Role.DOCTOR: "mason_night_doctor_confirmed",
        Role.SNIPER: "mason_night_sniper_confirmed",
        Role.COMMANDER: "mason_night_commander_confirmed",
        Role.GUNMAN: "mason_night_gunner_confirmed",
        Role.BODYGUARD: "mason_night_guardian_confirmed",
        Role.MASON: "mason_night_mason_confirmed",
        Role.DETECTIVE: "mason_night_detective_confirmed",
        Role.NATASHA: "mason_night_natasha_confirmed",
        Role.PRIEST: "mason_night_priest_confirmed",
    }.get(role)


def _night_action_holder_reason(game: Game, uid: int) -> str | None:
    from bot.mason_night_entry import night_action_holder_uids
    from bot.no_host_mafia_chooser import resolve_mafia_night1_panel_recipients

    if uid not in night_action_holder_uids(game):
        cmd = find_alive_role_holder(game, Role.COMMANDER)
        sn = find_alive_role_holder(game, Role.SNIPER)
        if cmd is not None and sn is not None and uid == cmd.user_id:
            return _commander_ready_reason(game)
        return None

    for p in resolve_mafia_night1_panel_recipients(game):
        if p.user_id == uid:
            return _mafia_ready_reason(game)

    for role in (
        Role.SABOTEUR,
        Role.DOCTOR,
        Role.SNIPER,
        Role.GUNMAN,
        Role.BODYGUARD,
        Role.MASON,
        Role.DETECTIVE,
        Role.NATASHA,
        Role.PRIEST,
    ):
        holder = find_alive_role_holder(game, role)
        if holder is not None and holder.user_id == uid:
            reason_by_role = {
                Role.SABOTEUR: _saboteur_ready_reason,
                Role.DOCTOR: _doctor_ready_reason,
                Role.SNIPER: _sniper_ready_reason,
                Role.GUNMAN: _gunner_ready_reason,
                Role.BODYGUARD: _guardian_ready_reason,
                Role.MASON: _mason_recruit_ready_reason,
                Role.DETECTIVE: _detective_ready_reason,
                Role.NATASHA: _natasha_ready_reason,
                Role.PRIEST: _priest_ready_reason,
            }
            reason_fn = reason_by_role.get(role)
            if reason_fn is not None:
                return reason_fn(game)
            if role == Role.COMMANDER:
                return _commander_ready_reason(game) or "اقدام فرمانده تمام نشده"
            return f"اقدام {role.value} تمام نشده"
    return None


@dataclass(frozen=True)
class MasonNightReadinessLine:
    label: str
    status: str
    reason: str | None = None


def build_mason_night_readiness_report(
    game: Game, gm: "GameManager"
) -> tuple[list[MasonNightReadinessLine], bool]:
    lines: list[MasonNightReadinessLine] = []
    if not is_mason_scenario(game):
        return [MasonNightReadinessLine("scenario", "waiting", "not mason")], False

    if not no_host_parallel_night_collect_active(game):
        lines.append(
            MasonNightReadinessLine(
                "collect phase",
                "waiting",
                "parallel night collect inactive",
            )
        )

    role_checks = (
        ("mafia", _mafia_ready(game), _mafia_ready_reason(game)),
        ("saboteur", _saboteur_ready(game), _saboteur_ready_reason(game)),
        ("doctor", _doctor_ready(game), _doctor_ready_reason(game)),
        ("sniper", _sniper_ready(game), _sniper_ready_reason(game)),
        ("commander", _commander_ready(game), _commander_ready_reason(game)),
        ("gunner", _gunner_ready(game), _gunner_ready_reason(game)),
        ("guardian", _guardian_ready(game), _guardian_ready_reason(game)),
        ("mason", _mason_recruit_ready(game), _mason_recruit_ready_reason(game)),
        ("detective", _detective_ready(game), _detective_ready_reason(game)),
        ("natasha", _natasha_ready(game), _natasha_ready_reason(game)),
        ("priest", _priest_ready(game), _priest_ready_reason(game)),
        (
            "wait ok",
            _waiters_ready(game),
            None if _waiters_ready(game) else "no-action OK pending",
        ),
    )
    for label, ok, reason in role_checks:
        lines.append(
            MasonNightReadinessLine(
                label,
                "complete" if ok else "waiting",
                None if ok else reason,
            )
        )

    holders = _night_wait_ok_holder_uids(game)
    done = set(game.mason_night_wait_ok_uids)

    for p in sorted(
        (pl for pl in game.players.values() if pl.is_alive),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        name = gm.format_player_tag(p)
        if p.user_id in holders:
            reason = _night_action_holder_reason(game, p.user_id)
            if reason:
                lines.append(MasonNightReadinessLine(name, "waiting", reason))
            else:
                lines.append(MasonNightReadinessLine(name, "complete", None))
        elif p.user_id in done:
            lines.append(MasonNightReadinessLine(name, "complete", None))
        elif _player_auto_satisfied_wait_ok(game, p):
            lines.append(MasonNightReadinessLine(name, "complete", None))
        else:
            lines.append(
                MasonNightReadinessLine(name, "waiting", "no-action OK panel")
            )

    return lines, all_mason_parallel_night_ready(game)


def format_mason_night_readiness_report(game: Game, gm: "GameManager") -> str:
    lines, ready = build_mason_night_readiness_report(game, gm)
    out = ["Night readiness status", ""]
    for line in lines:
        if line.status == "complete":
            out.append(f"{line.label}: complete")
        else:
            reason = line.reason or "unknown"
            out.append(f"{line.label}: waiting ({reason})")
    out.append("")
    out.append(f"Final readiness = {ready}")
    return "\n".join(out)


def all_mason_parallel_night_ready(game: Game) -> bool:
    if not is_mason_scenario(game):
        return False
    if not no_host_parallel_night_collect_active(game):
        return False
    checks = (
        _mafia_ready(game),
        _saboteur_ready(game),
        _doctor_ready(game),
        _sniper_ready(game),
        _commander_ready(game),
        _gunner_ready(game),
        _guardian_ready(game),
        _mason_recruit_ready(game),
        _detective_ready(game),
        _natasha_ready(game),
        _priest_ready(game),
        _waiters_ready(game),
    )
    return all(checks)


def _mason_no_pick_ok_panel_kind(game: Game, role: Role) -> str | None:
    """نوع پنل اوکی تک‌باره برای نقش بدون انتخاب شبانه."""
    from bot.roles import mason_commander as ms_cmd
    from bot.roles import mason_doctor as ms_doc
    from bot.roles import mason_guardian as ms_gd
    from bot.roles import mason_saboteur as ms_sb
    from bot.roles import mason_sniper as ms_sn

    if _holder_dead_or_absent_ready(game, role):
        return None
    if role == Role.SABOTEUR and not ms_sb.mason_saboteur_needs_night_pick(game):
        return "خرابکار — اوکی (تفنگ مصرف‌شده)"
    if role == Role.BODYGUARD and not ms_gd.mason_guardian_needs_night_pick(game):
        return "محافظ — اوکی (بدون انتخاب)"
    if role == Role.SNIPER and not ms_sn.mason_sniper_needs_night_pick(game):
        return "اسنایپر — اوکی (بدون گلوله)"
    if role == Role.COMMANDER and (
        ms_cmd.mason_commander_needs_no_pick_wait_panel(game)
        or ms_cmd.mason_commander_needs_sniper_no_shot_info_panel(game)
    ):
        return "فرمانده — اوکی (بدون انتخاب)"
    if role == Role.DOCTOR and game.mason_night_doctor_nato_void_pending:
        return "پزشک — اوکی (باطل‌شدهٔ ناتویی)"
    return None


def _mason_role_holder_alive(game: Game, role: Role) -> bool:
    return find_alive_role_holder(game, role) is not None


def explain_mason_night_stuck(game: Game, gm: "GameManager") -> str:
    """گزارش دیباگ — چرا شب ماسون جلو نمی‌رود؟"""
    if not is_mason_scenario(game):
        return "Not a Mason scenario."

    from bot.no_host_night_ready import no_host_parallel_night_collect_active

    phase = game.bazpors_narrator_step or "unknown"
    night = game.bazpors_narrator_night_count
    collect_active = no_host_parallel_night_collect_active(game)
    lines: list[str] = [
        f"Phase: {phase} (night {night})",
        f"Parallel night collect active: {collect_active}",
        "",
    ]

    skip_notes = _collect_mason_night_skip_notes(game)
    mafia_summary = _describe_mason_mafia_action_complete_summary(game, gm)
    if mafia_summary:
        lines.append(mafia_summary)
        next_blocker = _describe_mason_next_role_blocker(game, gm)
        if next_blocker:
            lines.append(next_blocker)
        lines.append("")

    from bot.mason_responsibilities import format_mason_responsibilities_report

    resp_report = format_mason_responsibilities_report(game, gm, phase="night")
    if resp_report and "No Mason" not in resp_report:
        lines.append(resp_report)
        lines.append("")

    if all_mason_parallel_night_ready(game):
        lines.append("Night readiness complete — game should advance.")
        if skip_notes:
            lines.extend(["", "Skipped (not blocking):", *[f"- {n}" for n in skip_notes]])
        return "\n".join(lines)

    waiting_roles: list[str] = []
    state_fields: list[str] = []
    blocker_details: list[str] = []

    role_gates = (
        (Role.SABOTEUR, "Saboteur", _saboteur_ready, _saboteur_ready_reason, "mason_night_saboteur_confirmed"),
        (Role.DOCTOR, "Doctor", _doctor_ready, _doctor_ready_reason, "mason_night_doctor_confirmed"),
        (Role.SNIPER, "Sniper", _sniper_ready, _sniper_ready_reason, "mason_night_sniper_confirmed"),
        (Role.COMMANDER, "Commander", _commander_ready, _commander_ready_reason, "mason_night_commander_confirmed"),
        (Role.GUNMAN, "Gunner", _gunner_ready, _gunner_ready_reason, "mason_night_gunner_confirmed"),
        (Role.BODYGUARD, "Guardian", _guardian_ready, _guardian_ready_reason, "mason_night_guardian_confirmed"),
        (Role.MASON, "Mason", _mason_recruit_ready, _mason_recruit_ready_reason, "mason_night_mason_confirmed"),
        (Role.DETECTIVE, "Detective", _detective_ready, _detective_ready_reason, "mason_night_detective_confirmed"),
        (Role.NATASHA, "Natasha", _natasha_ready, _natasha_ready_reason, "mason_night_natasha_confirmed"),
        (Role.PRIEST, "Priest", _priest_ready, _priest_ready_reason, "mason_night_priest_confirmed"),
    )
    if not _mafia_ready(game):
        waiting_roles.append("Mafia")
        reason = _mafia_ready_reason(game)
        if reason:
            state_fields.append(reason)
        mafia_detail = _describe_mason_mafia_night_blocker(game, gm)
        if mafia_detail:
            blocker_details.append(mafia_detail)

    for role, label, ready_fn, reason_fn, field in role_gates:
        if ready_fn(game):
            continue
        waiting_roles.append(label)
        reason = reason_fn(game)
        confirmed = getattr(game, field)
        state_fields.append(f"{field} = {confirmed}")
        if reason:
            state_fields.append(reason)
        alive = _mason_role_holder_alive(game, role)
        ok_panel = _mason_no_pick_ok_panel_kind(game, role)
        if alive:
            if ok_panel and not confirmed:
                blocker_details.append(
                    f"{label}: alive — needs role-panel {ok_panel} (اوکی); {field}=False"
                )
            elif ok_panel and confirmed:
                blocker_details.append(
                    f"{label}: alive — {ok_panel} already acknowledged; check stale panel"
                )
            else:
                blocker_details.append(
                    f"{label}: alive — needs night action; {field}=False"
                )
        else:
            blocker_details.append(
                f"{label}: holder dead/absent but readiness gate false — unexpected"
            )

    if not _waiters_ready(game):
        waiting_roles.append("No-action OK waiters")
        holders = _night_wait_ok_holder_uids(game)
        done = set(game.mason_night_wait_ok_uids)
        for p in game.players.values():
            if not p.is_alive or p.user_id in holders or p.user_id in done:
                continue
            if _player_auto_satisfied_wait_ok(game, p):
                continue
            tag = gm.format_player_tag(p)
            waiting_roles.append(tag)
            blocker_details.append(
                f"{tag}: alive — needs generic wait-panel اوکی "
                f"(mason_night_wait_ok_uids does not contain {p.user_id})"
            )

    if not collect_active:
        state_fields.insert(0, "no_host_parallel_night_collect_active = False")

    if skip_notes:
        lines.extend(["Skipped (not blocking):", *[f"- {n}" for n in skip_notes], ""])
    lines.extend(["Waiting for:", *[f"- {name}" for name in waiting_roles]])
    if state_fields:
        lines.extend(["", "Waiting because:", *[f"- {item}" for item in state_fields]])
    if blocker_details:
        lines.extend(["", "Blocker details:", *[f"- {item}" for item in blocker_details]])
    return "\n".join(lines)


def _collect_mason_night_skip_notes(game: Game) -> list[str]:
    notes: list[str] = []
    dead_labels = (
        (Role.DOCTOR, "Doctor"),
        (Role.SNIPER, "Sniper"),
        (Role.COMMANDER, "Commander"),
        (Role.GUNMAN, "Gunner"),
        (Role.BODYGUARD, "Guardian"),
        (Role.MASON, "Mason"),
        (Role.DETECTIVE, "Detective"),
        (Role.NATASHA, "Natasha"),
        (Role.PRIEST, "Priest"),
        (Role.SABOTEUR, "Saboteur"),
    )
    for role, label in dead_labels:
        if _holder_dead_or_absent_ready(game, role):
            notes.append(f"No blocker: {label} is dead, skipped.")
    if _role_was_dealt(game, Role.GODFATHER) and _holder_dead_or_absent_ready(
        game, Role.GODFATHER
    ):
        notes.append("No blocker: Godfather dead, skipped.")
    return notes


async def maybe_finish_mason_parallel_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    try:
        from bot.mason_night_reminder import refresh_mason_night_helper_reminder

        await refresh_mason_night_helper_reminder(bot, game, gm)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "mason night reminder refresh failed room=%s", game.room_code
        )
    if not all_mason_parallel_night_ready(game):
        return
    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)
