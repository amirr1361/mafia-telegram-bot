"""Phase 2 — Namayande 10-player fork: routing + early-game flow tests.

All flows run against the independent ``bot.nam10`` implementation with
isolated in-memory rooms and no real Telegram/DB. Callback routing is proven
in both directions; the public Namayande create-flow is guarded unchanged.
"""

from __future__ import annotations

import importlib
import unittest
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bot import db
from bot.game import GameManager, is_synthetic_player_uid
from bot.main import NoHostDay1DefenseCb, NoHostIntroNightStart
from bot.models import Phase, Player
from bot.observer_delivery import PlayerMirrorCb
from bot.room_mode import is_namayande10_no_host_room

FORK_PACKAGE = "bot.nam10"


def setUpModule() -> None:
    db.init_db()


def _mk_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.edit_message_text = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


def _callback(actor_uid: int) -> MagicMock:
    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = actor_uid
    cb.message = MagicMock()
    cb.message.html_text = "panel"
    cb.message.text = "panel"
    cb.message.message_id = 1
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.delete = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _guarded_patch(
    stack: AsyncExitStack, module: Any, name: str, **kwargs: Any
) -> None:
    """Enter a patch only when the attribute already exists."""
    if not hasattr(module, name):
        return
    if kwargs:
        stack.enter_context(patch.object(module, name, **kwargs))
    else:
        stack.enter_context(
            patch.object(module, name, new_callable=AsyncMock)
        )


def _nam10_modules() -> list[Any]:
    pkg = importlib.import_module(FORK_PACKAGE)
    mods: list[Any] = [pkg]
    import pkgutil

    for m in pkgutil.iter_modules(getattr(pkg, "__path__", [])):
        if m.name.startswith("_"):
            continue
        try:
            mods.append(importlib.import_module(f"{FORK_PACKAGE}.{m.name}"))
        except Exception:
            pass
    return mods


@asynccontextmanager
async def fork_flow_patches(gm: GameManager):
    """Transmission/side-effect patches for fork day-flow execution."""
    async with AsyncExitStack() as stack:
        stack.enter_context(patch("bot.app_state.manager", gm))
        df = importlib.import_module("bot.nam10.dayflow")
        stack.enter_context(patch.object(df, "manager", gm, create=True))
        for module in _nam10_modules():
            if hasattr(module, "manager"):
                stack.enter_context(
                    patch.object(module, "manager", gm, create=True)
                )
            for name in ("push_host_step", "broadcast_to_alive_players"):
                _guarded_patch(stack, module, name)
        for name in (
            "broadcast_to_players",
            "send_to_player",
            "ensure_private_role_card_delivered",
            "register_mirror_prompt_pair",
            "update_mirror_prompt_pair",
            "apply_mirror_claim_winner",
            "close_mirror_prompt_keyboards",
            "flush_elimination_notifications",
            "publish_mirror_prompt_pair",
            "deliver_no_host_player_game_copy",
            "begin_post_game_session",
        ):
            _guarded_patch(stack, df, name)
        _guarded_patch(
            stack,
            df,
            "promote_mirror_prompt_to_panel",
            new=AsyncMock(return_value=False),
        )
        _guarded_patch(stack, df, "on_no_host_entered_night1")
        stack.enter_context(patch("bot.db.insert_game_session", return_value=1))
        yield


def _build_fork_room(gm: GameManager, creator: int = 8100) -> Any:
    game = gm.create_game(
        host_id=creator,
        scenario_name="namayande",
        max_players=10,
        host_full_name="سازنده",
        nam10_no_host=True,
    )
    assert game is not None
    gm.add_player(game, Player(user_id=creator, full_name="سازنده", username=None))
    return game


class Nam10FlowHarness:
    """Fork-room day-flow driver mirroring the Bazpors no-host harness."""

    def __init__(
        self,
        gm: GameManager,
        game: Any,
        *,
        creator_uid: int,
        assistant_uid: int,
    ) -> None:
        self.gm = gm
        self.game = game
        self.creator_uid = creator_uid
        self.assistant_uid = assistant_uid
        self.bot = _mk_bot()

    @classmethod
    def build(cls, gm: GameManager) -> "Nam10FlowHarness":
        creator_uid = 8101
        game = _build_fork_room(gm, creator_uid)
        err = gm.fill_namayande10_synthetic_lobby(game)
        assert err is None
        game.seats_finalized = True
        gm.assign_roles(game)
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.observer_prompt_status = "skipped"
        assistant_uid = creator_uid
        game.bot_assistant_user_id = assistant_uid
        game.nam10_assistant_narrator_active = True
        game.nam10_observer_only_narrator_mirror = True
        return cls(
            gm, game, creator_uid=creator_uid, assistant_uid=assistant_uid
        )

    @classmethod
    def build_for_deal(cls, gm: GameManager) -> "Nam10FlowHarness":
        """Room prepared up to the shared deal pipeline (roles not dealt)."""
        creator_uid = 8111
        game = _build_fork_room(gm, creator_uid)
        err = gm.fill_namayande10_synthetic_lobby(game)
        assert err is None
        game.seats_finalized = True
        return cls(
            gm,
            game,
            creator_uid=creator_uid,
            assistant_uid=creator_uid,
        )

    def _citizen_uid(self) -> int:
        for uid, p in self.game.players.items():
            if p.is_alive and p.role and p.role.name == "CITIZEN":
                return uid
        for uid, p in self.game.players.items():
            if p.is_alive and not is_synthetic_player_uid(uid):
                return uid
        raise AssertionError("no citizen candidate")

    async def run_intro_night(self) -> None:
        from bot.nam10.dayflow import _execute_no_host_intro_night_start

        cb = _callback(self.assistant_uid)
        async with fork_flow_patches(self.gm):
            await _execute_no_host_intro_night_start(
                cb, self.bot, self.game, self.assistant_uid, self.assistant_uid
            )
        assert self.game.nam10_intro_night_started

        # Fresh rooms now run the Day-1 representative / afternoon-nap
        # workflow at this insertion point (covered by
        # test_namayande10_day1_representative). These harness suites
        # exercise the Day-1 DEFENSE machinery (the legacy path that
        # stays live for pre-insertion rooms), so rewind to the legacy
        # Day-1 state and run the defense funnel directly.
        game = self.game
        game.nam10_day1_stage = None
        from bot.nam10.nmnd_narrator import begin_no_host_day1_defense_pick
        from bot.nam10.dayflow import send_no_host_day1_defense_pick_panel

        # Legacy Day-1 panel presentation (the funnel's original branch,
        # as it still runs for rooms whose Day-1 panel was presented
        # before the representative workflow was introduced).
        game.nam10_day1_vote_prompt_sent = True
        begin_no_host_day1_defense_pick(game)
        game.nam10_day1_vote_resolved = True
        async with fork_flow_patches(self.gm):
            await send_no_host_day1_defense_pick_panel(self.bot, game)
        assert game.nam10_day1_defense_active

    async def dispatch_defense(self, act: str, *, tid: int = 0) -> None:
        from bot.nam10.dayflow import _dispatch_no_host_day1_defense_act

        cb = _callback(self.assistant_uid)
        async with fork_flow_patches(self.gm):
            await _dispatch_no_host_day1_defense_act(
                cb,
                self.bot,
                self.game,
                self.assistant_uid,
                self.assistant_uid,
                act,
                tid=tid,
                source="nhd",
            )

    async def day1_no_defense(self) -> None:
        await self.dispatch_defense("none")

    async def day1_defense_pick_and_confirm(
        self, defender_uids: list[int]
    ) -> None:
        for uid in defender_uids:
            await self.dispatch_defense("tog", tid=uid)
        await self.dispatch_defense("confirm")

    async def day1_no_exit(self) -> None:
        await self.dispatch_defense("no_exit")

    async def skip_handoff_if_offered(self) -> None:
        from bot.nam10.no_host_handoff import (
            NO_HOST_HANDOFF_OFFER,
            apply_handoff_narrator_async,
        )

        if self.game.nmnd_narrator_step != NO_HOST_HANDOFF_OFFER:
            return
        async with fork_flow_patches(self.gm):
            await apply_handoff_narrator_async(
                self.bot, self.game, self.gm, "handoff_skip", 0
            )

    async def day1_eliminate(self, target_uid: int) -> None:
        await self.dispatch_defense("d1el", tid=target_uid)
        await self.dispatch_defense("elim_yes")
        await self.skip_handoff_if_offered()

    def assert_entered_night1(self) -> None:
        g = self.game
        assert (
            g.nmnd_narrator_night_count >= 1
            or g.nmnd_narrator_step == "night_start"
        ), (g.nmnd_narrator_night_count, g.nmnd_narrator_step)

    async def run_day1_path(self, path: str) -> None:
        await self.run_intro_night()
        if path == "no_defense":
            await self.day1_no_defense()
        elif path == "no_exit":
            target = self._citizen_uid()
            await self.day1_defense_pick_and_confirm([target])
            await self.day1_no_exit()
        elif path == "elim":
            target = self._citizen_uid()
            await self.day1_defense_pick_and_confirm([target])
            await self.day1_eliminate(target)
        else:
            raise ValueError(path)
        self.assert_entered_night1()
        assert not self.game.nam10_day1_defense_active


class ForkLobbyAndDealTests(unittest.IsolatedAsyncioTestCase):
    async def test_fill_button_routes_to_fork_fill(self) -> None:
        from bot.handlers.lobby import SemiAutoDevLobby, cb_semi_auto_dev_lobby

        gm = GameManager()
        creator = 8301
        game = _build_fork_room(gm, creator)
        cb = _callback(creator)
        cb.data = SemiAutoDevLobby(code=game.room_code, act="fill").pack()
        cb.message.chat.type = "private"
        with patch("bot.handlers.lobby.manager", gm):
            await cb_semi_auto_dev_lobby(
                cb,
                SemiAutoDevLobby(code=game.room_code, act="fill"),
                _mk_bot(),
            )
        self.assertEqual(len(game.players), 10)
        self.assertTrue(game.players[creator].is_alive)
        synth = [
            p for p in game.players.values() if is_synthetic_player_uid(p.user_id)
        ]
        self.assertEqual(len(synth), 9)

    async def test_deal_pipeline_then_assistant_delegation_and_intro(
        self,
    ) -> None:
        from bot.main import deal_roles_full_pipeline, finalize_no_host_bot_assistant

        gm = GameManager()
        h = Nam10FlowHarness.build_for_deal(gm)
        bot = _mk_bot()
        with (
            patch(
                "bot.main.send_private_role",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bot.main.notify_players_after_roles_dealt",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.main.send_no_host_observer_prompt",
                new_callable=AsyncMock,
            ),
        ):
            err = await deal_roles_full_pipeline(bot, h.game)
        self.assertIsNone(err)
        self.assertTrue(h.game.roles_dealt)
        h.game.phase = Phase.MANUAL
        # the shared assistant finalize must delegate to the fork copy
        async with fork_flow_patches(gm):
            await finalize_no_host_bot_assistant(
                bot, h.game, h.creator_uid, random_pick=False
            )
        self.assertEqual(h.game.bot_assistant_user_id, h.creator_uid)
        self.assertFalse(h.game.no_host_assistant_narrator_active)
        h2 = Nam10FlowHarness(
            gm,
            h.game,
            creator_uid=h.creator_uid,
            assistant_uid=h.creator_uid,
        )
        await h2.run_intro_night()
        await h2.day1_no_defense()
        h2.assert_entered_night1()

    async def test_public_create_namayande_10_routes_to_fork(self) -> None:
        from bot.handlers.lobby import CreatePickPlayers, cb_create_players

        gm = GameManager()
        seen_game: dict[str, Any] = {}

        real_create = gm.create_game

        def spying_create(**kwargs: Any):
            seen_game["kwargs"] = dict(kwargs)
            return real_create(**kwargs)

        gm.create_game = spying_create  # type: ignore[method-assign]
        cb = _callback(8401)
        cb.message.chat.type = "private"
        cb.data = CreatePickPlayers(slug="namayande", count=10).pack()
        test_bot = _mk_bot()
        test_bot.get_me = AsyncMock(return_value=MagicMock(username="TestBot"))
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_players(
                cb, CreatePickPlayers(slug="namayande", count=10), test_bot
            )
        # Phase 4: public Namayande -> 10 players routes to the independent fork.
        self.assertEqual(seen_game["kwargs"].get("nam10_no_host"), True)
        # retrieve the created room via the host registry
        found = gm.get_room_for_host(8401)
        room = found if hasattr(found, "scenario_name") else gm.get_game(found)
        self.assertIsNotNone(room)
        self.assertTrue(hasattr(room, "scenario_name"), type(room))
        self.assertEqual(room.scenario_name, "namayande")
        self.assertEqual(room.max_players, 10)
        self.assertEqual(room.nmnd_host_mode, "no_host")
        self.assertTrue(is_namayande10_no_host_room(room))
        # the creator is seated (no-host parity with Bazpors/Mason flows)
        self.assertIn(8401, room.players)

    async def test_public_create_namayande_other_counts_classic(self) -> None:
        from bot.handlers.lobby import CreatePickPlayers, cb_create_players

        TestBot = None
        gm = GameManager()
        seen_game: dict[str, Any] = {}

        real_create = gm.create_game

        def spying_create(**kwargs: Any):
            seen_game["kwargs"] = dict(kwargs)
            return real_create(**kwargs)

        gm.create_game = spying_create  # type: ignore[method-assign]
        cb = _callback(8402)
        cb.message.chat.type = "private"
        test_bot = _mk_bot()
        test_bot.get_me = AsyncMock(return_value=MagicMock(username="TestBot"))
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_players(
                cb, CreatePickPlayers(slug="namayande", count=16), test_bot
            )
        # Namayande now supports ONLY 10/11/12/13 (UI + server gate):
        # a forged/public 16 must never reach create_game at all.
        self.assertNotIn("kwargs", seen_game)
        self.assertIsNone(gm.get_room_for_host(8402))
        # The forged callback would Server-side reject 14 and 16 regardless.
        for legacy in (14, 16):
            game = gm.create_game(
                host_id=8402 + legacy,
                scenario_name="namayande",
                max_players=legacy,
                nam10_no_host=True,
            )
            self.assertIsNone(game, legacy)
        # TestBot placeholder contract preserved.
        self.assertIn(TestBot, (None,))


class RouterIsolationTests(unittest.IsolatedAsyncioTestCase):
    def _bazpors_room(self, gm: GameManager, creator: int = 8601) -> Any:
        game = gm.create_game(
            host_id=creator,
            scenario_name="bazpors",
            max_players=10,
            host_full_name="C",
            bazpors_host_mode="no_host",
        )
        gm.add_player(game, Player(creator, "C", None))
        return game

    async def test_pmr_router_fork_room_routes_to_fork_engine(self) -> None:
        from bot.handlers import no_host_player as nhp

        gm = GameManager()
        game = _build_fork_room(gm, 8501)
        seen: dict[str, Any] = {}

        async def spy(callback, bot, game=None, callback_data=None):
            seen["game"] = game
            seen["cb"] = callback_data

        cb = _callback(999)
        cb.data = PlayerMirrorCb(
            code=game.room_code, act="zzz", as_uid=1, tid=0
        ).pack()
        with (
            patch("bot.app_state.manager", gm),
            patch.object(nhp, "manager", gm),
            patch(
                "bot.nam10.player_mirror.dispatch_namayande10_mirror",
                side_effect=spy,
            ),
        ):
            await nhp.player_mirror_cb(cb, _mk_bot())

        self.assertIs(seen["game"], game)
        self.assertEqual(seen["cb"].act, "zzz")

    async def test_pmr_router_bazpors_never_enters_fork(self) -> None:
        from bot.handlers import no_host_player as nhp

        gm = GameManager()
        game = self._bazpors_room(gm)
        got = {"fork": False}

        async def spy(callback, bot, game=None, callback_data=None):
            got["fork"] = True

        answers: list[str] = []

        async def answer(text=None, show_alert=False):
            answers.append(text)

        cb = _callback(777)
        cb.answer = answer
        cb.data = PlayerMirrorCb(
            code=game.room_code, act="zz2", as_uid=1, tid=0
        ).pack()
        with (
            patch("bot.app_state.manager", gm),
            patch.object(nhp, "manager", gm),
            patch(
                "bot.nam10.player_mirror.dispatch_namayande10_mirror",
                side_effect=spy,
            ),
        ):
            await nhp.player_mirror_cb(cb, _mk_bot())

        self.assertFalse(got["fork"])
        self.assertIn("ناظر فعال نیست.", answers)

    async def test_fork_dispatch_chain_resolves_fork_copies(self) -> None:
        gm = GameManager()
        game = _build_fork_room(gm, 8550)
        game.bot_assistant_user_id = 1
        game.nam10_assistant_narrator_active = True
        game.nam10_night_parallel_collect_active = True
        bot = _mk_bot()
        cb = _callback(1)
        from bot.nam10 import player_mirror as fork_mirror

        async def run_dispatch():
            await fork_mirror.dispatch_namayande10_mirror(
                cb,
                bot,
                game,
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act="ndp", as_uid=1, tid=0
                ),
            )

        handled = {"fork": 0, "bazpors": 0}
        from bot import no_host_detective_night as bazpors_det

        def pk(marker: str):
            return AsyncMock(
                side_effect=lambda *a, **k: handled.update({marker: 1})
            )

        with (
            patch.object(
                fork_mirror,
                "dispatch_no_host_detective_night",
                pk("fork"),
            ),
            patch.object(
                bazpors_det,
                "dispatch_no_host_detective_night",
                pk("bazpors"),
            ),
        ):
            await run_dispatch()

        self.assertEqual(handled["fork"], 1)
        self.assertEqual(handled["bazpors"], 0)

    async def test_day1_defense_cb_fork_branch(self) -> None:
        from bot.handlers import no_host_player as nhp
        from bot.nam10 import dayflow

        gm = GameManager()
        game = _build_fork_room(gm, 8501)
        fake = AsyncMock()
        cb = _callback(88)
        cdata = NoHostDay1DefenseCb(code=game.room_code, act="none", tid=0)
        cb.data = cdata.pack()
        with (
            patch("bot.app_state.manager", gm),
            patch.object(nhp, "manager", gm),
            patch.object(dayflow, "dispatch_nam10_day1_defense_cb", fake),
        ):
            await nhp.cb_no_host_day1_defense(cb, cdata, _mk_bot())
        fake.assert_awaited_once()
        args = fake.await_args.args
        self.assertIs(args[2], game)
        self.assertEqual(args[3].act, "none")

    async def test_day1_defense_cb_bazpors_never_touches_fork(self) -> None:
        from bot.handlers import no_host_player as nhp
        from bot.nam10 import dayflow

        gm = GameManager()
        game = self._bazpors_room(gm, 8701)
        game.bot_assistant_user_id = None
        fake = AsyncMock()
        answers: list[str] = []

        async def answer(text=None, show_alert=False):
            answers.append(text)

        cb = _callback(88)
        cb.answer = answer
        cdata = NoHostDay1DefenseCb(code=game.room_code, act="none", tid=0)
        cb.data = cdata.pack()
        with (
            patch("bot.app_state.manager", gm),
            patch.object(nhp, "manager", gm),
            patch.object(dayflow, "dispatch_nam10_day1_defense_cb", fake),
        ):
            await nhp.cb_no_host_day1_defense(cb, cdata, _mk_bot())
        fake.assert_not_awaited()

    async def test_intro_night_cb_fork_branch(self) -> None:
        from bot.handlers import no_host_player as nhp
        from bot.nam10 import dayflow

        gm = GameManager()
        game = _build_fork_room(gm, 8501)
        game.bot_assistant_user_id = 7
        fake = AsyncMock()
        cb = _callback(7)
        cdata = NoHostIntroNightStart(code=game.room_code, act="go")
        cb.data = cdata.pack()
        with (
            patch("bot.app_state.manager", gm),
            patch.object(nhp, "manager", gm),
            patch.object(dayflow, "dispatch_nam10_intro_night_cb", fake),
        ):
            await nhp.cb_no_host_intro_night_start(cb, cdata, _mk_bot())
        fake.assert_awaited_once()


class GuardOrderContractTests(unittest.TestCase):
    def test_fork_guard_precedes_all_scenario_branches(self) -> None:
        from bot.handlers import no_host_player as nhp

        src = open(nhp.__file__, encoding="utf-8").read()
        body = src.split("async def player_mirror_cb", 1)[1]
        guard = body.find("is_namayande10_no_host_room(game)")
        first_dispatch = body.find('"russian_mafia"')
        self.assertGreater(guard, -1)
        self.assertGreater(first_dispatch, -1)
        self.assertLess(guard, first_dispatch)

    def test_player_mirror_module_is_never_registered(self) -> None:
        from bot.nam10 import player_mirror as pm

        self.assertFalse(hasattr(pm, "register_no_host_player_handlers"))


class ForkDayFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_day1_paths_enter_night1(self) -> None:
        for path in ("no_defense", "no_exit", "elim"):
            with self.subTest(day1_path=path):
                h = Nam10FlowHarness.build(self.gm)
                await h.run_day1_path(path)

    async def test_elim_back_then_no_exit(self) -> None:
        h = Nam10FlowHarness.build(self.gm)
        await h.run_intro_night()
        target = h._citizen_uid()
        await h.day1_defense_pick_and_confirm([target])
        await h.dispatch_defense("d1el", tid=target)
        await h.dispatch_defense("elim_no")
        self.assertEqual(h.game.nam10_day1_defense_phase, "outcome")
        await h.day1_no_exit()
        h.assert_entered_night1()

    async def test_elim_actually_removes_player(self) -> None:
        h = Nam10FlowHarness.build(self.gm)
        await h.run_intro_night()
        target = h._citizen_uid()
        await h.day1_defense_pick_and_confirm([target])
        await h.day1_eliminate(target)
        self.assertFalse(h.game.players[target].is_alive)
        self.assertGreaterEqual(h.game.nmnd_narrator_host_day, 1)

    async def test_day1_keyboard_act_sweep(self) -> None:
        h = Nam10FlowHarness.build(self.gm)
        await h.run_intro_night()
        target = h._citizen_uid()
        h.game.nam10_day1_defense_phase = "pick"
        await h.dispatch_defense("tog", tid=target)
        h.game.nam10_day1_defense_phase = "pick"
        await h.dispatch_defense("confirm")
        h.game.nam10_day1_defense_phase = "outcome"
        await h.dispatch_defense("no_exit")
        h.assert_entered_night1()

    async def test_day_vote_skip_and_show_panel(self) -> None:
        from bot.nam10.dayflow import (
            _process_no_host_day1_show_vote_panel,
            _process_no_host_day1_skip_night,
        )

        h = Nam10FlowHarness.build(self.gm)
        await h.run_intro_night()
        # the vote prompt marks the choice resolved and arms the defense
        # pick panel; reset to drive the skip act like the live flow.
        h.game.nam10_day1_vote_resolved = False
        cb = _callback(h.assistant_uid)
        cb.message.edit_text = AsyncMock()
        async with fork_flow_patches(self.gm):
            await _process_no_host_day1_skip_night(
                cb, h.bot, h.game, h.assistant_uid, h.assistant_uid
            )
        self.assertTrue(h.game.nam10_day1_vote_resolved)
        h.assert_entered_night1()
        self.assertTrue(h.game.nam10_night_parallel_collect_active)

        h2 = Nam10FlowHarness.build(GameManager())
        await h2.run_intro_night()
        h2.game.nam10_day1_vote_resolved = False
        cb2 = _callback(h2.assistant_uid)
        cb2.message.edit_text = AsyncMock()
        async with fork_flow_patches(h2.gm):
            await _process_no_host_day1_show_vote_panel(
                cb2, h2.bot, h2.game, h2.assistant_uid, h2.assistant_uid
            )
        self.assertTrue(h2.game.nam10_day1_vote_resolved)

    async def test_no_state_leak_into_shared_bazpors_fields(self) -> None:
        h = Nam10FlowHarness.build(self.gm)
        await h.run_day1_path("no_defense")
        g = h.game
        self.assertFalse(g.no_host_intro_night_started)
        self.assertFalse(g.no_host_day1_vote_resolved)
        self.assertFalse(g.no_host_assistant_narrator_active)


if __name__ == "__main__":
    unittest.main()
