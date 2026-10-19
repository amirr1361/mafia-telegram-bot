"""پنل روز ترور در مافیای روسی ۸نفره، بعد از شب معارفه و در روزهای بعد."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.models import Phase, Role
from bot.observer_delivery import PlayerMirrorCb
from bot.russian_mafia import (
    ROLE_GODFATHER,
    ROLE_TERROR,
    mafia_shot_holder,
    required_waiting_player_ids,
)
from bot.russian_mafia_flow import (
    handle_host_action,
    open_day,
    open_night,
    route_russian_player_callback,
)
from tests.test_russian_mafia_workflow import _alive, _prep, _run


def _targets(markup) -> list[int]:
    found = []
    if markup is None:
        return found
    for row in markup.inline_keyboard:
        for button in row:
            data = button.callback_data
            if data.startswith("rmf:"):
                found.append(int(data.split(":")[4]))
            elif data.startswith("pmr:"):
                found.append(PlayerMirrorCb.unpack(data).tid)
    return found


def _generations(markup) -> set[int]:
    found = set()
    if markup is None:
        return found
    for row in markup.inline_keyboard:
        for button in row:
            data = button.callback_data
            if data.startswith("rmf:") and data.count(":") >= 5:
                found.add(int(data.split(":")[5]))
            elif data.startswith("pmr:"):
                rid = PlayerMirrorCb.unpack(data).rid
                if rid:
                    found.add(int(rid))
    return found


class _Sent:
    def __init__(self) -> None:
        self.rows: list[tuple] = []

    async def panel(self, bot, uid, text, **kwargs):
        self.rows.append((uid, text, kwargs.get("reply_markup")))
        return SimpleNamespace(message_id=len(self.rows) + 30)

    async def private(self, bot, uid, text, **kwargs):
        return True

    async def broadcast(self, bot, game, text, **kwargs):
        return None

    def patches(self):
        return (
            patch("bot.observer_delivery.safe_send_message_return", new=self.panel),
            patch("bot.russian_mafia_flow.safe_send_message", new=self.private),
            patch("bot.observer_delivery.broadcast_to_alive_players", new=self.broadcast),
            patch("bot.game_snapshot.persist_game_snapshot", new=lambda *a, **k: None),
            patch("bot.main.on_no_host_entered_night1", new=AsyncMock()),
            patch("bot.main.send_no_host_day1_defense_pick_panel", new=AsyncMock()),
        )


def _terror_rows(sent: _Sent):
    return [row for row in sent.rows if "توان روز ترور" in row[1]]


class TerrorDayPanelTests(unittest.TestCase):
    def _patches_of(self, sent: _Sent):
        return sent.patches()

    def test_intro_confirmation_opens_day1_terror_panel_for_real_player(self) -> None:
        _gm, game = _prep(8, real=8, observer=True)
        game.phase = Phase.LOBBY
        terror = _alive(game, ROLE_TERROR)
        sent = _Sent()

        class CB:
            def __init__(self):
                self.from_user = SimpleNamespace(id=100)
                self.data = f"rmh:{game.room_code}:intro_ok"
                self.message = SimpleNamespace(edit_reply_markup=AsyncMock(), edit_text=AsyncMock())
                self.answers: list[str] = []

            async def answer(self, text="", show_alert=False):
                self.answers.append(text or "")

        async def run():
            patches = sent.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await handle_host_action(CB(), AsyncMock(), game)

        _run(run())
        self.assertEqual(game.russian_mafia_day_index, 1)
        self.assertEqual(game.phase, Phase.DAY_DISCUSSION)
        self.assertTrue(game.no_host_day1_defense_active)
        self.assertTrue(game.russian_mafia_terror_day_active)
        player_rows = [row for row in _terror_rows(sent) if row[0] == terror]
        observer_rows = [row for row in _terror_rows(sent) if row[0] == 900]
        self.assertEqual(len(player_rows), 1)
        self.assertEqual(len(observer_rows), 1)
        targets = _targets(player_rows[0][2])
        self.assertNotIn(terror, targets)
        self.assertIn(_alive(game, Role.CITIZEN), targets)
        self.assertEqual(_generations(player_rows[0][2]), {1})
        key = f"russian:{game.room_code}:day:1:terror"
        self.assertIn(key, game.mirror_prompt_messages)
        self.assertIn(key + ":obs", game.mirror_prompt_messages)
        self.assertNotIn("بسته شد", game.mirror_prompt_messages[key]["text"])

    def test_synthetic_terror_is_only_sent_to_observer(self) -> None:
        _gm, game = _prep(8, real=1, observer=True)
        terror = _alive(game, ROLE_TERROR)
        self.assertLess(terror, 0)
        sent = _Sent()

        async def run():
            patches = sent.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await open_day(AsyncMock(), game)

        _run(run())
        rows = _terror_rows(sent)
        self.assertTrue(rows)
        self.assertTrue(all(row[0] == 900 for row in rows))
        self.assertTrue(all(PlayerMirrorCb.unpack(_targets and row[2].inline_keyboard[0][0].callback_data).as_uid == terror for row in rows))

    def test_two_step_confirm_eliminates_once_and_starts_night_or_ends(self) -> None:
        _gm, game = _prep(8, real=8, observer=True)
        game.russian_mafia_day_index = 0
        game.russian_mafia_night_index = 0
        game.bazpors_narrator_host_day = 0
        sent = _Sent()
        terror = _alive(game, ROLE_TERROR)
        citizen = _alive(game, Role.CITIZEN)
        godfather = _alive(game, ROLE_GODFATHER)

        async def open_it():
            patches = sent.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                await open_day(AsyncMock(), game)

        _run(open_it())
        self.assertTrue(game.no_host_day1_defense_active)
        self.assertTrue(game.russian_mafia_terror_day_active)

        async def choose():
            pending = await route_russian_player_callback(
                AsyncMock(), game, act="zrm_ter", as_uid=terror, actor_uid=terror,
                target_uid=citizen, generation=1,
            )
            self_target = await route_russian_player_callback(
                AsyncMock(), game, act="zrm_ter", as_uid=terror, actor_uid=terror,
                target_uid=terror, generation=1,
            )
            back = await route_russian_player_callback(
                AsyncMock(), game, act="zbk_ter", as_uid=terror, actor_uid=terror,
                target_uid=citizen, generation=1,
            )
            return pending, self_target, back

        pending, self_target, back = _run(choose())
        self.assertEqual(pending, "pending")
        self.assertEqual(self_target, "rejected")
        self.assertEqual(back, "back")
        self.assertTrue(game.players[terror].is_alive)
        self.assertTrue(game.players[citizen].is_alive)
        self.assertFalse(game.russian_mafia_terror_confirmed)

        async def confirm():
            patches = sent.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                first = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_ter", as_uid=terror, actor_uid=900,
                    target_uid=citizen, generation=1,
                )
                second = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_ter", as_uid=terror, actor_uid=terror,
                    target_uid=citizen, generation=1,
                )
                return first, second

        first, second = _run(confirm())
        self.assertEqual(first, "ok")
        self.assertNotEqual(second, "ok")
        self.assertFalse(game.players[terror].is_alive)
        self.assertFalse(game.players[citizen].is_alive)
        self.assertEqual(game.phase, Phase.NIGHT)
        self.assertEqual(game.russian_mafia_night_index, 1)
        self.assertFalse(game.no_host_day1_defense_active)
        self.assertFalse(game.russian_mafia_terror_day_active)

        _gm, won = _prep(8, real=8, observer=True)
        won.russian_mafia_day_index = 0
        won.russian_mafia_night_index = 0
        won.bazpors_narrator_host_day = 0
        night = AsyncMock()

        async def win():
            patches = sent.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
                "bot.russian_mafia_flow.open_night", new=night
            ):
                await open_day(AsyncMock(), won)
                terror_uid = _alive(won, ROLE_TERROR)
                boss = _alive(won, ROLE_GODFATHER)
                await route_russian_player_callback(
                    AsyncMock(), won, act="zrm_ter", as_uid=terror_uid, actor_uid=terror_uid,
                    target_uid=boss, generation=1,
                )
                return await route_russian_player_callback(
                    AsyncMock(), won, act="zok_ter", as_uid=terror_uid, actor_uid=terror_uid,
                    target_uid=boss, generation=1,
                )

        self.assertEqual(_run(win()), "ok")
        self.assertEqual(won.phase, Phase.ENDED)
        self.assertEqual(night.await_count, 0)
        self.assertFalse(won.players[_alive.__wrapped__] if False else won.players[
            next(p.user_id for p in won.players.values() if p.role == ROLE_TERROR)
        ].is_alive)
        self.assertFalse(won.players[next(p.user_id for p in won.players.values() if p.role == ROLE_GODFATHER)].is_alive)

    def test_unused_panel_closes_at_night_and_reopens_on_later_days(self) -> None:
        _gm, game = _prep(8, real=8, observer=True)
        game.russian_mafia_day_index = 0
        game.russian_mafia_night_index = 0
        game.bazpors_narrator_host_day = 0
        sent = _Sent()
        slots: list[str] = []

        async def pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            slots.append(slot)

        async def cycle():
            patches = sent.patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
                "bot.russian_mafia_flow._send_pair", new=pair
            ):
                await open_day(AsyncMock(), game)
                self.assertEqual(slots.count("terror"), 1)
                self.assertTrue(game.russian_mafia_terror_day_active)
                await open_night(AsyncMock(), game)
                self.assertFalse(game.russian_mafia_terror_day_active)
                self.assertNotIn("terror", slots[1:])
                self.assertIn(_alive(game, ROLE_TERROR), required_waiting_player_ids(game))
                self.assertEqual(mafia_shot_holder(game).role, ROLE_GODFATHER)
                stale = await route_russian_player_callback(
                    AsyncMock(), game, act="zok_ter", as_uid=_alive(game, ROLE_TERROR),
                    actor_uid=_alive(game, ROLE_TERROR), target_uid=_alive(game, Role.CITIZEN),
                    generation=1,
                )
                self.assertEqual(stale, "stale")
                self.assertFalse(game.russian_mafia_terror_confirmed)
                await open_day(AsyncMock(), game)
                self.assertEqual(game.russian_mafia_day_index, 2)
                self.assertEqual(slots.count("terror"), 2)
                await open_night(AsyncMock(), game)
                await open_day(AsyncMock(), game)
                self.assertEqual(game.russian_mafia_day_index, 3)
                self.assertEqual(slots.count("terror"), 3)
                old = await route_russian_player_callback(
                    AsyncMock(), game, act="zrm_ter", as_uid=_alive(game, ROLE_TERROR),
                    actor_uid=_alive(game, ROLE_TERROR), target_uid=_alive(game, Role.CITIZEN),
                    generation=2,
                )
                self.assertEqual(old, "stale")
                self.assertTrue(game.players[_alive(game, ROLE_TERROR)].is_alive)

        _run(cycle())

    def test_dead_terror_and_nine_player_games_get_no_panel(self) -> None:
        _gm, game = _prep(8, real=8)
        game.players[_alive(game, ROLE_TERROR)].is_alive = False
        slots: list[str] = []

        async def pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            slots.append(slot)

        async def run():
            with patch("bot.russian_mafia_flow._send_pair", new=pair), patch(
                "bot.russian_mafia_flow.safe_send_message", new=AsyncMock()
            ), patch("bot.observer_delivery.broadcast_to_alive_players", new=AsyncMock()), patch(
                "bot.main.send_no_host_day1_defense_pick_panel", new=AsyncMock()
            ):
                await open_day(AsyncMock(), game)

        _run(run())
        self.assertNotIn("terror", slots)
        self.assertFalse(game.russian_mafia_terror_day_active)

        _gm, nine = _prep(9, real=9)
        slots.clear()

        async def run9():
            with patch("bot.russian_mafia_flow._send_pair", new=pair), patch(
                "bot.observer_delivery.broadcast_to_alive_players", new=AsyncMock()
            ), patch("bot.main.send_no_host_day1_defense_pick_panel", new=AsyncMock()):
                await open_day(AsyncMock(), nine)
                await open_night(AsyncMock(), nine)

        _run(run9())
        self.assertNotIn("terror", slots)
        self.assertFalse(any(p.role == ROLE_TERROR for p in nine.players.values()))
        self.assertFalse(nine.russian_mafia_terror_day_active)

    def test_dead_godfather_gives_terror_the_mafia_shot_not_a_terror_night_panel(self) -> None:
        _gm, game = _prep(8, real=8)
        game.players[_alive(game, ROLE_GODFATHER)].is_alive = False
        slots: list[tuple] = []

        async def pair(bot, game, *, player_uid, slot, text, act, exclude, exclude_uids=None):
            slots.append((slot, player_uid, act))

        async def run():
            with patch("bot.russian_mafia_flow._send_pair", new=pair), patch(
                "bot.observer_delivery.safe_send_message_return", new=AsyncMock(return_value=SimpleNamespace(message_id=1))
            ), patch("bot.russian_mafia_flow.safe_send_message", new=AsyncMock()), patch(
                "bot.observer_delivery.broadcast_to_alive_players", new=AsyncMock()
            ):
                game.phase = Phase.DAY_DISCUSSION
                game.russian_mafia_day_index = 1
                game.russian_mafia_terror_day_active = True
                await open_night(AsyncMock(), game)

        _run(run())
        terror = _alive(game, ROLE_TERROR)
        self.assertEqual([(slot, uid) for slot, uid, _act in slots if slot == "mafia"], [("mafia", terror)])
        self.assertNotIn("terror", [slot for slot, _uid, _act in slots])
        self.assertNotIn("zrm_ter", [act for _slot, _uid, act in slots])
        self.assertNotIn(terror, required_waiting_player_ids(game))
        self.assertEqual(mafia_shot_holder(game).user_id, terror)


if __name__ == "__main__":
    unittest.main()
