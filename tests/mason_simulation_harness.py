"""شبیه‌سازی سناریوی ماسون — کمک‌کنندهٔ تست‌های end-to-end."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager, is_mafia_team, is_synthetic_player_uid
from bot.mason_night_entry import (
    MASON_NIGHT_WAIT_ACT,
    dispatch_mason_night_wait_ok,
)
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.mason_night_role import (
    MGD_OK,
    MGD_PICK,
    MGN_NONE,
    MSC_DONE,
    MSC_INFO_OK,
    MSC_NONE,
    MSB_OK,
    MSB_NONE,
    MSD_DONE,
    MSD_OK,
    MSM_NONE,
    MSS_NONE,
    MSS_OK,
    dispatch_mason_night_role,
)
from bot.mason_roles import MASON_PLAYER_COUNTS, masoon_roles_for_count
from bot.models import Game, Phase, Player, Role
from bot.observer_delivery import PlayerMirrorCb, unpack_player_mirror_cb
from bot.roles.night_state import mafia_night_state
from bot.roles.registry import find_alive_role_holder

if TYPE_CHECKING:
    from collections.abc import Iterable

MASON_COUNTS: tuple[int, ...] = tuple(sorted(MASON_PLAYER_COUNTS))

MASON_CORE_NIGHT_ROLES: frozenset[Role] = frozenset(
    {
        Role.SABOTEUR,
        Role.DOCTOR,
        Role.SNIPER,
        Role.COMMANDER,
        Role.GUNMAN,
        Role.BODYGUARD,
        Role.MASON,
    }
)


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


@dataclass
class CapturedPrompt:
    uid: int
    ui_key: str
    text: str
    button_texts: list[str]
    send_observer: bool


@dataclass
class MasonSimHarness:
    gm: GameManager
    game: Game
    creator_uid: int
    assistant_uid: int
    observer_uid: int = 999
    captured: list[CapturedPrompt] = field(default_factory=list)
    bot: MagicMock = field(default_factory=_make_bot)

    @classmethod
    def build(
        cls,
        gm: GameManager,
        *,
        max_players: int = 16,
        with_observer: bool = True,
    ) -> MasonSimHarness:
        creator_uid = 7001
        game = gm.create_game(
            host_id=creator_uid,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="masoon",
            max_players=max_players,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        err = gm.add_player(
            game,
            Player(user_id=creator_uid, full_name="امیر", username=None),
        )
        assert err is None
        err = gm.fill_no_host_synthetic_lobby(game)
        assert err is None
        game.seats_finalized = True
        gm.assign_roles(game)
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        assistant_uid = creator_uid
        game.bot_assistant_user_id = assistant_uid
        game.no_host_assistant_narrator_active = True
        if with_observer:
            game.observer_prompt_status = "registered"
            game.observer_user_id = 999
        return cls(
            gm=gm,
            game=game,
            creator_uid=creator_uid,
            assistant_uid=assistant_uid,
        )

    def clear_captures(self) -> None:
        self.captured.clear()

    def holder(self, role: Role) -> Player | None:
        return find_alive_role_holder(self.game, role)

    def holder_uid(self, role: Role) -> int | None:
        p = self.holder(role)
        return p.user_id if p is not None else None

    def roles_in_room(self) -> set[Role]:
        return {p.role for p in self.game.players.values() if p.role is not None}

    def alive_uids_except(self, *exclude: int) -> list[int]:
        ex = set(exclude)
        return [
            p.user_id
            for p in self.game.players.values()
            if p.is_alive and p.user_id not in ex
        ]

    def first_town_target(self, *, exclude_uids: Iterable[int] | None = None) -> int:
        skip = set(exclude_uids or ())
        sn_uid = self.holder_uid(Role.SNIPER)
        if sn_uid is not None:
            skip.add(sn_uid)
        for p in self.game.players.values():
            if not p.is_alive or p.user_id in skip:
                continue
            if p.role and not is_mafia_team(p.role):
                return p.user_id
        raise AssertionError("no town target")

    def setup_night(self, *, night_count: int = 1) -> None:
        g = self.game
        g.bazpors_narrator_step = NIGHT_START
        g.bazpors_narrator_night_count = night_count
        g.no_host_night_parallel_collect_active = False
        g.mason_night_entry_dispatched_night = None
        g.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in g.players.items()
        }

    def _prime_night_entry_state(self) -> None:
        from bot.mason_night_entry import reset_mason_night_panel_state
        from bot.mason_night_resolve import reset_mason_night_resolution_state
        from bot.roles import mason_gunner as ms_gn

        g = self.game
        nc = g.bazpors_narrator_night_count
        g.mason_night_entry_dispatched_night = nc
        reset_mason_night_panel_state(g)
        ms_gn.refresh_mason_day_gun_holder_if_eliminated(g)
        reset_mason_night_resolution_state(g)
        g.no_host_night_parallel_collect_active = True

    def arm_mafia_shot_done(self, target_uid: int | None = None) -> None:
        g = self.game
        g.no_host_mafia_night1_done = True
        g.no_host_mafia_night1_chosen_action = "shot"
        g.no_host_mafia_shot_done = True
        if target_uid is not None:
            mafia_night_state(g).commit_shot(target_uid)

    @asynccontextmanager
    async def capture_prompts(self) -> AsyncIterator[None]:
        self.clear_captures()

        async def _register(
            bot,
            game,
            uid,
            ui_key,
            text,
            kb,
            *,
            send_player=True,
            send_observer=False,
            **kw,
        ) -> None:
            buttons: list[str] = []
            if kb is not None:
                for row in kb.inline_keyboard:
                    for btn in row:
                        buttons.append(btn.text)
            self.captured.append(
                CapturedPrompt(
                    uid=uid,
                    ui_key=ui_key,
                    text=text,
                    button_texts=buttons,
                    send_observer=bool(send_observer),
                )
            )

        patches = [
            patch(
                "bot.observer_delivery.register_mirror_prompt_pair",
                side_effect=_register,
            ),
            patch(
                "bot.mason_night_entry.register_mirror_prompt_pair",
                side_effect=_register,
            ),
            patch(
                "bot.mason_night_role.register_mirror_prompt_pair",
                side_effect=_register,
            ),
            patch(
                "bot.mason_night_role.sync_role_mirror_panel",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_role.finalize_no_host_role_pick_message",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_ready.maybe_finish_mason_parallel_night",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.no_host_mafia_night1.start_no_host_night1_mafia_flow",
                new_callable=AsyncMock,
            ),
        ]
        for p in patches:
            p.start()
        try:
            yield
        finally:
            for p in patches:
                p.stop()

    def prompts_for_uid(self, uid: int) -> list[CapturedPrompt]:
        return [p for p in self.captured if p.uid == uid]

    def has_prompt_for_role(self, role: Role) -> bool:
        uid = self.holder_uid(role)
        if uid is None:
            return False
        return bool(self.prompts_for_uid(uid))

    def observer_mirror_count(self) -> int:
        return sum(1 for p in self.captured if p.send_observer)

    async def dispatch_night_entry(self) -> list[BaseException]:
        """اجرای dispatch شب — برگرداندن استثناها (نباید خالی نباشد اگر خطا داریم)."""
        errors: list[BaseException] = []
        async with self.capture_prompts():
            self._prime_night_entry_state()
            from bot.mason_night_role import (
                dispatch_mason_detective_panel,
                dispatch_mason_doctor_panel,
                dispatch_mason_gunner_panel,
                dispatch_mason_guardian_panel,
                dispatch_mason_mason_recruit_panel,
                dispatch_mason_natasha_panel,
                dispatch_mason_priest_panel,
                dispatch_mason_saboteur_panel,
                dispatch_mason_sniper_panel,
            )
            from bot.mason_night_entry import _dispatch_mason_wait_panels

            dispatches = (
                dispatch_mason_saboteur_panel,
                dispatch_mason_doctor_panel,
                dispatch_mason_sniper_panel,
                dispatch_mason_gunner_panel,
                dispatch_mason_guardian_panel,
                dispatch_mason_mason_recruit_panel,
                dispatch_mason_detective_panel,
                dispatch_mason_natasha_panel,
                dispatch_mason_priest_panel,
                _dispatch_mason_wait_panels,
            )
            for fn in dispatches:
                try:
                    if fn.__name__ == "_dispatch_mason_wait_panels":
                        await fn(self.bot, self.game)
                    else:
                        await fn(self.bot, self.game, self.gm)
                except BaseException as exc:
                    errors.append(exc)
        return errors

    async def dispatch_night_entry_gather(self) -> list[BaseException]:
        """همان مسیر production — استثناهای gather را برمی‌گرداند."""
        errors: list[BaseException] = []
        async with self.capture_prompts():
            import asyncio
            from bot.mason_night_entry import dispatch_mason_night_entry_panels

            self.game.mason_night_entry_dispatched_night = None
            gathered = await asyncio.gather(
                dispatch_mason_night_entry_panels(self.bot, self.game, self.gm),
                return_exceptions=True,
            )
            for item in gathered:
                if isinstance(item, BaseException):
                    errors.append(item)
        return errors

    async def click_role(
        self,
        *,
        as_uid: int,
        act: str,
        tid: int = 0,
        actor_uid: int | None = None,
    ) -> None:
        actor = actor_uid if actor_uid is not None else as_uid
        cb = _callback(actor)
        with (
            patch(
                "bot.mason_night_role.finalize_no_host_role_pick_message",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_role.sync_role_mirror_panel",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_role.update_mirror_prompt_pair",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_ready.maybe_finish_mason_parallel_night",
                new_callable=AsyncMock,
            ),
        ):
            await dispatch_mason_night_role(
                cb,
                self.bot,
                self.game,
                self.gm,
                as_uid=as_uid,
                actor_uid=actor,
                act=act,
                tid=tid,
            )

    async def press_wait_ok(self, as_uid: int, *, actor_uid: int | None = None) -> None:
        cb = _callback(actor_uid or as_uid)
        with patch(
            "bot.observer_delivery.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new_callable=AsyncMock,
        ):
            await dispatch_mason_night_wait_ok(
                cb,
                self.bot,
                self.game,
                self.gm,
                as_uid=as_uid,
                actor_uid=actor_uid or as_uid,
            )

    async def complete_minimal_night_actions(self) -> None:
        """اقدام حداقلی هر نقش شبانه — بدون شلیک واقعی."""
        g = self.game
        if self.holder_uid(Role.SABOTEUR) is not None:
            from bot.roles import mason_saboteur as ms_sb

            sb_uid = self.holder_uid(Role.SABOTEUR)
            if ms_sb.mason_saboteur_needs_night_pick(g):
                await self.click_role(as_uid=sb_uid, act=MSB_NONE)
            else:
                await self.click_role(as_uid=sb_uid, act=MSB_OK)
        doc_uid = self.holder_uid(Role.DOCTOR)
        if doc_uid is not None:
            if g.mason_night_doctor_nato_void_pending:
                await self.click_role(as_uid=doc_uid, act=MSD_OK)
            else:
                await self.click_role(as_uid=doc_uid, act=MSD_DONE)
        sn_uid = self.holder_uid(Role.SNIPER)
        if sn_uid is not None:
            from bot.roles import mason_sniper as ms_sn

            if ms_sn.mason_sniper_needs_night_pick(g):
                await self.click_role(as_uid=sn_uid, act=MSS_NONE)
            else:
                await self.click_role(as_uid=sn_uid, act=MSS_OK)
        cmd_uid = self.holder_uid(Role.COMMANDER)
        if cmd_uid is not None:
            from bot.roles import mason_commander as ms_cmd

            if ms_cmd.mason_commander_needs_no_pick_wait_panel(g):
                await self.click_role(as_uid=cmd_uid, act=MSC_INFO_OK)
            elif ms_cmd.mason_commander_needs_sniper_no_shot_info_panel(g):
                await self.click_role(as_uid=cmd_uid, act=MSC_INFO_OK)
            elif sn_uid is not None:
                await self.click_role(as_uid=cmd_uid, act=MSC_NONE)
            else:
                await self.click_role(as_uid=cmd_uid, act=MSC_NONE)
        gn_uid = self.holder_uid(Role.GUNMAN)
        if gn_uid is not None:
            from bot.roles import mason_gunner as ms_gn

            if ms_gn.mason_gunner_can_give_gun(g):
                await self.click_role(as_uid=gn_uid, act=MGN_NONE)
            else:
                await self.press_wait_ok(gn_uid)
        gd_uid = self.holder_uid(Role.BODYGUARD)
        if gd_uid is not None:
            from bot.roles import mason_guardian as ms_gd

            if ms_gd.mason_guardian_needs_night_pick(g):
                tgt = self.first_town_target(exclude_uids=[gd_uid])
                await self.click_role(as_uid=gd_uid, act=MGD_PICK, tid=tgt)
            else:
                await self.click_role(as_uid=gd_uid, act=MGD_OK)
        ms_uid = self.holder_uid(Role.MASON)
        if ms_uid is not None:
            await self.click_role(as_uid=ms_uid, act=MSM_NONE)
        dt_uid = self.holder_uid(Role.DETECTIVE)
        if dt_uid is not None:
            tgt = self.first_town_target(exclude_uids=[dt_uid])
            await self.click_role(as_uid=dt_uid, act="mdtp", tid=tgt)
            await self.click_role(as_uid=dt_uid, act="mdtc")
        nt_uid = self.holder_uid(Role.NATASHA)
        if nt_uid is not None:
            tgt = self.first_town_target(exclude_uids=[nt_uid])
            await self.click_role(as_uid=nt_uid, act="mnap", tid=tgt)
            await self.click_role(as_uid=nt_uid, act="mnac")
        pr_uid = self.holder_uid(Role.PRIEST)
        if pr_uid is not None:
            tgt = self.first_town_target(exclude_uids=[pr_uid])
            await self.click_role(as_uid=pr_uid, act="mprp", tid=tgt)
            await self.click_role(as_uid=pr_uid, act="mprc")
        self.arm_mafia_shot_done(self.first_town_target())
        from bot.mason_night_entry import night_action_holder_uids

        for uid in self.alive_uids_except():
            if uid not in night_action_holder_uids(g):
                if uid not in g.mason_night_wait_ok_uids:
                    await self.press_wait_ok(uid)

    def assert_readiness(self, *, expected: bool) -> None:
        actual = all_mason_parallel_night_ready(self.game)
        assert actual is expected, f"readiness expected {expected}, got {actual}"

    def parse_pmr(self, callback_data: str) -> PlayerMirrorCb | None:
        return unpack_player_mirror_cb(callback_data)

    @staticmethod
    def expected_roles_for_count(n: int) -> list[Role]:
        return masoon_roles_for_count(n)

    @staticmethod
    def synthetic_players(game: Game) -> list[Player]:
        return [p for p in game.players.values() if is_synthetic_player_uid(p.user_id)]

    @staticmethod
    def real_players(game: Game) -> list[Player]:
        return [p for p in game.players.values() if not is_synthetic_player_uid(p.user_id)]
