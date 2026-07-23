"""تست پنل‌های تفنگدار و خرابکار — سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.mason_night_role import (
    MASON_SABOTEUR_GUN_SPENT_TEXT,
    MGN_NONE,
    MSB_NONE,
    MSB_OK,
    dispatch_mason_gunner_panel,
    dispatch_mason_night_role,
    dispatch_mason_saboteur_panel,
)
from bot.models import Player, Role
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_saboteur as ms_sb


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.no_host_assistant_narrator_active = True
    return game


def _setup_players(gm, game):
    gunner = _p(10, "Gn", Role.GUNMAN)
    sab = _p(2, "Sb", Role.SABOTEUR)
    holder = _p(20, "Holder", Role.TOWN_SIMPLE)
    other = _p(30, "Other", Role.TOWN_SIMPLE)
    victim = _p(40, "Victim", Role.TOWN_SIMPLE)
    for pl in (gunner, sab, holder, other, victim):
        gm.add_player(game, pl)
    return gunner, sab, holder, other, victim


def _give_gun_and_prepare(game, gunner, holder):
    ms_gn.commit_mason_gunner_target(game, gunner, holder)
    ms_gn.prepare_mason_day_gun_from_night_choices(game)


class MasonSaboteurGunSpentPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_spent_gun_sends_no_action_ok_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner, sab, holder, _other, victim = _setup_players(gm, game)
        _give_gun_and_prepare(game, gunner, holder)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        bot = MagicMock()
        captured: list[tuple[str, str | None]] = []

        async def _capture(_bot, _game, _uid, _ui, text, kb, **kw):
            captured.append((text, kb.inline_keyboard[0][0].text if kb else None))

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_saboteur_panel(bot, game, gm)

        self.assertEqual(len(captured), 1)
        text, btn = captured[0]
        self.assertIn(MASON_SABOTEUR_GUN_SPENT_TEXT, text)
        self.assertIn("اوکی", btn or "")
        self.assertFalse(game.mason_night_saboteur_confirmed)

    async def test_observer_ok_satisfies_saboteur_readiness(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920002
        gm.add_player(game, _p(syn, "SynSb", Role.SABOTEUR))
        game.mason_gun_spent = True
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_guardian_confirmed = True
        game.mason_night_mason_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_natasha_confirmed = True
        game.mason_night_priest_confirmed = True
        self.assertTrue(is_synthetic_player_uid(syn))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=syn,
                actor_uid=999,
                act=MSB_OK,
                tid=0,
            )
        self.assertTrue(game.mason_night_saboteur_confirmed)

    async def test_unused_gun_holder_still_gets_saboteur_pick_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner, _sab, holder, _other, _victim = _setup_players(gm, game)
        _give_gun_and_prepare(game, gunner, holder)
        bot = MagicMock()
        captured_kb = []

        async def _capture(_bot, _game, _uid, _ui, _text, kb, **kw):
            captured_kb.append(kb)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_saboteur_panel(bot, game, gm)

        labels = [
            btn.text
            for row in captured_kb[0].inline_keyboard
            for btn in row
        ]
        self.assertIn("انتخابی ندارم", labels)

    async def test_holder_death_returns_gun_saboteur_still_picks(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner, _sab, holder, _other, _victim = _setup_players(gm, game)
        _give_gun_and_prepare(game, gunner, holder)
        holder.is_alive = False
        ms_gn.refresh_mason_day_gun_holder_if_eliminated(game)
        self.assertTrue(ms_sb.mason_saboteur_needs_night_pick(game))
        self.assertTrue(ms_gn.mason_gunner_can_give_gun(game))


class MasonGunnerSaboteurNoneButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_gunner_panel_includes_none_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _setup_players(gm, game)
        bot = MagicMock()
        captured_kb = []

        async def _capture(_bot, _game, _uid, _ui, _text, kb, **kw):
            captured_kb.append(kb)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_gunner_panel(bot, game, gm)

        labels = [
            btn.text
            for row in captured_kb[0].inline_keyboard
            for btn in row
        ]
        self.assertIn("انتخابی ندارم", labels)

    async def test_gunner_none_does_not_spend_gun(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner, _sab, _holder, _other, _victim = _setup_players(gm, game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role._after_role_confirmed",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=10,
                actor_uid=10,
                act=MGN_NONE,
                tid=0,
            )
        self.assertTrue(game.mason_gunner_night_no_give)
        self.assertFalse(ms_gn.mason_gun_is_spent(game))
        self.assertTrue(game.mason_night_gunner_confirmed)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        self.assertIsNone(ms_gn.mason_day_gun_holder_uid(game))
        self.assertTrue(ms_gn.mason_gunner_can_give_gun(game))

    async def test_saboteur_panel_includes_none_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _setup_players(gm, game)
        bot = MagicMock()
        captured_kb = []

        async def _capture(_bot, _game, _uid, _ui, _text, kb, **kw):
            captured_kb.append(kb)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_saboteur_panel(bot, game, gm)

        labels = [
            btn.text
            for row in captured_kb[0].inline_keyboard
            for btn in row
        ]
        self.assertIn("انتخابی ندارم", labels)

    async def test_saboteur_none_completes_action(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _setup_players(gm, game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role._after_role_confirmed",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=2,
                actor_uid=2,
                act=MSB_NONE,
                tid=0,
            )
        self.assertTrue(game.mason_saboteur_night_no_sabotage)
        self.assertTrue(game.mason_night_saboteur_confirmed)
        self.assertIsNone(game.mason_saboteur_night_target_uid)


class MasonSaboteurReadinessTests(unittest.TestCase):
    def test_readiness_blocked_saboteur_until_ok_when_gun_spent(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(2, "Sb", Role.SABOTEUR))
        game.mason_gun_spent = True
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 900
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.mason_night_saboteur_confirmed = False
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_guardian_confirmed = True
        game.mason_night_mason_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_natasha_confirmed = True
        game.mason_night_priest_confirmed = True
        self.assertFalse(all_mason_parallel_night_ready(game))


if __name__ == "__main__":
    unittest.main()
