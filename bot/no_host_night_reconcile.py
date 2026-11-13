"""Generalized night-readiness reconciliation for the Bazpors no-host mode.

Independent mirror of ``bot.nam10.no_host_night_reconcile`` (Namayande-10
fork): all night state changes funnel through
``bot.no_host_night_ready.maybe_finish_no_host_parallel_night``, which
delegates here before closing the parallel collection. Responsibilities:

A. A pending obligation must remain actionable - a never-delivered night
   panel for a still-pending role is re-delivered through the standard
   per-role entry flow.
B. Panels invalidated by rule changes are replaced: the doctor's pick panel
   on a Yakuza night is swapped for an informational notice and further
   picks are rejected by the doctor dispatcher (no void picks recorded).
C. Obligations eliminated by the rules are auto-disposed with a
   machine-readable audit reason (``no_host.night_ready_auto_resolve``).
F. After a Yakuza conversion the converted player's obsolete citizen /
   Ruintan ack panel is closed; readiness already auto-passes for the old
   role because role-holder lookups no longer match.

Idempotency: every disposition is recorded once per ``(tag, night)`` in
``game.no_host_night_ready_disposed`` (snapshot-safe), and the
assistant/observer pending panel is re-pushed only when the visible pending
set changes (``game.no_host_night_ready_signature``).

Uses the scenario-neutral ``no_host_*`` field namespace of the shared
no-host implementation; the Namayande-10 fork keeps its own ``nam10_*``
state and never reads these fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot

from bot.models import Game

if TYPE_CHECKING:
    from bot.game import GameManager

# Informational notice replacing the doctor's panel on a Yakuza night
# (rules: the doctor has no pick once the mafia special op is committed).
DOCTOR_OP_BLOCK_NOTE_HTML = (
    "⏭ <b>پزشک — انتخاب امشب ثبت نمی‌شود</b>\n\n"
    "🎭 عملیات مافیا (یاکوزایی) همین‌شب انجام شد و طبق قوانین بازی، پزشک امشب "
    "انتخاب ندارد.\n"
    "🚫 در صورت ثبت انتخاب پیش‌تر، آن انتخاب باطل شده است.\n\n"
    "⏳ لطفاً تا پایان فاز شب منتظر بمانید."
)

# Notice replacing a converted player's obsolete citizen/Ruintan ack panel.
YAKU_CONVERTED_ACK_NOTE_HTML = (
    "🎭 <b>نقش شما به‌تازگی تغییر کرد</b>\n\n"
    "⏳ تأیید قبلی فاز شب برای شما لازم نیست؛ لطفاً تا پایان فاز شب "
    "منتظر بمانید."
)


def _night_tag(game: Game, tag: str) -> str:
    return f"{tag}#{game.bazpors_narrator_night_count}"


def _claim_disposition(game: Game, key: str, reason: str) -> bool:
    """Record a one-shot disposition; True only when newly recorded."""
    disposed = game.no_host_night_ready_disposed
    if key in disposed:
        return False
    disposed[key] = reason
    return True


def _log_auto_resolve(game: Game, *, key: str, reason: str, **extra) -> None:
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night_ready_auto_resolve",
            key=key,
            reason=reason,
            **extra,
        )
    except Exception:
        pass


async def reconcile_no_host_night_readiness(
    bot: Bot, game: Game, gm: "GameManager", *, reason: str = "unspecified"
) -> bool:
    """Full readiness reconciliation; idempotent and safe to call often.

    Returns True when the parallel night collection was finished here.
    """
    from bot.no_host_night_ready import (
        all_no_host_parallel_night_ready,
        arm_all_pending_no_host_role_pick_flows,
        finish_no_host_parallel_night_collect,
        no_host_parallel_night_collect_active,
    )

    if not no_host_parallel_night_collect_active(game):
        return False
    # A night whose entry panels were not dispatched yet must never be
    # closed: a premature maybe_finish cannot skip panel delivery.
    if game.no_host_night_entry_dispatched_night != game.bazpors_narrator_night_count:
        return False
    arm_all_pending_no_host_role_pick_flows(game)
    await _auto_dispose_rule_blocked_doctor(bot, game, gm)
    await _invalidate_converted_player_ack_panels(bot, game, gm)
    await _restore_missing_actionable_panels(bot, game, gm)
    await _refresh_pending_panel(bot, game, gm, reason=reason)
    if all_no_host_parallel_night_ready(game):
        await finish_no_host_parallel_night_collect(bot, game, gm)
        return True
    return False


async def _auto_dispose_rule_blocked_doctor(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """Yakuza night: the doctor's pick is cancelled by the rules.

    The doctor panel is replaced by an informational notice and the
    obligation auto-resolves (machine-readable reason in the audit log).
    NATO-blocked nights are untouched: they keep their explicit OK-ack flow.
    """
    from bot.bazpors_narrator import Role
    from bot.no_host_doctor_night import _doctor_ui_key
    from bot.no_host_role_pick_common import sync_role_mirror_panel
    from bot.roles.doctor import blocked_this_night
    from bot.roles.night_state import yaku_night_state
    from bot.roles.registry import find_alive_role_holder

    if game.no_host_doctor_nato_blocked_panel:
        # NATO-blocked night: the explicit OK-ack panel flow owns the outcome.
        return
    if not yaku_night_state(game).civilian_picked_this_night:
        return
    if not blocked_this_night(game):
        return
    doc = find_alive_role_holder(game, Role.DOCTOR)
    if doc is None:
        return
    key = _night_tag(game, "doctor_op_block")
    if not _claim_disposition(game, key, "action_cancelled_by_rule"):
        return
    _log_auto_resolve(
        game,
        key=key,
        reason="doctor_pick_cancelled_by_yaku",
        doc_uid=doc.user_id,
    )
    await sync_role_mirror_panel(
        bot,
        game,
        _doctor_ui_key(game, doc.user_id),
        doc.user_id,
        DOCTOR_OP_BLOCK_NOTE_HTML,
        None,
    )


async def _invalidate_converted_player_ack_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """Close the converted player's obsolete citizen/Ruintan ack panels."""
    if game.bazpors_yaku_night_success is not True:
        return
    civ_uid = game.bazpors_yaku_night_civilian_uid
    if civ_uid is None or civ_uid not in game.players:
        return
    key = _night_tag(game, "yaku_civ_ack")
    if not _claim_disposition(game, key, "role_converted"):
        return
    _log_auto_resolve(game, key=key, reason="role_converted", civ_uid=civ_uid)
    from bot.no_host_citizen_night import _citizen_ui_key
    from bot.no_host_ruintan_night import _ruintan_ui_key
    from bot.observer_delivery import update_mirror_prompt_pair

    for ui_key in (_citizen_ui_key(game, civ_uid), _ruintan_ui_key(game, civ_uid)):
        if ui_key not in game.mirror_prompt_messages:
            continue
        try:
            await update_mirror_prompt_pair(
                bot,
                game,
                ui_key,
                YAKU_CONVERTED_ACK_NOTE_HTML,
                None,
                assistant_uid=civ_uid,
                parse_mode="HTML",
            )
        except Exception:
            pass


async def _restore_missing_actionable_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """Re-deliver a never-sent night panel for a still-pending role.

    Only fires when the role's dm-signature for this night is absent (the
    panel was genuinely never delivered). Roles whose obligation is
    rule-eliminated are skipped by their ready predicates.
    """
    from bot.bazpors_narrator import Role
    from bot.no_host_night_ready import (
        _citizens_ready,
        _detective_ready,
        _hunter_night1_ready,
        _interrogator_ready,
        _journalist_ready,
        _mafia_night1_parallel_ready,
        _ruintan_ready,
        _role_pick_ready,
        _sniper_ready,
    )
    from bot.roles.registry import find_alive_role_holder

    async def _send_shiad() -> None:
        from bot.no_host_shiad_night import start_no_host_shiad_night_flow

        await start_no_host_shiad_night_flow(bot, game, gm, at_night_entry=True)

    async def _send_detective() -> None:
        from bot.no_host_detective_night import start_no_host_detective_night_flow

        await start_no_host_detective_night_flow(bot, game, gm, at_night_entry=True)

    async def _send_sniper() -> None:
        from bot.no_host_sniper_night import start_no_host_sniper_night_flow

        await start_no_host_sniper_night_flow(bot, game, gm, at_night_entry=True)

    async def _send_journalist() -> None:
        from bot.no_host_journalist_night import start_no_host_journalist_night_flow

        await start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True)

    async def _send_interrogator() -> None:
        from bot.no_host_interrogator_night import (
            start_no_host_interrogator_night_flow,
        )

        await start_no_host_interrogator_night_flow(bot, game, gm, at_night_entry=True)

    spec = (
        (
            Role.SHIAD,
            lambda: _role_pick_ready(game, Role.SHIAD, "no_host_shiad_pick_confirmed"),
            "no_host_shiad_dm_signature",
            _send_shiad,
        ),
        (
            Role.DETECTIVE,
            lambda: _detective_ready(game),
            "no_host_detective_dm_signature",
            _send_detective,
        ),
        (
            Role.SNIPER,
            lambda: _sniper_ready(game),
            "no_host_sniper_dm_signature",
            _send_sniper,
        ),
        (
            Role.JOURNALIST,
            lambda: _journalist_ready(game),
            "no_host_journalist_dm_signature",
            _send_journalist,
        ),
        (
            Role.INTERROGATOR,
            lambda: _interrogator_ready(game),
            "no_host_interrog_dm_signature",
            _send_interrogator,
        ),
    )
    for role, ready_fn, sig_attr, sender in spec:
        if ready_fn():
            continue
        if getattr(game, sig_attr, None) is not None:
            # Panel for this night already delivered; the obligation is
            # actionable and just unconfirmed.
            continue
        if find_alive_role_holder(game, role) is None:
            continue
        key = _night_tag(game, f"restore_{role.value}")
        if not _claim_disposition(game, key, "panel_restored"):
            continue
        _log_auto_resolve(
            game, key=key, reason="missing_panel_restored", role=role.value
        )
        await sender()

    if not _citizens_ready(game):
        key = _night_tag(game, "restore_citizens")
        if _claim_disposition(game, key, "panel_restored"):
            from bot.no_host_citizen_night import dispatch_no_host_citizen_night_panel

            _log_auto_resolve(
                game, key=key, reason="missing_panel_restored", role="citizen"
            )
            await dispatch_no_host_citizen_night_panel(bot, game, gm)

    if not _ruintan_ready(game):
        key = _night_tag(game, "restore_ruintan")
        if _claim_disposition(game, key, "panel_restored"):
            from bot.no_host_ruintan_night import dispatch_no_host_ruintan_night_panel

            _log_auto_resolve(
                game, key=key, reason="missing_panel_restored", role="ruintan"
            )
            await dispatch_no_host_ruintan_night_panel(bot, game, gm)

    if not _mafia_night1_parallel_ready(game) and not game.no_host_mafia_night1_done:
        key = _night_tag(game, "restore_mafia_team")
        if _claim_disposition(game, key, "panel_restored"):
            from bot.no_host_mafia_night1 import start_no_host_night1_mafia_flow

            _log_auto_resolve(
                game, key=key, reason="missing_panel_restored", role="mafia_team"
            )
            await start_no_host_night1_mafia_flow(bot, game, gm)

    if not _hunter_night1_ready(game) and (
        not game.no_host_hunter1_dm_signature
    ):
        # پنل این شب قبلاً ارسال شده است (امضای شب ثبت شده)؛ فقط بی‌تأیید است.
        key = _night_tag(game, "restore_hunter")
        if _claim_disposition(game, key, "panel_restored"):
            from bot.no_host_night1 import start_no_host_night1_hunter_flow

            _log_auto_resolve(
                game, key=key, reason="missing_panel_restored", role="hunter"
            )
            await start_no_host_night1_hunter_flow(bot, game, gm)


async def _refresh_pending_panel(
    bot: Bot, game: Game, gm: "GameManager", *, reason: str
) -> None:
    """Re-push the assistant/observer pending list when it changes."""
    from bot.bazpors_narrator import push_host_step
    from bot.no_host_night_ready import pending_no_host_night_actor_labels

    labels = pending_no_host_night_actor_labels(game)
    signature = f"{game.bazpors_narrator_night_count}|{'|'.join(labels)}"
    if game.no_host_night_ready_signature == signature:
        return
    game.no_host_night_ready_signature = signature
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night_ready_panel_refreshed",
            pending=list(labels),
            reason=reason,
        )
    except Exception:
        pass
    await push_host_step(bot, game, gm)
