"""پنل بازپرس — فقط بازپرس و ناظر (no_host)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import Role, _find_alive_role
from bot.game import GameManager
from bot.models import Game, Player
from bot.no_host_interrogator_night import (
    _ensure_interrogator_observer_mirror,
    no_host_interrog_act_active,
    start_no_host_interrogator_night_flow,
)
from bot.no_host_night_ready import all_no_host_parallel_night_ready


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def _game() -> Game:
    players = {
        900: _p(900, 1, "دستیار", Role.CITIZEN),
        501: _p(501, 2, "پزشک", Role.DOCTOR),
        -3: _p(-3, 3, "بازپرس", Role.INTERROGATOR),
        -1: _p(-1, 4, "شهروند", Role.CITIZEN),
    }
    game = Game(
        room_code="int1",
        host_id=100,
        scenario_name="bazpors",
        players=players,
        max_players=13,
    )
    game.bazpors_host_mode = "no_host"
    game.bot_assistant_user_id = 900
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = "night_start"
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    return game


class NoHostInterrogatorNightTests(unittest.TestCase):
    def test_interrog_mirror_acts(self) -> None:
        self.assertTrue(no_host_interrog_act_active(_game(), "nii1"))
        self.assertFalse(no_host_interrog_act_active(_game(), "i1"))

    def test_ready_includes_interrogator_when_confirmed(self) -> None:
        game = _game()
        game.no_host_citizen_night_confirmed_uids = [-1, 900]
        game.no_host_ruintan_night_confirmed = True
        game.no_host_night1_hunter_done = True
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.no_host_shiad_pick_confirmed = True
        game.no_host_detective_pick_confirmed = True
        game.no_host_doctor_pick_confirmed = True
        game.no_host_sniper_pick_confirmed = True
        game.no_host_interrog_pick_confirmed = True
        self.assertTrue(all_no_host_parallel_night_ready(game))

    def test_interrogator_found(self) -> None:
        game = _game()
        pl = _find_alive_role(game, Role.INTERROGATOR)
        self.assertIsNotNone(pl)
        self.assertEqual(pl.user_id, -3)


class NoHostInterrogatorObserverMirrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_interrogator_backfills_observer_mirror(self) -> None:
        gm = GameManager()
        game = _game()
        game.observer_user_id = 300
        game.observer_prompt_status = "registered"
        game.no_host_interrog_dm_signature = "1:interrog:night_entry"
        game.no_host_interrog_flow_active = True
        game.no_host_interrog_ui_phase = "int1"
        bot = AsyncMock()
        with patch(
            "bot.no_host_interrogator_night.ensure_observer_mirror_prompt",
            new_callable=AsyncMock,
        ) as ensure:
            ensure.return_value = True
            sent = await _ensure_interrogator_observer_mirror(bot, game, gm)
        self.assertTrue(sent)
        ensure.assert_awaited_once()

    async def test_start_flow_uses_publish_with_fresh_observer_copy(self) -> None:
        gm = GameManager()
        game = _game()
        game.observer_user_id = 300
        game.observer_prompt_status = "registered"
        bot = AsyncMock()
        with patch(
            "bot.no_host_interrogator_night.publish_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as publish:
            ok = await start_no_host_interrogator_night_flow(
                bot, game, gm, at_night_entry=True
            )
        self.assertTrue(ok)
        publish.assert_awaited_once()
        self.assertTrue(publish.await_args.kwargs.get("fresh_observer_copy"))


if __name__ == "__main__":
    unittest.main()
