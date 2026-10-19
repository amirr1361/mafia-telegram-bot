"""مافیای روسی — ثبت سناریو، ناظر، شب، ترور، و برد."""

from __future__ import annotations

import asyncio
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.game import SEMI_AUTO_SYNTHETIC_UID_BASE, GameManager
from bot.main import host_deal_roles_keyboard, scenario_menu_keyboard
from bot.models import Phase, Player, Role
from bot.observer_delivery import PlayerMirrorCb, game_observer_mirror_active
from bot.russian_mafia import (
    HOST_HELPER_MODE,
    ROLE_GODFATHER,
    ROLE_SIMPLE_MAFIA,
    ROLE_TERROR,
    detective_alignment,
    faction_counts,
    host_mode_rejection_reason,
    mafia_shot_holder,
    required_night_slots,
    russian_alive_player_count,
    russian_doctor_heal_capacity,
    russian_doctor_self_save_limit,
    russian_roles_for_count,
    winner_of,
)
from bot.russian_mafia_flow import (
    action_keyboard,
    apply_terror_eliminations,
    build_russian_doctor_pick_html,
    complete_slot,
    open_day,
    open_night,
    resolve_night_state,
    try_confirm_action,
)
from bot.russian_mafia_player_role_pick import (
    ROLE_PICK_CB_PREFIX,
    ROLE_PICK_TAKEN_CB_PREFIX,
    build_role_pick_keyboard,
    start_player_role_pick,
)
from bot.player_role_pick_common import inline_button_supports_style


def _seat(game, gm=None) -> None:
    for seat, uid in enumerate(sorted(game.players), start=1):
        game.players[uid].seat = seat
    game.seats_finalized = True


def _room(*, n: int = 8, mode: str = HOST_HELPER_MODE, real: int | None = None):
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="russian_mafia",
        max_players=n,
        bazpors_host_mode=mode,
    )
    assert game is not None
    real_n = n if real is None else real
    for i in range(real_n):
        gm.add_player(game, Player(user_id=100 + i, full_name=f"P{i}", username=None))
    for i in range(n - real_n):
        gm.add_player(
            game,
            Player(
                user_id=SEMI_AUTO_SYNTHETIC_UID_BASE - i,
                full_name=f"S{i}",
                username=None,
            ),
        )
    _seat(game)
    return gm, game


def _deal(gm, game, roles: list[Role]) -> None:
    ids = list(game.players)
    mapping = dict(zip(ids, roles))
    gm.assign_russian_mafia_roles_by_player(game, mapping)


def _obs(game, uid: int = 900) -> None:
    game.observer_user_id = uid
    game.observer_prompt_status = "registered"
    game.observer_full_name = "ناظر"



async def _accept_russian_post_night(game) -> None:
    """کمک‌کننده اخراج را رد می‌کند و استعلام را هم رد می‌کند تا روز بعد باز شود."""
    from bot.russian_mafia_post_night import handle_russian_host_post_night

    if game.phase == Phase.ENDED:
        return

    class CB:
        def __init__(self) -> None:
            self.from_user = SimpleNamespace(
                id=game.bot_assistant_user_id or game.host_id
            )
            self.message = None
            self.data = ""

        async def answer(self, text="", show_alert=False):
            return None

    callback = CB()
    night = game.russian_mafia_night_index
    if game.russian_mafia_post_night_stage == "discipline_ask":
        await handle_russian_host_post_night(
            callback,
            AsyncMock(),
            game,
            "disc_no",
            ["rmh", game.room_code, "disc_no", str(night)],
        )
    if game.phase != Phase.ENDED and game.russian_mafia_post_night_stage == "inquiry_ask":
        await handle_russian_host_post_night(
            callback,
            AsyncMock(),
            game,
            "inq_no",
            ["rmh", game.room_code, "inq_no", str(night)],
        )



async def _ack_required_waiting(game) -> None:
    from bot.game import is_synthetic_player_uid
    from bot.russian_mafia import required_waiting_player_ids
    from bot.russian_mafia_flow import ack_russian_citizen

    for uid in sorted(required_waiting_player_ids(game)):
        actor = (
            game.observer_user_id
            if is_synthetic_player_uid(uid) and game.observer_user_id is not None
            else uid
        )
        result = await ack_russian_citizen(
            AsyncMock(),
            game,
            actor_uid=actor,
            as_uid=uid,
            generation=game.russian_mafia_night_index,
        )
        if result != "ack":
            raise AssertionError((uid, result, game.russian_mafia_night_index))


def _alive_uid(game, role: Role) -> int:
    for p in game.players.values():
        if p.role == role and p.is_alive:
            return p.user_id
    raise AssertionError(role)


class RegistrationTests(unittest.TestCase):
    def test_menu_and_counts(self) -> None:
        labels = [
            btn.text
            for row in scenario_menu_keyboard().inline_keyboard
            for btn in row
        ]
        self.assertIn("🕶 مافیای روسی", labels)
        self.assertIsNone(host_mode_rejection_reason(HOST_HELPER_MODE))
        self.assertIsNotNone(host_mode_rejection_reason("no_host"))
        self.assertIsNone(
            GameManager().create_game(
                host_id=1,
                scenario_name="russian_mafia",
                max_players=7,
                bazpors_host_mode=HOST_HELPER_MODE,
            )
        )
        self.assertIsNone(
            GameManager().create_game(
                host_id=1,
                scenario_name="russian_mafia",
                max_players=8,
                bazpors_host_mode="no_host",
            )
        )
        game = GameManager().create_game(
            host_id=1,
            scenario_name="russian_mafia",
            max_players=8,
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        self.assertIsNotNone(game)

    def test_rosters(self) -> None:
        eight = russian_roles_for_count(8)
        nine = russian_roles_for_count(9)
        self.assertEqual(Counter(eight)[ROLE_GODFATHER], 1)
        self.assertEqual(Counter(eight)[ROLE_TERROR], 1)
        self.assertEqual(Counter(eight)[Role.DOCTOR], 1)
        self.assertEqual(Counter(eight)[Role.DETECTIVE], 1)
        self.assertEqual(Counter(eight)[Role.CITIZEN], 4)
        self.assertNotIn(ROLE_SIMPLE_MAFIA, eight)
        self.assertEqual(Counter(nine)[ROLE_GODFATHER], 1)
        self.assertEqual(Counter(nine)[ROLE_SIMPLE_MAFIA], 2)
        self.assertEqual(Counter(nine)[Role.DOCTOR], 1)
        self.assertEqual(Counter(nine)[Role.DETECTIVE], 1)
        self.assertEqual(Counter(nine)[Role.CITIZEN], 4)
        self.assertNotIn(ROLE_TERROR, nine)
        self.assertEqual(len(eight), 8)
        self.assertEqual(len(nine), 9)


class ObserverAndDealTests(unittest.TestCase):
    def test_observer_not_a_player_and_mirror_active(self) -> None:
        gm, game = _room()
        _obs(game)
        self.assertNotIn(900, game.players)
        self.assertTrue(game_observer_mirror_active(game))
        _deal(gm, game, russian_roles_for_count(8))
        self.assertEqual(len([p for p in game.players.values() if p.role]), 8)
        self.assertNotIn(900, {p.user_id for p in game.players.values()})
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 0)

    def test_role_pick_excludes_observer_and_uses_styles(self) -> None:
        gm, game = _room(real=2)
        _obs(game)
        err = start_player_role_pick(game)
        self.assertIsNone(err)
        self.assertEqual(len(game.russian_mafia_role_number_map), 8)
        dealt = [Role(v) for v in game.russian_mafia_role_number_map.values()]
        self.assertEqual(Counter(dealt), Counter(russian_roles_for_count(8)))
        kb = build_role_pick_keyboard(game)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        self.assertTrue(all(len(row) <= 2 for row in kb.inline_keyboard))
        self.assertTrue(flat[0].callback_data.startswith(f"{ROLE_PICK_CB_PREFIX}:"))
        if inline_button_supports_style():
            self.assertEqual(flat[0].style, "primary")
        labels = [
            btn.text
            for row in host_deal_roles_keyboard(game).inline_keyboard
            for btn in row
        ]
        self.assertIn("🎭 پخش نقش‌های تصادفی", labels)
        self.assertIn("انتخاب نقش‌ها توسط بازیکنان", labels)
        self.assertEqual(ROLE_PICK_TAKEN_CB_PREFIX, "rrp_taken")


class NightAndTerrorTests(unittest.TestCase):
    def _prepared(self, n=8):
        gm, game = _room(n=n)
        _obs(game)
        _deal(gm, game, russian_roles_for_count(n))
        game.phase = Phase.NIGHT
        return game

    def test_godfather_holder_and_observer_race(self) -> None:
        game = self._prepared()
        holder = mafia_shot_holder(game)
        self.assertEqual(holder.role, ROLE_GODFATHER)
        terror = _alive_uid(game, ROLE_TERROR)
        citizen = _alive_uid(game, Role.CITIZEN)
        kb = action_keyboard(
            game, act="zrm_shot", as_uid=holder.user_id, exclude=None, mirror=True
        )
        self.assertTrue(kb.inline_keyboard)
        first = try_confirm_action(
            game,
            slot="mafia",
            actor_uid=holder.user_id,
            as_uid=holder.user_id,
            target_uid=citizen,
        )
        self.assertEqual(first, "ok")
        second = try_confirm_action(
            game,
            slot="mafia",
            actor_uid=game.observer_user_id,
            as_uid=holder.user_id,
            target_uid=terror,
        )
        self.assertEqual(second, "stale")
        self.assertEqual(game.russian_mafia_mafia_target, citizen)

    def test_observer_shot_then_player_stale(self) -> None:
        game = self._prepared()
        holder = mafia_shot_holder(game)
        citizen = _alive_uid(game, Role.CITIZEN)
        other = next(
            p.user_id
            for p in game.players.values()
            if p.is_alive and p.user_id not in (holder.user_id, citizen)
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="mafia",
                actor_uid=game.observer_user_id,
                as_uid=holder.user_id,
                target_uid=citizen,
            ),
            "ok",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="mafia",
                actor_uid=holder.user_id,
                as_uid=holder.user_id,
                target_uid=other,
            ),
            "stale",
        )

    def test_terror_becomes_holder_when_godfather_dead(self) -> None:
        game = self._prepared()
        gf = _alive_uid(game, ROLE_GODFATHER)
        game.players[gf].is_alive = False
        holder = mafia_shot_holder(game)
        self.assertEqual(holder.role, ROLE_TERROR)
        self.assertIn("mafia", required_night_slots(game))

    def test_doctor_self_save_once_and_repeat_other(self) -> None:
        game = self._prepared()
        self.assertEqual(russian_doctor_self_save_limit(game), 1)
        doctor = _alive_uid(game, Role.DOCTOR)
        citizen = _alive_uid(game, Role.CITIZEN)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=game.observer_user_id,
                as_uid=doctor,
                target_uid=doctor,
            ),
            "ok",
        )
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
        game.russian_mafia_doctor_confirmed = False
        game.russian_mafia_doctor_target = None
        game.russian_mafia_doctor_targets = []
        game.russian_mafia_doctor_night_capacity = 0
        game.mirror_action_claims.clear()
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=doctor,
            ),
            "rejected",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=citizen,
            ),
            "ok",
        )
        game.russian_mafia_doctor_confirmed = False
        game.russian_mafia_doctor_target = None
        game.russian_mafia_doctor_targets = []
        game.russian_mafia_doctor_night_capacity = 0
        game.mirror_action_claims.clear()
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=citizen,
            ),
            "ok",
        )

    def test_detective_godfather_negative_terror_positive(self) -> None:
        self.assertEqual(detective_alignment(ROLE_GODFATHER), "negative")
        self.assertEqual(detective_alignment(ROLE_TERROR), "positive")
        self.assertEqual(detective_alignment(Role.DOCTOR), "negative")
        self.assertEqual(detective_alignment(Role.CITIZEN), "negative")
        game = self._prepared()
        det = _alive_uid(game, Role.DETECTIVE)
        gf = _alive_uid(game, ROLE_GODFATHER)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="detective",
                actor_uid=det,
                as_uid=det,
                target_uid=gf,
            ),
            "ok",
        )
        self.assertEqual(game.russian_mafia_detective_alignment, "negative")

    def test_save_cancels_shot_and_win(self) -> None:
        game = self._prepared()
        citizen = _alive_uid(game, Role.CITIZEN)
        doctor = _alive_uid(game, Role.DOCTOR)
        game.russian_mafia_mafia_target = citizen
        game.russian_mafia_mafia_confirmed = True
        game.russian_mafia_doctor_target = citizen
        game.russian_mafia_doctor_targets = [citizen]
        game.russian_mafia_doctor_confirmed = True
        game.russian_mafia_detective_confirmed = True
        game.russian_mafia_detective_target = _alive_uid(game, ROLE_TERROR)
        self.assertIsNone(resolve_night_state(game))
        self.assertTrue(game.players[citizen].is_alive)
        self.assertEqual(game.russian_mafia_detective_alignment, "positive")
        for p in list(game.players.values()):
            if p.role in (ROLE_GODFATHER, ROLE_TERROR):
                p.is_alive = False
        self.assertEqual(winner_of(game), "town")

    def test_terror_skips_vote_and_can_win(self) -> None:
        game = self._prepared(n=8)
        terror = _alive_uid(game, ROLE_TERROR)
        citizen = _alive_uid(game, Role.CITIZEN)
        game.phase = Phase.DAY_DISCUSSION
        game.russian_mafia_terror_day_active = True
        self.assertEqual(
            try_confirm_action(
                game,
                slot="terror",
                actor_uid=terror,
                as_uid=terror,
                target_uid=terror,
            ),
            "rejected",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="terror",
                actor_uid=game.observer_user_id,
                as_uid=terror,
                target_uid=citizen,
            ),
            "ok",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="terror",
                actor_uid=terror,
                as_uid=terror,
                target_uid=_alive_uid(game, Role.DOCTOR),
            ),
            "stale",
        )
        winner = apply_terror_eliminations(game)
        self.assertIsNone(winner)
        self.assertFalse(game.players[terror].is_alive)
        self.assertFalse(game.players[citizen].is_alive)
        self.assertNotEqual(game.phase, Phase.DAY_VOTE)

        gm, tiny = _room(n=8)
        _obs(tiny)
        roles = russian_roles_for_count(8)
        _deal(gm, tiny, roles)
        for p in tiny.players.values():
            if p.role == Role.CITIZEN:
                p.is_alive = False
            if p.role == Role.DOCTOR:
                p.is_alive = False
            if p.role == Role.DETECTIVE:
                p.is_alive = False
        # godfather + terror + one citizen left: kill the citizen with terror
        left = [p for p in tiny.players.values() if p.is_alive and p.role == Role.CITIZEN]
        self.assertFalse(left)
        terror_uid = _alive_uid(tiny, ROLE_TERROR)
        gf = _alive_uid(tiny, ROLE_GODFATHER)
        tiny.phase = Phase.DAY_DISCUSSION
        tiny.russian_mafia_terror_day_active = True
        tiny.mirror_action_claims.clear()
        self.assertEqual(
            try_confirm_action(
                tiny,
                slot="terror",
                actor_uid=terror_uid,
                as_uid=terror_uid,
                target_uid=gf,
            ),
            "ok",
        )
        self.assertEqual(apply_terror_eliminations(tiny), "town")
        self.assertEqual(tiny.phase, Phase.ENDED)

    def test_mafia_wins_on_parity(self) -> None:
        game = self._prepared()
        for p in game.players.values():
            if p.role == Role.CITIZEN or p.role in (Role.DOCTOR, Role.DETECTIVE):
                p.is_alive = False
        # two mafia, zero town
        mafia, town = faction_counts(game)
        self.assertGreaterEqual(mafia, town)
        self.assertEqual(winner_of(game), "mafia")

    def test_synthetic_doctor_observer(self) -> None:
        gm, game = _room(real=1)
        _obs(game)
        roles = russian_roles_for_count(8)
        # first real player is citizen; doctor will be synthetic if we assign doctor to a negative uid
        ids = list(game.players)
        real = [i for i in ids if i > 0][0]
        synth = [i for i in ids if i < 0]
        mapping = {real: Role.CITIZEN}
        order = [ROLE_GODFATHER, ROLE_TERROR, Role.DOCTOR, Role.DETECTIVE, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN]
        for uid, role in zip(synth, order):
            mapping[uid] = role
        gm.assign_russian_mafia_roles_by_player(game, mapping)
        game.phase = Phase.NIGHT
        doctor = _alive_uid(game, Role.DOCTOR)
        self.assertLess(doctor, 0)
        citizen = real
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=game.observer_user_id,
                as_uid=doctor,
                target_uid=citizen,
            ),
            "ok",
        )

    def test_cross_room_actor_forbidden(self) -> None:
        game = self._prepared()
        holder = mafia_shot_holder(game)
        citizen = _alive_uid(game, Role.CITIZEN)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="mafia",
                actor_uid=424242,
                as_uid=holder.user_id,
                target_uid=citizen,
            ),
            "forbidden",
        )


class AsyncRaceTests(unittest.TestCase):
    def test_parallel_observer_and_player(self) -> None:
        gm, game = _room()
        _obs(game)
        _deal(gm, game, russian_roles_for_count(8))
        game.phase = Phase.NIGHT
        holder = mafia_shot_holder(game).user_id
        targets = [p.user_id for p in game.players.values() if p.role == Role.CITIZEN][:2]
        bot = AsyncMock()

        async def race():
            with patch("bot.russian_mafia_flow._close_slot", new=AsyncMock()), patch(
                "bot.russian_mafia_flow.open_day", new=AsyncMock()
            ), patch("bot.russian_mafia_flow.safe_send_message", new=AsyncMock()):
                return await asyncio.gather(
                    complete_slot(
                        bot, game, slot="mafia", actor_uid=holder, as_uid=holder, target_uid=targets[0]
                    ),
                    complete_slot(
                        bot,
                        game,
                        slot="mafia",
                        actor_uid=game.observer_user_id,
                        as_uid=holder,
                        target_uid=targets[1],
                    ),
                )

        results = asyncio.run(race())
        self.assertEqual(sorted(results), ["ok", "stale"])
        self.assertTrue(game.russian_mafia_mafia_confirmed)


class NinePlayerTests(unittest.TestCase):
    def _prepared(self):
        gm, game = _room(n=9)
        _obs(game)
        _deal(gm, game, russian_roles_for_count(9))
        game.phase = Phase.NIGHT
        return game

    def test_team_counts_and_no_terror(self) -> None:
        game = self._prepared()
        self.assertEqual(faction_counts(game), (3, 6))
        self.assertEqual(russian_doctor_self_save_limit(game), 1)
        self.assertEqual(russian_doctor_heal_capacity(game), 2)
        self.assertFalse(any(p.role == ROLE_TERROR for p in game.players.values()))
        self.assertEqual(
            sum(1 for p in game.players.values() if p.role == ROLE_SIMPLE_MAFIA),
            2,
        )

    def test_godfather_is_only_shot_holder(self) -> None:
        game = self._prepared()
        holder = mafia_shot_holder(game)
        self.assertEqual(holder.role, ROLE_GODFATHER)
        simples = [p for p in game.players.values() if p.role == ROLE_SIMPLE_MAFIA]
        self.assertTrue(all(p.user_id != holder.user_id for p in simples))

    def test_dead_godfather_picks_lowest_seat_simple_mafia(self) -> None:
        game = self._prepared()
        game.players[_alive_uid(game, ROLE_GODFATHER)].is_alive = False
        simples = [p for p in game.players.values() if p.role == ROLE_SIMPLE_MAFIA]
        simples.sort(key=lambda p: p.user_id)
        simples[0].seat = 9
        simples[1].seat = 2
        holder = mafia_shot_holder(game)
        self.assertEqual(holder.user_id, simples[1].user_id)
        again = mafia_shot_holder(game)
        self.assertEqual(again.user_id, holder.user_id)
        simples[1].is_alive = False
        self.assertEqual(mafia_shot_holder(game).user_id, simples[0].user_id)
        self.assertIn("mafia", required_night_slots(game))

    def test_shot_panel_goes_only_to_holder_and_observer_mirror(self) -> None:
        game = self._prepared()
        game.players[_alive_uid(game, ROLE_GODFATHER)].is_alive = False
        holder = mafia_shot_holder(game)
        sent: list[tuple] = []

        async def fake_send(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            sent.append((slot, player_uid, act, text))

        async def run():
            with patch("bot.russian_mafia_flow._send_pair", new=fake_send):
                await open_night(AsyncMock(), game)

        asyncio.run(run())
        mafia_panels = [row for row in sent if row[0] == "mafia"]
        self.assertEqual(len(mafia_panels), 1)
        self.assertEqual(mafia_panels[0][1], holder.user_id)
        self.assertEqual(mafia_panels[0][2], "zrm_shot")
        kb = action_keyboard(
            game, act="zrm_shot", as_uid=holder.user_id, exclude=None, mirror=True
        )
        packed = kb.inline_keyboard[0][0].callback_data
        mirrored = PlayerMirrorCb.unpack(packed)
        self.assertEqual(mirrored.as_uid, holder.user_id)
        self.assertEqual(mirrored.act, "zrm_shot")

    def test_detective_simple_mafia_positive_godfather_negative(self) -> None:
        self.assertEqual(detective_alignment(ROLE_GODFATHER), "negative")
        self.assertEqual(detective_alignment(ROLE_SIMPLE_MAFIA), "positive")
        self.assertEqual(detective_alignment(Role.DOCTOR), "negative")
        self.assertEqual(detective_alignment(Role.CITIZEN), "negative")
        game = self._prepared()
        det = _alive_uid(game, Role.DETECTIVE)
        for simple in [p for p in game.players.values() if p.role == ROLE_SIMPLE_MAFIA]:
            game.russian_mafia_detective_confirmed = False
            game.mirror_action_claims.clear()
            self.assertEqual(
                try_confirm_action(
                    game,
                    slot="detective",
                    actor_uid=det,
                    as_uid=det,
                    target_uid=simple.user_id,
                ),
                "ok",
            )
            self.assertEqual(game.russian_mafia_detective_alignment, "positive")

    def test_doctor_self_save_once_with_dual_capacity(self) -> None:
        """۹ زنده: دو نجات متمایز؛ نجات خود فقط یک‌بار در کل بازی."""
        game = self._prepared()
        doctor = _alive_uid(game, Role.DOCTOR)
        citizens = [
            p.user_id
            for p in game.players.values()
            if p.role == Role.CITIZEN and p.is_alive
        ]
        self.assertEqual(russian_doctor_heal_capacity(game), 2)
        self.assertEqual(russian_doctor_self_save_limit(game), 1)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=game.observer_user_id,
                as_uid=doctor,
                target_uid=doctor,
            ),
            "ok",
        )
        self.assertFalse(game.russian_mafia_doctor_confirmed)
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=doctor,
            ),
            "rejected",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=citizens[0],
            ),
            "ok",
        )
        self.assertTrue(game.russian_mafia_doctor_confirmed)
        self.assertEqual(
            game.russian_mafia_doctor_targets, [doctor, citizens[0]]
        )
        game.russian_mafia_doctor_confirmed = False
        game.russian_mafia_doctor_target = None
        game.russian_mafia_doctor_targets = []
        game.russian_mafia_doctor_night_capacity = 0
        game.mirror_action_claims.clear()
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=doctor,
            ),
            "rejected",
        )
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=citizens[1],
            ),
            "ok",
        )
        self.assertFalse(game.russian_mafia_doctor_confirmed)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=citizens[2],
            ),
            "ok",
        )
        self.assertTrue(game.russian_mafia_doctor_confirmed)


    def test_no_terror_panel_or_wait(self) -> None:
        game = self._prepared()
        sent: list[str] = []

        async def fake_send(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            sent.append(slot)

        async def run():
            with patch("bot.russian_mafia_flow._send_pair", new=fake_send), patch(
                "bot.russian_mafia_flow.safe_send_message", new=AsyncMock()
            ):
                await open_day(AsyncMock(), game)

        asyncio.run(run())
        self.assertNotIn("terror", sent)
        self.assertFalse(game.russian_mafia_terror_day_active)
        self.assertNotIn("terror", required_night_slots(game))
        citizen = _alive_uid(game, Role.CITIZEN)
        simple = next(p.user_id for p in game.players.values() if p.role == ROLE_SIMPLE_MAFIA)
        self.assertEqual(
            try_confirm_action(
                game,
                slot="terror",
                actor_uid=simple,
                as_uid=simple,
                target_uid=citizen,
            ),
            "stale",
        )
        game.russian_mafia_terror_day_active = True
        self.assertEqual(
            try_confirm_action(
                game,
                slot="terror",
                actor_uid=simple,
                as_uid=simple,
                target_uid=citizen,
            ),
            "forbidden",
        )
        self.assertFalse(game.russian_mafia_terror_confirmed)
        self.assertTrue(game.players[citizen].is_alive)
        self.assertTrue(game.players[simple].is_alive)

    def test_role_pick_map_has_three_mafia_and_no_terror(self) -> None:
        _gm, game = _room(n=9, real=2)
        _obs(game)
        self.assertIsNone(start_player_role_pick(game))
        dealt = [Role(v) for v in game.russian_mafia_role_number_map.values()]
        self.assertEqual(Counter(dealt), Counter(russian_roles_for_count(9)))
        self.assertNotIn(ROLE_TERROR, dealt)
        self.assertEqual(Counter(dealt)[ROLE_SIMPLE_MAFIA], 2)
        self.assertEqual(Counter(dealt)[ROLE_GODFATHER], 1)
        self.assertEqual(len(game.russian_mafia_role_number_map), 9)


class LobbyFillTests(unittest.TestCase):
    def test_created_room_shows_mozakere_fill_buttons(self) -> None:
        from bot.app_state import manager as app_manager
        from bot.russian_mafia_flow import accept_russian_host_mode

        class _Msg:
            def __init__(self) -> None:
                self.kwargs = None
                self.text = ""

            async def edit_text(self, text, **kwargs):
                self.text = text
                self.kwargs = kwargs

        class _CB:
            def __init__(self) -> None:
                self.message = _Msg()
                self.from_user = SimpleNamespace(id=88001, full_name="Helper", username=None)

            async def answer(self, *args, **kwargs):
                return None

        callback = _CB()
        bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="Bot")))
        data = SimpleNamespace(mode=HOST_HELPER_MODE, count=8)
        app_manager.host_to_room.pop(88001, None)
        asyncio.run(accept_russian_host_mode(callback, bot, data))
        kb = callback.message.kwargs["reply_markup"]
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("🎲 پر کردن تصادفی بازیکن‌ها", labels)
        self.assertIn("⏳ منتظر بازیکن‌های واقعی می‌مانم", labels)
        game = app_manager.get_game(app_manager.host_to_room[88001])
        self.assertIsNotNone(game)
        from bot.game_snapshot import delete_game_snapshot

        delete_game_snapshot(game.room_code)
        app_manager.player_to_room.pop(88001, None)
        app_manager.games.pop(game.room_code, None)
        app_manager.host_to_room.pop(88001, None)

    def test_random_fill_exact_capacity_keeps_real_players(self) -> None:
        from bot.game import is_synthetic_player_uid
        from bot.game_snapshot import delete_game_snapshot

        for count, host in ((8, 88011), (9, 88012)):
            gm = GameManager()
            game = gm.create_game(
                host_id=host,
                scenario_name="russian_mafia",
                max_players=count,
                bazpors_host_mode=HOST_HELPER_MODE,
            )
            self.assertIsNotNone(game)
            try:
                for i in range(2):
                    gm.add_player(
                        game,
                        Player(user_id=700 + i, full_name=f"R{i}", username=None),
                    )
                _obs(game)
                real_ids = {700, 701}
                not_ready, _err = gm.lobby_ready_for_deal(game)
                self.assertFalse(not_ready)
                self.assertIsNone(gm.fill_russian_mafia_synthetic_lobby(game))
                self.assertEqual(len(game.players), count)
                self.assertTrue(real_ids <= set(game.players))
                synthetic = [uid for uid in game.players if uid not in real_ids]
                self.assertEqual(len(synthetic), count - 2)
                self.assertTrue(all(is_synthetic_player_uid(uid) for uid in synthetic))
                self.assertNotIn(900, game.players)
                self.assertFalse(game.roles_dealt)
                ready, err = gm.lobby_ready_for_deal(game)
                self.assertTrue(ready, err)
                labels = [
                    btn.text
                    for row in host_deal_roles_keyboard(game).inline_keyboard
                    for btn in row
                ]
                self.assertIn("🎭 پخش نقش‌های تصادفی", labels)
                self.assertIn("انتخاب نقش‌ها توسط بازیکنان", labels)
            finally:
                delete_game_snapshot(game.room_code)

    def test_wait_does_not_add_synthetic_players(self) -> None:
        from aiogram.enums import ChatType

        from bot.app_state import manager as app_manager
        from bot.handlers.lobby import cb_semi_auto_dev_lobby
        from bot.main import SemiAutoDevLobby

        gm = app_manager
        game = gm.create_game(
            host_id=88002,
            scenario_name="russian_mafia",
            max_players=8,
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        self.assertIsNotNone(game)
        before = set(game.players)

        class _Msg:
            def __init__(self) -> None:
                self.html_text = "اتاق"
                self.text = "اتاق"
                self.chat = SimpleNamespace(type=ChatType.PRIVATE)

            async def edit_text(self, *args, **kwargs):
                return None

        class _CB:
            def __init__(self) -> None:
                self.message = _Msg()
                self.from_user = SimpleNamespace(id=88002)
                self.answers = []

            async def answer(self, text=None, **kwargs):
                self.answers.append(text)

        callback = _CB()
        asyncio.run(
            cb_semi_auto_dev_lobby(
                callback,
                SemiAutoDevLobby(code=game.room_code, act="wait"),
                AsyncMock(),
            )
        )
        self.assertEqual(set(game.players), before)
        self.assertEqual(callback.answers, ["منتظر بازیکن‌های واقعی می‌مانید."])
        from bot.game_snapshot import delete_game_snapshot

        delete_game_snapshot(game.room_code)
        gm.games.pop(game.room_code, None)
        gm.host_to_room.pop(88002, None)

    def test_observer_controls_synthetic_after_fill(self) -> None:
        from bot.game_snapshot import delete_game_snapshot

        gm = GameManager()
        game = gm.create_game(
            host_id=88013,
            scenario_name="russian_mafia",
            max_players=8,
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        self.assertIsNotNone(game)
        try:
            _obs(game)
            self.assertIsNone(gm.fill_russian_mafia_synthetic_lobby(game))
            self.assertEqual(len(game.players), 8)
            self.assertTrue(all(uid < 0 for uid in game.players))
            self.assertNotIn(900, game.players)
            _deal(gm, game, russian_roles_for_count(8))
            game.phase = Phase.NIGHT
            doctor = _alive_uid(game, Role.DOCTOR)
            self.assertLess(doctor, 0)
            citizen = _alive_uid(game, Role.CITIZEN)
            self.assertEqual(
                try_confirm_action(
                    game,
                    slot="doctor",
                    actor_uid=game.observer_user_id,
                    as_uid=doctor,
                    target_uid=citizen,
                ),
                "ok",
            )
        finally:
            delete_game_snapshot(game.room_code)



class HostPlayerPrivacyTests(unittest.TestCase):
    def _filled(self, n: int, host: int):
        from bot.game_snapshot import delete_game_snapshot

        gm = GameManager()
        game = gm.create_game(
            host_id=host,
            scenario_name="russian_mafia",
            max_players=n,
            host_full_name="Host",
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        self.assertIsNotNone(game)
        gm.add_player(game, Player(user_id=host, full_name="Host", username=None))
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        return gm, game

    def test_creator_is_one_player_and_fill_leaves_capacity(self) -> None:
        from bot.game import is_synthetic_player_uid
        from bot.room_mode import host_receives_moderator_deal_messages

        for count, host, extra in ((8, 88101, 7), (9, 88102, 8)):
            gm, game = self._filled(count, host)
            self.assertEqual(list(game.players), [host])
            self.assertEqual(game.host_id, host)
            self.assertIsNone(gm.fill_russian_mafia_synthetic_lobby(game))
            self.assertEqual(len(game.players), count)
            self.assertEqual(game.players[host].full_name, "Host")
            synth = [uid for uid in game.players if uid != host]
            self.assertEqual(len(synth), extra)
            self.assertTrue(all(is_synthetic_player_uid(uid) for uid in synth))
            self.assertFalse(host_receives_moderator_deal_messages(game))
            gm.prepare_shuffle(game)
            seated = gm.confirm_shuffle(game)
            host_seat = next(seat for seat, player in seated if player.user_id == host)
            self.assertGreaterEqual(host_seat, 1)
            _deal(gm, game, russian_roles_for_count(count))
            self.assertIsNotNone(game.players[host].role)
            self.assertEqual(game.host_id, host)

    def test_roles_do_not_reveal_teammates_or_roster(self) -> None:
        from bot.main import deal_roles_full_pipeline
        from bot.russian_mafia_flow import begin_after_roles

        gm, game = self._filled(8, 88103)
        gm.fill_russian_mafia_synthetic_lobby(game)
        gm.prepare_shuffle(game)
        gm.confirm_shuffle(game)
        sent: list[tuple] = []

        async def fake_private(bot, uid, role, game=None):
            sent.append(("role", uid, role))
            return True

        async def fake_roster(*args, **kwargs):
            sent.append(("roster",))

        async def run():
            with patch("bot.main.send_private_role", new=fake_private), patch(
                "bot.main.send_host_secret_role_roster", new=fake_roster
            ), patch("bot.russian_mafia_flow.begin_after_roles", new=AsyncMock()), patch("bot.main.notify_players_after_roles_dealt", new=AsyncMock()):
                return await deal_roles_full_pipeline(AsyncMock(), game)

        asyncio.run(run())
        self.assertFalse(any(kind == "roster" for kind, *_ in sent))
        role_uids = [uid for kind, uid, _role in sent if kind == "role"]
        self.assertEqual(role_uids, [88103])
        self.assertFalse(game.russian_mafia_mafia_team_revealed)

        messages: list[str] = []

        async def capture(bot, uid, text, **kwargs):
            messages.append(text)

        async def run_begin():
            with patch("bot.russian_mafia_flow.safe_send_message", new=capture):
                await begin_after_roles(AsyncMock(), game)

        asyncio.run(run_begin())
        blob = "\n".join(messages)
        self.assertNotIn("هم‌تیمی", blob)
        self.assertNotIn("اعضای تیم مافیا", blob)
        self.assertFalse(game.russian_mafia_mafia_team_revealed)

    def test_mafia_reveal_waits_for_intro_and_is_once(self) -> None:
        from bot.russian_mafia_flow import notify_mafia_teammates, send_russian_intro_prompt

        for count, host, must, banned in (
            (8, 88104, ("گادفادر", "ترور"), ()),
            (9, 88105, ("گادفادر", "مافیا ساده"), ("ترور",)),
        ):
            gm, game = self._filled(count, host)
            gm.fill_russian_mafia_synthetic_lobby(game)
            gm.prepare_shuffle(game)
            gm.confirm_shuffle(game)
            _deal(gm, game, russian_roles_for_count(count))
            game.roles_dealt = True
            self.assertFalse(game.russian_mafia_mafia_team_revealed)
            messages: list[tuple[int, str]] = []

            async def capture(bot, uid, text, **kwargs):
                messages.append((uid, text))

            async def run():
                with patch("bot.russian_mafia_flow.safe_send_message", new=capture):
                    await send_russian_intro_prompt(AsyncMock(), game)
                    await notify_mafia_teammates(AsyncMock(), game)
                    await notify_mafia_teammates(AsyncMock(), game)

            asyncio.run(run())
            intro = [text for _uid, text in messages if "شروع شب معارفه" in text]
            self.assertEqual(len(intro), 1)
            reveals = [text for _uid, text in messages if "اعضای تیم شما" in text]
            self.assertEqual(len(reveals), 1)
            body = reveals[0]
            for token in must:
                self.assertIn(token, body)
            for token in banned:
                self.assertNotIn(token, body)
            self.assertEqual([uid for uid, text in messages if "اعضای تیم شما" in text], [host])
            self.assertTrue(game.russian_mafia_mafia_team_revealed)

    def test_observer_mirror_is_not_granted_to_helper(self) -> None:
        gm, game = self._filled(8, 88106)
        self.assertFalse(game_observer_mirror_active(game))
        gm.fill_russian_mafia_synthetic_lobby(game)
        _obs(game)
        self.assertTrue(game_observer_mirror_active(game))
        self.assertNotIn(900, game.players)
        _deal(gm, game, russian_roles_for_count(8))
        game.phase = Phase.NIGHT
        doctor = _alive_uid(game, Role.DOCTOR)
        if doctor == 88106:
            target = next(uid for uid in game.players if uid != doctor)
            actor = doctor
        else:
            self.assertLess(doctor, 0)
            target = 88106
            actor = game.observer_user_id
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=actor,
                as_uid=doctor,
                target_uid=target,
            ),
            "ok",
        )



class FullRoomSeatTests(unittest.TestCase):
    def _host_room(self, n: int, host: int):
        from bot.game_snapshot import delete_game_snapshot

        gm = GameManager()
        game = gm.create_game(
            host_id=host,
            scenario_name="russian_mafia",
            max_players=n,
            host_full_name="Host",
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        self.assertIsNotNone(game)
        gm.add_player(game, Player(user_id=host, full_name="Host", username=None))
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        return gm, game

    def test_full_room_panel_once_for_fill_join_and_mixed(self) -> None:
        from bot.main import send_host_lobby_full_prompt
        from bot.room_mode import is_russian_mafia_host_helper_room

        async def panel(game):
            bot = AsyncMock()
            bot.send_message = AsyncMock()
            await send_host_lobby_full_prompt(bot, game)
            await send_host_lobby_full_prompt(bot, game)
            return bot.send_message

        # random fill, 8
        gm, game = self._host_room(8, 88201)
        _obs(game)
        self.assertIsNone(gm.fill_russian_mafia_synthetic_lobby(game))
        self.assertEqual(len(game.players), 8)
        self.assertNotIn(900, game.players)
        send = asyncio.run(panel(game))
        self.assertEqual(send.call_count, 1)
        body = send.call_args.args[1]
        kb = send.call_args.kwargs["reply_markup"]
        labels = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("ظرفیت اتاق کامل شد", body)
        self.assertIn("شماره صندلی‌ها را شافل کنید", body)
        self.assertNotIn("کمک‌کننده ربات", body)
        self.assertEqual(labels, ["🔀 شافل شماره صندلی‌ها"])
        self.assertIsNone(game.bot_assistant_user_id)
        self.assertEqual(send.call_args.args[0], 88201)

        # real joins, 9
        gm9, game9 = self._host_room(9, 88202)
        for i in range(8):
            gm9.add_player(
                game9, Player(user_id=5000 + i, full_name=f"R{i}", username=None)
            )
        self.assertEqual(len(game9.players), 9)
        send9 = asyncio.run(panel(game9))
        self.assertEqual(send9.call_count, 1)
        self.assertIn("شماره صندلی‌ها را شافل کنید", send9.call_args.args[1])
        self.assertNotIn("کمک‌کننده ربات", send9.call_args.args[1])
        labels9 = [
            b.text for row in send9.call_args.kwargs["reply_markup"].inline_keyboard for b in row
        ]
        self.assertEqual(labels9, ["🔀 شافل شماره صندلی‌ها"])
        self.assertIsNone(game9.bot_assistant_user_id)

        # mixed
        gmm, gamem = self._host_room(8, 88203)
        gmm.add_player(gamem, Player(user_id=6100, full_name="Real", username=None))
        self.assertIsNone(gmm.fill_russian_mafia_synthetic_lobby(gamem))
        self.assertEqual(len(gamem.players), 8)
        self.assertIn(6100, gamem.players)
        sendm = asyncio.run(panel(gamem))
        self.assertEqual(sendm.call_count, 1)
        self.assertTrue(is_russian_mafia_host_helper_room(gamem))

    def test_shuffle_hides_mapping_and_players_get_seats(self) -> None:
        from bot.main import (
            _host_shuffle_hides_player_names,
            build_shuffle_confirm_prompt_html,
            bump_seat_shuffle_count,
            deliver_seat_assignments,
            host_deal_roles_keyboard,
        )

        gm, game = self._host_room(8, 88204)
        other = 6200
        gm.add_player(game, Player(user_id=other, full_name="OtherReal", username=None))
        gm.fill_russian_mafia_synthetic_lobby(game)
        _obs(game)
        self.assertTrue(_host_shuffle_hides_player_names(game))
        rows = gm.prepare_shuffle(game)
        self.assertEqual(sorted(p.user_id for _seat, p in rows), sorted(game.players))
        n1 = bump_seat_shuffle_count(game)
        text1 = build_shuffle_confirm_prompt_html(game, rows)
        self.assertIn("۱ بار", text1)
        self.assertNotIn("OtherReal", text1)
        self.assertNotIn("Host", text1)
        self.assertNotIn("صندلی 1", text1)
        rows2 = gm.prepare_shuffle(game)
        n2 = bump_seat_shuffle_count(game)
        text2 = build_shuffle_confirm_prompt_html(game, rows2)
        self.assertEqual((n1, n2), (1, 2))
        self.assertIn("۲ بار", text2)
        self.assertNotIn("OtherReal", text2)
        self.assertEqual(sorted(game.pending_seat_order), sorted(game.players))

        sent: list[tuple[int, str]] = []

        async def capture(bot, uid, text, **kwargs):
            sent.append((uid, text))
            return True

        async def forbidden(*args, **kwargs):
            raise AssertionError("seat list must not use the mirrored player send")

        async def run():
            with patch("bot.main.safe_send_message", new=capture), patch(
                "bot.main.send_to_player", new=forbidden
            ):
                failed = await deliver_seat_assignments(AsyncMock(), game)
                self.assertEqual(failed, [])

        asyncio.run(run())
        by_uid = {uid: text for uid, text in sent}
        self.assertIn(88204, by_uid)
        self.assertIn(other, by_uid)
        self.assertNotIn(900, by_uid)
        synth_name = next(
            player.full_name for uid, player in game.players.items() if uid < 0
        )
        for uid in (88204, other):
            self.assertIn("لیست بازیکنها", by_uid[uid])
            self.assertIn("OtherReal", by_uid[uid])
            self.assertIn("Host", by_uid[uid])
            self.assertIn(synth_name, by_uid[uid])
            self.assertNotIn("شماره صندلی شما", by_uid[uid])
        gm.confirm_shuffle(game)
        self.assertIsNotNone(game.players[88204].seat)
        labels = [
            btn.text
            for row in host_deal_roles_keyboard(game).inline_keyboard
            for btn in row
        ]
        self.assertIn("🎭 پخش نقش‌های تصادفی", labels)
        self.assertIn("انتخاب نقش‌ها توسط بازیکنان", labels)

    def test_other_scenarios_keep_shuffle_visibility(self) -> None:
        from bot.game_snapshot import delete_game_snapshot
        from bot.main import _host_shuffle_hides_player_names

        gm = GameManager()
        moz = gm.create_game(
            host_id=88210,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        baz = gm.create_game(
            host_id=88211,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="manual",
        )
        mason = gm.create_game(
            host_id=88212,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="manual",
        )
        try:
            self.assertIsNotNone(moz)
            self.assertIsNotNone(baz)
            self.assertIsNotNone(mason)
            self.assertTrue(_host_shuffle_hides_player_names(moz))
            self.assertFalse(_host_shuffle_hides_player_names(baz))
            self.assertFalse(_host_shuffle_hides_player_names(mason))
        finally:
            for game in (moz, baz, mason):
                if game is not None:
                    delete_game_snapshot(game.room_code)



class SetupAlignmentTests(unittest.TestCase):
    def _host_room(self, n: int, host: int):
        from bot.game_snapshot import delete_game_snapshot

        gm = GameManager()
        game = gm.create_game(
            host_id=host,
            scenario_name="russian_mafia",
            max_players=n,
            host_full_name="Host",
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        self.assertIsNotNone(game)
        gm.add_player(game, Player(user_id=host, full_name="Host", username=None))
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        return gm, game

    def test_mode_label_is_player_gardaanandeh(self) -> None:
        from bot.russian_mafia import russian_host_mode_keyboard
        from bot.russian_mafia_flow import accept_russian_host_mode
        from bot.app_state import manager

        labels = [
            button.text
            for row in russian_host_mode_keyboard(8).inline_keyboard
            for button in row
        ]
        self.assertEqual(labels, ["بازیکن گرداننده"])
        self.assertIsNone(host_mode_rejection_reason(HOST_HELPER_MODE))
        self.assertIn("بازیکن گرداننده", host_mode_rejection_reason("manual"))

        saved: dict[str, str] = {}

        class Msg:
            async def edit_text(self, text, **kwargs):
                saved["text"] = text
                saved["markup"] = kwargs.get("reply_markup")

        class CB:
            from_user = SimpleNamespace(id=889901, full_name="Creator", username="c")
            message = Msg()

            async def answer(self, *args, **kwargs):
                saved["answer"] = args[0] if args else ""

        class Data:
            mode = HOST_HELPER_MODE
            count = 8

        async def run():
            bot = AsyncMock()
            bot.get_me = AsyncMock(return_value=SimpleNamespace(username="Bot"))
            await accept_russian_host_mode(CB(), bot, Data())

        try:
            asyncio.run(run())
            text = saved["text"]
            self.assertIn("بازیکن گرداننده", text)
            self.assertNotIn("بازیکن و کمک‌کننده", text)
            self.assertIn("شما به‌عنوان", text)
            self.assertIsNotNone(saved["markup"])
        finally:
            room = manager.get_room_for_host(889901)
            if room:
                manager.end_game(room)

    def test_helper_pick_stores_one_player_and_routes_panels(self) -> None:
        from aiogram.enums import ChatType
        from bot.handlers.lobby import cb_no_host_bot_assistant_pick
        from bot.main import (
            NoHostBotAssistantPick,
            pick_random_no_host_bot_assistant,
            send_host_lobby_full_prompt,
        )
        from bot.russian_mafia_flow import finalize_russian_bot_helper

        gm, game = self._host_room(8, 889902)
        helper = 6301
        other = 6302
        gm.add_player(game, Player(user_id=helper, full_name="Helper", username=None))
        gm.add_player(game, Player(user_id=other, full_name="Other", username=None))
        gm.fill_russian_mafia_synthetic_lobby(game)
        _obs(game)
        self.assertEqual(len(game.players), 8)

        async def panel():
            bot = AsyncMock()
            await send_host_lobby_full_prompt(bot, game)
            await send_host_lobby_full_prompt(bot, game)
            return bot.send_message

        send = asyncio.run(panel())
        self.assertEqual(send.call_count, 1)
        labels = [
            button.text
            for row in send.call_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertEqual(send.call_args.args[0], 889902)
        self.assertEqual(labels, ["🔀 شافل شماره صندلی‌ها"])
        self.assertNotIn("کمک‌کننده ربات", send.call_args.args[1])
        self.assertIsNone(game.bot_assistant_user_id)
        gm.prepare_shuffle(game)
        from bot.handlers.host_panel import host_panel_cb
        from bot.main import HostPanel

        class SeatCB:
            def __init__(self, uid: int):
                self.from_user = SimpleNamespace(id=uid)
                self.message = SimpleNamespace(
                    chat=SimpleNamespace(type=ChatType.PRIVATE),
                    edit_text=AsyncMock(),
                    answer=AsyncMock(),
                )
                self.answers: list[str] = []

            async def answer(self, text="", show_alert=False):
                self.answers.append(text)

        seat_cb = SeatCB(889902)
        stranger = SeatCB(helper)

        notices: list[tuple[int, str]] = []

        async def capture_notice(bot, uid, text, **kwargs):
            notices.append((uid, text))
            return True

        async def confirm_seats():
            with patch("bot.handlers.host_panel.manager.get_game", return_value=game), patch(
                "bot.russian_mafia_flow.safe_send_message", new=capture_notice
            ):
                await host_panel_cb(stranger, HostPanel(code=game.room_code, act="fs"), AsyncMock())
                await host_panel_cb(seat_cb, HostPanel(code=game.room_code, act="sy"), AsyncMock())

        asyncio.run(confirm_seats())
        self.assertTrue(any("سازنده" in item for item in stranger.answers))
        shown = seat_cb.message.edit_text.await_args.args[0]
        self.assertNotIn("کمک‌کننده ربات", shown)
        self.assertIsNone(seat_cb.message.edit_text.await_args.kwargs.get("reply_markup"))
        self.assertTrue(any(uid == 889902 and "پخش نقش" in text for uid, text in notices))
        self.assertFalse(any("ناظر" in text for _uid, text in notices))
        self.assertFalse(any("کمک‌کننده ربات" in text for _uid, text in notices))
        self.assertFalse(any("شروع شب معارفه" in text for _uid, text in notices))
        self.assertIsNone(game.bot_assistant_user_id)
        self.assertTrue(game.seats_finalized)

        from bot.russian_mafia_flow import continue_russian_mafia_after_observer

        game.observer_prompt_status = "skipped"
        helper_notes: list[tuple[int, str]] = []

        async def capture_helper(bot, uid, text, **kwargs):
            helper_notes.append((uid, text))
            return True

        async def run_helper_prompt():
            with patch("bot.russian_mafia_flow.safe_send_message", new=capture_helper):
                await continue_russian_mafia_after_observer(AsyncMock(), game)
                await continue_russian_mafia_after_observer(AsyncMock(), game)

        asyncio.run(run_helper_prompt())
        helper_msgs = [(uid, text) for uid, text in helper_notes if "کمک‌کننده ربات" in text]
        self.assertEqual(len(helper_msgs), 1)
        self.assertEqual(helper_msgs[0][0], 889902)
        self.assertFalse(any("شروع شب معارفه" in text for _uid, text in helper_notes))

        chosen = pick_random_no_host_bot_assistant(game)
        self.assertIn(chosen, {889902, helper, other})
        self.assertNotEqual(chosen, 900)
        self.assertGreater(chosen, 0)

        answers: list[str] = []

        class CB:
            def __init__(self, uid: int):
                self.from_user = SimpleNamespace(id=uid)
                self.message = SimpleNamespace(
                    chat=SimpleNamespace(type=ChatType.PRIVATE),
                    html_text="prompt",
                    text="prompt",
                    edit_text=self._edit,
                    edit_reply_markup=AsyncMock(),
                )

            async def _edit(self, text, **kwargs):
                self.message.saved = text
                if kwargs.get("reply_markup") is not None:
                    raise AssertionError("old helper keyboard must be removed")

            async def answer(self, text="", show_alert=False):
                answers.append(text)

        data = NoHostBotAssistantPick(code=game.room_code, act="pick", tid=helper)
        recorded = {}

        async def fake_finalize(bot, got, uid, random_pick=True):
            recorded["uid"] = uid
            recorded["random"] = random_pick
            got.bot_assistant_user_id = uid

        async def run_pick():
            with patch("bot.handlers.lobby.manager.get_game", return_value=game), patch(
                "bot.russian_mafia_flow.finalize_russian_bot_helper", new=fake_finalize
            ):
                await cb_no_host_bot_assistant_pick(CB(889902), data, AsyncMock())
                await cb_no_host_bot_assistant_pick(CB(889902), data, AsyncMock())

        asyncio.run(run_pick())
        self.assertEqual(recorded["uid"], helper)
        self.assertFalse(recorded["random"])
        self.assertEqual(game.bot_assistant_user_id, helper)
        self.assertTrue(any("قبلاً" in item for item in answers))

        sent: list[tuple[int, str]] = []

        async def capture_safe(bot, uid, text, **kwargs):
            sent.append((uid, text))
            return True

        async def capture_broadcast(bot, got, text, exclude=None, **kwargs):
            sent.append((exclude or 0, "BROADCAST:" + text))

        async def run_final():
            game.bot_assistant_user_id = None
            from bot.russian_mafia_flow import _RUSSIAN_HELPER_ANNOUNCED

            _RUSSIAN_HELPER_ANNOUNCED.discard(game.room_code)
            with patch("bot.russian_mafia_flow.safe_send_message", new=capture_safe), patch(
                "bot.observer_delivery.broadcast_to_players", new=capture_broadcast
            ):
                bot = AsyncMock()
                await finalize_russian_bot_helper(
                    bot, game, helper, random_pick=False
                )
                await finalize_russian_bot_helper(
                    bot, game, other, random_pick=True
                )
                return bot.send_message

        asyncio.run(run_final())
        self.assertEqual(game.bot_assistant_user_id, helper)
        intro = [uid for uid, text in sent if "شروع شب معارفه" in text]
        self.assertEqual(intro, [helper])
        self.assertNotIn(889902, intro)
        self.assertNotIn(900, intro)
        self.assertFalse(any("پخش نقش‌های تصادفی" in text for _uid, text in sent))
        self.assertTrue(any(uid == helper and "کمک‌کننده ربات" in text for uid, text in sent))
        self.assertFalse(any("اعضای تیم شما" in text for _uid, text in sent))

    def test_shuffle_controls_belong_to_selected_helper(self) -> None:
        from aiogram.enums import ChatType
        from bot.handlers.host_panel import host_panel_cb
        from bot.main import HostPanel

        gm, game = self._host_room(8, 889903)
        helper = 6401
        gm.add_player(game, Player(user_id=helper, full_name="Helper", username=None))
        gm.fill_russian_mafia_synthetic_lobby(game)
        game.lobby_full_notice_sent = True
        self.assertIsNone(game.bot_assistant_user_id)

        class CB:
            def __init__(self, uid: int):
                self.from_user = SimpleNamespace(id=uid)
                self.message = SimpleNamespace(
                    chat=SimpleNamespace(type=ChatType.PRIVATE),
                    edit_text=AsyncMock(),
                    answer=AsyncMock(),
                )
                self.answers: list[str] = []

            async def answer(self, text="", show_alert=False):
                self.answers.append(text)

        creator = CB(889903)
        helper_cb = CB(helper)
        data = HostPanel(code=game.room_code, act="fs")

        async def run():
            with patch("bot.handlers.host_panel.manager.get_game", return_value=game):
                await host_panel_cb(creator, data, AsyncMock())
                await host_panel_cb(helper_cb, data, AsyncMock())

        asyncio.run(run())
        self.assertTrue(any("سازنده" in item for item in helper_cb.answers))
        edited = creator.message.edit_text.await_args
        self.assertIsNotNone(edited)
        shown = edited.args[0]
        self.assertIn("بار", shown)
        self.assertNotIn("Helper", shown)
        self.assertNotIn("Host", shown)
        self.assertIsNone(game.bot_assistant_user_id)

    def test_intro_goes_to_helper_and_reveals_mafia_once(self) -> None:
        from bot.russian_mafia_flow import (
            handle_host_action,
            notify_mafia_teammates,
            send_russian_intro_prompt,
        )

        gm, game = self._host_room(8, 889904)
        helper = 6501
        boss = 6502
        terror = 6503
        for uid, name in ((helper, "Helper"), (boss, "Boss"), (terror, "Terror")):
            gm.add_player(game, Player(user_id=uid, full_name=name, username=None))
        gm.fill_russian_mafia_synthetic_lobby(game)
        gm.prepare_shuffle(game)
        gm.confirm_shuffle(game)
        game.bot_assistant_user_id = helper
        game.players[889904].role = Role.CITIZEN
        game.players[helper].role = Role.CITIZEN
        game.players[boss].role = ROLE_GODFATHER
        game.players[terror].role = ROLE_TERROR
        for player in game.players.values():
            if player.role is None:
                player.role = Role.CITIZEN
        game.roles_dealt = True
        game.phase = Phase.LOBBY

        messages: list[tuple[int, str]] = []

        async def capture(bot, uid, text, **kwargs):
            messages.append((uid, text))
            return True

        class CB:
            def __init__(self, uid: int, act: str):
                self.from_user = SimpleNamespace(id=uid)
                self.data = f"rmh:{game.room_code}:{act}"
                self.message = SimpleNamespace(edit_text=AsyncMock(), edit_reply_markup=AsyncMock())
                self.answers: list[str] = []

            async def answer(self, text="", show_alert=False):
                self.answers.append(text)

        async def run():
            with patch("bot.russian_mafia_flow.safe_send_message", new=capture), patch(
                "bot.russian_mafia_flow.open_day", new=AsyncMock()
            ):
                await send_russian_intro_prompt(AsyncMock(), game)
                await send_russian_intro_prompt(AsyncMock(), game)
                creator = CB(889904, "intro_ok")
                await handle_host_action(creator, AsyncMock(), game)
                helper_cb = CB(helper, "intro_ok")
                await handle_host_action(helper_cb, AsyncMock(), game)
                await handle_host_action(CB(helper, "intro_ok"), AsyncMock(), game)
                return creator.answers

        creator_answers = asyncio.run(run())
        intro = [(uid, text) for uid, text in messages if "شروع شب معارفه" in text]
        self.assertEqual([uid for uid, _text in intro], [helper])
        self.assertTrue(any("کمک" in item for item in creator_answers))
        reveals = [
            (uid, text) for uid, text in messages if "اعضای تیم شما" in text
        ]
        self.assertEqual(sorted(uid for uid, _text in reveals), [boss, terror])
        body = reveals[0][1]
        self.assertIn("گادفادر", body)
        self.assertIn("ترور", body)
        self.assertNotIn(helper, [uid for uid, _text in reveals])
        self.assertTrue(game.russian_mafia_mafia_team_revealed)

        gm9, game9 = self._host_room(9, 889905)
        helper9 = 6601
        a = 6602
        b = 6603
        for uid, name in ((helper9, "Helper"), (a, "A"), (b, "B")):
            gm9.add_player(game9, Player(user_id=uid, full_name=name, username=None))
        for i in range(5):
            gm9.add_player(game9, Player(user_id=6700 + i, full_name=f"C{i}", username=None))
        gm9.prepare_shuffle(game9)
        gm9.confirm_shuffle(game9)
        game9.bot_assistant_user_id = helper9
        game9.players[889905].role = Role.CITIZEN
        game9.players[helper9].role = Role.DOCTOR
        game9.players[a].role = ROLE_GODFATHER
        game9.players[b].role = ROLE_SIMPLE_MAFIA
        game9.players[6700].role = ROLE_SIMPLE_MAFIA
        for player in game9.players.values():
            if player.role is None:
                player.role = Role.CITIZEN
        game9.roles_dealt = True
        nine: list[tuple[int, str]] = []

        async def capture9(bot, uid, text, **kwargs):
            nine.append((uid, text))
            return True

        async def run9():
            with patch("bot.russian_mafia_flow.safe_send_message", new=capture9):
                await notify_mafia_teammates(AsyncMock(), game9)
                await notify_mafia_teammates(AsyncMock(), game9)

        asyncio.run(run9())
        reveals9 = [text for uid, text in nine if "اعضای تیم شما" in text]
        self.assertEqual(len(reveals9), 3)
        self.assertIn("گادفادر", reveals9[0])
        self.assertIn("مافیا ساده", reveals9[0])
        self.assertNotIn("ترور", reveals9[0])
        self.assertEqual(
            sorted(uid for uid, text in nine if "اعضای تیم شما" in text),
            [a, b, 6700],
        )

    def test_observer_completion_sends_helper_then_intro(self) -> None:
        from aiogram.enums import ChatType
        from bot.handlers.lobby import cb_no_host_observer_prompt
        from bot.main import NoHostObserverPrompt
        from bot.russian_mafia_flow import (
            continue_russian_mafia_after_seat_confirmation,
            finalize_russian_bot_helper,
        )

        async def one(act: str, host: int) -> list[tuple[int, str]]:
            gm, game = self._host_room(8, host)
            helper = host + 50
            gm.add_player(game, Player(user_id=helper, full_name="Helper", username=None))
            gm.fill_russian_mafia_synthetic_lobby(game)
            gm.prepare_shuffle(game)
            gm.confirm_shuffle(game)
            self.assertIsNone(game.bot_assistant_user_id)
            messages: list[tuple[int, str]] = []

            async def capture(bot, uid, text, **kwargs):
                messages.append((uid, text))
                return True

            class CB:
                from_user = SimpleNamespace(id=host)
                message = SimpleNamespace(
                    chat=SimpleNamespace(type=ChatType.PRIVATE),
                    html_text="obs",
                    text="obs",
                    edit_text=AsyncMock(),
                    edit_reply_markup=AsyncMock(),
                )

                async def answer(self, text="", show_alert=False):
                    return None

            with patch("bot.russian_mafia_flow.safe_send_message", new=capture), patch(
                "bot.handlers.lobby.manager.get_game", return_value=game
            ), patch("bot.main.send_private_role", new=AsyncMock(return_value=True)), patch(
                "bot.observer_delivery.broadcast_to_players", new=AsyncMock()
            ):
                from bot.russian_mafia_flow import _ensure_russian_roles_ready

                await _ensure_russian_roles_ready(AsyncMock(), game)
                await continue_russian_mafia_after_seat_confirmation(AsyncMock(), game)
                await cb_no_host_observer_prompt(
                    CB(), NoHostObserverPrompt(code=game.room_code, act=act), AsyncMock()
                )
                await cb_no_host_observer_prompt(
                    CB(), NoHostObserverPrompt(code=game.room_code, act=act), AsyncMock()
                )
                self.assertIsNone(game.bot_assistant_user_id)
                self.assertFalse(any("شروع شب معارفه" in text for _uid, text in messages))
                await finalize_russian_bot_helper(
                    AsyncMock(), game, helper, random_pick=False
                )
            return messages

        for act, host in (("skip", 889920), ("code_sent", 889921)):
            messages = asyncio.run(one(act, host))
            self.assertTrue(any(uid == host and "ناظر" in text for uid, text in messages))
            helper_prompts = [
                uid for uid, text in messages if "انتخاب شود" in text
            ]
            self.assertEqual(helper_prompts, [host])
            intro = [uid for uid, text in messages if "شروع شب معارفه" in text]
            self.assertEqual(intro, [host + 50])
            self.assertNotIn(host, intro)
            self.assertFalse(any("اعضای تیم شما" in text for _uid, text in messages))

    def test_other_scenarios_still_get_their_full_room_panel(self) -> None:
        from bot.game_snapshot import delete_game_snapshot
        from bot.main import send_host_lobby_full_prompt

        gm = GameManager()
        moz = gm.create_game(
            host_id=889910,
            scenario_name="mozakere",
            max_players=10,
            host_full_name="Moz",
            bazpors_host_mode="no_host",
        )
        baz = gm.create_game(
            host_id=889911,
            scenario_name="bazpors",
            max_players=10,
            host_full_name="Baz",
            bazpors_host_mode="manual",
        )
        self.assertIsNotNone(moz)
        self.assertIsNotNone(baz)
        gm.add_player(moz, Player(user_id=889910, full_name="Moz", username=None))
        for i in range(9):
            gm.add_player(moz, Player(user_id=6800 + i, full_name=f"M{i}", username=None))
        for i in range(10):
            gm.add_player(baz, Player(user_id=6900 + i, full_name=f"B{i}", username=None))

        async def send(game):
            bot = AsyncMock()
            await send_host_lobby_full_prompt(bot, game)
            return bot.send_message

        try:
            moz_send = asyncio.run(send(moz))
            baz_send = asyncio.run(send(baz))
        finally:
            delete_game_snapshot(moz.room_code)
            delete_game_snapshot(baz.room_code)
        moz_labels = [
            button.text
            for row in moz_send.call_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertEqual(moz_labels, ["🔀 شافل شماره صندلی‌ها"])
        self.assertNotIn("کمک‌کننده ربات", moz_send.call_args.args[1])
        self.assertEqual(moz_send.call_args.args[0], 889910)
        baz_labels = [
            button.text
            for row in baz_send.call_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("🔀 شافل شماره صندلی", baz_labels)
        self.assertIn("🎭 پخش نقش‌ها", baz_labels)



class PostIntroPanelTests(unittest.TestCase):
    """بعد از تأیید شب معارفه، همان پنل دفاعیهٔ مذاکره/بازپرس."""

    def _room(self):
        from bot.game_snapshot import delete_game_snapshot

        gm = GameManager()
        host = 889930
        game = gm.create_game(
            host_id=host,
            scenario_name="russian_mafia",
            max_players=8,
            host_full_name="Host",
            bazpors_host_mode=HOST_HELPER_MODE,
        )
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        helper = 6501
        boss = 6502
        terror = 6503
        for uid, name in (
            (host, "Host"),
            (helper, "Helper"),
            (boss, "Boss"),
            (terror, "Terror"),
        ):
            gm.add_player(game, Player(user_id=uid, full_name=name, username=None))
        gm.fill_russian_mafia_synthetic_lobby(game)
        gm.prepare_shuffle(game)
        gm.confirm_shuffle(game)
        game.bot_assistant_user_id = helper
        game.players[host].role = Role.CITIZEN
        game.players[helper].role = Role.CITIZEN
        game.players[boss].role = ROLE_GODFATHER
        game.players[terror].role = ROLE_TERROR
        for player in game.players.values():
            if player.role is None:
                player.role = Role.CITIZEN
        game.roles_dealt = True
        game.phase = Phase.LOBBY
        return game, helper, boss, terror

    def _callback(self, uid: int, data: str):
        class CB:
            def __init__(self):
                self.from_user = SimpleNamespace(id=uid)
                self.data = data
                self.message = SimpleNamespace(
                    message_id=42,
                    html_text="panel",
                    text="panel",
                    edit_text=AsyncMock(),
                    edit_reply_markup=AsyncMock(),
                )
                self.answers: list[str] = []

            async def answer(self, text="", show_alert=False):
                self.answers.append(text)

        return CB()

    def _run_intro(self, game, helper, *, observer: int | None = None):
        from bot.russian_mafia_flow import handle_host_action

        if observer is not None:
            _obs(game, observer)
        reveals: list[tuple[int, str]] = []
        panels: list[tuple] = []
        mid = {"n": 100}

        async def capture_reveal(bot, uid, text, **kwargs):
            reveals.append((uid, text))
            return True

        async def capture_panel(bot, uid, text, **kwargs):
            mid["n"] += 1
            panels.append((uid, text, kwargs.get("reply_markup"), mid["n"]))
            return SimpleNamespace(message_id=mid["n"])

        async def run():
            with patch(
                "bot.russian_mafia_flow.safe_send_message", new=capture_reveal
            ), patch(
                "bot.observer_delivery.safe_send_message_return", new=capture_panel
            ):
                creator = self._callback(game.host_id, f"rmh:{game.room_code}:intro_ok")
                await handle_host_action(creator, AsyncMock(), game)
                helper_cb = self._callback(helper, f"rmh:{game.room_code}:intro_ok")
                await handle_host_action(helper_cb, AsyncMock(), game)
                await handle_host_action(
                    self._callback(helper, f"rmh:{game.room_code}:intro_ok"),
                    AsyncMock(),
                    game,
                )
                return creator.answers

        creator_answers = asyncio.run(run())
        return creator_answers, reveals, panels

    def test_intro_confirm_sends_reference_panel_to_helper_once(self) -> None:
        from bot.main import (
            NoHostDay1DefenseCb,
            build_no_host_day1_defense_pick_html,
            day1_defense_pick_keyboard_for,
        )
        from bot.room_mode import no_host_bot_assistant_flow_enabled

        game, helper, boss, terror = self._room()
        creator_answers, reveals, panels = self._run_intro(game, helper)
        self.assertTrue(any("کمک" in item for item in creator_answers))
        self.assertEqual(
            sorted(uid for uid, text in reveals if "اعضای تیم شما" in text),
            [boss, terror],
        )
        self.assertEqual(len([t for _u, t in reveals if "اعضای تیم شما" in t]), 2)
        day_panels = [row for row in panels if "روز شروع شد" in row[1]]
        self.assertEqual(len(day_panels), 1)
        uid, text, markup, _mid = day_panels[0]
        self.assertEqual(uid, helper)
        self.assertNotEqual(uid, game.host_id)
        self.assertEqual(text, build_no_host_day1_defense_pick_html(game))
        expected = day1_defense_pick_keyboard_for(game, helper)
        got_rows = [[b.text for b in row] for row in markup.inline_keyboard]
        exp_rows = [[b.text for b in row] for row in expected.inline_keyboard]
        self.assertEqual(got_rows, exp_rows)
        flat = [text for row in got_rows for text in row]
        self.assertTrue(any("Helper" in text for text in flat))
        self.assertTrue(any("Boss" in text for text in flat))
        self.assertTrue(got_rows[-2][0].startswith("⏭️ برو به مرحله بعد"))
        self.assertEqual(got_rows[-1], ["🌙 دفاعیه نداریم"])
        self.assertTrue(all(len(row) <= 2 for row in got_rows))
        for row in markup.inline_keyboard[:-2]:
            for button in row:
                unpacked = NoHostDay1DefenseCb.unpack(button.callback_data)
                self.assertEqual(unpacked.code, game.room_code)
                self.assertEqual(unpacked.act, "tog")
        self.assertEqual(
            NoHostDay1DefenseCb.unpack(
                markup.inline_keyboard[-2][0].callback_data
            ).act,
            "confirm",
        )
        self.assertEqual(
            NoHostDay1DefenseCb.unpack(
                markup.inline_keyboard[-1][0].callback_data
            ).act,
            "none",
        )
        self.assertNotIn("گادفادر", text)
        self.assertNotIn("ترور", text)
        self.assertNotIn("کارآگاه", text)
        self.assertFalse(no_host_bot_assistant_flow_enabled(game))
        self.assertFalse(game.no_host_assistant_narrator_active)
        self.assertTrue(game.russian_mafia_mafia_team_revealed)
        self.assertTrue(game.no_host_day1_defense_active)
        self.assertEqual(game.phase, Phase.DAY_DISCUSSION)

    def test_observer_receives_same_choices_and_stale_claim(self) -> None:
        from bot.handlers.no_host_player import player_mirror_cb
        from bot.main import (
            _no_host_day1_defense_actor_may_act,
            _no_host_day1_defense_pick_ui_key,
            day1_defense_pick_keyboard_for,
        )
        from bot.observer_delivery import try_claim_mirror_ui

        game, helper, _boss, _terror = self._room()
        observer = 900
        _creator, _reveals, panels = self._run_intro(game, helper, observer=observer)
        day_panels = [row for row in panels if "روز شروع شد" in row[1]]
        self.assertEqual([row[0] for row in day_panels], [helper, observer])
        self.assertEqual(
            [[b.text for b in row] for row in day_panels[0][2].inline_keyboard],
            [[b.text for b in row] for row in day_panels[1][2].inline_keyboard],
        )
        expected = day1_defense_pick_keyboard_for(game, helper)
        self.assertEqual(
            [[b.text for b in row] for row in day_panels[0][2].inline_keyboard],
            [[b.text for b in row] for row in expected.inline_keyboard],
        )
        mirrored = PlayerMirrorCb.unpack(
            day_panels[0][2].inline_keyboard[-1][0].callback_data
        )
        self.assertEqual(mirrored.act, "d1dn")
        self.assertEqual(mirrored.as_uid, helper)
        self.assertTrue(_no_host_day1_defense_actor_may_act(game, observer, helper))
        self.assertTrue(_no_host_day1_defense_actor_may_act(game, helper, helper))
        self.assertFalse(_no_host_day1_defense_actor_may_act(game, game.host_id, helper))
        ui_key = _no_host_day1_defense_pick_ui_key(game, helper)
        self.assertIsNone(try_claim_mirror_ui(game, ui_key, observer, helper))
        self.assertEqual(
            try_claim_mirror_ui(game, ui_key, helper, helper),
            "already_claimed",
        )
        game.mirror_action_claims.clear()
        none_data = day_panels[1][2].inline_keyboard[-1][0].callback_data
        obs_cb = self._callback(observer, none_data)
        helper_cb = self._callback(helper, none_data)

        async def press():
            with patch(
                "bot.handlers.no_host_player.manager.get_game", return_value=game
            ):
                await player_mirror_cb(obs_cb, AsyncMock())
                await player_mirror_cb(helper_cb, AsyncMock())

        asyncio.run(press())
        self.assertIn("ثبت شد.", obs_cb.answers)
        self.assertIn("پنل دفاعیه فعال نیست.", helper_cb.answers)
        self.assertFalse(game.no_host_day1_defense_active)
        self.assertNotIn("گادفادر", " ".join(obs_cb.answers + helper_cb.answers))
        stale = self._callback(observer, none_data)

        async def press_stale():
            with patch(
                "bot.handlers.no_host_player.manager.get_game", return_value=game
            ):
                await player_mirror_cb(stale, AsyncMock())

        asyncio.run(press_stale())
        self.assertIn("پنل دفاعیه فعال نیست.", stale.answers)
        self.assertNotIn("گادفادر", day_panels[1][1])

    def test_reference_actor_rules_unchanged_for_mozakere(self) -> None:
        from bot.game_snapshot import delete_game_snapshot
        from bot.main import _no_host_day1_defense_actor_may_act
        from bot.room_mode import no_host_bot_assistant_flow_enabled

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            host_full_name="H",
            bazpors_host_mode="no_host",
        )
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        game.bot_assistant_user_id = 2
        game.observer_user_id = 3
        game.observer_prompt_status = "registered"
        self.assertTrue(no_host_bot_assistant_flow_enabled(game))
        self.assertTrue(_no_host_day1_defense_actor_may_act(game, 2, 2))
        self.assertTrue(_no_host_day1_defense_actor_may_act(game, 3, 2))
        self.assertFalse(_no_host_day1_defense_actor_may_act(game, 9, 2))





class DayDefenseContinuationTests(unittest.TestCase):
    """ادامهٔ پنل دفاعیه تا شب مافیای روسی، بدون شب مذاکره."""

    def _game(self, n: int = 8, *, observer: bool = False):
        from bot.bazpors_narrator import begin_no_host_day1_defense_pick
        from bot.game_snapshot import delete_game_snapshot

        gm, game = _room(n=n)
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        _deal(gm, game, russian_roles_for_count(n))
        helper = 100
        game.bot_assistant_user_id = helper
        game.phase = Phase.DAY_DISCUSSION
        game.roles_dealt = True
        if observer:
            _obs(game)
        begin_no_host_day1_defense_pick(game)
        return game

    def _cb(self, uid: int, data: str):
        class CB:
            def __init__(self):
                self.from_user = SimpleNamespace(id=uid)
                self.data = data
                self.message = SimpleNamespace(
                    message_id=7,
                    html_text="panel",
                    text="panel",
                    edit_text=AsyncMock(),
                    edit_reply_markup=AsyncMock(),
                )
                self.answers: list[str] = []

            async def answer(self, text="", show_alert=False):
                self.answers.append(text)

        return CB()

    def _patches(self, nights: list, notices: list):
        async def fake_pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            nights.append((slot, player_uid, act))

        async def fake_notice(bot, uid, text, **kwargs):
            notices.append((uid, text))
            return True

        return (
            patch("bot.russian_mafia_flow._send_pair", new=fake_pair),
            patch("bot.russian_mafia_flow.safe_send_message", new=fake_notice),
            patch("bot.main.broadcast_to_alive_players", new=AsyncMock()),
            patch("bot.main.on_no_host_entered_night1", new=AsyncMock()),
        )

    async def _press_mirror(self, game, actor: int, act: str, tid: int = 0):
        from bot.handlers.no_host_player import player_mirror_cb

        data = PlayerMirrorCb(
            code=game.room_code,
            act=act,
            as_uid=game.bot_assistant_user_id,
            tid=tid,
        ).pack()
        cb = self._cb(actor, data)
        with patch(
            "bot.handlers.no_host_player.manager.get_game", return_value=game
        ):
            await player_mirror_cb(cb, AsyncMock())
        return cb

    async def _press_direct(self, game, actor: int, act: str, tid: int = 0):
        from bot.handlers.no_host_player import cb_no_host_day1_defense
        from bot.main import NoHostDay1DefenseCb

        data = NoHostDay1DefenseCb(code=game.room_code, act=act, tid=tid)
        cb = self._cb(actor, data.pack())
        with patch(
            "bot.handlers.no_host_player.manager.get_game", return_value=game
        ):
            await cb_no_host_day1_defense(cb, data, AsyncMock())
        return cb

    def test_no_defense_starts_russian_night_once(self) -> None:
        game = self._game()
        nights: list = []
        notices: list = []
        moz_night = AsyncMock()

        async def run():
            with self._patches(nights, notices)[0], self._patches(nights, notices)[1], self._patches(nights, notices)[2], patch(
                "bot.main.on_no_host_entered_night1", new=moz_night
            ):
                first = await self._press_direct(game, 100, "none")
                second = await self._press_direct(game, 100, "none")
                return first, second

        first, second = asyncio.run(run())
        self.assertIn("ثبت شد.", first.answers)
        self.assertIn("پنل دفاعیه فعال نیست.", second.answers)
        self.assertEqual(game.phase, Phase.NIGHT)
        self.assertFalse(any(not p.is_alive for p in game.players.values()))
        self.assertEqual([row[0] for row in nights], ["mafia", "doctor", "detective"])
        self.assertEqual(nights[0][1], _alive_uid(game, ROLE_GODFATHER))
        self.assertFalse(game.no_host_assistant_narrator_active)
        moz_night.assert_not_awaited()
        self.assertEqual(len([row for row in nights if row[0] == "mafia"]), 1)

    def test_observer_no_defense_invalidates_helper_and_starts_night_once(self) -> None:
        game = self._game(observer=True)
        nights: list = []
        notices: list = []

        async def run():
            with self._patches(nights, notices)[0], self._patches(nights, notices)[1], self._patches(nights, notices)[2], self._patches(nights, notices)[3]:
                obs = await self._press_mirror(game, 900, "d1dn")
                helper = await self._press_mirror(game, 100, "d1dn")
                return obs, helper

        obs, helper = asyncio.run(run())
        self.assertIn("ثبت شد.", obs.answers)
        self.assertIn("پنل دفاعیه فعال نیست.", helper.answers)
        self.assertEqual(game.phase, Phase.NIGHT)
        self.assertEqual(len([row for row in nights if row[0] == "mafia"]), 1)

    def test_selected_players_follow_reference_outcome_panel(self) -> None:
        from bot.main import build_no_host_day1_defense_outcome_html

        game = self._game(observer=True)
        target = _alive_uid(game, Role.CITIZEN)
        other = next(
            p.user_id
            for p in game.players.values()
            if p.is_alive and p.user_id not in (target, _alive_uid(game, ROLE_GODFATHER))
            and p.role == Role.CITIZEN
        )
        panels: list[tuple] = []

        async def capture(bot, uid, text, **kwargs):
            panels.append((uid, text, kwargs.get("reply_markup")))
            return SimpleNamespace(message_id=len(panels))

        from bot.main import (
            _no_host_day1_defense_outcome_keyboard,
            _no_host_day1_defense_outcome_ui_key,
            send_no_host_day1_defense_pick_panel,
        )

        async def run():
            with patch(
                "bot.observer_delivery.safe_send_message_return", new=capture
            ), patch("bot.main.broadcast_to_alive_players", new=AsyncMock()), patch(
                "bot.main.on_no_host_entered_night1", new=AsyncMock()
            ):
                await send_no_host_day1_defense_pick_panel(AsyncMock(), game)
                await self._press_mirror(game, 100, "d1dt", target)
                await self._press_mirror(game, 100, "d1dt", other)
                await self._press_mirror(game, 100, "d1dc")

        asyncio.run(run())
        self.assertEqual(game.no_host_day1_defense_phase, "outcome")
        entry = game.mirror_prompt_messages[
            _no_host_day1_defense_outcome_ui_key(game, 100)
        ]
        self.assertEqual(entry["text"], build_no_host_day1_defense_outcome_html(game))
        self.assertIn("player", entry)
        self.assertIn("observer", entry)
        labels = [
            button.text
            for row in _no_host_day1_defense_outcome_keyboard(
                game, 100, mirror=True
            ).inline_keyboard
            for button in row
        ]
        self.assertEqual(len([label for label in labels if label.startswith("خروج (")]), 2)
        self.assertIn("خروجی نداشتیم. شب کن", labels)
        self.assertIn(100, [row[0] for row in panels])
        self.assertIn(900, [row[0] for row in panels])
        self.assertNotIn("گادفادر", entry["text"])

    def test_no_exit_starts_night_without_elimination(self) -> None:
        game = self._game()
        citizen = _alive_uid(game, Role.CITIZEN)
        nights: list = []
        notices: list = []

        async def run():
            with self._patches(nights, notices)[0], self._patches(nights, notices)[1], self._patches(nights, notices)[2], self._patches(nights, notices)[3]:
                await self._press_direct(game, 100, "tog", citizen)
                await self._press_direct(game, 100, "confirm")
                done = await self._press_direct(game, 100, "no_exit")
                return done

        done = asyncio.run(run())
        self.assertIn("ثبت شد.", done.answers)
        self.assertTrue(game.players[citizen].is_alive)
        self.assertEqual(game.phase, Phase.NIGHT)
        self.assertIn("mafia", [row[0] for row in nights])

    def test_confirmed_elimination_kills_once_then_starts_night(self) -> None:
        game = self._game(observer=True)
        citizen = _alive_uid(game, Role.CITIZEN)
        nights: list = []
        notices: list = []

        async def run():
            with self._patches(nights, notices)[0], self._patches(nights, notices)[1], self._patches(nights, notices)[2], self._patches(nights, notices)[3]:
                await self._press_mirror(game, 100, "d1dt", citizen)
                await self._press_mirror(game, 100, "d1dc")
                opened = await self._press_mirror(game, 900, "d1el", citizen)
                yes = await self._press_mirror(game, 100, "d1ey")
                again = await self._press_mirror(game, 900, "d1ey")
                return opened, yes, again

        opened, yes, again = asyncio.run(run())
        self.assertIn("تأیید کنید.", opened.answers)
        self.assertIn("حذف ثبت شد.", yes.answers)
        self.assertFalse(game.players[citizen].is_alive)
        self.assertEqual(game.phase, Phase.NIGHT)
        self.assertEqual(len([row for row in nights if row[0] == "mafia"]), 1)
        self.assertIn("پنل دفاعیه فعال نیست.", again.answers)

    def test_town_win_and_mafia_win_do_not_start_night(self) -> None:
        game = self._game()
        godfather = _alive_uid(game, ROLE_GODFATHER)
        terror = _alive_uid(game, ROLE_TERROR)
        game.players[terror].is_alive = False
        nights: list = []
        notices: list = []

        async def eliminate_last_mafia():
            with self._patches(nights, notices)[0], self._patches(nights, notices)[1], self._patches(nights, notices)[2], self._patches(nights, notices)[3]:
                await self._press_direct(game, 100, "tog", godfather)
                await self._press_direct(game, 100, "confirm")
                await self._press_direct(game, 100, "d1el", godfather)
                return await self._press_direct(game, 100, "elim_yes")

        asyncio.run(eliminate_last_mafia())
        self.assertFalse(game.players[godfather].is_alive)
        self.assertEqual(game.phase, Phase.ENDED)
        self.assertEqual(nights, [])
        self.assertEqual(
            [text for _uid, text in notices],
            ["شهروندها برنده شدند."],
        )

        game2 = self._game()
        citizens = [p for p in game2.players.values() if p.role == Role.CITIZEN]
        for extra in citizens[1:]:
            extra.is_alive = False
        victim = citizens[0].user_id
        nights2: list = []
        notices2: list = []

        async def eliminate_for_parity():
            with self._patches(nights2, notices2)[0], self._patches(nights2, notices2)[1], self._patches(nights2, notices2)[2], self._patches(nights2, notices2)[3]:
                await self._press_direct(game2, 100, "tog", victim)
                await self._press_direct(game2, 100, "confirm")
                await self._press_direct(game2, 100, "d1el", victim)
                first = await self._press_direct(game2, 100, "elim_yes")
                second = await self._press_direct(game2, 100, "elim_yes")
                return first, second

        first, second = asyncio.run(eliminate_for_parity())
        self.assertEqual(game2.phase, Phase.ENDED)
        self.assertEqual(nights2, [])
        self.assertEqual([text for _uid, text in notices2], ["مافیا برنده شد."])
        self.assertIn("حذف ثبت شد.", first.answers)
        self.assertTrue(second.answers)

    def test_night_responsibility_fallbacks(self) -> None:
        game = self._game()
        game.players[_alive_uid(game, ROLE_GODFATHER)].is_alive = False
        game.players[_alive_uid(game, Role.DOCTOR)].is_alive = False
        nights: list = []
        notices: list = []

        async def run():
            with self._patches(nights, notices)[0], self._patches(nights, notices)[1], self._patches(nights, notices)[2], self._patches(nights, notices)[3]:
                await self._press_direct(game, 100, "none")

        asyncio.run(run())
        slots = [row[0] for row in nights]
        self.assertEqual(slots, ["mafia", "detective"])
        self.assertEqual(nights[0][1], _alive_uid(game, ROLE_TERROR))

        game9 = self._game(9)
        self.assertFalse(any(p.role == ROLE_TERROR for p in game9.players.values()))
        game9.players[_alive_uid(game9, ROLE_GODFATHER)].is_alive = False
        nights9: list = []
        notices9: list = []

        async def run9():
            with self._patches(nights9, notices9)[0], self._patches(nights9, notices9)[1], self._patches(nights9, notices9)[2], self._patches(nights9, notices9)[3]:
                await self._press_direct(game9, 100, "none")

        asyncio.run(run9())
        holder = mafia_shot_holder(game9)
        mafia_rows = [row for row in nights9 if row[0] == "mafia"]
        self.assertEqual(len(mafia_rows), 1)
        self.assertEqual(mafia_rows[0][1], holder.user_id)
        self.assertEqual(holder.role, ROLE_SIMPLE_MAFIA)
        self.assertIn("doctor", [row[0] for row in nights9])
        self.assertIn("detective", [row[0] for row in nights9])

    def test_observer_receives_night_mirror_for_synthetic_holder(self) -> None:
        from bot.game import is_synthetic_player_uid

        game = self._game(observer=True)
        holder = game.players.pop(_alive_uid(game, ROLE_GODFATHER))
        holder.user_id = SEMI_AUTO_SYNTHETIC_UID_BASE - 4
        game.players[holder.user_id] = holder
        self.assertTrue(is_synthetic_player_uid(holder.user_id))
        sent: list[tuple] = []

        async def capture(bot, uid, text, **kwargs):
            sent.append((uid, text, kwargs.get("reply_markup")))
            return SimpleNamespace(message_id=len(sent) + 1)

        async def run():
            with patch(
                "bot.observer_delivery.safe_send_message_return", new=capture
            ), patch("bot.main.broadcast_to_alive_players", new=AsyncMock()), patch(
                "bot.main.on_no_host_entered_night1", new=AsyncMock()
            ):
                await self._press_mirror(game, 900, "d1dn")

        asyncio.run(run())
        shot = [row for row in sent if "شلیک مافیا" in row[1]]
        self.assertNotIn(holder.user_id, [row[0] for row in shot])
        self.assertIn(900, [row[0] for row in shot])
        obs = next(row for row in shot if row[0] == 900)
        mirrored = PlayerMirrorCb.unpack(obs[2].inline_keyboard[0][0].callback_data)
        self.assertEqual(mirrored.act, "zrm_shot")
        self.assertEqual(mirrored.as_uid, holder.user_id)

    def test_terror_success_closes_defense_and_starts_one_night(self) -> None:
        from bot.russian_mafia_flow import complete_slot

        game = self._game(observer=True)
        terror = _alive_uid(game, ROLE_TERROR)
        citizen = _alive_uid(game, Role.CITIZEN)
        game.russian_mafia_terror_day_active = True
        nights: list = []
        notices: list = []

        async def run():
            with self._patches(nights, notices)[0], self._patches(nights, notices)[1], self._patches(nights, notices)[2], self._patches(nights, notices)[3]:
                result = await complete_slot(
                    AsyncMock(),
                    game,
                    slot="terror",
                    actor_uid=terror,
                    as_uid=terror,
                    target_uid=citizen,
                )
                stale = await self._press_mirror(game, 900, "d1dn")
                return result, stale

        result, stale = asyncio.run(run())
        self.assertEqual(result, "ok")
        self.assertFalse(game.players[terror].is_alive)
        self.assertFalse(game.players[citizen].is_alive)
        self.assertFalse(game.no_host_day1_defense_active)
        self.assertEqual(game.phase, Phase.NIGHT)
        self.assertEqual(len([row for row in nights if row[0] == "mafia"]), 1)
        self.assertIn("پنل دفاعیه فعال نیست.", stale.answers)
        self.assertFalse(any(p.role == ROLE_TERROR for p in self._game(9).players.values()))

    def test_mozakere_no_defense_still_enters_mozakere_night(self) -> None:
        from bot.bazpors_narrator import begin_no_host_day1_defense_pick
        from bot.game_snapshot import delete_game_snapshot
        from bot.main import _no_host_day1_defense_no_votes

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            host_full_name="H",
            bazpors_host_mode="no_host",
        )
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        game.bot_assistant_user_id = 2
        begin_no_host_day1_defense_pick(game)
        moz_night = AsyncMock()
        cb = self._cb(2, "nhd")

        async def run():
            with patch("bot.main.broadcast_to_alive_players", new=AsyncMock()), patch(
                "bot.main.on_no_host_entered_night1", new=moz_night
            ):
                await _no_host_day1_defense_no_votes(cb, AsyncMock(), game, 2, 2)

        asyncio.run(run())
        moz_night.assert_awaited()
        self.assertTrue(game.no_host_assistant_narrator_active)
        self.assertFalse(game.russian_mafia_day_result_applied)



class PostNightContinuationTests(unittest.TestCase):
    """بعد از شب مافیای روسی: اعلان عمومی و پنل روز بعد."""

    def _night_ready(self, n: int = 8, *, observer: bool = False):
        from bot.game_snapshot import delete_game_snapshot

        gm, game = _room(n=n)
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        _deal(gm, game, russian_roles_for_count(n))
        game.bot_assistant_user_id = 100
        game.russian_mafia_day_index = 1
        game.bazpors_narrator_host_day = 1
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        alive = {uid: player.is_alive for uid, player in game.players.items()}
        game.bazpors_alive_at_day_start = dict(alive)
        game.bazpors_alive_at_night_start = dict(alive)
        if observer:
            _obs(game)
        return game

    def _patches(self, public: list, private: list, panels: list, nights: list):
        async def fake_broadcast(bot, game, text, **kwargs):
            public.append(text)

        async def fake_private(bot, uid, text, **kwargs):
            private.append((uid, text))
            return True

        async def fake_panel(bot, uid, text, **kwargs):
            panels.append((uid, text, kwargs.get("reply_markup")))
            return SimpleNamespace(message_id=len(panels) + 10)

        async def fake_pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            nights.append((slot, player_uid, act))

        return (
            patch("bot.observer_delivery.broadcast_to_alive_players", new=fake_broadcast),
            patch("bot.russian_mafia_flow.safe_send_message", new=fake_private),
            patch("bot.observer_delivery.safe_send_message_return", new=fake_panel),
            patch("bot.russian_mafia_flow._send_pair", new=fake_pair),
            patch("bot.main.on_no_host_entered_night1", new=AsyncMock()),
        )

    async def _act(self, game, slot: str, actor: int, as_uid: int, target: int):
        from bot.russian_mafia_flow import complete_slot

        return await complete_slot(
            AsyncMock(),
            game,
            slot=slot,
            actor_uid=actor,
            as_uid=as_uid,
            target_uid=target,
        )

    async def _resolve(
        self,
        game,
        *,
        shot: int,
        save: int,
        investigate: int,
        public: list,
        private: list,
        panels: list,
        nights: list,
    ):
        holder = mafia_shot_holder(game).user_id
        doctor = _alive_uid(game, Role.DOCTOR)
        detective = _alive_uid(game, Role.DETECTIVE)
        patches = self._patches(public, private, panels, nights)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            await _ack_required_waiting(game)
            await self._act(game, "mafia", holder, holder, shot)
            await self._act(game, "doctor", doctor, doctor, save)
            if not game.russian_mafia_doctor_confirmed:
                second = next(
                    p.user_id
                    for p in game.players.values()
                    if p.is_alive
                    and p.user_id not in (doctor, save)
                    and p.user_id not in (game.russian_mafia_doctor_targets or [])
                    and p.role != Role.OBSERVER
                )
                await self._act(game, "doctor", doctor, doctor, second)
            result = await self._act(game, "detective", detective, detective, investigate)
            await _accept_russian_post_night(game)
            return result

    def test_successful_shot_announces_and_opens_day_two(self) -> None:
        game = self._night_ready(observer=True)
        victim = next(
            p.user_id
            for p in game.players.values()
            if p.role == Role.CITIZEN and p.user_id != 100
        )
        other = next(
            p.user_id
            for p in game.players.values()
            if p.role == Role.CITIZEN and p.user_id not in (victim, 100)
        )
        public: list = []
        private: list = []
        panels: list = []
        nights: list = []
        asyncio.run(
            self._resolve(
                game,
                shot=victim,
                save=other,
                investigate=_alive_uid(game, ROLE_GODFATHER),
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        self.assertFalse(game.players[victim].is_alive)
        self.assertEqual(game.phase, Phase.DAY_DISCUSSION)
        self.assertEqual(game.russian_mafia_day_index, 2)
        self.assertEqual(game.bazpors_narrator_host_day, 2)
        joined = "\n".join(public)
        self.assertIn("در شبی که گذشت، با", joined)
        self.assertIn(game.players[victim].full_name, joined)
        self.assertNotIn("مثبت", joined)
        self.assertNotIn("منفی", joined)
        self.assertNotIn("استعلام", joined)
        day_panels = [row for row in panels if "روز شروع شد" in row[1]]
        self.assertIn(100, [row[0] for row in day_panels])
        self.assertIn(900, [row[0] for row in day_panels])
        self.assertNotIn(1, [row[0] for row in day_panels])
        self.assertIn("terror", [row[0] for row in nights])
        self.assertTrue(game.russian_mafia_terror_day_active)
        self.assertTrue(game.no_host_day1_defense_active)

    def test_doctor_save_announces_no_death_and_opens_next_day(self) -> None:
        game = self._night_ready(observer=True)
        citizen = next(p.user_id for p in game.players.values() if p.role == Role.CITIZEN)
        public: list = []
        private: list = []
        panels: list = []
        nights: list = []
        asyncio.run(
            self._resolve(
                game,
                shot=citizen,
                save=citizen,
                investigate=_alive_uid(game, Role.DOCTOR),
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        self.assertTrue(game.players[citizen].is_alive)
        joined = "\n".join(public)
        self.assertIn("در شبی که گذشت با کسی خداحافظی نکردیم.", joined)
        self.assertNotIn("نجات", joined)
        self.assertEqual(game.russian_mafia_day_index, 2)
        self.assertTrue(any(row[0] == 100 and "روز شروع شد" in row[1] for row in panels))
        self.assertTrue(any(row[0] == 900 and "روز شروع شد" in row[1] for row in panels))
        self.assertIn("روز دوم آغاز شد", joined)

    def test_detective_result_stays_private(self) -> None:
        game = self._night_ready()
        detective = _alive_uid(game, Role.DETECTIVE)
        citizen = _alive_uid(game, Role.CITIZEN)
        public: list = []
        private: list = []
        panels: list = []
        nights: list = []
        asyncio.run(
            self._resolve(
                game,
                shot=citizen,
                save=_alive_uid(game, Role.DOCTOR),
                investigate=_alive_uid(game, ROLE_GODFATHER),
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        self.assertTrue(any(uid == detective and "نتیجهٔ استعلام" in text for uid, text in private))
        self.assertNotIn("نتیجهٔ استعلام", "\n".join(public))
        self.assertTrue(all("گادفادر" not in text for text in public))

    def test_night_win_does_not_open_next_day(self) -> None:
        game = self._night_ready()
        game.players[_alive_uid(game, ROLE_TERROR)].is_alive = False
        game.bazpors_alive_at_night_start = {
            uid: player.is_alive for uid, player in game.players.items()
        }
        godfather = _alive_uid(game, ROLE_GODFATHER)
        public: list = []
        private: list = []
        panels: list = []
        nights: list = []
        asyncio.run(
            self._resolve(
                game,
                shot=godfather,
                save=_alive_uid(game, Role.CITIZEN),
                investigate=_alive_uid(game, Role.DOCTOR),
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        self.assertEqual(game.phase, Phase.ENDED)
        self.assertEqual(
            [text for _uid, text in private if "برنده" in text],
            ["شهروندها برنده شدند."],
        )
        self.assertFalse(any("روز شروع شد" in row[1] for row in panels))
        self.assertEqual(nights, [])

        from bot.russian_mafia_flow import continue_russian_mafia_after_night

        async def again():
            with self._patches(public, private, panels, nights)[1]:
                await continue_russian_mafia_after_night(AsyncMock(), game)

        asyncio.run(again())
        self.assertEqual([text for _uid, text in private if "برنده" in text], ["شهروندها برنده شدند."])

        game2 = self._night_ready()
        citizens = [p for p in game2.players.values() if p.role == Role.CITIZEN]
        for extra in citizens[1:]:
            extra.is_alive = False
        victim = citizens[0].user_id
        game2.bazpors_alive_at_night_start = {
            uid: player.is_alive for uid, player in game2.players.items()
        }
        public2: list = []
        private2: list = []
        panels2: list = []
        nights2: list = []
        asyncio.run(
            self._resolve(
                game2,
                shot=victim,
                save=_alive_uid(game2, Role.DOCTOR),
                investigate=_alive_uid(game2, Role.DETECTIVE),
                public=public2,
                private=private2,
                panels=panels2,
                nights=nights2,
            )
        )
        self.assertEqual(game2.phase, Phase.ENDED)
        self.assertEqual([text for _uid, text in private2 if "برنده" in text], ["مافیا برنده شد."])
        self.assertFalse(any("روز شروع شد" in row[1] for row in panels2))

    def test_day_two_none_then_night_two_opens_day_three(self) -> None:
        game = self._night_ready()
        citizen = _alive_uid(game, Role.CITIZEN)
        doctor = _alive_uid(game, Role.DOCTOR)
        public: list = []
        private: list = []
        panels: list = []
        nights: list = []
        asyncio.run(
            self._resolve(
                game,
                shot=citizen,
                save=citizen,
                investigate=doctor,
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        self.assertEqual(game.russian_mafia_day_index, 2)
        self.assertEqual(game.russian_mafia_night_index, 1)
        terror_day2 = [row for row in nights if row[0] == "terror"]
        self.assertEqual(len(terror_day2), 1)

        from bot.main import _no_host_day1_defense_no_votes

        class CB:
            def __init__(self):
                self.from_user = SimpleNamespace(id=100)
                self.message = SimpleNamespace(
                    message_id=3,
                    html_text="day",
                    text="day",
                    edit_text=AsyncMock(),
                )
                self.answers: list[str] = []

            async def answer(self, text="", show_alert=False):
                self.answers.append(text)

        async def skip_day():
            with patch("bot.main.broadcast_to_alive_players", new=AsyncMock()), patch(
                "bot.russian_mafia_flow._send_pair", new=AsyncMock()
            ), patch("bot.main.on_no_host_entered_night1", new=AsyncMock()):
                await _no_host_day1_defense_no_votes(CB(), AsyncMock(), game, 100, 100)

        asyncio.run(skip_day())
        self.assertEqual(game.phase, Phase.NIGHT)
        self.assertEqual(game.russian_mafia_night_index, 2)
        game.russian_mafia_mafia_confirmed = False
        game.russian_mafia_doctor_confirmed = False
        game.russian_mafia_detective_confirmed = False
        game.mirror_action_claims.clear()
        public.clear()
        panels.clear()
        nights.clear()
        asyncio.run(
            self._resolve(
                game,
                shot=doctor,
                save=_alive_uid(game, Role.CITIZEN),
                investigate=_alive_uid(game, ROLE_GODFATHER),
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        self.assertEqual(game.russian_mafia_night_index, 2)
        self.assertEqual(game.russian_mafia_day_index, 3)
        self.assertEqual(game.bazpors_narrator_host_day, 3)
        self.assertIn("روز سوم آغاز شد", "\n".join(public))
        self.assertTrue(any("روز شروع شد" in row[1] for row in panels))
        self.assertTrue(any(row[0] == "terror" for row in nights))
        holder = mafia_shot_holder(game).user_id
        detective = next(p.user_id for p in game.players.values() if p.role == Role.DETECTIVE)
        doctor_uid = next(p.user_id for p in game.players.values() if p.role == Role.DOCTOR)
        citizen = _alive_uid(game, Role.CITIZEN)
        self.assertEqual(
            try_confirm_action(
                game, slot="mafia", actor_uid=holder, as_uid=holder, target_uid=citizen
            ),
            "stale",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor_uid,
                as_uid=doctor_uid,
                target_uid=citizen,
            ),
            "stale",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="detective",
                actor_uid=detective,
                as_uid=detective,
                target_uid=citizen,
            ),
            "stale",
        )

    def test_dead_terror_and_nine_player_have_no_terror_panel(self) -> None:
        game = self._night_ready()
        game.players[_alive_uid(game, ROLE_TERROR)].is_alive = False
        game.bazpors_alive_at_night_start = {
            uid: player.is_alive for uid, player in game.players.items()
        }
        citizen = _alive_uid(game, Role.CITIZEN)
        public: list = []
        private: list = []
        panels: list = []
        nights: list = []
        asyncio.run(
            self._resolve(
                game,
                shot=citizen,
                save=citizen,
                investigate=_alive_uid(game, Role.DOCTOR),
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        self.assertNotIn("terror", [row[0] for row in nights])
        self.assertFalse(game.russian_mafia_terror_day_active)

        game9 = self._night_ready(9)
        self.assertFalse(any(p.role == ROLE_TERROR for p in game9.players.values()))
        public9: list = []
        nights9: list = []
        asyncio.run(
            self._resolve(
                game9,
                shot=_alive_uid(game9, Role.CITIZEN),
                save=_alive_uid(game9, Role.CITIZEN),
                investigate=_alive_uid(game9, Role.DOCTOR),
                public=public9,
                private=[],
                panels=[],
                nights=nights9,
            )
        )
        self.assertNotIn("terror", [row[0] for row in nights9])
        self.assertEqual(game9.russian_mafia_day_index, 2)

    def test_observer_day_panel_first_claim_starts_one_night(self) -> None:
        game = self._night_ready(observer=True)
        citizen = _alive_uid(game, Role.CITIZEN)
        public: list = []
        private: list = []
        panels: list = []
        nights: list = []
        asyncio.run(
            self._resolve(
                game,
                shot=citizen,
                save=citizen,
                investigate=_alive_uid(game, Role.DOCTOR),
                public=public,
                private=private,
                panels=panels,
                nights=nights,
            )
        )
        from bot.handlers.no_host_player import player_mirror_cb

        def cb(uid: int):
            data = PlayerMirrorCb(
                code=game.room_code, act="d1dn", as_uid=100, tid=0
            ).pack()

            class CB:
                def __init__(self):
                    self.from_user = SimpleNamespace(id=uid)
                    self.data = data
                    self.message = SimpleNamespace(
                        message_id=8,
                        html_text="day",
                        text="day",
                        edit_text=AsyncMock(),
                    )
                    self.answers: list[str] = []

                async def answer(self, text="", show_alert=False):
                    self.answers.append(text)

            return CB()

        obs = cb(900)
        helper = cb(100)

        async def press():
            with patch("bot.handlers.no_host_player.manager.get_game", return_value=game), patch(
                "bot.main.broadcast_to_alive_players", new=AsyncMock()
            ), patch("bot.russian_mafia_flow._send_pair", new=AsyncMock()), patch(
                "bot.main.on_no_host_entered_night1", new=AsyncMock()
            ):
                await player_mirror_cb(obs, AsyncMock())
                await player_mirror_cb(helper, AsyncMock())

        asyncio.run(press())
        self.assertIn("ثبت شد.", obs.answers)
        self.assertIn("پنل دفاعیه فعال نیست.", helper.answers)
        self.assertEqual(game.russian_mafia_night_index, 2)
        self.assertEqual(game.phase, Phase.NIGHT)


class MultiNightClaimTests(unittest.TestCase):
    def _prepared(self, n: int = 8, *, real: int | None = None):
        from bot.game_snapshot import delete_game_snapshot

        gm, game = _room(n=n, real=real)
        self.addCleanup(lambda: delete_game_snapshot(game.room_code))
        _obs(game)
        _deal(gm, game, russian_roles_for_count(n))
        game.bot_assistant_user_id = 100
        game.russian_mafia_doctor_self_save_count = 0
        return game

    def _arm(self, game, night: int) -> None:
        from bot.russian_mafia import reset_russian_night_actions

        reset_russian_night_actions(game)
        game.russian_mafia_night_index = night
        game.phase = Phase.NIGHT

    def _confirm(self, game, slot: str, actor: int, as_uid: int, target: int, generation: int):
        return try_confirm_action(
            game,
            slot=slot,
            actor_uid=actor,
            as_uid=as_uid,
            target_uid=target,
            generation=generation,
        )

    def test_observer_confirms_each_slot_on_three_nights(self) -> None:
        game = self._prepared(real=0)
        observer = game.observer_user_id
        holder = mafia_shot_holder(game).user_id
        doctor = _alive_uid(game, Role.DOCTOR)
        detective = _alive_uid(game, Role.DETECTIVE)
        citizen = _alive_uid(game, Role.CITIZEN)
        self.assertTrue(all(uid < 0 for uid in (holder, doctor, detective)))
        for night in (1, 2, 3):
            self._arm(game, night)
            if night > 1:
                for slot, as_uid in (
                    ("mafia", holder),
                    ("doctor", doctor),
                    ("detective", detective),
                ):
                    self.assertEqual(
                        self._confirm(game, slot, observer, as_uid, citizen, night - 1),
                        "stale",
                    )
                    self.assertFalse(
                        {
                            "mafia": game.russian_mafia_mafia_confirmed,
                            "doctor": game.russian_mafia_doctor_confirmed,
                            "detective": game.russian_mafia_detective_confirmed,
                        }[slot]
                    )
            self.assertEqual(self._confirm(game, "mafia", observer, holder, citizen, night), "ok")
            self.assertEqual(self._confirm(game, "doctor", observer, doctor, citizen, night), "ok")
            self.assertEqual(
                self._confirm(game, "detective", observer, detective, holder, night),
                "ok",
            )
            self.assertEqual(
                self._confirm(game, "mafia", observer, holder, doctor, night),
                "stale",
            )
            self.assertEqual(game.russian_mafia_mafia_target, citizen)

    def test_real_holder_and_observer_alternate_first_claim(self) -> None:
        game = self._prepared()
        holder = mafia_shot_holder(game).user_id
        citizen = _alive_uid(game, Role.CITIZEN)
        other = next(
            p.user_id
            for p in game.players.values()
            if p.is_alive and p.user_id not in (holder, citizen)
        )
        self._arm(game, 1)
        self.assertEqual(self._confirm(game, "mafia", holder, holder, citizen, 1), "ok")
        self.assertEqual(
            self._confirm(game, "mafia", game.observer_user_id, holder, other, 1),
            "stale",
        )
        self.assertEqual(game.russian_mafia_mafia_target, citizen)
        self._arm(game, 2)
        self.assertEqual(
            self._confirm(game, "mafia", game.observer_user_id, holder, other, 2),
            "ok",
        )
        self.assertEqual(self._confirm(game, "mafia", holder, holder, citizen, 2), "stale")
        self.assertEqual(game.russian_mafia_mafia_target, other)

    def test_old_callbacks_rejected_while_current_night_unclaimed(self) -> None:
        from bot.russian_mafia_flow import dispatch_russian_mafia_mirror, parse_player_action

        game = self._prepared()
        holder = mafia_shot_holder(game).user_id
        citizen = _alive_uid(game, Role.CITIZEN)
        self._arm(game, 2)
        game.mirror_action_claims.clear()
        old_player = parse_player_action(f"rmf:{game.room_code}:zrm_shot:{holder}:{citizen}")
        self.assertIsNotNone(old_player)
        self.assertIsNone(old_player[4])
        current = parse_player_action(
            f"rmf:{game.room_code}:zrm_shot:{holder}:{citizen}:2"
        )
        self.assertEqual(current[4], 2)

        async def run():
            old = await complete_slot(
                AsyncMock(),
                game,
                slot="mafia",
                actor_uid=holder,
                as_uid=holder,
                target_uid=citizen,
                generation=old_player[4],
            )
            mirror = await dispatch_russian_mafia_mirror(
                SimpleNamespace(answer=AsyncMock()),
                AsyncMock(),
                game,
                as_uid=holder,
                actor_uid=game.observer_user_id,
                act="zrm_shot",
                tid=citizen,
                generation=None,
            )
            return old, mirror

        old, mirror = asyncio.run(run())
        self.assertEqual(old, "stale")
        self.assertTrue(mirror)
        self.assertFalse(game.russian_mafia_mafia_confirmed)
        self.assertIsNone(game.russian_mafia_mafia_target)
        self.assertEqual(self._confirm(game, "mafia", holder, holder, citizen, 2), "ok")

    def test_doctor_self_save_count_survives_night_reset(self) -> None:
        game = self._prepared()
        doctor = _alive_uid(game, Role.DOCTOR)
        citizen = _alive_uid(game, Role.CITIZEN)
        self._arm(game, 1)
        self.assertEqual(self._confirm(game, "doctor", doctor, doctor, doctor, 1), "ok")
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
        self._arm(game, 2)
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
        self.assertEqual(self._confirm(game, "doctor", doctor, doctor, doctor, 2), "rejected")
        self.assertEqual(self._confirm(game, "doctor", doctor, doctor, citizen, 2), "ok")
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
        self.assertEqual(russian_doctor_self_save_limit(game), 1)

    def test_dead_detective_does_not_block_later_night(self) -> None:
        game = self._prepared(n=9)
        detective = _alive_uid(game, Role.DETECTIVE)
        game.players[detective].is_alive = False
        holder = mafia_shot_holder(game).user_id
        citizen = _alive_uid(game, Role.CITIZEN)
        game.mirror_action_claims[f"russian:{game.room_code}:detective"] = game.observer_user_id
        game.mirror_action_claims[f"russian:{game.room_code}:night:1:detective"] = (
            game.observer_user_id
        )
        self._arm(game, 2)
        self.assertNotIn("detective", required_night_slots(game))
        self.assertEqual(self._confirm(game, "mafia", holder, holder, citizen, 1), "stale")
        self.assertEqual(self._confirm(game, "mafia", holder, holder, citizen, 2), "ok")

    def test_godfather_death_transfers_shot_for_current_night_only(self) -> None:
        game = self._prepared()
        godfather = _alive_uid(game, ROLE_GODFATHER)
        game.players[godfather].is_alive = False
        holder = mafia_shot_holder(game)
        self.assertEqual(holder.role, ROLE_TERROR)
        citizen = _alive_uid(game, Role.CITIZEN)
        self._arm(game, 2)
        self.assertEqual(
            self._confirm(game, "mafia", holder.user_id, godfather, citizen, 2),
            "forbidden",
        )
        self.assertEqual(
            self._confirm(game, "mafia", holder.user_id, holder.user_id, citizen, 2),
            "ok",
        )

    def test_terror_callbacks_are_scoped_to_the_day(self) -> None:
        from bot.russian_mafia import reset_russian_day_actions

        game = self._prepared()
        terror = _alive_uid(game, ROLE_TERROR)
        citizen = _alive_uid(game, Role.CITIZEN)
        other = next(
            p.user_id
            for p in game.players.values()
            if p.is_alive and p.user_id not in (terror, citizen)
        )
        game.phase = Phase.DAY_DISCUSSION
        game.russian_mafia_day_index = 1
        game.russian_mafia_terror_day_active = True
        kb = action_keyboard(game, act="zrm_ter", as_uid=terror, exclude=terror, mirror=True)
        self.assertEqual(PlayerMirrorCb.unpack(kb.inline_keyboard[0][0].callback_data).rid, "1")
        self.assertEqual(self._confirm(game, "terror", terror, terror, citizen, 1), "ok")
        reset_russian_day_actions(game)
        game.russian_mafia_terror_day_active = True
        game.russian_mafia_day_index = 2
        self.assertEqual(self._confirm(game, "terror", terror, terror, citizen, 1), "stale")
        self.assertFalse(game.russian_mafia_terror_confirmed)
        self.assertEqual(self._confirm(game, "terror", game.observer_user_id, terror, other, 2), "ok")

        fresh = self._prepared()
        terror = _alive_uid(fresh, ROLE_TERROR)
        citizen = _alive_uid(fresh, Role.CITIZEN)
        fresh.phase = Phase.DAY_DISCUSSION
        fresh.russian_mafia_day_index = 2
        fresh.russian_mafia_terror_day_active = True

        async def run():
            return await complete_slot(
                AsyncMock(),
                fresh,
                slot="terror",
                actor_uid=terror,
                as_uid=terror,
                target_uid=citizen,
                generation=2,
            )

        self.assertEqual(asyncio.run(run()), "ok")
        self.assertFalse(fresh.players[terror].is_alive)
        self.assertFalse(fresh.players[citizen].is_alive)

    def test_nine_player_close_does_not_invent_terror_panel(self) -> None:
        from bot.russian_mafia_flow import _close_slot

        game = self._prepared(n=9)
        game.phase = Phase.DAY_DISCUSSION
        game.russian_mafia_day_index = 2
        bot = AsyncMock()

        async def run():
            await _close_slot(bot, game, "terror")

        asyncio.run(run())
        bot.edit_message_text.assert_not_called()
        bot.send_message.assert_not_called()
        self.assertFalse(any("terror" in key for key in game.mirror_prompt_messages))

    def test_close_edits_existing_panel_only(self) -> None:
        from bot.russian_mafia_flow import _close_slot

        game = self._prepared(n=9)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 2
        key = f"russian:{game.room_code}:night:2:doctor:obs"
        game.mirror_prompt_messages[key] = {"text": "open", "observer": (900, 44)}
        bot = AsyncMock()

        async def run():
            await _close_slot(bot, game, "doctor")

        asyncio.run(run())
        bot.edit_message_text.assert_awaited()
        bot.send_message.assert_not_called()
        self.assertEqual(game.mirror_prompt_messages[key]["text"], "این اقدام بسته شد.")

    def test_reissue_current_night_panels_is_idempotent(self) -> None:
        from bot.russian_mafia_flow import reissue_open_russian_action_panels

        game = self._prepared(n=9, real=0)
        detective = _alive_uid(game, Role.DETECTIVE)
        game.players[detective].is_alive = False
        holder = mafia_shot_holder(game).user_id
        doctor = _alive_uid(game, Role.DOCTOR)
        self.assertTrue(holder < 0 and doctor < 0)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 2
        game.russian_mafia_day_index = 2
        game.russian_mafia_night_result_sent_index = 1
        game.russian_mafia_doctor_self_save_count = 0
        game.mirror_action_claims[f"russian:{game.room_code}:mafia"] = game.observer_user_id
        game.mirror_action_claims[f"russian:{game.room_code}:doctor"] = game.observer_user_id
        game.mirror_prompt_messages[f"russian:{game.room_code}:mafia:obs"] = {
            "text": "old",
            "observer": (900, 58),
        }
        game.mirror_prompt_messages[f"russian:{game.room_code}:doctor:obs"] = {
            "text": "old",
            "observer": (900, 59),
        }
        alive_before = {uid: p.is_alive for uid, p in game.players.items()}
        sent: list[tuple] = []

        async def capture(bot, uid, text, **kwargs):
            sent.append((uid, text, kwargs.get("reply_markup")))
            return SimpleNamespace(message_id=1000 + len(sent))

        async def run():
            with patch("bot.observer_delivery.safe_send_message_return", new=capture), patch(
                "bot.game_snapshot.persist_game_snapshot", new=lambda *a, **k: None
            ):
                first = await reissue_open_russian_action_panels(AsyncMock(), game)
                count = len(sent)
                second = await reissue_open_russian_action_panels(AsyncMock(), game)
                return first, second, count

        first, second, count = asyncio.run(run())
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(sent), count)
        self.assertEqual(game.russian_mafia_night_index, 2)
        self.assertEqual(game.russian_mafia_day_index, 2)
        self.assertEqual(game.russian_mafia_night_result_sent_index, 1)
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 0)
        self.assertFalse(game.russian_mafia_mafia_confirmed)
        self.assertFalse(game.russian_mafia_doctor_confirmed)
        self.assertEqual(alive_before, {uid: p.is_alive for uid, p in game.players.items()})
        self.assertTrue(all(row[0] == 900 for row in sent))
        self.assertFalse(any("کارآگاه" in row[1] for row in sent))
        self.assertFalse(any("ترور" in row[1] for row in sent))
        rids = {
            PlayerMirrorCb.unpack(row[2].inline_keyboard[0][0].callback_data).rid
            for row in sent
        }
        self.assertEqual(rids, {"2"})
        citizen = _alive_uid(game, Role.CITIZEN)
        self.assertEqual(self._confirm(game, "mafia", game.observer_user_id, holder, citizen, 1), "stale")
        self.assertFalse(game.russian_mafia_mafia_confirmed)

    def test_night_resolution_opens_later_days_once(self) -> None:
        from bot.russian_mafia_flow import continue_russian_mafia_after_night

        game = self._prepared()
        game.russian_mafia_day_index = 1
        game.bazpors_narrator_host_day = 1
        game.bazpors_alive_at_day_start = {uid: True for uid in game.players}
        holder = mafia_shot_holder(game).user_id
        doctor = _alive_uid(game, Role.DOCTOR)
        detective = _alive_uid(game, Role.DETECTIVE)
        citizen = _alive_uid(game, Role.CITIZEN)
        public: list[str] = []
        defense = AsyncMock()

        async def broadcast(bot, game, text, **kwargs):
            public.append(text)

        async def resolve(night_target: int):
            game.bazpors_alive_at_night_start = {
                uid: p.is_alive for uid, p in game.players.items()
            }
            await _ack_required_waiting(game)
            await complete_slot(
                AsyncMock(), game, slot="mafia", actor_uid=holder, as_uid=holder,
                target_uid=night_target, generation=game.russian_mafia_night_index,
            )
            await complete_slot(
                AsyncMock(), game, slot="doctor", actor_uid=doctor, as_uid=doctor,
                target_uid=holder, generation=game.russian_mafia_night_index,
            )
            living = next(
                p.user_id
                for p in game.players.values()
                if p.is_alive and p.role == Role.CITIZEN and p.user_id != night_target
            )
            await complete_slot(
                AsyncMock(), game, slot="detective", actor_uid=detective, as_uid=detective,
                target_uid=living, generation=game.russian_mafia_night_index,
            )
            await _accept_russian_post_night(game)

        async def run():
            with patch("bot.observer_delivery.broadcast_to_alive_players", new=broadcast), patch(
                "bot.observer_delivery.safe_send_message_return", new=AsyncMock(return_value=SimpleNamespace(message_id=1))
            ), patch("bot.russian_mafia_flow.safe_send_message", new=AsyncMock()), patch(
                "bot.main.send_no_host_day1_defense_pick_panel", new=defense
            ), patch("bot.game_snapshot.persist_game_snapshot", new=lambda *a, **k: None):
                await open_night(AsyncMock(), game)
                self.assertEqual(game.russian_mafia_night_index, 1)
                await resolve(citizen)
                self.assertEqual(game.russian_mafia_day_index, 2)
                self.assertEqual(defense.await_count, 1)
                await open_night(AsyncMock(), game)
                self.assertEqual(
                    self._confirm(game, "mafia", game.observer_user_id, holder, doctor, 1),
                    "stale",
                )
                await resolve(doctor)
                self.assertEqual(game.russian_mafia_day_index, 3)
                self.assertEqual(defense.await_count, 2)
                before = len(public)
                await continue_russian_mafia_after_night(AsyncMock(), game)
                self.assertEqual(len(public), before)
                await open_night(AsyncMock(), game)
                self.assertEqual(game.russian_mafia_night_index, 3)
                self.assertEqual(
                    self._confirm(game, "detective", game.observer_user_id, detective, holder, 3),
                    "ok",
                )

        asyncio.run(run())
        results = [text for text in public if "نتیجه نهایی شب" in text]
        self.assertEqual(len(results), 2)
        self.assertTrue(any("خداحافظی" in text for text in results))
        self.assertIn("روز دوم آغاز شد", "\n".join(public))
        self.assertIn("روز سوم آغاز شد", "\n".join(public))


class RussianDoctorCapacityUiTests(unittest.TestCase):
    def _prepared(self, n: int = 8):
        gm, game = _room(n=n)
        _obs(game)
        _deal(gm, game, russian_roles_for_count(n))
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        return game

    def test_panel_matches_mozakere_conventions(self) -> None:
        game = self._prepared(n=8)
        html = build_russian_doctor_pick_html(game)
        self.assertIn("ثبت انتخاب پزشک", html)
        self.assertIn("شب اول", html)
        self.assertIn("یک نفر", html)
        self.assertIn("۰ از ۱", html)
        self.assertIn("تا ۱ نجات", html)
        self.assertIn("پس از پایان فاز امشب", html)

    def test_self_heal_counter_starts_zero_of_one(self) -> None:
        game = self._prepared(n=9)
        html = build_russian_doctor_pick_html(game)
        self.assertIn("۰ از ۱", html)
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 0)

    def test_self_heal_counter_after_confirm(self) -> None:
        game = self._prepared(n=8)
        doctor = _alive_uid(game, Role.DOCTOR)
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=doctor
            ),
            "ok",
        )
        html = build_russian_doctor_pick_html(game)
        self.assertIn("۱ از ۱", html)

    def test_nine_alive_allows_two_distinct(self) -> None:
        game = self._prepared(n=9)
        self.assertEqual(russian_alive_player_count(game), 9)
        self.assertEqual(russian_doctor_heal_capacity(game), 2)
        doctor = _alive_uid(game, Role.DOCTOR)
        a, b = [p.user_id for p in game.players.values() if p.role == Role.CITIZEN][:2]
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=a
            ),
            "ok",
        )
        self.assertFalse(game.russian_mafia_doctor_confirmed)
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=a
            ),
            "rejected",
        )
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=b
            ),
            "ok",
        )
        self.assertTrue(game.russian_mafia_doctor_confirmed)
        self.assertEqual(game.russian_mafia_doctor_targets, [a, b])

    def test_eight_alive_allows_only_one(self) -> None:
        game = self._prepared(n=8)
        self.assertEqual(russian_doctor_heal_capacity(game), 1)
        doctor = _alive_uid(game, Role.DOCTOR)
        a, b = [p.user_id for p in game.players.values() if p.role == Role.CITIZEN][:2]
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=a
            ),
            "ok",
        )
        self.assertTrue(game.russian_mafia_doctor_confirmed)
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=b
            ),
            "stale",
        )

    def test_fewer_than_eight_allows_only_one(self) -> None:
        game = self._prepared(n=9)
        # kill one → 8 alive still capacity 1? User: exactly 9 → 2, 8 or fewer → 1
        dead = _alive_uid(game, Role.CITIZEN)
        game.players[dead].is_alive = False
        self.assertEqual(russian_alive_player_count(game), 8)
        self.assertEqual(russian_doctor_heal_capacity(game), 1)
        game.players[dead].is_alive = True
        # kill two → 7 alive
        cits = [p for p in game.players.values() if p.role == Role.CITIZEN]
        cits[0].is_alive = False
        cits[1].is_alive = False
        self.assertEqual(russian_alive_player_count(game), 7)
        self.assertEqual(russian_doctor_heal_capacity(game), 1)

    def test_more_than_nine_preserves_single_heal(self) -> None:
        game = self._prepared(n=9)
        # inject a 10th alive seat beyond normal roster
        game.players[99999] = Player(
            user_id=99999, full_name="Extra", username=None, role=Role.CITIZEN, is_alive=True
        )
        self.assertEqual(russian_alive_player_count(game), 10)
        self.assertEqual(russian_doctor_heal_capacity(game), 1)

    def test_eliminated_excluded_from_alive_count(self) -> None:
        game = self._prepared(n=9)
        game.players[_alive_uid(game, Role.CITIZEN)].is_alive = False
        self.assertEqual(russian_alive_player_count(game), 8)
        self.assertEqual(russian_doctor_heal_capacity(game), 1)

    def test_observer_excluded_from_alive_count(self) -> None:
        game = self._prepared(n=9)
        game.players[game.observer_user_id] = Player(
            user_id=game.observer_user_id,
            full_name="Obs",
            username=None,
            role=Role.OBSERVER,
            is_alive=True,
        )
        self.assertEqual(russian_alive_player_count(game), 9)
        self.assertEqual(russian_doctor_heal_capacity(game), 2)

    def test_synthetic_seats_counted(self) -> None:
        gm, game = _room(n=9, real=1)
        _obs(game)
        _deal(gm, game, russian_roles_for_count(9))
        game.phase = Phase.NIGHT
        self.assertEqual(russian_alive_player_count(game), 9)
        self.assertEqual(russian_doctor_heal_capacity(game), 2)
        self.assertTrue(any(uid < 0 for uid in game.players))

    def test_dual_targets_both_save_shot(self) -> None:
        from bot.russian_mafia import apply_night_resolution

        game = self._prepared(n=9)
        doctor = _alive_uid(game, Role.DOCTOR)
        a, b = [p.user_id for p in game.players.values() if p.role == Role.CITIZEN][:2]
        game.russian_mafia_mafia_target = b
        game.russian_mafia_mafia_confirmed = True
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=a
            ),
            "ok",
        )
        self.assertEqual(
            try_confirm_action(
                game, slot="doctor", actor_uid=doctor, as_uid=doctor, target_uid=b
            ),
            "ok",
        )
        apply_night_resolution(game)
        self.assertTrue(game.players[b].is_alive)

    def test_stale_self_heal_callback_rejected(self) -> None:
        game = self._prepared(n=8)
        doctor = _alive_uid(game, Role.DOCTOR)
        citizen = _alive_uid(game, Role.CITIZEN)
        game.russian_mafia_night_index = 1
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=doctor,
                generation=1,
            ),
            "ok",
        )
        game.russian_mafia_doctor_confirmed = False
        game.russian_mafia_doctor_target = None
        game.russian_mafia_doctor_targets = []
        game.russian_mafia_doctor_night_capacity = 0
        game.mirror_action_claims.clear()
        game.russian_mafia_night_index = 2
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=doctor,
                generation=1,
            ),
            "stale",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=doctor,
                generation=2,
            ),
            "rejected",
        )
        self.assertEqual(
            try_confirm_action(
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=citizen,
                generation=2,
            ),
            "ok",
        )

    def test_capacity_set_at_panel_emit(self) -> None:
        game = self._prepared(n=9)
        sent = []

        async def fake_send(
            bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None
        ):
            sent.append((slot, text, game.russian_mafia_doctor_night_capacity))

        async def run():
            with patch("bot.russian_mafia_flow._send_pair", new=fake_send):
                await open_night(AsyncMock(), game)

        asyncio.run(run())
        doc_rows = [r for r in sent if r[0] == "doctor"]
        self.assertEqual(len(doc_rows), 1)
        self.assertEqual(doc_rows[0][2], 2)
        self.assertIn("تا ۲ نجات", doc_rows[0][1])
        self.assertIn("۰ از ۱", doc_rows[0][1])
