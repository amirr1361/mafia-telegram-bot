"""شبیه‌سازی مسیر no_host — از لابی تا پایان بازی (بدون تلگرام واقعی)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from bot.nam10.nmnd_narrator import NIGHT_START, _enter_night_from_day_end
from bot.nam10.engine import GameManager, is_synthetic_player_uid
from bot.models import Game, Phase, Player, Role
from bot.nam10.no_host_night_ready import all_no_host_parallel_night_ready
from bot.nam10.no_host_night_resolve import (
    _apply_no_host_night_resolution,
    nam10_complete_discipline_and_resolve,
)
from bot import nam10 as _nm10_rolls

detective = _nm10_rolls.roles_detective
doctor = _nm10_rolls.roles_doctor
hunter = _nm10_rolls.roles_hunter
interrogator = _nm10_rolls.roles_interrogator
shiad = _nm10_rolls.roles_shiad
sniper = _nm10_rolls.roles_sniper
ruintan = _nm10_rolls.roles_ruintan
from bot.nam10.roles_doctor import commit_pick as doctor_commit_pick
from bot.nam10.role_registry import find_alive_role_holder

if TYPE_CHECKING:
    from collections.abc import Iterable


def _make_bot() -> MagicMock:
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
    cb.answer = AsyncMock()
    return cb


@asynccontextmanager
async def _telegram_patches(gm: GameManager | None = None) -> AsyncIterator[None]:
    patches = [
        patch("bot.nam10.dayflow.broadcast_to_alive_players", new_callable=AsyncMock),
        patch("bot.nam10.dayflow.on_no_host_entered_night1", new_callable=AsyncMock),
        patch("bot.nam10.no_host_night1.on_no_host_entered_night1", new_callable=AsyncMock),
        patch("bot.nam10.nmnd_narrator.push_host_step", new_callable=AsyncMock),
        patch("bot.nam10.no_host_table_inquiry.push_host_step", new_callable=AsyncMock),
        patch(
            "bot.nam10.dayflow.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.dayflow.promote_mirror_prompt_to_panel",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "bot.nam10.dayflow.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.dayflow.deliver_no_host_intro_night_started_messages",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.no_host_night_resolve.broadcast_to_alive_players",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.no_host_night_resolve.deliver_night_results_to_eliminated_from_night",
            new_callable=AsyncMock,
        ),
        patch(
            "bot.nam10.nmnd_night_panel_purge.purge_stale_night_and_day_panel_messages",
            new_callable=AsyncMock,
        ),
        patch("bot.nam10.no_host_night_resolve.push_host_step", new_callable=AsyncMock),
        patch(
            "bot.nam10.no_host_night_resolve.nam10_maybe_end_on_faction_win",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ]
    if gm is not None:
        patches.append(patch("bot.nam10.dayflow.manager", gm))
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


class Nam10FlowHarness:
    """راه‌اندازی اتاق no_host و پیش‌برد مرحله‌ای با dispatch مستقیم callbackها."""

    def __init__(
        self,
        gm: GameManager,
        game: Game,
        *,
        creator_uid: int,
        assistant_uid: int,
    ) -> None:
        self.gm = gm
        self.game = game
        self.creator_uid = creator_uid
        self.assistant_uid = assistant_uid
        self.bot = _make_bot()
        self._captured_winner: str | None = None

    async def run_until_natural_game_end(
        self, day1_path: str = "no_defense", *, max_steps: int = 100
    ) -> str:
        from tests.nam10_game_loop import run_until_natural_end

        return await run_until_natural_end(
            self, day1_path=day1_path, max_steps=max_steps
        )

    async def complete_night1_via_role_buttons(self) -> None:
        """شب ۱ — dispatch واقعی دکمه‌های نقش‌ها سپس resolve."""
        from tests.nam10_game_loop import (
            complete_discipline_no_and_resolve,
            complete_night_role_picks,
            full_simulation_patches,
        )
        from bot.nam10.no_host_night_ready import maybe_finish_no_host_parallel_night

        async with full_simulation_patches(self):
            await complete_night_role_picks(self)
            g = self.game
            if g.nam10_night_parallel_collect_active:
                assert all_no_host_parallel_night_ready(g)
                await maybe_finish_no_host_parallel_night(self.bot, g, self.gm)
            await complete_discipline_no_and_resolve(self)
        assert self.game.nmnd_night_report_html

    @classmethod
    def build(cls, gm: GameManager, *, max_players: int = 10) -> Nam10FlowHarness:
        creator_uid = 7001
        game = gm.create_game(
            host_id=creator_uid,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="namayande",
            max_players=max_players,
            nam10_no_host=True,
        )
        assert game is not None
        err = gm.add_player(
            game,
            Player(
                user_id=creator_uid,
                full_name="سازنده",
                username=None,
            ),
        )
        assert err is None
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
        return cls(gm, game, creator_uid=creator_uid, assistant_uid=assistant_uid)

    def _holder_uid(self, role) -> int:
        p = find_alive_role_holder(self.game, role)
        assert p is not None, f"missing role holder {role}"
        return p.user_id

    def _citizen_uid(self) -> int:
        for p in self.game.players.values():
            if not p.is_alive:
                continue
            if p.role and p.role.name == "CITIZEN":
                return p.user_id
        for p in self.game.players.values():
            if p.is_alive and not is_synthetic_player_uid(p.user_id):
                return p.user_id
        raise AssertionError("no citizen candidate")

    async def run_intro_night(self) -> None:
        from bot.nam10.dayflow import _execute_no_host_intro_night_start

        cb = _callback(self.assistant_uid)
        async with _telegram_patches(self.gm):
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
        async with _telegram_patches(self.gm):
            await send_no_host_day1_defense_pick_panel(self.bot, game)
        assert game.nam10_day1_defense_active

    async def dispatch_defense(self, act: str, *, tid: int = 0) -> None:
        from bot.nam10.dayflow import _dispatch_no_host_day1_defense_act

        cb = _callback(self.assistant_uid)
        async with _telegram_patches(self.gm):
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

    async def day1_defense_pick_and_confirm(self, defender_uids: Iterable[int]) -> None:
        for uid in defender_uids:
            await self.dispatch_defense("tog", tid=uid)
        await self.dispatch_defense("confirm")

    async def day1_no_exit(self) -> None:
        await self.dispatch_defense("no_exit")

    async def day1_eliminate(self, target_uid: int) -> None:
        await self.dispatch_defense("d1el", tid=target_uid)
        await self.dispatch_defense("elim_yes")
        await self.skip_handoff_if_offered()

    async def skip_handoff_if_offered(self) -> None:
        from bot.nam10.no_host_handoff import (
            NO_HOST_HANDOFF_OFFER,
            apply_handoff_narrator_async,
        )

        if self.game.nmnd_narrator_step != NO_HOST_HANDOFF_OFFER:
            return
        async with _telegram_patches(self.gm):
            await apply_handoff_narrator_async(
                self.bot, self.game, self.gm, "handoff_skip", 0
            )

    def assert_entered_night1(self) -> None:
        assert self.game.nmnd_narrator_night_count >= 1 or (
            self.game.nmnd_narrator_step == NIGHT_START
        )

    def arm_night1_parallel_ready(self) -> None:
        g = self.game
        g.nmnd_narrator_step = NIGHT_START
        g.nmnd_narrator_night_count = max(1, g.nmnd_narrator_night_count)
        g.nam10_night_parallel_collect_active = True
        g.nmnd_alive_at_night_start = {
            uid: p.is_alive for uid, p in g.players.items()
        }

        try:
            self._holder_uid(Role.HUNTER)
            hunter.apply_pick(g, self._citizen_uid())
        except AssertionError:
            pass

        g.nmnd_mafia_shot_registered = True
        g.actions.mafia_target = self._citizen_uid()

        try:
            self._holder_uid(Role.SHIAD)
            shiad.commit_pick(g, self._citizen_uid())
            g.nam10_shiad_pick_confirmed = True
        except AssertionError:
            g.nam10_shiad_pick_confirmed = True

        try:
            self._holder_uid(Role.DETECTIVE)
            detective.commit_pick(g, self._citizen_uid())
            g.nmnd_det_ack_positive = True
            g.nam10_detective_pick_confirmed = True
        except AssertionError:
            g.nam10_detective_pick_confirmed = True

        try:
            doc_uid = self._holder_uid(Role.DOCTOR)
            doctor_commit_pick(g, doc_uid)
            g.nam10_doctor_pick_confirmed = True
        except AssertionError:
            g.nam10_doctor_pick_confirmed = True

        try:
            self._holder_uid(Role.INTERROGATOR)
            c1, c2 = self._two_distinct_citizens()
            interrogator.commit_first_nominee(g, c1)
            interrogator.commit_second_nominee(g, c2)
            g.nmnd_interrog_night_finished = True
            g.nam10_interrog_pick_confirmed = True
        except AssertionError:
            g.nam10_interrog_pick_confirmed = True

        try:
            sniper.commit_pick(g, None)
            g.nam10_sniper_pick_confirmed = True
        except Exception:
            g.nam10_sniper_pick_confirmed = True

        g.nam10_night1_hunter_done = True
        g.nam10_mafia_night1_done = True
        g.nam10_mafia_shot_done = True
        g.nam10_ruintan_night_confirmed = True
        g.nam10_citizen_night_confirmed_uids = [
            uid for uid in g.players if g.players[uid].is_alive
        ]

    def _two_distinct_citizens(self) -> tuple[int, int]:
        alive = [
            uid
            for uid, p in self.game.players.items()
            if p.is_alive and uid != self.assistant_uid
        ]
        assert len(alive) >= 2
        return alive[0], alive[1]

    async def resolve_night1(self) -> None:
        g = self.game
        snap = dict(g.nmnd_alive_at_night_start or {})
        _apply_no_host_night_resolution(g, self.gm)
        async with _telegram_patches(self.gm):
            await nam10_complete_discipline_and_resolve(
                self.bot, g, self.gm, send_discipline_broadcast=False
            )
        assert g.nmnd_night_report_html

    async def force_civilian_win(self) -> bool:
        from bot.nam10.no_host_mafia_win import nam10_maybe_end_on_faction_win

        for p in list(self.game.players.values()):
            if not p.is_alive or p.role is None:
                continue
            if p.role in (
                Role.MAFIA,
                Role.MAFIA_BOSS,
                Role.MAFIA_BASIC,
                Role.MAFIA_NEGOTIATOR,
                Role.MAFIA_SIMPLE,
                Role.MAFIA_SIMPLE_2,
                Role.NATO,
                Role.SHIAD,
            ):
                p.is_alive = False
        with patch(
            "bot.post_game_flow.finalize_game_winner", new_callable=AsyncMock
        ):
            return await nam10_maybe_end_on_faction_win(
                self.bot, self.game, self.gm
            )

    async def force_mafia_win(self) -> bool:
        from bot.nam10.no_host_mafia_win import nam10_maybe_end_on_faction_win

        for p in list(self.game.players.values()):
            if not p.is_alive or p.role is None:
                continue
            if p.role in (Role.CITIZEN, Role.DOCTOR, Role.DETECTIVE, Role.HUNTER):
                p.is_alive = False
        with patch(
            "bot.post_game_flow.finalize_game_winner", new_callable=AsyncMock
        ):
            return await nam10_maybe_end_on_faction_win(
                self.bot, self.game, self.gm
            )

    async def run_day1_path(self, path: str) -> None:
        """مسیرهای روز اول: no_defense | no_exit | elim."""
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

    async def run_full_path_to_game_end(self, day1_path: str, *, winner: str) -> None:
        await self.run_day1_path(day1_path)
        self.arm_night1_parallel_ready()
        await self.resolve_night1()
        if winner == "citizen":
            ended = await self.force_civilian_win()
        else:
            ended = await self.force_mafia_win()
        assert ended
