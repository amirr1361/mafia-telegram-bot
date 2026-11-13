"""حلقهٔ شبیه‌سازی no_host — شب با dispatch دکمه‌ها تا پایان طبیعی بازی."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator
from unittest.mock import AsyncMock, patch

from bot.nam10.nmnd_narrator import (
    CONFIRM_DISCIPLINE_NO,
    DAY_DISCUSS,
    NIGHT_ACTIONS,
    NIGHT_START,
    NS_DISCIPLINE_ASK,
    process_narrator_callback,
)
from bot.nam10.engine import is_mafia_team
from bot.models import Role
from bot.nam10 import roles_ruintan as _ruintan_role
from bot.nam10.no_host_handoff import NO_HOST_HANDOFF_OFFER, apply_handoff_narrator_async
from bot.nam10.no_host_interrog_day import (
    IH_PHASE_ASSIST,
    IH_PHASE_SESSION,
    IH_PHASE_VOTE,
    IH_PHASE_VOTE_CONFIRM,
    NO_HOST_INTERROG_DAY,
    apply_no_host_interrog_day_narrator_async,
    process_no_host_interrog_day_narrator_cb,
)
from bot.nam10.no_host_night_ready import (
    all_no_host_parallel_night_ready,
    maybe_finish_no_host_parallel_night,
)
from bot.nam10.no_host_night_resolve import nam10_complete_discipline_and_resolve
from bot.nam10.no_host_table_inquiry import (
    NO_HOST_TABLE_INQUIRY,
    apply_no_host_table_inquiry_confirm,
    process_no_host_table_inquiry_narrator_cb,
)
from bot.nam10.role_registry import find_alive_role_holder, get_role_module

if TYPE_CHECKING:
    from tests.nam10_flow_harness import Nam10FlowHarness


@asynccontextmanager
async def full_simulation_patches(harness: Nam10FlowHarness) -> AsyncIterator[None]:
    """پچ‌های لازم برای شبیه‌سازی کامل بدون تلگرام/دیتابیس واقعی."""
    harness._captured_winner = None

    async def capture_finalize(
        bot, game, winner: str, picker_uid: int
    ) -> None:
        harness._captured_winner = winner
        harness.gm.end_game(game.room_code)

    patches = [
        patch("bot.post_game_flow.finalize_game_winner", side_effect=capture_finalize),
        patch("bot.app_state.manager", harness.gm),
        patch("bot.post_game_flow.manager", harness.gm),
        patch("bot.nam10.dayflow.manager", harness.gm),
        patch("bot.handlers.narrator_cb.manager", harness.gm),
        patch("bot.db.insert_game_session", return_value=1),
        patch("bot.main.begin_post_game_session", new_callable=AsyncMock),
        patch(
            "bot.observer_delivery.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.observer_delivery.publish_mirror_prompt_pair",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.observer_delivery.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.no_host_night_common.publish_no_host_night_wait_panel",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.no_host_night_common.finalize_no_host_role_pick_message",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.no_host_role_pick_common.sync_role_mirror_panel",
            new_callable=AsyncMock,
        ),
    ]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


def game_ended(harness: Nam10FlowHarness) -> bool:
    return (
        harness.gm.get_game(harness.game.room_code) is None
        or harness._captured_winner is not None
    )


def pick_mafia_victim(harness: Nam10FlowHarness) -> int:
    g = harness.game
    pool = [
        uid
        for uid, p in g.players.items()
        if p.is_alive
        and p.role
        and not is_mafia_team(p.role)
        and uid != harness.assistant_uid
        and not _ruintan_role.mafia_shot_survives(p)
    ]
    if not pool:
        pool = [
            uid
            for uid, p in g.players.items()
            if p.is_alive and p.role and not is_mafia_team(p.role)
        ]
    assert pool, "no mafia shot victim"
    return pool[0]


def pick_any_alive_non_self(harness: Nam10FlowHarness, actor_uid: int) -> int:
    g = harness.game
    pool = [
        uid
        for uid, p in g.players.items()
        if p.is_alive and uid != actor_uid
    ]
    assert pool
    return pool[0]


async def dispatch_role_mirror(
    harness: Nam10FlowHarness, act: str, as_uid: int, tid: int = 0
) -> None:
    from tests.nam10_flow_harness import _callback

    cb = _callback(as_uid)
    bot, g, gm = harness.bot, harness.game, harness.gm

    if act == "cic":
        from bot.nam10.no_host_citizen_night import dispatch_no_host_citizen_night

        await dispatch_no_host_citizen_night(
            cb, bot, g, gm, cit_uid=as_uid, actor_uid=as_uid
        )
        return
    if act == "ruc":
        from bot.nam10.no_host_ruintan_night import dispatch_no_host_ruintan_night

        await dispatch_no_host_ruintan_night(
            cb, bot, g, gm, ru_uid=as_uid, actor_uid=as_uid
        )
        return
    if act in ("hnp", "hns", "hnc", "hnb"):
        from bot.nam10.no_host_night1 import dispatch_no_host_hunter_night1

        await dispatch_no_host_hunter_night1(
            cb,
            bot,
            g,
            gm,
            hunter_uid=as_uid,
            actor_uid=as_uid,
            act=act,
            tid=tid,
        )
        return
    if act in ("nms", "nmy", "nmn", "nmc", "nmb"):
        from bot.nam10.no_host_mafia_night1 import dispatch_no_host_mafia_night1

        await dispatch_no_host_mafia_night1(
            cb, bot, g, gm, mafia_uid=as_uid, actor_uid=as_uid, act=act
        )
        return
    if act in ("msk", "msc", "msb"):
        from bot.nam10.no_host_mafia_shot import dispatch_no_host_mafia_shot

        await dispatch_no_host_mafia_shot(
            cb,
            bot,
            g,
            gm,
            mafia_uid=as_uid,
            actor_uid=as_uid,
            act=act,
            tid=tid,
        )
        return
    if act in ("sgt", "sgb", "sgc"):
        from bot.nam10.no_host_shiad_night import dispatch_no_host_shiad_night

        await dispatch_no_host_shiad_night(
            cb,
            bot,
            g,
            gm,
            sh_uid=as_uid,
            actor_uid=as_uid,
            act=act,
            tid=tid,
        )
        return
    if act in ("ndp", "ndb", "ndc"):
        from bot.nam10.no_host_detective_night import dispatch_no_host_detective_night

        await dispatch_no_host_detective_night(
            cb,
            bot,
            g,
            gm,
            det_uid=as_uid,
            actor_uid=as_uid,
            act=act,
            tid=tid,
        )
        return
    if act in ("dkt", "dkn", "dkb", "dkc", "dko"):
        from bot.nam10.no_host_doctor_night import dispatch_no_host_doctor_night

        await dispatch_no_host_doctor_night(
            cb,
            bot,
            g,
            gm,
            doc_uid=as_uid,
            actor_uid=as_uid,
            act=act,
            tid=tid,
        )
        return
    if act in ("skt", "skn", "skb", "skc"):
        from bot.nam10.no_host_sniper_night import dispatch_no_host_sniper_night

        await dispatch_no_host_sniper_night(
            cb,
            bot,
            g,
            gm,
            sn_uid=as_uid,
            actor_uid=as_uid,
            act=act,
            tid=tid,
        )
        return
    if act in ("nii1", "nii1s", "nii2", "nii2s", "niisk"):
        from bot.nam10.no_host_interrogator_night import dispatch_no_host_interrogator_night

        await dispatch_no_host_interrogator_night(
            cb,
            bot,
            g,
            gm,
            int_uid=as_uid,
            actor_uid=as_uid,
            act=act,
            tid=tid,
        )
        return
    if act == "ihok":
        from bot.nam10.no_host_interrog_day import dispatch_no_host_interrog_day_player

        await dispatch_no_host_interrog_day_player(
            cb, bot, g, gm, as_uid=as_uid, actor_uid=as_uid, act=act
        )
        return
    if act in ("ihco", "ihdi"):
        from bot.nam10.no_host_interrog_day import dispatch_no_host_interrog_day_player

        await dispatch_no_host_interrog_day_player(
            cb, bot, g, gm, as_uid=as_uid, actor_uid=as_uid, act=act
        )
        return
    raise ValueError(f"unsupported mirror act: {act}")


async def ensure_night_entry(harness: Nam10FlowHarness) -> None:
    g = harness.game
    if g.nmnd_narrator_step != NIGHT_START:
        return
    nc = g.nmnd_narrator_night_count
    if g.nam10_night_entry_dispatched_night == nc:
        return
    from bot.nam10.no_host_night_entry import dispatch_all_no_host_night_entry_panels

    await dispatch_all_no_host_night_entry_panels(
        harness.bot, g, harness.gm
    )


async def _complete_shiad_pick(harness: Nam10FlowHarness) -> None:
    g = harness.game
    sh = find_alive_role_holder(g, Role.SHIAD)
    if sh is None or g.nam10_shiad_pick_confirmed:
        return
    if not g.nam10_shiad_flow_active:
        from bot.nam10.no_host_shiad_night import start_no_host_shiad_night_flow

        await start_no_host_shiad_night_flow(
            harness.bot, g, harness.gm, at_night_entry=True
        )
    from bot.nam10.no_host_shiad_night import _shiad_guess_pool

    pool = _shiad_guess_pool(g)
    if not pool:
        return
    guess = pick_any_alive_non_self(harness, sh.user_id)
    pool_uids = {p.user_id for p in pool}
    if guess not in pool_uids:
        guess = pool[0].user_id
    await dispatch_role_mirror(harness, "sgt", sh.user_id, tid=guess)
    await dispatch_role_mirror(harness, "sgc", sh.user_id)


async def complete_night_role_picks(harness: Nam10FlowHarness) -> None:
    g = harness.game
    await ensure_night_entry(harness)
    victim = pick_mafia_victim(harness)

    citizen_mod = get_role_module(Role.CITIZEN)
    assert citizen_mod is not None
    for uid, p in g.players.items():
        if p.is_alive and citizen_mod.is_simple_citizen(p):
            if uid not in g.nam10_citizen_night_confirmed_uids:
                await dispatch_role_mirror(harness, "cic", uid)

    ru = find_alive_role_holder(g, Role.RUINTAN)
    if ru is not None and not g.nam10_ruintan_night_confirmed:
        await dispatch_role_mirror(harness, "ruc", ru.user_id)

    hunter = find_alive_role_holder(g, Role.HUNTER)
    if hunter is not None and not g.nam10_night1_hunter_done:
        await dispatch_role_mirror(harness, "hns", hunter.user_id)

    from bot.nam10.no_host_mafia_night1 import resolve_mafia_night1_panel_recipients

    if not g.nam10_mafia_night1_done:
        recipients = resolve_mafia_night1_panel_recipients(g)
        if recipients:
            mafia_uid = recipients[0].user_id
            await dispatch_role_mirror(harness, "nms", mafia_uid)
            await dispatch_role_mirror(harness, "nmc", mafia_uid)

    if (
        g.nam10_mafia_shot_flow_active or g.nam10_mafia_night1_chosen_action == "shot"
    ) and not g.nam10_mafia_shot_done and not g.nmnd_mafia_shot_registered:
        from bot.nam10.no_host_mafia_night1 import resolve_mafia_night1_panel_recipients

        recipients = resolve_mafia_night1_panel_recipients(g)
        mafia_uid = (
            g.nam10_mafia_night1_chooser_uid
            or (recipients[0].user_id if recipients else None)
        )
        if mafia_uid is not None:
            await dispatch_role_mirror(harness, "msk", mafia_uid, tid=victim)
            await dispatch_role_mirror(harness, "msc", mafia_uid)

    await _complete_shiad_pick(harness)

    det = find_alive_role_holder(g, Role.DETECTIVE)
    if det is not None and not g.nam10_detective_pick_confirmed:
        await dispatch_role_mirror(harness, "ndp", det.user_id, tid=victim)
        await dispatch_role_mirror(harness, "ndc", det.user_id)

    doc = find_alive_role_holder(g, Role.DOCTOR)
    if doc is not None and not g.nam10_doctor_pick_confirmed:
        await dispatch_role_mirror(harness, "dkn", doc.user_id)
        await dispatch_role_mirror(harness, "dkc", doc.user_id)

    sn = find_alive_role_holder(g, Role.SNIPER)
    if sn is not None and not g.nam10_sniper_pick_confirmed:
        await dispatch_role_mirror(harness, "skn", sn.user_id)
        await dispatch_role_mirror(harness, "skc", sn.user_id)

    intr = find_alive_role_holder(g, Role.INTERROGATOR)
    if intr is not None and not g.nam10_interrog_pick_confirmed:
        if not g.nmnd_interrog_night_finished:
            await dispatch_role_mirror(harness, "nii1s", intr.user_id)

    await _complete_shiad_pick(harness)

    if g.nam10_night_parallel_collect_active and all_no_host_parallel_night_ready(g):
        await maybe_finish_no_host_parallel_night(
            harness.bot, g, harness.gm
        )


async def complete_discipline_no_and_resolve(harness: Nam10FlowHarness) -> None:
    g = harness.game
    if g.nmnd_narrator_step == NIGHT_ACTIONS and g.nmnd_night_substep == NS_DISCIPLINE_ASK:
        err = process_narrator_callback(g, harness.gm, "disc_no", 0, "")
        assert err is None, err
        assert g.nmnd_narrator_step == CONFIRM_DISCIPLINE_NO
        err = process_narrator_callback(g, harness.gm, "disc_no_ok", 0, "")
        assert err is None, err
    await nam10_complete_discipline_and_resolve(
        harness.bot,
        g,
        harness.gm,
        send_discipline_broadcast=False,
    )


async def complete_table_inquiry_no(harness: Nam10FlowHarness) -> None:
    g = harness.game
    if g.nmnd_narrator_step != NO_HOST_TABLE_INQUIRY:
        return
    err = process_no_host_table_inquiry_narrator_cb(
        g, harness.gm, "tinq_no", 0
    )
    assert err is None, err
    err = process_no_host_table_inquiry_narrator_cb(g, harness.gm, "tinq_ok", 0)
    assert err is None, err
    await apply_no_host_table_inquiry_confirm(harness.bot, g, harness.gm)
    if g.nmnd_narrator_step == NO_HOST_HANDOFF_OFFER:
        await apply_handoff_narrator_async(
            harness.bot, g, harness.gm, "handoff_skip", 0
        )


async def skip_day_vote_to_night(harness: Nam10FlowHarness) -> None:
    from bot.nam10.dayflow import _process_no_host_day1_skip_night
    from tests.nam10_flow_harness import _callback

    g = harness.game
    if g.nam10_day1_vote_resolved:
        return
    cb = _callback(harness.assistant_uid)
    await _process_no_host_day1_skip_night(
        cb,
        harness.bot,
        g,
        harness.assistant_uid,
        harness.assistant_uid,
    )


async def complete_interrog_day_tie(harness: Nam10FlowHarness) -> None:
    g = harness.game
    if g.nmnd_narrator_step != NO_HOST_INTERROG_DAY:
        return
    phase = g.nam10_interrog_day_phase
    if phase == IH_PHASE_ASSIST:
        err = process_no_host_interrog_day_narrator_cb(
            g, harness.gm, "ih_req", 0
        )
        assert err is None, err
        await apply_no_host_interrog_day_narrator_async(
            harness.bot, g, harness.gm, "ih_req_ok"
        )
        phase = g.nam10_interrog_day_phase
    if phase == IH_PHASE_SESSION:
        from bot.nam10.no_host_interrog_day import _interrogator_uid

        intr_uid = _interrogator_uid(g)
        if intr_uid is not None:
            await dispatch_role_mirror(harness, "ihco", intr_uid)
        for uid, p in g.players.items():
            if not p.is_alive or uid == intr_uid:
                continue
            if uid not in g.nam10_interrog_day_ok_uids:
                await dispatch_role_mirror(harness, "ihok", uid)
        phase = g.nam10_interrog_day_phase
    if phase == IH_PHASE_VOTE:
        err = process_no_host_interrog_day_narrator_cb(
            g, harness.gm, "ih_vtie", 0
        )
        assert err is None, err
        phase = g.nam10_interrog_day_phase
    if phase == IH_PHASE_VOTE_CONFIRM:
        await apply_no_host_interrog_day_narrator_async(
            harness.bot, g, harness.gm, "ih_vok"
        )


async def run_default_day_elim(harness: Nam10FlowHarness) -> None:
    """Day 2+: real defense/vote session; eliminate the first town member."""
    from bot.nam10.engine import nmnd_counts_as_mafia_faction

    g = harness.game
    town = [
        uid
        for uid, p in sorted(g.players.items())
        if p.is_alive and not nmnd_counts_as_mafia_faction(g, p)
    ]
    candidates = town or [
        uid for uid, p in sorted(g.players.items()) if p.is_alive
    ]
    if not candidates:
        return
    target = candidates[0]
    from bot.nam10.nmnd_narrator import begin_no_host_day1_defense_pick

    begin_no_host_day1_defense_pick(g)
    await harness.dispatch_defense('tog', tid=target)
    await harness.dispatch_defense('confirm')
    await harness.dispatch_defense('d1el', tid=target)
    await harness.dispatch_defense('elim_yes')
    await harness.skip_handoff_if_offered()


async def advance_one_phase(harness: Nam10FlowHarness) -> bool:
    if game_ended(harness):
        return False

    g = harness.game
    step = g.nmnd_narrator_step

    if step == NO_HOST_HANDOFF_OFFER:
        await apply_handoff_narrator_async(
            harness.bot, g, harness.gm, "handoff_skip", 0
        )
        return True

    if step == NO_HOST_TABLE_INQUIRY:
        await complete_table_inquiry_no(harness)
        return True

    if step == NO_HOST_INTERROG_DAY:
        await complete_interrog_day_tie(harness)
        return True

    if g.nam10_day1_defense_active and g.nmnd_narrator_host_day <= 1:
        await harness.day1_no_defense()
        return True

    if step == DAY_DISCUSS:
        await run_default_day_elim(harness)
        return True

    if step == NIGHT_START or g.nam10_night_parallel_collect_active:
        if g.nmnd_night_substep == NS_DISCIPLINE_ASK:
            if step != NIGHT_ACTIONS:
                g.nmnd_narrator_step = NIGHT_ACTIONS
            await complete_discipline_no_and_resolve(harness)
            return True
        if g.nam10_night_parallel_collect_active and not all_no_host_parallel_night_ready(
            g
        ):
            await complete_night_role_picks(harness)
            return True
        if g.nmnd_night_substep != NS_DISCIPLINE_ASK:
            if g.nam10_night_parallel_collect_active:
                await maybe_finish_no_host_parallel_night(
                    harness.bot, g, harness.gm
                )
            elif step == NIGHT_START:
                from bot.nam10.nmnd_narrator import _goto_discipline_ask

                _goto_discipline_ask(g)
            return True

    if step == NIGHT_ACTIONS and g.nmnd_night_substep == NS_DISCIPLINE_ASK:
        await complete_discipline_no_and_resolve(harness)
        return True

    return False


async def run_until_natural_end(
    harness: Nam10FlowHarness,
    *,
    day1_path: str = "no_defense",
    max_steps: int = 100,
) -> str:
    harness._captured_winner = None
    await harness.run_day1_path(day1_path)

    async with full_simulation_patches(harness):
        steps = 0
        while steps < max_steps and not game_ended(harness):
            steps += 1
            progressed = await advance_one_phase(harness)
            if not progressed:
                break

    assert harness._captured_winner in (
        "mafia",
        "citizen",
    ), f"game did not end naturally (winner={harness._captured_winner!r}, step={harness.game.nmnd_narrator_step})"
    return harness._captured_winner
