"""بازنشستن پنل‌های مشورت تیم ماسون پس از فروپاشی — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_helper_flow import (
    handle_mason_helper_action,
    mason_team_consult_should_prompt,
    maybe_retire_mason_team_consultation_on_vote_start,
    mason_team_consultation_prompts_suppressed,
    send_mason_midday_step_prompt,
    send_mason_team_consult_prompt,
)
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.models import Player, Role
from bot.roles import mason_fraternity as ms_mf


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.observer_prompt_status = "registered"
    game.no_host_assistant_narrator_active = True
    return game


def _setup_mason_team(game, gm):
    mason = _p(10, "Mason", Role.MASON)
    hasan = _p(20, "Hasan", Role.TOWN_SIMPLE)
    gm.add_player(game, mason)
    gm.add_player(game, hasan)
    ms_mf.commit_mason_recruit(game, mason, hasan)
    ms_mf.resolve_mason_recruitment_result(game)
    return mason, hasan


class MasonCollapseConsultationRetirementTests(unittest.IsolatedAsyncioTestCase):
    async def test_before_collapse_both_prompts_sent(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 2
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await send_mason_midday_step_prompt(bot, game)
            await send_mason_team_consult_prompt(bot, game)
        self.assertEqual(register.await_count, 2)

    async def test_after_collapse_same_night_midday_still_sent(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 1
        game.bazpors_narrator_host_day = 1
        game.mason_collapse_night_number = 1
        game.mason_last_night_had_collapse = True
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await send_mason_midday_step_prompt(bot, game)
        register.assert_awaited_once()

    async def test_after_collapse_next_day_before_vote_prompts_still_sent(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 2
        game.bazpors_narrator_host_day = 2
        game.mason_collapse_night_number = 1
        self.assertFalse(game.mason_team_consultation_retired)
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await send_mason_midday_step_prompt(bot, game)
            await send_mason_team_consult_prompt(bot, game)
        self.assertEqual(register.await_count, 2)

    def test_vote_start_after_full_day_retires_consultation(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.mason_collapse_night_number = 1
        game.bazpors_narrator_host_day = 2
        maybe_retire_mason_team_consultation_on_vote_start(game)
        self.assertTrue(game.mason_team_consultation_retired)

    def test_vote_start_same_day_as_collapse_does_not_retire(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.mason_collapse_night_number = 1
        game.bazpors_narrator_host_day = 1
        maybe_retire_mason_team_consultation_on_vote_start(game)
        self.assertFalse(game.mason_team_consultation_retired)

    async def test_retired_suppresses_prompt_a(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.mason_team_consultation_retired = True
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await send_mason_midday_step_prompt(bot, game)
        register.assert_not_awaited()
        self.assertTrue(mason_team_consultation_prompts_suppressed(game))

    async def test_retired_suppresses_prompt_b(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        game.mason_team_consultation_retired = True
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await send_mason_team_consult_prompt(bot, game)
        register.assert_not_awaited()

    async def test_vote_ok_triggers_retirement(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.mason_collapse_night_number = 1
        game.bazpors_narrator_host_day = 2
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.apply_mirror_claim_winner",
            new=AsyncMock(),
        ), patch(
            "bot.mason_day_ability.dismiss_mason_day_ability_panels",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_phase.no_host_run_day1_end_vote_flow",
            new=AsyncMock(),
        ):
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="vote",
            )
        self.assertTrue(game.mason_team_consultation_retired)

    async def test_future_nights_never_show_prompts_after_retirement(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.mason_team_consultation_retired = True
        bot = MagicMock()
        for night in (3, 4, 5):
            game.bazpors_narrator_night_count = night
            game.mason_midday_step_prompt_sent = False
            game.mason_team_consult_prompt_sent = False
            with patch(
                "bot.mason_helper_flow.register_mirror_prompt_pair",
                new=AsyncMock(),
            ) as register:
                await send_mason_midday_step_prompt(bot, game)
                await send_mason_team_consult_prompt(bot, game)
            register.assert_not_awaited()

    def test_night_resolve_records_collapse_night_once(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 1
        mason, hasan = _setup_mason_team(game, gm)
        ms_mf.clear_mason_recruit_night_state(game)
        mafia = _p(30, "Boss", Role.GODFATHER)
        gm.add_player(game, mafia)
        ms_mf.commit_mason_recruit(game, mason, mafia)
        apply_mason_night_resolution(game, gm)
        self.assertEqual(game.mason_collapse_night_number, 1)
        self.assertTrue(game.mason_last_night_had_collapse)

        game.mason_night_resolution_applied = False
        game.mason_last_night_had_collapse = False
        ms_mf.clear_mason_recruit_night_state(game)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        apply_mason_night_resolution(game, gm)
        self.assertEqual(game.mason_collapse_night_number, 1)

    async def test_mafia_consult_still_sent_when_retired(self) -> None:
        from bot.mason_helper_flow import send_mason_mafia_consult_prompt

        gm = GameManager()
        game = _mason_game(gm)
        game.mason_team_consultation_retired = True
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await send_mason_mafia_consult_prompt(bot, game)
        register.assert_awaited_once()

    async def test_mafia_consult_ok_sends_team_consult_when_not_retired(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        game.mason_collapse_night_number = 1
        game.bazpors_narrator_host_day = 1
        self.assertFalse(game.mason_team_consultation_retired)
        self.assertTrue(mason_team_consult_should_prompt(game))
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.apply_mirror_claim_winner",
            new=AsyncMock(),
        ), patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new=AsyncMock(),
        ) as team, patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new=AsyncMock(),
        ) as night:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="consult",
            )
        team.assert_awaited_once()
        night.assert_not_awaited()

    async def test_mafia_consult_ok_skips_team_consult_and_starts_night_when_retired(
        self,
    ) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        game.mason_team_consultation_retired = True
        self.assertFalse(mason_team_consult_should_prompt(game))
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.apply_mirror_claim_winner",
            new=AsyncMock(),
        ), patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new=AsyncMock(),
        ) as team, patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new=AsyncMock(),
        ) as night:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="consult",
            )
        team.assert_not_awaited()
        night.assert_awaited_once()

    async def test_collapse_alone_does_not_suppress_team_consult_prompt(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 2
        game.bazpors_narrator_host_day = 2
        game.mason_collapse_night_number = 1
        self.assertFalse(game.mason_team_consultation_retired)
        self.assertTrue(mason_team_consult_should_prompt(game))


class MasonCollapseConsultationNewGameResetTests(unittest.TestCase):
    def test_assign_roles_resets_collapse_consultation_state(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        for i in range(12):
            gm.add_player(game, _p(100 + i, f"P{i}", Role.TOWN_SIMPLE))
        game.mason_collapse_night_number = 2
        game.mason_team_consultation_retired = True
        game.mason_last_night_had_collapse = True

        gm.assign_roles(game)

        self.assertIsNone(game.mason_collapse_night_number)
        self.assertFalse(game.mason_team_consultation_retired)
        self.assertFalse(game.mason_last_night_had_collapse)


class BazporsMozakereUnchangedTests(unittest.IsolatedAsyncioTestCase):
    async def test_bazpors_no_mason_retirement_fields(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertFalse(mason_team_consultation_prompts_suppressed(game))
        maybe_retire_mason_team_consultation_on_vote_start(game)
        self.assertFalse(game.mason_team_consultation_retired)

    async def test_mozakere_no_mason_retirement_fields(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertFalse(mason_team_consultation_prompts_suppressed(game))
        game.mason_collapse_night_number = 2
        game.bazpors_narrator_host_day = 5
        maybe_retire_mason_team_consultation_on_vote_start(game)
        self.assertFalse(game.mason_team_consultation_retired)
