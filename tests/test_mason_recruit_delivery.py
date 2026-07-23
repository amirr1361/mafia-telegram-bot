"""ارسال پیام عضویت پس از جذب — سناریوی ماسون (Room 53 style)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_night_role import MSM_PICK, MSM_TAILOR, dispatch_mason_night_role
from bot.models import Player, Role
from bot.observer_delivery import observer_player_copy_prefix
from bot.roles import mason_fraternity as ms_mf


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
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


def _setup_mason(game, gm) -> Player:
    mason = _p(10, "Amir", Role.MASON, seat=1)
    gm.add_player(game, mason)
    ms_mf.initialize_mason_team_for_new_game(game)
    return mason


class MasonRecruitDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def _dispatch_tailor_recruit(self, game, gm, *, mason_uid: int, tailor_uid: int):
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        delivered: list[tuple[int, str]] = []

        async def _capture(bot_, g, uid, text, **kw):
            delivered.append((uid, text))

        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            new=AsyncMock(side_effect=_capture),
        ), patch(
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
                as_uid=mason_uid,
                actor_uid=mason_uid,
                act=MSM_TAILOR,
                tid=tailor_uid,
            )
        return delivered

    async def test_tailor_recruit_delivers_membership_message(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, seat=5)
        gm.add_player(game, tailor)
        delivered = await self._dispatch_tailor_recruit(
            game, gm, mason_uid=mason.user_id, tailor_uid=tailor.user_id
        )
        self.assertEqual(len(delivered), 1)
        uid, text = delivered[0]
        self.assertEqual(uid, tailor.user_id)
        self.assertIn("شما عضو تیم ماسون شدید", text)
        self.assertIn("نقش ماسون متعلق به", text)
        self.assertIn("Amir", text)
        self.assertTrue(ms_mf.is_mason_team_member(game, tailor))
        self.assertEqual(game.mason_pending_recruit_uid, tailor.user_id)

    async def test_synthetic_tailor_still_delivers_via_helper(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        syn_tailor = -920053
        self.assertTrue(is_synthetic_player_uid(syn_tailor))
        tailor = _p(syn_tailor, "SynTyler", Role.TAILOR, seat=5)
        gm.add_player(game, tailor)
        delivered = await self._dispatch_tailor_recruit(
            game, gm, mason_uid=mason.user_id, tailor_uid=tailor.user_id
        )
        self.assertEqual(len(delivered), 1)
        uid, text = delivered[0]
        self.assertEqual(uid, syn_tailor)
        self.assertIn("شما عضو تیم ماسون شدید", text)

    async def test_observer_mirror_for_real_tailor(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR, seat=5)
        gm.add_player(game, tailor)
        bot = MagicMock()
        sends: list[tuple[int, str]] = []

        async def _capture(bot_, uid, text, **kw):
            sends.append((uid, text))

        cb = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            side_effect=_capture,
        ), patch(
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

        player_msgs = [text for uid, text in sends if uid == tailor.user_id]
        observer_msgs = [text for uid, text in sends if uid == 999]
        self.assertEqual(len(player_msgs), 1)
        self.assertEqual(len(observer_msgs), 1)
        self.assertIn("شما عضو تیم ماسون شدید", player_msgs[0])
        prefix = observer_player_copy_prefix(game, tailor.user_id)
        self.assertTrue(observer_msgs[0].startswith(prefix))
        self.assertIn("تایلر", observer_msgs[0])
        self.assertIn("Tyler", observer_msgs[0])
        self.assertIn("شما عضو تیم ماسون شدید", observer_msgs[0])

    async def test_observer_mirror_for_synthetic_tailor(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        syn_tailor = -920053
        tailor = _p(syn_tailor, "SynTyler", Role.TAILOR, seat=5)
        gm.add_player(game, tailor)
        bot = MagicMock()
        sends: list[tuple[int, str]] = []

        async def _capture(bot_, uid, text, **kw):
            sends.append((uid, text))

        cb = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            side_effect=_capture,
        ), patch(
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

        self.assertFalse(any(uid == syn_tailor for uid, _ in sends))
        observer_msgs = [text for uid, text in sends if uid == 999]
        self.assertEqual(len(observer_msgs), 1)
        self.assertIn("ناظر — پیام صندلی", observer_msgs[0])
        self.assertIn("تایلر", observer_msgs[0])
        self.assertIn("شما عضو تیم ماسون شدید", observer_msgs[0])

    async def test_town_pick_also_delivers_membership_message(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        mason = _setup_mason(game, gm)
        town = _p(20, "Hasan", Role.TOWN_SIMPLE, seat=2)
        gm.add_player(game, town)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        delivered: list[tuple[int, str]] = []

        async def _capture(bot_, g, uid, text, **kw):
            delivered.append((uid, text))

        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            new=AsyncMock(side_effect=_capture),
        ), patch(
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
                act=MSM_PICK,
                tid=town.user_id,
            )

        self.assertEqual(delivered, [(20, delivered[0][1])])
        self.assertIn("شما عضو تیم ماسون شدید", delivered[0][1])

    def test_tailor_recruit_does_not_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        ms_mf.commit_mason_recruit_tailor(game, mason)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)
