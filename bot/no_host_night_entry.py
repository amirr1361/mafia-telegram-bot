"""ورود به فاز شب — ارسال هم‌زمان پیام‌های نقش‌ها (no_host)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.bazpors_narrator import push_host_step
from bot.models import Game
from bot.roles.registry import find_alive_role_holder
from bot.no_host_night_common import no_host_should_dispatch_night_entry

if TYPE_CHECKING:
    from bot.game import GameManager


async def dispatch_all_no_host_night_entry_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """یک‌بار در شروع هر شب — همهٔ پیام‌های انتظار/انتخاب را هم‌زمان بفرست."""
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        return
    if not no_host_should_dispatch_night_entry(game):
        return
    nc = game.bazpors_narrator_night_count
    if game.no_host_night_entry_dispatched_night == nc:
        return
    game.no_host_night_entry_dispatched_night = nc

    from bot.no_host_night_sage_quote import dispatch_no_host_night_sage_quotes_at_entry

    await dispatch_no_host_night_sage_quotes_at_entry(bot, game)

    from bot.no_host_citizen_night import dispatch_no_host_citizen_night_panel
    from bot.no_host_detective_night import start_no_host_detective_night_flow
    from bot.no_host_doctor_night import start_no_host_doctor_night_flow
    from bot.no_host_ruintan_night import dispatch_no_host_ruintan_night_panel
    from bot.no_host_shiad_night import start_no_host_shiad_night_flow
    from bot.no_host_interrogator_night import start_no_host_interrogator_night_flow
    from bot.no_host_sniper_night import start_no_host_sniper_night_flow
    from bot.no_host_journalist_night import start_no_host_journalist_night_flow

    async def _hunter_at_entry() -> None:
        from bot.no_host_night1 import start_no_host_night1_hunter_flow

        await start_no_host_night1_hunter_flow(bot, game, gm)

    async def _mafia_team_at_entry() -> None:
        from bot.no_host_mafia_night1 import start_no_host_night1_mafia_flow

        await start_no_host_night1_mafia_flow(bot, game, gm)

    results = await asyncio.gather(
        dispatch_no_host_citizen_night_panel(bot, game, gm),
        dispatch_no_host_ruintan_night_panel(bot, game, gm),
        start_no_host_shiad_night_flow(bot, game, gm, at_night_entry=True),
        start_no_host_detective_night_flow(bot, game, gm, at_night_entry=True),
        start_no_host_doctor_night_flow(bot, game, gm, at_night_entry=True),
        start_no_host_sniper_night_flow(bot, game, gm, at_night_entry=True),
        start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True),
        start_no_host_interrogator_night_flow(bot, game, gm, at_night_entry=True),
        _hunter_at_entry(),
        _mafia_team_at_entry(),
        return_exceptions=True,
    )
    for err in results:
        if isinstance(err, BaseException):
            try:
                from bot.game_audit_log import log_event

                log_event(
                    game,
                    "no_host.night_entry_panel_error",
                    night_count=nc,
                    error=repr(err),
                )
            except Exception:
                pass

    await resync_observer_night_entry_panels(bot, game, gm)

    from bot.no_host_night_ready import arm_all_pending_no_host_role_pick_flows

    arm_all_pending_no_host_role_pick_flows(game)

    try:
        from bot.game_audit_log import log_event

        log_event(game, "no_host.night_entry_panels_dispatched", night_count=nc)
    except Exception:
        pass


async def complete_no_host_role_night_if_already_picked(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """اگر بازیکن قبلاً در ورود شب انتخاب کرده، هنگام رسیدن نوبت نریتور را جلو ببرد."""
    from bot.bazpors_narrator import (
        NS_DET,
        NS_DOC,
        NS_SHIAD,
        NS_SNIPER,
        _advance_after_det,
        _advance_after_doc,
        _advance_after_shiad,
        _goto_discipline_ask,
    )
    from bot.no_host_night_common import maybe_advance_narrator_at_substep
    from bot.no_host_shiad_night import _advance_past_shiad_if_cannot_act
    from bot.no_host_sniper_night import _advance_past_sniper_if_cannot_act

    advanced = False
    if game.bazpors_night_substep == NS_SHIAD:
        if game.no_host_shiad_pick_confirmed:
            if maybe_advance_narrator_at_substep(game, NS_SHIAD, _advance_after_shiad):
                advanced = True
        elif _advance_past_shiad_if_cannot_act(game):
            advanced = True
    if game.bazpors_night_substep == NS_DET and game.no_host_detective_pick_confirmed:
        if maybe_advance_narrator_at_substep(game, NS_DET, _advance_after_det):
            advanced = True
    if game.bazpors_night_substep == NS_DOC and game.no_host_doctor_pick_confirmed:
        if maybe_advance_narrator_at_substep(game, NS_DOC, _advance_after_doc):
            advanced = True
    if game.bazpors_night_substep == NS_SNIPER:
        if game.no_host_sniper_pick_confirmed:
            if maybe_advance_narrator_at_substep(game, NS_SNIPER, _goto_discipline_ask):
                advanced = True
        elif _advance_past_sniper_if_cannot_act(game):
            advanced = True
    if advanced:
        await push_host_step(bot, game, gm)


async def resync_observer_night_entry_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """ناظر بعد از ارسال پنل‌های شب ثبت شده — آینهٔ پنل‌های باز را بفرست."""
    from bot.bazpors_narrator import (
        NIGHT_START,
        Role,
        _bazpors_sniper_nights_enabled,
        _sniper_can_shoot,
    )
    from bot.no_host_night_ready import no_host_parallel_night_collect_active
    from bot.observer_delivery import (
        ensure_observer_mirror_prompt,
        no_host_observer_registered,
    )
    from bot.tg_send import safe_send_message

    if not no_host_observer_registered(game):
        return
    if not no_host_parallel_night_collect_active(game):
        return
    if game.bazpors_narrator_step != NIGHT_START:
        return
    nc = game.bazpors_narrator_night_count
    if game.no_host_night_entry_dispatched_night != nc:
        return

    sent = 0

    from bot.no_host_citizen_night import (
        _alive_citizens,
        _citizen_confirmed,
        _citizen_ui_key,
        _confirm_keyboard as _citizen_kb,
        build_no_host_citizen_night_html,
    )

    for pl in _alive_citizens(game):
        if _citizen_confirmed(game, pl.user_id):
            continue
        if await ensure_observer_mirror_prompt(
            bot,
            game,
            pl.user_id,
            _citizen_ui_key(game, pl.user_id),
            build_no_host_citizen_night_html(confirmed=False),
            _citizen_kb(game, pl.user_id),
        ):
            sent += 1

    from bot.no_host_ruintan_night import (
        _confirm_keyboard as _ru_kb,
        _ruintan_ui_key,
        build_no_host_ruintan_night_html,
    )

    ru = find_alive_role_holder(game, Role.RUINTAN)
    if ru is not None and not game.no_host_ruintan_night_confirmed:
        if await ensure_observer_mirror_prompt(
            bot,
            game,
            ru.user_id,
            _ruintan_ui_key(game, ru.user_id),
            build_no_host_ruintan_night_html(confirmed=False),
            _ru_kb(game, ru.user_id),
        ):
            sent += 1

    from bot.no_host_shiad_night import (
        _pick_keyboard as _shiad_kb,
        _shiad_ui_key,
        build_no_host_shiad_pick_html,
    )

    sh = find_alive_role_holder(game, Role.SHIAD)
    if sh is not None and not game.no_host_shiad_pick_confirmed:
        if await ensure_observer_mirror_prompt(
            bot,
            game,
            sh.user_id,
            _shiad_ui_key(game, sh.user_id),
            build_no_host_shiad_pick_html(game),
            _shiad_kb(game, sh.user_id, gm),
        ):
            sent += 1

    from bot.no_host_detective_night import (
        _detective_ui_key,
        _pick_keyboard as _det_kb,
        build_no_host_detective_pick_html,
    )

    det = find_alive_role_holder(game, Role.DETECTIVE)
    if (
        det is not None
        and not game.bazpors_detective_blocked
        and not game.no_host_detective_pick_confirmed
    ):
        det_text = build_no_host_detective_pick_html(game)
        det_kb = _det_kb(game, det.user_id, gm)
        if await ensure_observer_mirror_prompt(
            bot,
            game,
            det.user_id,
            _detective_ui_key(game, det.user_id),
            det_text,
            det_kb,
        ):
            sent += 1

    from bot.no_host_doctor_night import (
        _doctor_ui_key,
        _nato_blocked_keyboard,
        _pick_keyboard as _doc_kb,
        build_no_host_doctor_nato_blocked_html,
        build_no_host_doctor_pick_html,
    )

    doc = find_alive_role_holder(game, Role.DOCTOR)
    if doc is not None and not game.no_host_doctor_pick_confirmed:
        doc_uid = doc.user_id
        if game.no_host_doctor_nato_blocked_panel or game.bazpors_nato_action_registered:
            doc_text = build_no_host_doctor_nato_blocked_html()
            doc_kb = _nato_blocked_keyboard(game, doc_uid)
        else:
            doc_text = build_no_host_doctor_pick_html(game)
            doc_kb = _doc_kb(game, doc_uid, gm)
        if await ensure_observer_mirror_prompt(
            bot,
            game,
            doc_uid,
            _doctor_ui_key(game, doc_uid),
            doc_text,
            doc_kb,
        ):
            sent += 1

    if _bazpors_sniper_nights_enabled(game):
        from bot.no_host_sniper_night import (
            _pick_keyboard as _sn_kb,
            _sniper_ui_key,
            build_no_host_sniper_pick_html,
        )

        sn = find_alive_role_holder(game, Role.SNIPER)
        if (
            sn is not None
            and _sniper_can_shoot(game)
            and not game.no_host_sniper_pick_confirmed
        ):
            sn_text = build_no_host_sniper_pick_html(game)
            sn_kb = _sn_kb(game, sn.user_id, gm)
            if await ensure_observer_mirror_prompt(
                bot,
                game,
                sn.user_id,
                _sniper_ui_key(game, sn.user_id),
                sn_text,
                sn_kb,
            ):
                sent += 1

    from bot.no_host_journalist_night import (
        _idle_keyboard,
        _journalist_ui_key,
        _pick_keyboard as _jr_kb,
        build_no_host_journalist_idle_html,
        build_no_host_journalist_pick_html,
    )
    from bot.roles.mozakere_journalist import mozakere_journalist_active

    jr = find_alive_role_holder(game, Role.JOURNALIST)
    if jr is not None:
        from bot.room_mode import is_mozakere_scenario

        if is_mozakere_scenario(game):
            jr_uid = jr.user_id
            if mozakere_journalist_active(game):
                if not game.no_host_journalist_pick_confirmed:
                    if await ensure_observer_mirror_prompt(
                        bot,
                        game,
                        jr_uid,
                        _journalist_ui_key(game, jr_uid),
                        build_no_host_journalist_pick_html(game),
                        _jr_kb(game, jr_uid, gm),
                    ):
                        sent += 1
            elif not game.no_host_journalist_idle_confirmed:
                if await ensure_observer_mirror_prompt(
                    bot,
                    game,
                    jr_uid,
                    _journalist_ui_key(game, jr_uid),
                    build_no_host_journalist_idle_html(confirmed=False),
                    _idle_keyboard(game, jr_uid),
                ):
                    sent += 1

    from bot.no_host_interrogator_night import (
        PHASE_INT1,
        PHASE_INT2,
        PHASE_SKIP_ACK,
        _int1_keyboard,
        _int2_keyboard,
        _interrog_ui_key,
        _skip_ack_keyboard,
        build_no_host_interrog_int1_html,
        build_no_host_interrog_int2_html,
        build_no_host_interrog_skip_ack_html,
    )

    intr = find_alive_role_holder(game, Role.INTERROGATOR)
    if intr is not None and not game.no_host_interrog_pick_confirmed:
        int_uid = intr.user_id
        phase = game.no_host_interrog_ui_phase or PHASE_INT1
        if game.bazpors_interrog_once_done or phase == PHASE_SKIP_ACK:
            int_text = build_no_host_interrog_skip_ack_html(game)
            int_kb = _skip_ack_keyboard(game, int_uid)
        elif phase == PHASE_INT2:
            int_text = build_no_host_interrog_int2_html(game, gm)
            int_kb = _int2_keyboard(game, int_uid, gm)
        else:
            int_text = build_no_host_interrog_int1_html(game)
            int_kb = _int1_keyboard(game, int_uid, gm)
        if await ensure_observer_mirror_prompt(
            bot,
            game,
            int_uid,
            _interrog_ui_key(game, int_uid),
            int_text,
            int_kb,
        ):
            sent += 1

    if game.bazpors_narrator_night_count == 1:
        from bot.no_host_night1 import (
            _hunter_night1_ui_key,
            _hunter_pick_keyboard,
            build_no_host_hunter_night1_pick_html,
            build_no_host_hunter_rules_html,
        )
        if (
            not game.no_host_night1_hunter_done
            and game.no_host_night1_hunter_flow_active
        ):
            hunter = find_alive_role_holder(game, Role.HUNTER)
            if hunter is not None:
                h_uid = hunter.user_id
                if await ensure_observer_mirror_prompt(
                    bot,
                    game,
                    h_uid,
                    _hunter_night1_ui_key(game, h_uid),
                    build_no_host_hunter_night1_pick_html(game),
                    _hunter_pick_keyboard(game, h_uid, gm),
                ):
                    sent += 1

    if (
        not game.no_host_mafia_night1_done
        and game.no_host_mafia_night1_flow_active
    ):
        from bot.no_host_mafia_night1 import (
            _mafia_menu_keyboard,
            _mafia_night1_ui_key,
            build_no_host_mafia_night1_menu_html,
            resolve_mafia_night1_panel_recipients,
        )

        for p in resolve_mafia_night1_panel_recipients(game):
            m_uid = p.user_id
            if await ensure_observer_mirror_prompt(
                bot,
                game,
                m_uid,
                _mafia_night1_ui_key(game, m_uid),
                build_no_host_mafia_night1_menu_html(game),
                _mafia_menu_keyboard(game, m_uid, gm),
            ):
                sent += 1

    if sent and game.observer_user_id is not None:
        await safe_send_message(
            bot,
            game.observer_user_id,
            "👁 <b>پنل‌های نقش این شب</b> برای شما ارسال شد.\n"
            "می‌توانید به‌جای صندلی‌های مصنوعی (و در صورت نیاز صندلی واقعی) "
            "دکمه‌ها را بزنید.",
            parse_mode="HTML",
        )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.observer_night_panels_backfilled",
            night_count=nc,
            panel_count=sent,
        )
    except Exception:
        pass
