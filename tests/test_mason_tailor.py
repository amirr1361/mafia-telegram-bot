"""تست جذب تایلر — سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_night_role import MSM_TAILOR, dispatch_mason_night_role
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


def _mason_game(gm: GameManager, *, n: int = 15):
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


def _setup_mason_team(game, gm) -> Player:
    mason = _p(10, "Amir", Role.MASON)
    gm.add_player(game, mason)
    ms_mf.initialize_mason_team_for_new_game(game)
    return mason


class MasonTailorPanelTests(unittest.TestCase):
    def test_panel_includes_tailor_when_alive(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        labels = ms_mf.mason_recruit_panel_button_labels(game, mason)
        self.assertIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, labels)
        self.assertIn(ms_mf.MASON_NO_RECRUIT_LABEL, labels)

    def test_panel_excludes_tailor_when_not_in_room(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        mason = _setup_mason_team(game, gm)
        gm.add_player(game, _p(20, "Hasan", Role.TOWN_SIMPLE))
        labels = ms_mf.mason_recruit_panel_button_labels(game, mason)
        self.assertNotIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, labels)

    def test_panel_includes_tailor_button_when_dead(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        labels = ms_mf.mason_recruit_panel_button_labels(game, mason)
        self.assertIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, labels)
        self.assertNotIn("Tyler", labels)

    def test_dead_tailor_name_not_in_normal_player_buttons(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        town = _p(20, "Hasan", Role.TOWN_SIMPLE)
        gm.add_player(game, tailor)
        gm.add_player(game, town)
        labels = ms_mf.mason_recruit_panel_button_labels(game, mason)
        self.assertIn("Hasan", labels)
        self.assertNotIn("Tyler", labels)
        self.assertIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, labels)

    def test_panel_excludes_tailor_when_already_on_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        game.mason_team_member_ids.add(40)
        labels = ms_mf.mason_recruit_panel_button_labels(game, mason)
        self.assertNotIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, labels)

    def test_panel_excludes_tailor_after_consumed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        game.mason_tyler_button_consumed = True
        labels = ms_mf.mason_recruit_panel_button_labels(game, mason)
        self.assertNotIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, labels)

    def test_dead_tailor_button_still_shows_after_normal_recruit_night1(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        town = _p(20, "Hasan", Role.TOWN_SIMPLE)
        gm.add_player(game, tailor)
        gm.add_player(game, town)
        ms_mf.commit_mason_recruit(game, mason, town)
        ms_mf.clear_mason_recruit_night_state(game)
        labels = ms_mf.mason_recruit_panel_button_labels(game, mason)
        self.assertIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, labels)
        self.assertNotIn("Hasan", labels)
        self.assertNotIn("Tyler", labels)


class MasonTailorRecruitTests(unittest.TestCase):
    def test_selecting_tailor_adds_to_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        msg = ms_mf.commit_mason_recruit_tailor(game, mason)
        self.assertIsNotNone(msg)
        self.assertTrue(ms_mf.is_mason_team_member(game, tailor))
        self.assertEqual(game.mason_pending_recruit_uid, 40)

    def test_selecting_tailor_sends_normal_membership_message(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        msg = ms_mf.commit_mason_recruit_tailor(game, mason)
        assert msg is not None
        self.assertIn("شما عضو تیم ماسون شدید", msg)
        self.assertIn("نقش ماسون متعلق به", msg)
        self.assertIn("Amir", msg)

    def test_selecting_tailor_does_not_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        ms_mf.commit_mason_recruit_tailor(game, mason)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)
        self.assertEqual(result.eliminated_uids, ())

    def test_selecting_alive_tailor_consumes_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        ms_mf.commit_mason_recruit_tailor(game, mason)
        self.assertTrue(game.mason_tyler_button_consumed)
        self.assertFalse(ms_mf.mason_show_tailor_recruit_button(game, mason))

    def test_dead_tailor_removed_from_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        ms_mf.commit_mason_recruit_tailor(game, mason)
        tailor.is_alive = False
        ms_mf.remove_dead_from_mason_team(game)
        self.assertFalse(ms_mf.is_mason_team_member(game, tailor))
        self.assertNotIn(40, game.mason_team_member_ids)


class MasonDeadTailorRecruitTests(unittest.TestCase):
    def test_selecting_dead_tailor_marks_no_recruit(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        self.assertTrue(ms_mf.commit_mason_recruit_dead_tailor(game, mason))
        self.assertTrue(game.mason_mason_night_no_recruit)
        self.assertIsNone(game.mason_pending_recruit_uid)

    def test_selecting_dead_tailor_does_not_add_team_member(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        before = set(game.mason_team_member_ids)
        ms_mf.commit_mason_recruit_dead_tailor(game, mason)
        self.assertEqual(game.mason_team_member_ids, before)

    def test_selecting_dead_tailor_does_not_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        ms_mf.commit_mason_recruit_dead_tailor(game, mason)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)
        self.assertEqual(result.eliminated_uids, ())

    def test_selecting_dead_tailor_consumes_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        ms_mf.commit_mason_recruit_dead_tailor(game, mason)
        self.assertTrue(game.mason_tyler_button_consumed)
        self.assertFalse(ms_mf.mason_show_tailor_recruit_button(game, mason))


class MasonDeadTailorDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dead_tailor_dispatch_shows_unavailable_message(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        game.no_host_night_parallel_collect_active = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        finalized: list[str] = []

        async def _capture(bot_, game_, gm_, uid, ui_key, text):
            finalized.append(text)

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(side_effect=_capture),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.mason_recruit_delivery.deliver_mason_recruit_membership_message",
            new=AsyncMock(),
        ) as deliver:
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=mason.user_id,
                actor_uid=mason.user_id,
                act=MSM_TAILOR,
                tid=tailor.user_id,
            )

        deliver.assert_not_awaited()
        self.assertEqual(finalized, [ms_mf.MASON_DEAD_TAILOR_UNAVAILABLE_TEXT])
        self.assertTrue(game.mason_night_mason_confirmed)
        self.assertTrue(game.mason_mason_night_no_recruit)
        self.assertTrue(game.mason_tyler_button_consumed)

    async def test_dead_tailor_dispatch_does_not_add_team_member(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason_team(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, alive=False)
        gm.add_player(game, tailor)
        game.no_host_night_parallel_collect_active = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
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
                as_uid=mason.user_id,
                actor_uid=mason.user_id,
                act=MSM_TAILOR,
                tid=tailor.user_id,
            )

        self.assertEqual(game.mason_team_member_ids, {mason.user_id})


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_bazpors_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        mason = _p(10, "M", Role.MASON)
        tailor = _p(40, "T", Role.TAILOR)
        gm.add_player(game, mason)
        gm.add_player(game, tailor)
        self.assertFalse(ms_mf.mason_show_tailor_recruit_button(game, mason))
        self.assertIsNone(ms_mf.commit_mason_recruit_tailor(game, mason))
        self.assertFalse(ms_mf.commit_mason_recruit_dead_tailor(game, mason))

    def test_mozakere_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        mason = _p(10, "M", Role.MASON)
        tailor = _p(40, "T", Role.TAILOR)
        gm.add_player(game, mason)
        gm.add_player(game, tailor)
        self.assertFalse(ms_mf.mason_tailor_in_room_roles(game))
        self.assertIsNone(ms_mf.find_alive_mason_tailor(game))
        self.assertFalse(ms_mf.commit_mason_recruit_dead_tailor(game, mason))
