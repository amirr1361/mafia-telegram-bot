"""مسئولیت‌های مستقل پنل — فقط سناریوی ماسون."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bot.models import Game, Player, Role
from bot.observer_delivery import mirror_ui_claim_key
from bot.room_mode import is_mason_scenario
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from bot.game import GameManager

# نقش‌های مافیا که ممکن است پنل شلیک/مافیا جدا از پنل نقش خود داشته باشند.
MASON_MAFIA_DUAL_NIGHT_ROLES: frozenset[Role] = frozenset(
    {
        Role.NATO,
        Role.SABOTEUR,
        Role.MAFIA_BASIC,
        Role.NATASHA,
        Role.SPY,
        Role.APACHE,
    }
)


@dataclass(frozen=True)
class MasonResponsibility:
    """یک مسئولیت مستقل — پنل، state و readiness جدا."""

    responsibility_id: str
    label: str
    holder_uid: int | None
    role: Role | None
    state_field: str
    done: bool
    panel_sent: bool
    required: bool
    skipped_reason: str | None = None
    panel_ui_kind: str | None = None


def _mirror_panel_sent(game: Game, ui_kind: str, uid: int) -> bool:
    key = mirror_ui_claim_key(game.room_code, ui_kind, uid)
    entry = game.mirror_prompt_messages.get(key, {})
    return bool(entry.get("player") or entry.get("observer"))


def _mafia_night1_panel_sent(game: Game, uid: int) -> bool:
    from bot.no_host_mafia_night1 import (
        _mafia_night1_ui_key,
        mafia_night1_panel_delivered,
    )

    if mafia_night1_panel_delivered(game, uid):
        return True
    key = _mafia_night1_ui_key(game, uid)
    entry = game.mirror_prompt_messages.get(key, {})
    return bool(entry.get("player") or entry.get("observer"))


def _mafia_shot_panel_sent(game: Game, uid: int) -> bool:
    from bot.no_host_mafia_shot import _mafia_shot_ui_key

    if _mirror_panel_sent(game, "night1_mafia", uid):
        return True
    nc = max(1, game.bazpors_narrator_night_count)
    key = mirror_ui_claim_key(game.room_code, f"mafia_shot_n{nc}", uid)
    entry = game.mirror_prompt_messages.get(key, {})
    return bool(entry.get("player") or entry.get("observer"))


def mason_holder_has_separate_night_panel(game: Game, uid: int) -> bool:
    """بازیکن هم پنل مافیا دارد هم پنل/اوکی نقش مستقل."""
    if not is_mason_scenario(game):
        return False
    player = game.players.get(uid)
    if player is None or not player.is_alive:
        return False
    if player.role not in MASON_MAFIA_DUAL_NIGHT_ROLES:
        return False
    if player.role == Role.SABOTEUR:
        from bot.roles import mason_saboteur as ms_sb

        if find_alive_role_holder(game, Role.SABOTEUR) is None:
            return False
        return True
    if player.role == Role.NATASHA:
        return find_alive_role_holder(game, Role.NATASHA) is not None
    if player.role == Role.NATO:
        return find_alive_role_holder(game, Role.NATO) is not None
    if player.role == Role.MAFIA_BASIC:
        return find_alive_role_holder(game, Role.MAFIA_BASIC) is not None
    if player.role == Role.SPY:
        return find_alive_role_holder(game, Role.SPY) is not None
    if player.role == Role.APACHE:
        return find_alive_role_holder(game, Role.APACHE) is not None
    return False


def mason_mafia_shot_uses_dedicated_panel(game: Game, mafia_uid: int) -> bool:
    """پنل شلیک مافیا نباید پیام پنل نقش دیگر را بازنویسی کند."""
    return is_mason_scenario(game) and mason_holder_has_separate_night_panel(
        game, mafia_uid
    )


def _mafia_shot_responsibility(game: Game, gm: "GameManager") -> MasonResponsibility:
    from bot.no_host_mafia_chooser import resolve_mafia_shot_chooser
    from bot.roles.mason_godfather import resolve_mason_mafia_action_holder_label

    chooser = resolve_mafia_shot_chooser(game)
    uid = chooser.user_id if chooser is not None else None
    holder_label = resolve_mason_mafia_action_holder_label(game)
    shot_done = bool(
        game.no_host_mafia_shot_done or game.bazpors_mafia_shot_registered
    )
    panel_sent = _mafia_shot_panel_sent(game, uid) if uid is not None else False
    return MasonResponsibility(
        responsibility_id="mafia_shot",
        label=f"Mafia shot ({holder_label})",
        holder_uid=uid,
        role=chooser.role if chooser is not None else None,
        state_field="no_host_mafia_shot_done",
        done=shot_done,
        panel_sent=panel_sent,
        required=chooser is not None,
        panel_ui_kind="mafia_shot",
    )


def _role_night_responsibility(
    game: Game,
    role: Role,
    *,
    resp_id: str,
    label: str,
    state_field: str,
    ui_kind: str,
    ready_fn,
    holder_dead_fn,
) -> MasonResponsibility | None:
    if holder_dead_fn(game, role):
        if not _role_was_dealt(game, role):
            return None
        return MasonResponsibility(
            responsibility_id=resp_id,
            label=label,
            holder_uid=None,
            role=role,
            state_field=state_field,
            done=True,
            panel_sent=False,
            required=False,
            skipped_reason=f"{label} holder dead/absent, skipped.",
        )
    holder = find_alive_role_holder(game, role)
    if holder is None:
        return None
    return MasonResponsibility(
        responsibility_id=resp_id,
        label=label,
        holder_uid=holder.user_id,
        role=role,
        state_field=state_field,
        done=ready_fn(game),
        panel_sent=_mirror_panel_sent(game, ui_kind, holder.user_id),
        required=True,
        panel_ui_kind=ui_kind,
    )


def _role_was_dealt(game: Game, role: Role) -> bool:
    return any(p.role == role for p in game.players.values())


def collect_mason_night_responsibilities(
    game: Game, gm: "GameManager"
) -> list[MasonResponsibility]:
    if not is_mason_scenario(game):
        return []

    from bot.mason_night_ready import (
        _commander_ready,
        _detective_ready,
        _doctor_ready,
        _gunner_ready,
        _guardian_ready,
        _holder_dead_or_absent_ready,
        _mason_recruit_ready,
        _natasha_ready,
        _priest_ready,
        _saboteur_ready,
        _sniper_ready,
    )

    out: list[MasonResponsibility] = []

    from bot.no_host_mafia_night1 import MAFIA_ACTION_NATO, MAFIA_ACTION_SHOT

    if not game.no_host_mafia_night1_done:
        from bot.no_host_mafia_chooser import resolve_mafia_night1_panel_recipients
        from bot.roles.mason_godfather import resolve_mason_mafia_action_holder_label

        recipients = resolve_mafia_night1_panel_recipients(game)
        uid = recipients[0].user_id if recipients else None
        holder_label = resolve_mason_mafia_action_holder_label(game)
        out.append(
            MasonResponsibility(
                responsibility_id="mafia_menu",
                label=f"Mafia menu ({holder_label})",
                holder_uid=uid,
                role=recipients[0].role if recipients else None,
                state_field="no_host_mafia_night1_done",
                done=False,
                panel_sent=_mafia_night1_panel_sent(game, uid) if uid else False,
                required=bool(recipients),
                panel_ui_kind="night1_mafia",
            )
        )
    elif game.no_host_mafia_night1_chosen_action == MAFIA_ACTION_NATO:
        if not game.no_host_mafia_nato_done:
            nato = find_alive_role_holder(game, Role.NATO)
            from bot.no_host_mafia_nato import _nato_ui_key

            uid = nato.user_id if nato else game.no_host_mafia_night1_chooser_uid
            panel_sent = False
            if uid is not None:
                key = _nato_ui_key(game, uid)
                entry = game.mirror_prompt_messages.get(key, {})
                panel_sent = bool(entry.get("player") or entry.get("observer"))
            out.append(
                MasonResponsibility(
                    responsibility_id="mafia_nato",
                    label="NATO sub-flow",
                    holder_uid=uid,
                    role=Role.NATO,
                    state_field="no_host_mafia_nato_done",
                    done=game.no_host_mafia_nato_done,
                    panel_sent=panel_sent,
                    required=True,
                    panel_ui_kind="nato",
                )
            )
    elif game.no_host_mafia_night1_chosen_action in (MAFIA_ACTION_SHOT, None):
        shot_resp = _mafia_shot_responsibility(game, gm)
        if shot_resp.required or not shot_resp.done:
            out.append(shot_resp)

    role_specs = (
        (Role.SABOTEUR, "saboteur_role", "Saboteur role", "mason_night_saboteur_confirmed", "mason_saboteur", _saboteur_ready),
        (Role.DOCTOR, "doctor_role", "Doctor", "mason_night_doctor_confirmed", "mason_doctor", _doctor_ready),
        (Role.SNIPER, "sniper_role", "Sniper", "mason_night_sniper_confirmed", "mason_sniper", _sniper_ready),
        (Role.COMMANDER, "commander_role", "Commander", "mason_night_commander_confirmed", "mason_commander", _commander_ready),
        (Role.GUNMAN, "gunner_role", "Gunner", "mason_night_gunner_confirmed", "mason_gunner", _gunner_ready),
        (Role.BODYGUARD, "guardian_role", "Guardian", "mason_night_guardian_confirmed", "mason_guardian", _guardian_ready),
        (Role.MASON, "mason_role", "Mason recruit", "mason_night_mason_confirmed", "mason_recruit", _mason_recruit_ready),
        (Role.DETECTIVE, "detective_role", "Detective", "mason_night_detective_confirmed", "mason_detective", _detective_ready),
        (Role.NATASHA, "natasha_role", "Natasha", "mason_night_natasha_confirmed", "mason_natasha", _natasha_ready),
        (Role.PRIEST, "priest_role", "Priest", "mason_night_priest_confirmed", "mason_priest", _priest_ready),
    )
    for role, resp_id, label, field, ui_kind, ready_fn in role_specs:
        resp = _role_night_responsibility(
            game,
            role,
            resp_id=resp_id,
            label=label,
            state_field=field,
            ui_kind=ui_kind,
            ready_fn=ready_fn,
            holder_dead_fn=_holder_dead_or_absent_ready,
        )
        if resp is not None:
            out.append(resp)

    from bot.mason_night_entry import _wait_ui_key
    from bot.mason_night_ready import (
        _night_wait_ok_holder_uids,
        _player_auto_satisfied_wait_ok,
        _waiters_ready,
    )

    if not _waiters_ready(game):
        holders = _night_wait_ok_holder_uids(game)
        done = set(game.mason_night_wait_ok_uids)
        for p in game.players.values():
            if not p.is_alive or p.user_id in holders or p.user_id in done:
                continue
            if _player_auto_satisfied_wait_ok(game, p):
                continue
            key = _wait_ui_key(game, p.user_id)
            entry = game.mirror_prompt_messages.get(key, {})
            panel_sent = bool(entry.get("player") or entry.get("observer"))
            out.append(
                MasonResponsibility(
                    responsibility_id=f"wait_ok_{p.user_id}",
                    label="Night wait OK",
                    holder_uid=p.user_id,
                    role=p.role,
                    state_field="mason_night_wait_ok_uids",
                    done=False,
                    panel_sent=panel_sent,
                    required=True,
                    panel_ui_kind="mason_night_wait",
                )
            )
    return out


def collect_mason_day_responsibilities(
    game: Game, gm: "GameManager"
) -> list[MasonResponsibility]:
    if not is_mason_scenario(game):
        return []
    from bot.roles import mason_apache as ms_ap
    from bot.roles import mason_cowboy as ms_cw
    from bot.roles import mason_gunner as ms_gn

    out: list[MasonResponsibility] = []
    panels_open = (
        game.mason_intro_day_ability_open and not game.mason_intro_day_ability_locked
    )

    apache = ms_ap.find_alive_mason_apache(game)
    if apache is not None and panels_open:
        out.append(
            MasonResponsibility(
                responsibility_id="apache_day",
                label="Apache day ability",
                holder_uid=apache.user_id,
                role=Role.APACHE,
                state_field="mason_apache_day_pick_confirmed",
                done=bool(game.mason_apache_day_pick_confirmed),
                panel_sent=_mirror_panel_sent(game, "mason_apache_day", apache.user_id),
                required=True,
                panel_ui_kind="mason_apache_day",
            )
        )

    cowboy = ms_cw.find_alive_mason_cowboy(game)
    if cowboy is not None and panels_open:
        out.append(
            MasonResponsibility(
                responsibility_id="cowboy_day",
                label="Cowboy day ability",
                holder_uid=cowboy.user_id,
                role=Role.COWBOY,
                state_field="mason_cowboy_day_pick_confirmed",
                done=bool(game.mason_cowboy_day_pick_confirmed),
                panel_sent=_mirror_panel_sent(game, "mason_cowboy_day", cowboy.user_id),
                required=True,
                panel_ui_kind="mason_cowboy_day",
            )
        )

    holder_uid = ms_gn.mason_day_gun_holder_uid(game)
    if holder_uid is not None and ms_gn.mason_day_gun_available(game) and panels_open:
        holder = game.players.get(holder_uid)
        out.append(
            MasonResponsibility(
                responsibility_id="day_gun",
                label="Day gun",
                holder_uid=holder_uid,
                role=holder.role if holder else None,
                state_field="mason_day_gun_used",
                done=ms_gn.mason_day_gun_is_used(game),
                panel_sent=_mirror_panel_sent(game, "mason_day_gun", holder_uid),
                required=True,
                panel_ui_kind="mason_day_gun",
            )
        )
    return out


def _format_resp_line(game: Game, gm: "GameManager", resp: MasonResponsibility) -> str:
    if resp.skipped_reason:
        return f"- {resp.label}: skipped ({resp.skipped_reason})"
    tag = "none"
    if resp.holder_uid is not None:
        pl = game.players.get(resp.holder_uid)
        if pl is not None:
            tag = gm.format_player_tag(pl)
    alive = (
        game.players[resp.holder_uid].is_alive
        if resp.holder_uid is not None and resp.holder_uid in game.players
        else False
    )
    status = "done=True" if resp.done else "done=False"
    return (
        f"- {resp.label}: holder={tag}, alive={alive}, "
        f"{status}, panel_sent={resp.panel_sent}, field={resp.state_field}"
    )


def format_mason_responsibilities_report(
    game: Game, gm: "GameManager", *, phase: str = "night"
) -> str:
    if phase == "day":
        resps = collect_mason_day_responsibilities(game, gm)
    else:
        resps = collect_mason_night_responsibilities(game, gm)
    if not resps:
        return "No Mason responsibilities tracked."
    completed = [r for r in resps if r.done or r.skipped_reason]
    waiting = [r for r in resps if not r.done and not r.skipped_reason]
    lines: list[str] = []
    if completed:
        lines.append("Completed responsibilities:")
        lines.extend(_format_resp_line(game, gm, r) for r in completed)
    if waiting:
        if completed:
            lines.append("")
        lines.append("Waiting responsibilities:")
        lines.extend(_format_resp_line(game, gm, r) for r in waiting)
    return "\n".join(lines)


async def redispatch_mason_role_panel_after_mafia_shot(
    bot, game: Game, gm: "GameManager", *, mafia_uid: int
) -> None:
    """پس از شلیک مافیا — پنل نقش مستقل را دوباره بفرست اگر هنوز تأیید نشده."""
    if not is_mason_scenario(game):
        return
    player = game.players.get(mafia_uid)
    if player is None or not player.is_alive:
        return
    if player.role == Role.SABOTEUR and not game.mason_night_saboteur_confirmed:
        from bot.mason_night_role import dispatch_mason_saboteur_panel

        await dispatch_mason_saboteur_panel(bot, game, gm)
    elif player.role == Role.NATASHA and not game.mason_night_natasha_confirmed:
        from bot.mason_night_role import dispatch_mason_natasha_panel

        await dispatch_mason_natasha_panel(bot, game, gm)
