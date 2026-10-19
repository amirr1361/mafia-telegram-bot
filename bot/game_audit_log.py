"""
لاگ رویدادهای بازی برای عیب‌یابی — یک فایل JSONL به ازای هر دست.

هر خط یک رویداد با زمان، نوع، و وضعیت/جزئیات است تا بتوان روند بازی را
بعداً مرور یا شبیه‌سازی کرد.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bot.config import game_audit_log_enabled, get_game_audit_log_dir

from bot.models import Game, Role
from bot.roles.night_state import yaku_night_state

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_val(role: Role | None) -> str | None:
    return role.value if role else None


def init_audit_log(game: Game) -> Path | None:
    """فایل لاگ را هنگام شروع بازی (پخش نقش) می‌سازد."""
    if not game_audit_log_enabled():
        return None
    base = get_game_audit_log_dir()
    base.mkdir(parents=True, exist_ok=True)
    started = game.roles_dealt_at or datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    path = base / f"{game.room_code}_{stamp}.jsonl"
    game.audit_log_path = str(path)
    log_event(
        game,
        "audit.initialized",
        path=str(path),
        scenario=game.scenario_name,
        host_id=game.host_id,
        max_players=game.max_players,
    )
    return path


def log_event(game: Game, event: str, **payload: Any) -> None:
    if not game_audit_log_enabled():
        return
    path = game.audit_log_path
    if not path:
        return
    record: dict[str, Any] = {
        "ts": _utc_iso(),
        "room": game.room_code,
        "event": event,
        **payload,
    }
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("game audit log write failed (%s): %s", path, exc)


def players_snapshot(game: Game) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in sorted(
        game.players.values(),
        key=lambda x: (x.seat if x.seat is not None else 999, x.user_id),
    ):
        rows.append(
            {
                "uid": p.user_id,
                "seat": p.seat,
                "name": p.full_name,
                "username": p.username,
                "role": _role_val(p.role),
                "alive": p.is_alive,
                "yakuza_converted": p.bazpors_converted_by_yakuza,
                "original_role": _role_val(p.bazpors_original_role),
            }
        )
    return rows


def _uses_bazpors_snapshot(game: Game) -> bool:
    return game.scenario_name in (
        "bazpors",
        "bazpors_salamat_test",
        "mozakere",
        "masoon",
    )


def bazpors_snapshot(game: Game) -> dict[str, Any]:
    actions = game.actions
    snap: dict[str, Any] = {
        "narrator_step": game.bazpors_narrator_step,
        "night_substep": game.bazpors_night_substep,
        "host_day": game.bazpors_narrator_host_day,
        "night_count": game.bazpors_narrator_night_count,
        "pending_uid": game.bazpors_narrator_pending_uid,
        "hunter_link_uid": game.bazpors_hunter_link_uid,
        "hunter_linked_this_night": game.bazpors_hunter_linked_this_night,
        "mafia_shot_registered": game.bazpors_mafia_shot_registered,
        "mafia_target": actions.mafia_target,
        "doctor_save": actions.doctor_save,
        "detective_check": actions.detective_check,
        "detective_blocked": game.bazpors_detective_blocked,
        "det_no_inquiry": game.bazpors_det_no_inquiry,
        "det_ack_positive": game.bazpors_det_ack_positive,
        "shiad_target_uid": game.bazpors_shiad_target_uid,
        "nato_action_registered": game.bazpors_nato_action_registered,
        "nato_success": game.bazpors_nato_success,
        "nato_kill_target_uid": game.bazpors_nato_kill_target_uid,
        "yakuzai_used": yaku_night_state(game).used,
        "yaku_sac_uid": yaku_night_state(game).sac_uid,
        "yaku_sac_elim_uid": yaku_night_state(game).sac_elim_uid,
        "yaku_night_civilian_uid": yaku_night_state(game).night_civilian_uid,
        "yaku_night_success": yaku_night_state(game).night_success,
        "interrog_first_uid": game.bazpors_interrog_first_uid,
        "interrog_second_uid": game.bazpors_interrog_second_uid,
        "interrog_night_finished": game.bazpors_interrog_night_finished,
        "interrog_ready_for_day": game.bazpors_interrog_ready_for_day,
        "interrog_cancel_next_day": game.bazpors_interrog_cancel_next_day,
        "interrog_once_done": game.bazpors_interrog_once_done,
        "night_discipline_kick_uid": game.bazpors_night_discipline_kick_uid,
        "day_vote_defenders": game.bazpors_day_vote_defender_uids,
        "day_vote_elim_reason": game.bazpors_day_vote_elim_reason,
        "day_vote_participations": dict(game.bazpors_day_vote_participations),
        "mafia_recruit_ids": sorted(game.bazpors_mafia_recruit_ids),
        "sniper_eliminated_uids": sorted(game.bazpors_sniper_eliminated_uids),
        "night_step_history": list(game.bazpors_night_step_history),
        "ki_as_today": game.bazpors_ki_as_today,
        "chaos_handshake_round": game.bazpors_chaos_handshake_round,
        "chaos_choices": dict(game.bazpors_chaos_choices),
        "doctor_self_saves": game.bazpors_doctor_self_save_count,
        "sniper_shot_used": game.bazpors_sniper_shot_used,
        "sniper_night_target_uid": game.bazpors_sniper_night_target_uid,
        "observer_code": game.observer_code,
        "observer_prompt_status": game.observer_prompt_status,
        "observer_user_id": game.observer_user_id,
        "players": players_snapshot(game),
    }
    if game.scenario_name == "mozakere":
        snap.update(
            {
                "mozakere_negotiation_used": game.mozakere_negotiation_used,
                "mozakere_negotiation_tonight": game.mozakere_negotiation_tonight,
                "mozakere_negotiation_target_uid": game.mozakere_negotiation_target_uid,
                "mozakere_negotiation_success": game.mozakere_negotiation_success,
                "mozakere_mafia_recruit_ids": sorted(game.mozakere_mafia_recruit_ids),
                "mozakere_journalist_target_uid": game.mozakere_journalist_target_uid,
                "mozakere_journalist_ack_positive": game.mozakere_journalist_ack_positive,
                "mozakere_sniper_shots_used": game.mozakere_sniper_shots_used,
            }
        )
    return snap


def log_game_started(game: Game, gm: GameManager | None = None) -> None:
    init_audit_log(game)
    payload: dict[str, Any] = {
        "players": players_snapshot(game),
        "mafia_ids": sorted(game.mafia_ids),
    }
    if _uses_bazpors_snapshot(game):
        payload["bazpors"] = bazpors_snapshot(game)
    log_event(game, "game.roles_dealt", **payload)


def log_narrator_callback(
    game: Game,
    gm: GameManager | None,
    *,
    act: str,
    tid: int,
    rid: str,
    step_before: str | None,
    ns_before: str | None,
    pending_before: int | None,
    error: str | None,
) -> None:
    payload: dict[str, Any] = {
        "act": act,
        "tid": tid,
        "rid": rid or None,
        "error": error,
        "before": {
            "step": step_before,
            "night_substep": ns_before,
            "pending_uid": pending_before,
        },
        "after": {
            "step": game.bazpors_narrator_step,
            "night_substep": game.bazpors_night_substep,
            "pending_uid": game.bazpors_narrator_pending_uid,
        },
    }
    if _uses_bazpors_snapshot(game):
        payload["bazpors"] = bazpors_snapshot(game)
    log_event(game, "narrator.callback", **payload)


def log_player_eliminated(
    game: Game,
    uid: int,
    *,
    source: str,
    hunter_chain: bool = True,
    companion_note: str = "",
) -> None:
    p = game.players.get(uid)
    log_event(
        game,
        "player.eliminated",
        uid=uid,
        source=source,
        hunter_chain=hunter_chain,
        companion_note=companion_note or None,
        role=_role_val(p.role) if p else None,
        name=p.full_name if p else None,
        bazpors=bazpors_snapshot(game) if _uses_bazpors_snapshot(game) else None,
    )


def log_night_resolved(game: Game, gm: GameManager | None = None) -> None:
    payload: dict[str, object] = {
        "bazpors": bazpors_snapshot(game),
        "night_report_html": game.bazpors_night_report_html,
    }
    try:
        from bot.room_mode import is_mason_scenario

        if is_mason_scenario(game):
            from bot.mason_final_outcome import record_mason_final_night_outcome

            entry = record_mason_final_night_outcome(game, gm)
            if entry is not None:
                payload["mason_final_outcome"] = dict(entry)
    except Exception:
        pass
    log_event(game, "night.resolved", **payload)
    if gm is not None:
        gm.persist_snapshot(game, reason="night_resolved")


def normalize_day1_defense_act(act: str) -> str:
    """نام یکسان برای actهای آینه (d1d0) و مستقیم (no_exit)."""
    aliases = {
        "d1dc": "confirm",
        "d1dn": "no_defense",
        "d1d0": "no_exit",
        "d1d1": "has_exit",
        "d1el": "pick_elim",
        "d1ey": "elim_yes",
        "d1en": "elim_back",
        "d1dt": "toggle_pick",
        "tog": "toggle_pick",
        "confirm": "confirm",
        "none": "no_defense",
        "no_exit": "no_exit",
        "has_exit": "has_exit",
        "elim_yes": "elim_yes",
        "elim_no": "elim_back",
    }
    if act in aliases:
        return aliases[act]
    for prefix in ("d1dt-", "d1dt:", "tog-", "tog:"):
        if act.startswith(prefix):
            return "toggle_pick"
    return act


def log_no_host_day1_defense_callback(
    game: Game,
    *,
    act: str,
    actor_uid: int,
    assistant_uid: int | None,
    source: str,
    target_uid: int | None = None,
    outcome: str = "received",
    reject_reason: str | None = None,
) -> None:
    """هر فشار دکمهٔ پنل دفاعیهٔ روز اول — برای عیب‌یابی (شامل رد شدن)."""
    log_event(
        game,
        "no_host.day1_defense_callback",
        act=normalize_day1_defense_act(act),
        raw_act=act,
        actor_uid=actor_uid,
        assistant_uid=assistant_uid,
        target_uid=target_uid,
        phase=game.no_host_day1_defense_phase,
        defense_active=bool(game.no_host_day1_defense_active),
        source=source,
        outcome=outcome,
        reject_reason=reject_reason,
    )


def log_game_ended(
    game: Game,
    winner: str,
    picker_uid: int,
    gm: GameManager | None = None,
) -> None:
    payload: dict[str, Any] = {
        "winner": winner,
        "picker_uid": picker_uid,
        "players": players_snapshot(game),
    }
    if _uses_bazpors_snapshot(game):
        payload["bazpors"] = bazpors_snapshot(game)
        if gm is not None and game.bazpors_narrator_night_count > 0:
            if game.scenario_name == "masoon":
                from bot.mason_night_report import build_mason_night_timeline_lines

                payload["night_timeline_lines"] = build_mason_night_timeline_lines(
                    game, gm
                )
            else:
                from bot.bazpors_narrator import build_bazpors_night_timeline_lines

                payload["night_timeline_lines"] = build_bazpors_night_timeline_lines(
                    game, gm
                )
    log_event(game, "game.ended", **payload)
