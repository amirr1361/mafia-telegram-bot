"""آمادگی شب مافیای روسی: هر بازیکن زنده باید عمل یا اوکی را تمام کند."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.game import SEMI_AUTO_SYNTHETIC_UID_BASE, is_synthetic_player_uid
from bot.models import Phase, Role
from bot.observer_delivery import PlayerMirrorCb
from bot.russian_mafia import (
    ROLE_GODFATHER,
    ROLE_SIMPLE_MAFIA,
    ROLE_TERROR,
    explain_russian_mafia_night_readiness,
    mafia_shot_holder,
    night_ready_to_resolve,
    night_slots_complete,
    required_waiting_player_ids,
    russian_doctor_self_save_limit,
    waiting_acks_complete,
    winner_of,
)
from bot.russian_mafia_flow import (
    ack_russian_citizen,
    complete_slot,
    continue_russian_mafia_after_night,
    open_night,
    try_confirm_action,
)
from bot.russian_mafia_post_night import russian_table_inquiry_limit
from tests.test_russian_mafia import _accept_russian_post_night
from tests.test_russian_mafia_workflow import _alive, _prep, _run


def _uids(game, role: Role) -> list[int]:
    return sorted(p.user_id for p in game.players.values() if p.role == role and p.is_alive)


def _labels(markup) -> list[str]:
    if markup is None:
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


def _callbacks(markup) -> list[str]:
    if markup is None:
        return []
    return [button.callback_data for row in markup.inline_keyboard for button in row]


class _Capture:
    def __init__(self) -> None:
        self.rows: list[tuple] = []
        self.private: list[tuple] = []
        self.public: list[str] = []
        self.defense = AsyncMock()

    async def panel(self, bot, uid, text, **kwargs):
        self.rows.append((uid, text, kwargs.get("reply_markup")))
        return SimpleNamespace(message_id=len(self.rows) + 20)

    async def private_send(self, bot, uid, text, **kwargs):
        self.private.append((uid, text, kwargs.get("reply_markup")))
        return True

    async def broadcast(self, bot, game, text, **kwargs):
        self.public.append(text)

    def patches(self):
        return (
            patch("bot.observer_delivery.safe_send_message_return", new=self.panel),
            patch("bot.russian_mafia_flow.safe_send_message", new=self.private_send),
            patch("bot.observer_delivery.broadcast_to_alive_players", new=self.broadcast),
            patch("bot.main.send_no_host_day1_defense_pick_panel", new=self.defense),
            patch("bot.game_snapshot.persist_game_snapshot", new=lambda *a, **k: None),
            patch("bot.main.on_no_host_entered_night1", new=AsyncMock()),
        )


def _ok_rows(capture: _Capture):
    return [row for row in capture.rows if "منتظر اتمام فاز شب" in row[1]]


async def _ack(game, uid: int, *, actor: int | None = None, generation: int | None = None):
    if actor is None:
        actor = game.observer_user_id if is_synthetic_player_uid(uid) else uid
    return await ack_russian_citizen(
        AsyncMock(),
        game,
        actor_uid=actor,
        as_uid=uid,
        generation=game.russian_mafia_night_index if generation is None else generation,
    )


async def _ack_all(game) -> None:
    for uid in sorted(required_waiting_player_ids(game)):
        result = await _ack(game, uid)
        if result != "ack":
            raise AssertionError((uid, result))


class WaitingPanelTests(unittest.TestCase):
    def test_eight_player_ok_goes_to_terror_and_citizens_only(self) -> None:
        _gm, game = _prep(8, observer=True)
        capture = _Capture()
        slots: list[tuple] = []

        async def pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            slots.append((slot, player_uid, act))

        async def run():
            patches = capture.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
                "bot.russian_mafia_flow._send_pair", new=pair
            ):
                await open_night(AsyncMock(), game)

        _run(run())
        ok_players = {row[0] for row in _ok_rows(capture) if row[0] != 900}
        self.assertEqual(ok_players, set(_uids(game, Role.CITIZEN)) | {_alive(game, ROLE_TERROR)})
        self.assertNotIn(_alive(game, ROLE_GODFATHER), ok_players)
        self.assertNotIn(_alive(game, Role.DOCTOR), ok_players)
        self.assertNotIn(_alive(game, Role.DETECTIVE), ok_players)
        self.assertEqual([row[1] for row in slots if row[0] == "mafia"], [_alive(game, ROLE_GODFATHER)])
        self.assertEqual([row[1] for row in slots if row[0] == "doctor"], [_alive(game, Role.DOCTOR)])
        self.assertEqual([row[1] for row in slots if row[0] == "detective"], [_alive(game, Role.DETECTIVE)])
        for row in _ok_rows(capture):
            self.assertEqual(_labels(row[2]), ["✅ اوکی"])
        mirrors = [row for row in _ok_rows(capture) if row[0] == 900]
        self.assertEqual(len(mirrors), 5)
        observed = {PlayerMirrorCb.unpack(data).as_uid for row in mirrors for data in _callbacks(row[2])}
        self.assertEqual(observed, ok_players)

    def test_nine_player_simple_mafia_ack_and_godfather_shoots(self) -> None:
        _gm, game = _prep(9, observer=True)
        self.assertFalse(any(p.role == ROLE_TERROR for p in game.players.values()))
        capture = _Capture()
        slots: list[tuple] = []

        async def pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            slots.append((slot, player_uid))

        async def run():
            with capture.patches()[0], patch("bot.russian_mafia_flow._send_pair", new=pair):
                await open_night(AsyncMock(), game)

        _run(run())
        ok_players = {row[0] for row in _ok_rows(capture) if row[0] != 900}
        self.assertEqual(ok_players, set(_uids(game, Role.CITIZEN)) | set(_uids(game, ROLE_SIMPLE_MAFIA)))
        self.assertEqual(slots, [
            ("mafia", _alive(game, ROLE_GODFATHER)),
            ("doctor", _alive(game, Role.DOCTOR)),
            ("detective", _alive(game, Role.DETECTIVE)),
        ])

    def test_dead_godfather_makes_terror_or_one_simple_mafia_the_only_shooter(self) -> None:
        _gm, game = _prep(8, observer=True)
        game.players[_alive(game, ROLE_GODFATHER)].is_alive = False
        capture = _Capture()
        slots: list[tuple] = []

        async def pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            slots.append((slot, player_uid))

        async def run():
            with capture.patches()[0], patch("bot.russian_mafia_flow._send_pair", new=pair):
                await open_night(AsyncMock(), game)

        _run(run())
        terror = _alive(game, ROLE_TERROR)
        ok_players = {row[0] for row in _ok_rows(capture) if row[0] != 900}
        self.assertEqual([row[1] for row in slots if row[0] == "mafia"], [terror])
        self.assertNotIn(terror, ok_players)
        self.assertTrue(set(_uids(game, Role.CITIZEN)) <= ok_players)

        _gm9, game9 = _prep(9, observer=True)
        game9.players[_alive(game9, ROLE_GODFATHER)].is_alive = False
        capture9 = _Capture()
        slots9: list[tuple] = []

        async def pair9(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            slots9.append((slot, player_uid))

        async def run9():
            with capture9.patches()[0], patch("bot.russian_mafia_flow._send_pair", new=pair9):
                await open_night(AsyncMock(), game9)

        _run(run9())
        holder = mafia_shot_holder(game9).user_id
        other = next(uid for uid in _uids(game9, ROLE_SIMPLE_MAFIA) if uid != holder)
        ok9 = {row[0] for row in _ok_rows(capture9) if row[0] != 900}
        self.assertEqual(mafia_shot_holder(game9).role, ROLE_SIMPLE_MAFIA)
        self.assertEqual([row[1] for row in slots9 if row[0] == "mafia"], [holder])
        self.assertIn(other, ok9)
        self.assertNotIn(holder, ok9)
        self.assertTrue(set(_uids(game9, Role.CITIZEN)) <= ok9)

    def test_dead_player_gets_no_panel_and_does_not_block(self) -> None:
        _gm, game = _prep(8, real=8)
        dead = _uids(game, Role.CITIZEN)[0]
        game.players[dead].is_alive = False
        game.players[_alive(game, Role.DOCTOR)].is_alive = False
        capture = _Capture()

        async def run():
            with capture.patches()[0]:
                await open_night(AsyncMock(), game)
                await _ack_all(game)

        _run(run())
        ok_players = {row[0] for row in _ok_rows(capture)}
        self.assertNotIn(dead, ok_players)
        self.assertNotIn(dead, required_waiting_player_ids(game))
        report = explain_russian_mafia_night_readiness(game)
        self.assertNotIn(dead, report["pending_player_ids"])
        self.assertNotIn("doctor_save", report["pending_responsibility_types"])
        self.assertTrue(waiting_acks_complete(game))
        self.assertNotIn("گادفادر", str(report))
        self.assertNotIn("ترور", str(report))


class AcknowledgementTests(unittest.TestCase):
    def _opened(self, n: int = 8, *, real: int | None = None):
        _gm, game = _prep(n, real=real, observer=True)
        capture = _Capture()

        async def open_it():
            patches = capture.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await open_night(AsyncMock(), game)

        _run(open_it())
        return game, capture

    def test_ack_is_per_player_and_rejects_duplicates_and_old_nights(self) -> None:
        game, _capture = self._opened()
        citizen = _uids(game, Role.CITIZEN)[0]
        other = _uids(game, Role.CITIZEN)[1]
        key = f"russian:{game.room_code}:night:1:ready:{citizen}"
        self.assertIn(key, game.mirror_prompt_messages)
        self.assertIn(key + ":obs", game.mirror_prompt_messages)

        async def run():
            first = await _ack(game, citizen, actor=citizen)
            duplicate = await _ack(game, citizen, actor=game.observer_user_id)
            stale = await _ack(game, other, generation=0)
            return first, duplicate, stale

        first, duplicate, stale = _run(run())
        self.assertEqual(first, "ack")
        self.assertEqual(duplicate, "duplicate")
        self.assertEqual(stale, "stale")
        self.assertIn(citizen, game.russian_mafia_citizen_ack_uids)
        self.assertNotIn(other, game.russian_mafia_citizen_ack_uids)

    def test_player_ack_closes_observer_copy_and_observer_ack_closes_player_copy(self) -> None:
        game, _capture = self._opened()
        citizens = _uids(game, Role.CITIZEN)
        edits: list[tuple] = []

        async def edit(bot, chat_id, message_id, text, markup):
            edits.append((chat_id, message_id, text, markup))
            return True

        async def run():
            with patch("bot.russian_mafia_flow._try_edit_mirror_message", new=edit):
                await _ack(game, citizens[0], actor=citizens[0])
                await _ack(game, citizens[1], actor=game.observer_user_id)

        _run(run())
        closed = {(chat, mid, text) for chat, mid, text, markup in edits if markup is None}
        player_key = game.mirror_prompt_messages[f"russian:{game.room_code}:night:1:ready:{citizens[0]}"]
        obs_key = game.mirror_prompt_messages[f"russian:{game.room_code}:night:1:ready:{citizens[0]}:obs"]
        self.assertEqual(player_key["text"], "✅ متوجه شدم")
        self.assertEqual(obs_key["text"], "✅ متوجه شدم")
        other_player = game.mirror_prompt_messages[f"russian:{game.room_code}:night:1:ready:{citizens[1]}"]
        other_obs = game.mirror_prompt_messages[f"russian:{game.room_code}:night:1:ready:{citizens[1]}:obs"]
        self.assertEqual(other_player["text"], "✅ متوجه شدم")
        self.assertEqual(other_obs["text"], "✅ متوجه شدم")
        self.assertTrue(closed)
        before = len(edits)
        _run(_ack(game, citizens[0], actor=game.observer_user_id))
        self.assertEqual(len(edits), before)

    def test_observer_acks_each_synthetic_independently(self) -> None:
        game, _capture = self._opened(8, real=0)
        citizens = _uids(game, Role.CITIZEN)
        terror = _alive(game, ROLE_TERROR)
        self.assertTrue(all(uid < 0 for uid in citizens))
        self.assertLess(terror, 0)
        self.assertNotEqual(mafia_shot_holder(game).user_id, terror)

        async def run():
            first = await _ack(game, citizens[0], actor=game.observer_user_id)
            second = await _ack(game, citizens[1], actor=game.observer_user_id)
            terror_ack = await _ack(game, terror, actor=game.observer_user_id)
            return first, second, terror_ack

        first, second, terror_ack = _run(run())
        self.assertEqual((first, second, terror_ack), ("ack", "ack", "ack"))
        done = game.russian_mafia_citizen_ack_uids
        self.assertIn(citizens[0], done)
        self.assertIn(citizens[1], done)
        self.assertIn(terror, done)
        self.assertNotIn(citizens[2], done)
        self.assertTrue(is_synthetic_player_uid(SEMI_AUTO_SYNTHETIC_UID_BASE))

    def test_observer_acks_synthetic_simple_mafia_who_is_not_shooting(self) -> None:
        game, _capture = self._opened(9, real=0)
        self.assertFalse(any(p.role == ROLE_TERROR for p in game.players.values()))
        simples = _uids(game, ROLE_SIMPLE_MAFIA)
        self.assertEqual(len(simples), 2)

        async def run():
            return [await _ack(game, uid, actor=game.observer_user_id) for uid in simples]

        self.assertEqual(_run(run()), ["ack", "ack"])
        self.assertTrue(set(simples) <= game.russian_mafia_citizen_ack_uids)
        self.assertNotIn(_alive(game, ROLE_GODFATHER), game.russian_mafia_citizen_ack_uids)


class ReadinessGateTests(unittest.TestCase):
    def _night(self, n: int = 8):
        _gm, game = _prep(n, observer=True)
        capture = _Capture()

        async def open_it():
            patches = capture.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await open_night(AsyncMock(), game)

        _run(open_it())
        return game, capture

    async def _act(self, game, slot: str, target: int):
        actor = {
            "mafia": mafia_shot_holder(game).user_id,
            "doctor": _alive(game, Role.DOCTOR),
            "detective": _alive(game, Role.DETECTIVE),
        }[slot]
        return await complete_slot(
            AsyncMock(),
            game,
            slot=slot,
            actor_uid=actor,
            as_uid=actor,
            target_uid=target,
            generation=game.russian_mafia_night_index,
        )

    def test_missing_ok_or_any_active_action_keeps_night_open(self) -> None:
        game, capture = self._night()
        citizens = _uids(game, Role.CITIZEN)
        holder = mafia_shot_holder(game).user_id
        doctor = _alive(game, Role.DOCTOR)
        detective = _alive(game, Role.DETECTIVE)

        async def run():
            patches = capture.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await _ack_all(game)
                game.russian_mafia_citizen_ack_uids.discard(citizens[0])
                await self._act(game, "mafia", citizens[1])
                await self._act(game, "doctor", doctor)
                await self._act(game, "detective", holder)
                self.assertEqual(game.phase, Phase.NIGHT)
                self.assertIsNone(game.russian_mafia_post_night_stage)
                self.assertFalse(night_ready_to_resolve(game))
                report = explain_russian_mafia_night_readiness(game)
                self.assertIn(citizens[0], report["pending_player_ids"])
                self.assertIn("waiting_ok", report["pending_responsibility_types"])
                self.assertFalse(report["ready"])

                await _ack(game, citizens[0])
                self.assertEqual(game.russian_mafia_post_night_stage, "discipline_ask")
                again = await continue_russian_mafia_after_night(AsyncMock(), game)
                del again
                discipline = [text for _uid, text, _kb in capture.private if "اخراج انضباطی" in text]
                self.assertEqual(len(discipline), 1)

        _run(run())

    def _assert_blocked(self, game, capture, slots: tuple[str, ...], pending: str) -> None:
        citizen = _uids(game, Role.CITIZEN)[0]
        holder = mafia_shot_holder(game).user_id

        async def run():
            patches = capture.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await _ack_all(game)
                for slot in slots:
                    target = holder if slot == "detective" else citizen
                    await self._act(game, slot, target)
                self.assertEqual(game.phase, Phase.NIGHT)
                self.assertIsNone(game.russian_mafia_post_night_stage)
                self.assertIn(pending, explain_russian_mafia_night_readiness(game)["pending_responsibility_types"])
                self.assertFalse(night_ready_to_resolve(game))

        _run(run())

    def test_each_missing_active_action_blocks_resolution(self) -> None:
        game, capture = self._night()
        self._assert_blocked(game, capture, ("doctor", "detective"), "mafia_shot")
        fresh, fresh_capture = self._night()
        self._assert_blocked(fresh, fresh_capture, ("mafia", "detective"), "doctor_save")
        third, third_capture = self._night()
        self._assert_blocked(third, third_capture, ("mafia", "doctor"), "detective_inquiry")

    def test_completed_night_resolves_once_and_old_acks_do_not_carry(self) -> None:
        game, capture = self._night()
        victim = _uids(game, Role.CITIZEN)[0]
        other = _uids(game, Role.CITIZEN)[1]
        doctor = _alive(game, Role.DOCTOR)

        async def finish(current, cap, target):
            patches = cap.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await _ack_all(current)
                await self._act(current, "mafia", target)
                await self._act(current, "doctor", other if target != other else victim)
                await self._act(current, "detective", mafia_shot_holder(current).user_id)
                self.assertEqual(current.russian_mafia_post_night_stage, "discipline_ask")
                await _accept_russian_post_night(current)
                await continue_russian_mafia_after_night(AsyncMock(), current)
                await open_night(AsyncMock(), current)

        async def run():
            await finish(game, capture, victim)
            self.assertEqual(game.russian_mafia_night_index, 2)
            self.assertEqual(game.russian_mafia_citizen_ack_uids, set())
            self.assertFalse(night_ready_to_resolve(game))
            self.assertEqual(game.russian_mafia_doctor_self_save_count, 0)
            stale = await _ack(game, other, generation=1)
            self.assertEqual(stale, "stale")
            old_shot = await complete_slot(
                AsyncMock(), game, slot="mafia",
                actor_uid=mafia_shot_holder(game).user_id,
                as_uid=mafia_shot_holder(game).user_id,
                target_uid=other, generation=1,
            )
            self.assertEqual(old_shot, "stale")
            self.assertEqual(
                try_confirm_action(
                    game, slot="doctor", actor_uid=doctor, as_uid=doctor,
                    target_uid=doctor, generation=2,
                ),
                "ok",
            )
            self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
            await finish(game, capture, other)
            self.assertEqual(game.russian_mafia_night_index, 3)
            self.assertEqual(game.russian_mafia_doctor_self_save_count, 1)
            self.assertEqual(
                try_confirm_action(
                    game, slot="doctor", actor_uid=doctor, as_uid=doctor,
                    target_uid=doctor, generation=3,
                ),
                "rejected",
            )
            self.assertEqual(await _ack(game, _uids(game, Role.CITIZEN)[0], generation=2), "stale")
            night_results = [text for text in capture.public if "نتیجه نهایی شب" in text or "در شبی که گذشت" in text]
            self.assertEqual(len(night_results), 2)
            self.assertEqual(capture.defense.await_count, 2)
            discipline = [text for _uid, text, _kb in capture.private if "اخراج انضباطی" in text]
            self.assertEqual(len(discipline), 2)

        _run(run())
        self.assertEqual(russian_doctor_self_save_limit(game), 1)

    def test_observer_ack_works_on_later_nights(self) -> None:
        game, capture = self._night(8)
        game.players[_alive(game, ROLE_GODFATHER)].is_alive = False
        # شب دوباره باز می‌شود تا ترورِ مصنوعیِ تیرانداز نباشد؛ این دست ترور اوکی می‌خواهد.
        terror = _alive(game, ROLE_TERROR)
        # گادفادر همین حالا مرد، پس شبِ بازشده هنوز پنل تیر را به او داده. شب تازه:
        capture2 = _Capture()

        async def run():
            patches = capture2.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                game.phase = Phase.DAY_DISCUSSION
                await open_night(AsyncMock(), game)
                self.assertEqual(mafia_shot_holder(game).user_id, terror)
                citizens = [uid for uid in _uids(game, Role.CITIZEN)]
                self.assertEqual(await _ack(game, citizens[0], actor=game.observer_user_id), "ack")
                self.assertNotIn(citizens[1], game.russian_mafia_citizen_ack_uids)
                await open_night(AsyncMock(), game)
                self.assertEqual(game.russian_mafia_night_index, 3)
                self.assertNotIn(citizens[0], game.russian_mafia_citizen_ack_uids)
                self.assertEqual(await _ack(game, citizens[0], actor=game.observer_user_id), "ack")
                self.assertEqual(await _ack(game, citizens[0], generation=2), "stale")

        # first open in _night already consumed night 1; restart cleanly
        _gm, game = _prep(8, real=0, observer=True)
        capture = _Capture()

        async def run_clean():
            patches = capture.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await open_night(AsyncMock(), game)
                citizen = _uids(game, Role.CITIZEN)[0]
                terror = _alive(game, ROLE_TERROR)
                self.assertNotEqual(mafia_shot_holder(game).user_id, terror)
                self.assertEqual(await _ack(game, citizen, actor=900), "ack")
                self.assertEqual(await _ack(game, terror, actor=900), "ack")
                for uid in sorted(required_waiting_player_ids(game)):
                    if uid in (citizen, terror):
                        continue
                    self.assertEqual(await _ack(game, uid, actor=900), "ack")
                await self._act(game, "mafia", _uids(game, Role.CITIZEN)[1])
                await self._act(game, "doctor", _alive(game, Role.DOCTOR))
                await self._act(game, "detective", mafia_shot_holder(game).user_id)
                await _accept_russian_post_night(game)
                await open_night(AsyncMock(), game)
                self.assertEqual(await _ack(game, citizen, generation=1), "stale")
                self.assertEqual(await _ack(game, citizen, actor=900), "ack")
                self.assertEqual(await _ack(game, terror, actor=900), "ack")

        _run(run_clean())


class ScenarioInvariantTests(unittest.TestCase):
    def test_priorities_wins_and_inquiry_limits_stay(self) -> None:
        _gm, eight = _prep(8)
        self.assertEqual(mafia_shot_holder(eight).role, ROLE_GODFATHER)
        eight.players[_alive(eight, ROLE_GODFATHER)].is_alive = False
        self.assertEqual(mafia_shot_holder(eight).role, ROLE_TERROR)
        for player in list(eight.players.values()):
            if player.role in (ROLE_GODFATHER, ROLE_TERROR):
                player.is_alive = False
        self.assertEqual(winner_of(eight), "town")

        _gm, parity = _prep(8)
        citizens = [p for p in parity.players.values() if p.role == Role.CITIZEN]
        for player in citizens[:4]:
            player.is_alive = False
        self.assertEqual(winner_of(parity), "mafia")

        _gm, nine = _prep(9)
        self.assertFalse(any(p.role == ROLE_TERROR for p in nine.players.values()))
        self.assertEqual(mafia_shot_holder(nine).role, ROLE_GODFATHER)
        nine.players[_alive(nine, ROLE_GODFATHER)].is_alive = False
        self.assertEqual(mafia_shot_holder(nine).role, ROLE_SIMPLE_MAFIA)
        self.assertEqual(russian_table_inquiry_limit(eight), 1)
        self.assertEqual(russian_table_inquiry_limit(nine), 2)
        self.assertEqual(russian_doctor_self_save_limit(eight), 1)
        self.assertEqual(russian_doctor_self_save_limit(nine), 1)
        self.assertTrue(night_slots_complete(nine) or not night_ready_to_resolve(nine))


if __name__ == "__main__":
    unittest.main()
