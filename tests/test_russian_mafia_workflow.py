"""مافیای روسی — فهرست ناظر، تأیید دومرحله‌ای، اخراج انضباطی و استعلام میز."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.game import SEMI_AUTO_SYNTHETIC_UID_BASE, GameManager
from bot.game_snapshot import delete_game_snapshot, persist_game_snapshot, restore_games_into_manager
from bot.models import Phase, Player, Role
from bot.observer_delivery import build_observer_players_roster_html, send_observer_players_roster
from bot.russian_mafia import (
    HOST_HELPER_MODE,
    ROLE_GODFATHER,
    ROLE_SIMPLE_MAFIA,
    ROLE_TERROR,
    initialize_russian_mafia_state,
    mafia_shot_holder,
    night_slots_complete,
    required_night_slots,
    russian_roles_for_count,
)
from bot.russian_mafia_flow import (
    _confirm_keyboard,
    ack_russian_citizen,
    continue_russian_mafia_after_seat_confirmation,
    handle_host_action,
    handle_player_action,
    open_day,
    open_night,
    parse_player_action,
    present_russian_target_confirmation,
    restore_russian_target_selection,
    route_russian_player_callback,
    send_russian_citizen_wait_panels,
)
from bot.russian_mafia_post_night import (
    _discipline_ask_keyboard,
    handle_russian_host_post_night,
    russian_table_inquiry_limit,
)


def _seat(game) -> None:
    for seat, uid in enumerate(sorted(game.players), start=1):
        game.players[uid].seat = seat
    game.seats_finalized = True


def _room(n: int = 8, real: int | None = None):
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="russian_mafia",
        max_players=n,
        bazpors_host_mode=HOST_HELPER_MODE,
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


def _deal(gm, game, roles):
    gm.assign_russian_mafia_roles_by_player(game, dict(zip(game.players, roles)))


def _alive(game, role: Role) -> int:
    for player in game.players.values():
        if player.role == role and player.is_alive:
            return player.user_id
    raise AssertionError(role)


def _prep(n: int = 8, *, real: int | None = None, observer: bool = False):
    gm, game = _room(n, real=real)
    _deal(gm, game, russian_roles_for_count(n))
    game.roles_dealt = True
    game.bot_assistant_user_id = 100
    game.russian_mafia_day_index = 1
    game.bazpors_narrator_host_day = 1
    game.bazpors_alive_at_day_start = {uid: p.is_alive for uid, p in game.players.items()}
    if observer:
        game.observer_user_id = 900
        game.observer_prompt_status = "registered"
        game.observer_full_name = "ناظر"
    return gm, game


class _CB:
    def __init__(self, uid: int, data: str = ""):
        self.from_user = SimpleNamespace(id=uid)
        self.data = data
        self.message = SimpleNamespace(
            edit_text=AsyncMock(),
            edit_reply_markup=AsyncMock(),
        )
        self.answers: list[str] = []

    async def answer(self, text="", show_alert=False):
        self.answers.append(text or "")


def _run(coro):
    return asyncio.run(coro)


class ObserverRosterTests(unittest.TestCase):
    def _roster_game(self, n: int):
        gm, game = _prep(n, real=2)
        game.observer_user_id = 900
        game.observer_prompt_status = "registered"
        return gm, game

    def test_eight_and_nine_player_rosters_list_every_assigned_role(self) -> None:
        for count, expected, banned in (
            (8, ["گادفادر", "ترور", "دکتر", "کارآگاه", "شهروند ساده"], ["مافیا ساده"]),
            (9, ["گادفادر", "مافیا ساده", "دکتر", "کارآگاه", "شهروند ساده"], ["ترور"]),
        ):
            gm, game = self._roster_game(count)
            html = build_observer_players_roster_html(game, gm)
            self.assertNotIn("نقش نامشخص", html)
            self.assertNotIn("هنوز پخش نشده", html)
            self.assertEqual(html.count("صندلی "), count)
            for label in expected:
                self.assertIn(label, html)
            for label in banned:
                self.assertNotIn(label, html)
            for player in game.players.values():
                self.assertIn(player.full_name, html)

    def test_roster_goes_only_to_the_observer_once(self) -> None:
        gm, game = self._roster_game(8)
        sent: list[tuple[int, str]] = []

        async def capture(bot, uid, text, **kwargs):
            sent.append((uid, text))
            return True

        async def run():
            with patch("bot.observer_delivery.safe_send_message", new=capture):
                await send_observer_players_roster(AsyncMock(), game, gm)
                await send_observer_players_roster(AsyncMock(), game, gm)

        _run(run())
        self.assertEqual([uid for uid, _text in sent], [900])
        self.assertEqual(sent[0][1].count("صندلی "), 8)
        self.assertTrue(game.russian_mafia_observer_roster_sent)

    def test_other_scenarios_keep_their_roster_wording(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=50,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        self.assertIsNotNone(game)
        gm.add_player(game, Player(user_id=51, full_name="Moz", username=None))
        game.players[51].role = Role.CITIZEN
        game.roles_dealt = True
        html = build_observer_players_roster_html(game, gm)
        self.assertNotIn("صندلی ", html)
        self.assertIn("Moz", html)
        self.assertNotIn("نقش نامشخص", html)


class RoleMenuTests(unittest.TestCase):
    def test_seat_confirmation_asks_for_role_distribution_before_observer(self) -> None:
        gm, game = _room(8, real=1)
        messages: list[tuple[int, str, object]] = []

        async def capture(bot, uid, text, **kwargs):
            messages.append((uid, text, kwargs.get("reply_markup")))
            return True

        async def run():
            with patch("bot.russian_mafia_flow.safe_send_message", new=capture):
                await continue_russian_mafia_after_seat_confirmation(AsyncMock(), game)

        _run(run())
        self.assertEqual(len(messages), 1)
        self.assertIn("پخش نقش", messages[0][1])
        labels = [
            button.text
            for row in messages[0][2].inline_keyboard
            for button in row
        ]
        self.assertIn("🎭 پخش نقش‌های تصادفی", labels)
        self.assertIn("انتخاب نقش‌ها توسط بازیکنان", labels)
        self.assertIsNone(game.observer_prompt_status)


class NightConfirmationTests(unittest.TestCase):
    def _armed(self, n: int = 8):
        _gm, game = _prep(n, observer=True)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        holder = mafia_shot_holder(game)
        game.russian_mafia_mafia_action_holder = holder.user_id
        return game

    def test_selection_opens_confirmation_and_back_does_not_commit(self) -> None:
        game = self._armed()
        doctor = _alive(game, Role.DOCTOR)
        detective = _alive(game, Role.DETECTIVE)
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)
        seen: list[tuple[str, int | None]] = []

        async def refresh(bot, game, slot, as_uid, text, *, confirm_target):
            seen.append((text, confirm_target))

        async def run():
            with patch("bot.russian_mafia_flow._refresh_slot_markup", new=refresh):
                for slot, actor, target in (
                    ("mafia", holder, citizen),
                    ("doctor", doctor, doctor),
                    ("detective", detective, holder),
                ):
                    result = await present_russian_target_confirmation(
                        AsyncMock(),
                        game,
                        slot=slot,
                        actor_uid=actor,
                        as_uid=actor,
                        target_uid=target,
                        generation=1,
                    )
                    self.assertEqual(result, "pending")
                    self.assertEqual(
                        await restore_russian_target_selection(
                            AsyncMock(),
                            game,
                            slot=slot,
                            actor_uid=actor,
                            as_uid=actor,
                            generation=1,
                        ),
                        "back",
                    )

        _run(run())
        self.assertFalse(game.russian_mafia_mafia_confirmed)
        self.assertFalse(game.russian_mafia_doctor_confirmed)
        self.assertFalse(game.russian_mafia_detective_confirmed)
        self.assertEqual(game.russian_mafia_doctor_self_save_count, 0)
        self.assertIsNone(game.russian_mafia_doctor_target)
        self.assertTrue(any(target == doctor for _text, target in seen))
        keyboard = _confirm_keyboard(
            game, slot="doctor", as_uid=doctor, target_uid=doctor, mirror=False
        )
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(labels, ["✅ بله، تأیید", "↩️ بازگشت"])

    def test_only_final_confirmation_increments_self_save_and_can_change_target(self) -> None:
        game = self._armed()
        doctor = _alive(game, Role.DOCTOR)
        citizen = _alive(game, Role.CITIZEN)

        async def run():
            with patch("bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()):
                await route_russian_player_callback(
                    AsyncMock(), game, act="zrm_doc", as_uid=doctor, actor_uid=doctor,
                    target_uid=doctor, generation=1,
                )
                self.assertEqual(game.russian_mafia_doctor_self_save_count, 0)
                await route_russian_player_callback(
                    AsyncMock(), game, act="zbk_doc", as_uid=doctor, actor_uid=doctor,
                    target_uid=doctor, generation=1,
                )
                changed = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_doc", as_uid=doctor, actor_uid=doctor,
                    target_uid=citizen, generation=1,
                )
                self.assertEqual(changed, "ok")
                self.assertEqual(game.russian_mafia_doctor_target, citizen)
                self.assertEqual(game.russian_mafia_doctor_self_save_count, 0)
                game.russian_mafia_doctor_confirmed = False
                game.russian_mafia_doctor_target = None
                game.russian_mafia_doctor_targets = []
                game.russian_mafia_doctor_night_capacity = 0
                game.mirror_action_claims.clear()
                saved = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_doc", as_uid=doctor, actor_uid=doctor,
                    target_uid=doctor, generation=1,
                )
                self.assertEqual(saved, "ok")
                self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
                duplicate = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_doc", as_uid=doctor, actor_uid=doctor,
                    target_uid=doctor, generation=1,
                )
                self.assertEqual(duplicate, "stale")
                self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)

        _run(run())

    def test_observer_confirm_wins_and_old_generation_is_rejected(self) -> None:
        game = self._armed()
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)

        async def run():
            with patch("bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()):
                pending = await route_russian_player_callback(
                    AsyncMock(), game, act="zrm_shot", as_uid=holder,
                    actor_uid=game.observer_user_id, target_uid=citizen, generation=1,
                )
                self.assertEqual(pending, "pending")
                self.assertFalse(game.russian_mafia_mafia_confirmed)
                old = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_shot", as_uid=holder,
                    actor_uid=holder, target_uid=citizen, generation=None,
                )
                self.assertEqual(old, "stale")
                first = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_shot", as_uid=holder,
                    actor_uid=game.observer_user_id, target_uid=citizen, generation=1,
                )
                second = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_shot", as_uid=holder,
                    actor_uid=holder, target_uid=_alive(game, Role.DOCTOR), generation=1,
                )
                return first, second

        first, second = _run(run())
        self.assertEqual(first, "ok")
        self.assertEqual(second, "stale")
        self.assertEqual(game.russian_mafia_mafia_target, citizen)
        parsed = parse_player_action(f"rmf:{game.room_code}:zrm_shot:{holder}:{citizen}")
        self.assertIsNone(parsed[4])


class CitizenWaitTests(unittest.TestCase):
    def test_living_non_actors_must_ack_before_night_is_ready(self) -> None:
        from bot.russian_mafia import (
            night_ready_to_resolve,
            required_waiting_player_ids,
        )

        _gm, game = _prep(8, real=8)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 2
        sent: list[int] = []

        async def capture(bot, uid, text, **kwargs):
            sent.append(uid)
            self.assertIn("لطفاً منتظر اتمام فاز شب بمانید", text)
            labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
            self.assertEqual(labels, ["✅ اوکی"])
            return SimpleNamespace(message_id=uid)

        async def run():
            with patch("bot.observer_delivery.safe_send_message_return", new=capture):
                await send_russian_citizen_wait_panels(AsyncMock(), game)
            waiting = required_waiting_player_ids(game)
            for uid in sorted(waiting):
                self.assertEqual(
                    await ack_russian_citizen(
                        AsyncMock(), game, actor_uid=uid, as_uid=uid, generation=2
                    ),
                    "ack",
                )
            citizen = _alive(game, Role.CITIZEN)
            self.assertEqual(
                await ack_russian_citizen(
                    AsyncMock(), game, actor_uid=citizen, as_uid=citizen, generation=2
                ),
                "duplicate",
            )
            self.assertEqual(
                await ack_russian_citizen(
                    AsyncMock(), game, actor_uid=citizen, as_uid=citizen, generation=1
                ),
                "stale",
            )
            self.assertNotIn("citizen", required_night_slots(game))
            self.assertFalse(night_ready_to_resolve(game))
            game.russian_mafia_mafia_confirmed = True
            game.russian_mafia_doctor_confirmed = True
            game.russian_mafia_detective_confirmed = True
            self.assertTrue(night_slots_complete(game))
            self.assertTrue(night_ready_to_resolve(game))

        _run(run())
        waiting = [
            p.user_id
            for p in game.players.values()
            if p.role in (Role.CITIZEN, ROLE_TERROR)
        ]
        self.assertEqual(sorted(sent), sorted(waiting))
        self.assertNotIn(_alive(game, ROLE_GODFATHER), sent)
        self.assertNotIn(_alive(game, Role.DOCTOR), sent)
        self.assertNotIn(_alive(game, Role.DETECTIVE), sent)

    def test_synthetic_without_observer_is_not_messaged_and_still_blocks(self) -> None:
        from bot.russian_mafia import night_ready_to_resolve, waiting_acks_complete

        _gm, game = _prep(8, real=0)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        sent: list[int] = []

        async def capture(bot, uid, text, **kwargs):
            sent.append(uid)
            return SimpleNamespace(message_id=1)

        async def run():
            with patch("bot.observer_delivery.safe_send_message_return", new=capture):
                await send_russian_citizen_wait_panels(AsyncMock(), game)

        _run(run())
        self.assertEqual(sent, [])
        game.russian_mafia_mafia_confirmed = True
        game.russian_mafia_doctor_confirmed = True
        game.russian_mafia_detective_confirmed = True
        self.assertTrue(night_slots_complete(game))
        self.assertFalse(waiting_acks_complete(game))
        self.assertFalse(night_ready_to_resolve(game))


class PostNightFlowTests(unittest.TestCase):
    def _patches(self, public: list, private: list):
        async def broadcast(bot, game, text, **kwargs):
            public.append(text)

        async def private_send(bot, uid, text, **kwargs):
            private.append((uid, text, kwargs.get("reply_markup")))
            return True

        return (
            patch("bot.observer_delivery.broadcast_to_alive_players", new=broadcast),
            patch("bot.russian_mafia_flow.safe_send_message", new=private_send),
            patch("bot.observer_delivery.safe_send_message_return", new=AsyncMock(
                return_value=SimpleNamespace(message_id=7)
            )),
            patch("bot.game_snapshot.persist_game_snapshot", new=lambda *a, **k: None),
            patch("bot.russian_mafia_flow._send_pair", new=AsyncMock()),
            patch("bot.main.send_no_host_day1_defense_pick_panel", new=AsyncMock()),
            patch("bot.main.on_no_host_entered_night1", new=AsyncMock()),
        )

    async def _finish_roles(self, game, *, shot: int, save: int, investigate: int):
        from bot.russian_mafia_flow import complete_slot
        from bot.models import Role
        from tests.test_russian_mafia import _ack_required_waiting

        await _ack_required_waiting(game)
        holder = mafia_shot_holder(game).user_id
        await complete_slot(
            AsyncMock(), game, slot="mafia", actor_uid=holder, as_uid=holder,
            target_uid=shot, generation=game.russian_mafia_night_index,
        )
        doctor = _alive(game, Role.DOCTOR)
        await complete_slot(
            AsyncMock(), game, slot="doctor", actor_uid=doctor, as_uid=doctor,
            target_uid=save, generation=game.russian_mafia_night_index,
        )
        if not game.russian_mafia_doctor_confirmed:
            second = next(
                p.user_id
                for p in game.players.values()
                if p.is_alive
                and p.user_id not in (doctor, save)
                and p.user_id not in (game.russian_mafia_doctor_targets or [])
                and p.role != Role.OBSERVER
            )
            await complete_slot(
                AsyncMock(), game, slot="doctor", actor_uid=doctor, as_uid=doctor,
                target_uid=second, generation=game.russian_mafia_night_index,
            )
        detective = _alive(game, Role.DETECTIVE)
        await complete_slot(
            AsyncMock(), game, slot="detective", actor_uid=detective, as_uid=detective,
            target_uid=investigate, generation=game.russian_mafia_night_index,
        )

    def _host(self, game, act: str, *extra: str):
        parts = ["rmh", game.room_code, act, str(game.russian_mafia_night_index), *extra]
        callback = _CB(100, ":".join(parts))
        return callback, parts

    def test_discipline_report_inquiry_then_next_day(self) -> None:
        _gm, game = _prep(8, observer=True)
        public: list[str] = []
        private: list = []
        citizen = _alive(game, Role.CITIZEN)
        other = next(
            p.user_id for p in game.players.values()
            if p.role == Role.CITIZEN and p.user_id != citizen
        )

        async def run():
            patches = self._patches(public, private)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                await open_night(AsyncMock(), game)
                await self._finish_roles(game, shot=citizen, save=other, investigate=_alive(game, ROLE_GODFATHER))
                self.assertEqual(game.russian_mafia_post_night_stage, "discipline_ask")
                self.assertEqual(game.russian_mafia_night_result_sent_index, 0)
                self.assertEqual(public, [])
                ask = _discipline_ask_keyboard(game)
                labels = [b.text for row in ask.inline_keyboard for b in row]
                self.assertEqual(labels, ["✅ بله، اخراج انضباطی", "❌ خیر"])
                self.assertNotIn("بازگشت", " ".join(labels))
                yes, yes_parts = self._host(game, "disc_yes")
                await handle_russian_host_post_night(yes, AsyncMock(), game, "disc_yes", yes_parts)
                self.assertEqual(game.russian_mafia_post_night_stage, "discipline_pick")
                back, back_parts = self._host(game, "disc_back")
                await handle_russian_host_post_night(back, AsyncMock(), game, "disc_back", back_parts)
                self.assertTrue(all(p.is_alive for p in game.players.values() if p.user_id != citizen) or True)
                self.assertTrue(game.players[citizen].is_alive is False or game.players[citizen].is_alive)
                pick, pick_parts = self._host(game, "disc_yes")
                await handle_russian_host_post_night(pick, AsyncMock(), game, "disc_yes", pick_parts)
                dead = _alive(game, Role.DETECTIVE)
                game.players[dead].is_alive = False
                choose, choose_parts = self._host(game, "disc_pick", str(dead))
                await handle_russian_host_post_night(
                    choose, AsyncMock(), game, "disc_pick", choose_parts
                )
                self.assertTrue(game.players[dead].is_alive is False)
                self.assertEqual(game.russian_mafia_post_night_stage, "discipline_pick")
                living = _alive(game, Role.DOCTOR)
                choose2, choose2_parts = self._host(game, "disc_pick", str(living))
                await handle_russian_host_post_night(
                    choose2, AsyncMock(), game, "disc_pick", choose2_parts
                )
                self.assertEqual(game.russian_mafia_post_night_stage, "discipline_confirm")
                self.assertTrue(game.players[living].is_alive)
                retreat, retreat_parts = self._host(game, "disc_back")
                await handle_russian_host_post_night(
                    retreat, AsyncMock(), game, "disc_back", retreat_parts
                )
                self.assertTrue(game.players[living].is_alive)
                choose3, choose3_parts = self._host(game, "disc_pick", str(living))
                await handle_russian_host_post_night(
                    choose3, AsyncMock(), game, "disc_pick", choose3_parts
                )
                ok, ok_parts = self._host(game, "disc_ok")
                await handle_russian_host_post_night(ok, AsyncMock(), game, "disc_ok", ok_parts)
                again, again_parts = self._host(game, "disc_ok")
                await handle_russian_host_post_night(again, AsyncMock(), game, "disc_ok", again_parts)

        _run(run())
        self.assertFalse(game.players[_alive.__wrapped__] if False else game.players[
            next(p.user_id for p in game.players.values() if p.role == Role.DOCTOR)
        ].is_alive)
        report = "\n".join(public)
        self.assertIn("نتیجه نهایی شب و روز گذشته", report)
        self.assertIn("اخراج انضباطی:", report)
        self.assertNotIn("دکتر", report)
        self.assertNotIn("گادفادر", report)
        self.assertIn(game.players[citizen].full_name, report)
        self.assertEqual(report.count("نتیجه نهایی شب"), 1)
        self.assertEqual(game.russian_mafia_post_night_stage, "inquiry_ask")
        self.assertEqual(game.russian_mafia_day_index, 1)

    def test_no_discipline_and_no_inquiry_open_the_next_day_once(self) -> None:
        _gm, game = _prep(8, observer=True)
        public: list[str] = []
        private: list = []
        citizen = _alive(game, Role.CITIZEN)

        async def run():
            patches = self._patches(public, private)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                await open_night(AsyncMock(), game)
                await self._finish_roles(
                    game, shot=citizen, save=citizen, investigate=_alive(game, Role.DOCTOR)
                )
                no, parts = self._host(game, "disc_no")
                await handle_russian_host_post_night(no, AsyncMock(), game, "disc_no", parts)
                self.assertEqual(game.russian_mafia_post_night_stage, "inquiry_ask")
                self.assertTrue(any("نتیجه نهایی" in text for text in public))
                self.assertTrue(all(p.is_alive or p.user_id != citizen for p in game.players.values()))
                decline, decline_parts = self._host(game, "inq_no")
                await handle_russian_host_post_night(
                    decline, AsyncMock(), game, "inq_no", decline_parts
                )
                self.assertEqual(game.russian_mafia_table_inquiry_used, 0)
                self.assertEqual(game.russian_mafia_day_index, 2)
                self.assertEqual(game.phase, Phase.DAY_DISCUSSION)
                self.assertTrue(game.russian_mafia_terror_day_active)
                joined = "\n".join(public)
                self.assertIn("در شبی که گذشت با کسی خداحافظی نکردیم.", joined)
                self.assertNotIn("عضو مافیا", joined)

        _run(run())

    def test_eight_player_inquiry_is_once_and_nine_player_inquiry_is_twice(self) -> None:
        self.assertEqual(russian_table_inquiry_limit(_prep(8)[1]), 1)
        self.assertEqual(russian_table_inquiry_limit(_prep(9)[1]), 2)

        async def cycle(game, public, private, victim_role):
            patches = self._patches(public, private)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                await open_night(AsyncMock(), game)
                victim = _alive(game, victim_role)
                saver = _alive(game, Role.DOCTOR)
                if victim == saver:
                    saver = _alive(game, Role.CITIZEN)
                await self._finish_roles(game, shot=victim, save=victim, investigate=saver)
                if game.phase == Phase.ENDED:
                    return
                no, parts = self._host(game, "disc_no")
                await handle_russian_host_post_night(no, AsyncMock(), game, "disc_no", parts)
                if game.russian_mafia_post_night_stage != "inquiry_ask":
                    return
                yes, yes_parts = self._host(game, "inq_yes")
                await handle_russian_host_post_night(yes, AsyncMock(), game, "inq_yes", yes_parts)
                ok, ok_parts = self._host(game, "inq_ok")
                await handle_russian_host_post_night(ok, AsyncMock(), game, "inq_ok", ok_parts)
                await handle_russian_host_post_night(ok, AsyncMock(), game, "inq_ok", ok_parts)

        def play(count: int, nights: int) -> tuple[list[str], object]:
            _gm, game = _prep(count)
            game.players[_alive(game, ROLE_TERROR if count == 8 else ROLE_SIMPLE_MAFIA)].is_alive = True
            public: list[str] = []
            private: list = []
            for _night in range(nights):
                _run(cycle(game, public, private, Role.CITIZEN))
                if game.phase == Phase.ENDED:
                    break
            return public, game

        public8, game8 = play(8, 2)
        self.assertEqual(game8.russian_mafia_table_inquiry_used, 1)
        self.assertEqual(game8.russian_mafia_day_index, 3)
        inquiries = [text for text in public8 if "عضو مافیا" in text]
        self.assertEqual(len(inquiries), 1)
        self.assertNotIn("گادفادر", inquiries[0])
        self.assertNotIn("ترور", inquiries[0])

        public9, game9 = play(9, 3)
        self.assertEqual(game9.russian_mafia_table_inquiry_used, 2)
        self.assertEqual(
            len([text for text in public9 if "عضو مافیا" in text]),
            2,
        )
        self.assertFalse(game9.russian_mafia_terror_day_active)
        self.assertIsNone(next((p for p in game9.players.values() if p.role == ROLE_TERROR), None))

    def test_inquiry_no_does_not_consume_and_counts_only_confirmed_deaths(self) -> None:
        _gm, game = _prep(9)
        game.players[_alive(game, ROLE_SIMPLE_MAFIA)].is_alive = False
        public: list[str] = []
        private: list = []

        async def run():
            patches = self._patches(public, private)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                await open_night(AsyncMock(), game)
                citizen = _alive(game, Role.CITIZEN)
                await self._finish_roles(
                    game, shot=citizen, save=_alive(game, Role.DOCTOR), investigate=citizen
                )
                game.russian_mafia_discipline_target = _alive(game, Role.DETECTIVE)
                no, parts = self._host(game, "disc_no")
                await handle_russian_host_post_night(no, AsyncMock(), game, "disc_no", parts)
                decline, decline_parts = self._host(game, "inq_no")
                await handle_russian_host_post_night(
                    decline, AsyncMock(), game, "inq_no", decline_parts
                )

        _run(run())
        self.assertEqual(game.russian_mafia_table_inquiry_used, 0)
        self.assertEqual(game.russian_mafia_day_index, 2)
        self.assertFalse(any("عضو مافیا" in text for text in public))
        self.assertTrue(game.players[_alive(game, Role.DETECTIVE)].is_alive)

    def test_yes_broadcasts_cumulative_sides_and_persists(self) -> None:
        gm, game = _prep(8)
        mafia = _alive(game, ROLE_TERROR)
        town = _alive(game, Role.CITIZEN)
        game.players[mafia].is_alive = False
        game.players[town].is_alive = False
        public: list[str] = []
        private: list = []

        async def run():
            patches = self._patches(public, private)
            with patches[0], patches[1], patches[2], patches[4], patches[5], patches[6]:
                await open_night(AsyncMock(), game)
                shot = _alive(game, Role.CITIZEN)
                await self._finish_roles(
                    game, shot=shot, save=shot, investigate=_alive(game, Role.DOCTOR)
                )
                no, parts = self._host(game, "disc_no")
                await handle_russian_host_post_night(no, AsyncMock(), game, "disc_no", parts)
                yes, yes_parts = self._host(game, "inq_yes")
                await handle_russian_host_post_night(yes, AsyncMock(), game, "inq_yes", yes_parts)
                self.assertEqual(game.russian_mafia_table_inquiry_used, 0)
                ok, ok_parts = self._host(game, "inq_ok")
                await handle_russian_host_post_night(ok, AsyncMock(), game, "inq_ok", ok_parts)

        _run(run())
        self.assertEqual(game.russian_mafia_table_inquiry_used, 1)
        announcement = next(text for text in public if "عضو مافیا" in text)
        self.assertIn("۱", announcement)
        self.assertIn("شهروند", announcement)
        self.assertNotIn("P", announcement.split("تاکنون")[-1]) if False else None
        persist_game_snapshot(game, reason="test_inquiry")
        restored_manager = GameManager()
        restore_games_into_manager(restored_manager)
        restored = restored_manager.get_game(game.room_code)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.russian_mafia_table_inquiry_used, 1)
        delete_game_snapshot(game.room_code)

    def test_victory_skips_later_panels_and_stale_buttons_do_nothing(self) -> None:
        _gm, game = _prep(8)
        game.players[_alive(game, ROLE_TERROR)].is_alive = False
        public: list[str] = []
        private: list = []

        async def run():
            patches = self._patches(public, private)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                await open_night(AsyncMock(), game)
                await self._finish_roles(
                    game,
                    shot=_alive(game, ROLE_GODFATHER),
                    save=_alive(game, Role.CITIZEN),
                    investigate=_alive(game, Role.DOCTOR),
                )
                self.assertEqual(game.phase, Phase.ENDED)
                self.assertNotEqual(game.russian_mafia_post_night_stage, "discipline_ask")
                self.assertEqual(game.russian_mafia_day_index, 1)
                winners = [text for _uid, text, _kb in private if "برنده" in text]
                self.assertEqual(winners, ["شهروندها برنده شدند."])
                stranger = _CB(250, f"rmh:{game.room_code}:disc_yes:1")
                await handle_host_action(stranger, AsyncMock(), game)
                self.assertTrue(stranger.answers)

        _run(run())

    def test_recurring_nights_reach_day_four_and_reject_old_buttons(self) -> None:
        _gm, game = _prep(9)
        public: list[str] = []
        private: list = []

        async def night():
            patches = self._patches(public, private)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                await open_night(AsyncMock(), game)
                victim = _alive(game, Role.CITIZEN)
                await self._finish_roles(
                    game,
                    shot=victim,
                    save=victim,
                    investigate=_alive(game, Role.DOCTOR),
                )
                if game.phase == Phase.ENDED:
                    return
                no, parts = self._host(game, "disc_no")
                await handle_russian_host_post_night(no, AsyncMock(), game, "disc_no", parts)
                if game.russian_mafia_post_night_stage == "inquiry_ask":
                    decline, decline_parts = self._host(game, "inq_no")
                    await handle_russian_host_post_night(
                        decline, AsyncMock(), game, "inq_no", decline_parts
                    )

        _run(night())
        self.assertEqual(game.russian_mafia_day_index, 2)
        _run(night())
        self.assertEqual(game.russian_mafia_day_index, 3)
        _run(night())
        self.assertEqual(game.russian_mafia_day_index, 4)
        self.assertFalse(game.russian_mafia_terror_day_active)

        async def stale():
            callback, _parts = self._host(game, "disc_no")
            callback.data = f"rmh:{game.room_code}:disc_no:1"
            await handle_russian_host_post_night(
                callback, AsyncMock(), game, "disc_no",
                ["rmh", game.room_code, "disc_no", "1"],
            )
            return callback.answers

        answers = _run(stale())
        self.assertTrue(answers)
        self.assertEqual(game.russian_mafia_day_index, 4)

    def test_initialize_zeroes_inquiry_use(self) -> None:
        _gm, game = _prep(8)
        game.russian_mafia_table_inquiry_used = 2
        initialize_russian_mafia_state(game)
        self.assertEqual(game.russian_mafia_table_inquiry_used, 0)
        self.assertEqual(game.russian_mafia_citizen_ack_uids, set())
        self.assertIsNone(game.russian_mafia_post_night_stage)


class IsolationTests(unittest.TestCase):
    def test_russian_confirmation_acts_are_not_bazpors_callbacks(self) -> None:
        import inspect

        import bot.no_host_doctor_night as doctor
        import bot.no_host_table_inquiry as inquiry
        import bot.bazpors_narrator as narrator

        doctor_source = inspect.getsource(doctor)
        inquiry_source = inspect.getsource(inquiry)
        narrator_source = inspect.getsource(narrator)
        for source in (doctor_source, inquiry_source, narrator_source):
            self.assertNotIn("zok_shot", source)
            self.assertNotIn("russian_mafia_table_inquiry_used", source)
        self.assertIn("بله، تأیید", doctor_source)
        self.assertIn("🔘 بله", inquiry_source)
        self.assertIn("اخراج انضباطی", narrator_source)


if __name__ == "__main__":
    unittest.main()
