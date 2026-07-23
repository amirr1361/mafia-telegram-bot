"""پیام نهایی پس از تأیید انتخاب شب — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_night_role import (
    MGD_PICK,
    MSD_PICK,
    MSD_DONE,
    MSS_NONE,
    MSM_NONE,
    build_mason_night_finalized_selection_label,
    dispatch_mason_night_role,
)
from bot.models import Player, Role
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_msn
from bot.roles import mason_guardian as ms_gd
from bot.roles import mason_sniper as ms_sn
from bot.roles.detective import commit_pick as detective_commit_pick


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
    return game


class MasonNightFinalizedLabelTests(unittest.TestCase):
    def test_guardian_shows_selected_player(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Guardian", Role.BODYGUARD))
        gm.add_player(game, _p(20, "Target", Role.TOWN_SIMPLE))
        ms_gd.commit_mason_guardian_night_pick(game, 20)
        label = build_mason_night_finalized_selection_label(
            game, gm, "mason_guardian"
        )
        self.assertIn("Target", label)
        self.assertNotEqual(label, "انتخابی ندارم")

    def test_doctor_shows_all_saved_players(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        for i in range(10):
            gm.add_player(game, _p(100 + i, f"F{i}", Role.TOWN_SIMPLE))
        ms_doc.commit_mason_doctor_save(game, 21)
        ms_doc.commit_mason_doctor_save(game, 22)
        label = build_mason_night_finalized_selection_label(game, gm, "mason_doctor")
        self.assertIn("A", label)
        self.assertIn("B", label)
        self.assertNotIn("انتخابی ندارم", label)

    def test_doctor_no_save_shows_none_label(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        label = build_mason_night_finalized_selection_label(game, gm, "mason_doctor")
        self.assertEqual(label, "انتخابی ندارم")

    def test_sniper_no_shot_shows_explicit_none(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        ms_sn.clear_mason_sniper_night_selection(game)
        label = build_mason_night_finalized_selection_label(game, gm, "mason_sniper")
        self.assertEqual(label, "بدون شلیک")

    def test_sniper_shows_selected_targets(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [21])
        label = build_mason_night_finalized_selection_label(game, gm, "mason_sniper")
        self.assertIn("A", label)

    def test_mason_recruit_no_pick(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _p(60, "Mason", Role.MASON)
        gm.add_player(game, mason)
        ms_msn.commit_mason_recruit(game, mason, None)
        label = build_mason_night_finalized_selection_label(game, gm, "mason_recruit")
        self.assertEqual(label, "انتخابی ندارم")

    def test_detective_shows_inquiry_target(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(70, "Det", Role.DETECTIVE))
        gm.add_player(game, _p(21, "Suspect", Role.SPY))
        detective_commit_pick(game, 21)
        label = build_mason_night_finalized_selection_label(
            game, gm, "mason_detective"
        )
        self.assertIn("Suspect", label)


class MasonNightFinalizedDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_guardian_confirm_sends_target_in_final_message(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Guardian", Role.BODYGUARD))
        gm.add_player(game, _p(20, "Target", Role.TOWN_SIMPLE))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        captured: list[str] = []

        async def _capture_finalize(
            bot_, game_, gm_, uid, ui_key, selection_label, **kw
        ):
            captured.append(selection_label)

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            side_effect=_capture_finalize,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=30,
                actor_uid=30,
                act=MGD_PICK,
                tid=20,
            )
        self.assertEqual(len(captured), 1)
        self.assertIn("Target", captured[0])
        self.assertNotEqual(captured[0], "انتخابی ندارم")

    async def test_guardian_observer_mirror_uses_same_label(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Guardian", Role.BODYGUARD))
        gm.add_player(game, _p(20, "Target", Role.TOWN_SIMPLE))
        game.mason_night_guardian_confirmed = False
        bot = MagicMock()
        bodies: list[str] = []

        async def _capture_update(
            bot_, game_, ui_key, body, markup, *, assistant_uid, **kw
        ):
            bodies.append(body)

        cb = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.no_host_night_common.update_mirror_prompt_pair",
            side_effect=_capture_update,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=30,
                actor_uid=30,
                act=MGD_PICK,
                tid=20,
            )
        self.assertEqual(len(bodies), 1)
        self.assertIn("Target", bodies[0])
        self.assertIn("✅ انتخاب شما:", bodies[0])
        self.assertNotIn("✅ انتخاب شما: <b>انتخابی ندارم</b>", bodies[0])

    async def test_doctor_done_with_no_saves_shows_none(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        captured: list[str] = []

        async def _capture_finalize(
            bot_, game_, gm_, uid, ui_key, selection_label, **kw
        ):
            captured.append(selection_label)

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            side_effect=_capture_finalize,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=40,
                actor_uid=40,
                act=MSD_DONE,
                tid=0,
            )
        self.assertEqual(captured, ["انتخابی ندارم"])

    async def test_sniper_none_shows_explicit_no_shot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        captured: list[str] = []

        async def _capture_finalize(
            bot_, game_, gm_, uid, ui_key, selection_label, **kw
        ):
            captured.append(selection_label)

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            side_effect=_capture_finalize,
        ), patch(
            "bot.mason_night_role.dispatch_mason_commander_panel",
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
                as_uid=50,
                actor_uid=50,
                act=MSS_NONE,
                tid=0,
            )
        self.assertEqual(captured, ["بدون شلیک"])


if __name__ == "__main__":
    unittest.main()
