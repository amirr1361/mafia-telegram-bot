"""فاز ۳ — nested view روی state بازی (بدون شکستن فیلدهای flat موجود).

Game همچنان فیلدهای ``no_host_*`` / ``bazpors_*`` را دارد؛ این ماژول API
گروه‌بندی‌شده برای reset، arm و تست integration فراهم می‌کند.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bot.models import Game


@dataclass(frozen=True)
class RolePickFieldSpec:
    """نام فیلدهای flat روی Game برای یک پنل pick+confirm."""

    role: str
    flow_active: str
    pick_confirmed: str
    dm_signature: str
    extra_resets: tuple[tuple[str, Any], ...] = ()


# پنل‌های pick+confirm ساده (doctor، detective، shiad، sniper، interrog)
NO_HOST_ROLE_PICK_SPECS: tuple[RolePickFieldSpec, ...] = (
    RolePickFieldSpec(
        "doctor",
        "nam10_doctor_flow_active",
        "nam10_doctor_pick_confirmed",
        "nam10_doctor_dm_signature",
        (
            ("nam10_doctor_nato_blocked_panel", False),
            ("nam10_doctor_pending_save_uids", []),
        ),
    ),
    RolePickFieldSpec(
        "detective",
        "nam10_detective_flow_active",
        "nam10_detective_pick_confirmed",
        "nam10_detective_dm_signature",
        (("nam10_detective_pending_tid", None),),
    ),
    RolePickFieldSpec(
        "shiad",
        "nam10_shiad_flow_active",
        "nam10_shiad_pick_confirmed",
        "nam10_shiad_dm_signature",
        (("nam10_shiad_pending_tid", None),),
    ),
    RolePickFieldSpec(
        "sniper",
        "nam10_sniper_flow_active",
        "nam10_sniper_pick_confirmed",
        "nam10_sniper_dm_signature",
        (("nam10_sniper_pending_target_uid", None),),
    ),
    RolePickFieldSpec(
        "interrog",
        "nam10_interrog_flow_active",
        "nam10_interrog_pick_confirmed",
        "nam10_interrog_dm_signature",
    ),
    RolePickFieldSpec(
        "journalist",
        "nam10_journalist_flow_active",
        "nam10_journalist_pick_confirmed",
        "nam10_journalist_dm_signature",
        (
            ("nam10_journalist_pending_tid", None),
            ("nam10_journalist_idle_confirmed", False),
        ),
    ),
)

_ROLE_PICK_BY_NAME = {s.role: s for s in NO_HOST_ROLE_PICK_SPECS}


@dataclass
class NoHostRolePickView:
    """nested view — خواندن/نوشتن فیلدهای flat یک نقش."""

    game: Game
    spec: RolePickFieldSpec

    @property
    def flow_active(self) -> bool:
        return bool(getattr(self.game, self.spec.flow_active))

    @flow_active.setter
    def flow_active(self, value: bool) -> None:
        setattr(self.game, self.spec.flow_active, value)

    @property
    def pick_confirmed(self) -> bool:
        return bool(getattr(self.game, self.spec.pick_confirmed))

    @pick_confirmed.setter
    def pick_confirmed(self, value: bool) -> None:
        setattr(self.game, self.spec.pick_confirmed, value)

    @property
    def dm_signature(self) -> str | None:
        return getattr(self.game, self.spec.dm_signature)

    @dm_signature.setter
    def dm_signature(self, value: str | None) -> None:
        setattr(self.game, self.spec.dm_signature, value)

    def reset(self) -> None:
        self.flow_active = False
        self.pick_confirmed = False
        self.dm_signature = None
        for attr, default in self.spec.extra_resets:
            setattr(self.game, attr, default if not isinstance(default, list) else [])


@dataclass
class NoHostMafiaNight1View:
    game: Game

    def reset(self) -> None:
        g = self.game
        g.nam10_mafia_night1_flow_active = False
        g.nam10_mafia_night1_done = False
        g.nam10_mafia_night1_pending_action = None
        g.nam10_mafia_night1_chosen_action = None
        g.nam10_mafia_night1_actor_uid = None
        g.nam10_mafia_night1_panel_uids = []
        g.nam10_mafia_night1_refs.clear()


@dataclass
class NoHostMafiaOpsView:
    game: Game

    def reset(self) -> None:
        g = self.game
        g.nam10_mafia_shot_done = False
        g.nam10_mafia_shot_flow_active = False
        from bot.nam10.roles_night_state import yaku_night_state

        yaku_night_state(g).reset_no_host_ops()
        g.nam10_mafia_nato_done = False
        g.nam10_mafia_nato_flow_active = False
        g.nam10_mafia_nato_phase = None
        g.nam10_mafia_nato_pending_role = None
        g.nam10_mafia_nato_pending_target_uid = None
        g.nam10_negotiator_flow_active = False
        g.nam10_negotiator_pick_confirmed = False
        g.nam10_negotiator_pending_tid = None
        from bot.nam10.mode import is_mason_scenario

        if is_mason_scenario(g):
            from bot.roles.mason_nato import clear_mason_nato_night_state

            clear_mason_nato_night_state(g)


@dataclass
class NoHostHunterNight1View:
    game: Game

    def reset(self) -> None:
        g = self.game
        g.nam10_night1_hunter_flow_active = False
        g.nam10_night1_hunter_done = False
        g.nam10_hunter_pending_pick_uid = None
        g.nam10_hunter_awaiting_confirm = False


@dataclass
class NoHostNightStateView:
    """تمام state پنل‌های شبانه no_host — reset یک‌جا."""

    game: Game
    hunter: NoHostHunterNight1View = field(init=False)
    mafia_night1: NoHostMafiaNight1View = field(init=False)
    mafia_ops: NoHostMafiaOpsView = field(init=False)

    def __post_init__(self) -> None:
        self.hunter = NoHostHunterNight1View(self.game)
        self.mafia_night1 = NoHostMafiaNight1View(self.game)
        self.mafia_ops = NoHostMafiaOpsView(self.game)

    def role_pick(self, role: str) -> NoHostRolePickView:
        spec = _ROLE_PICK_BY_NAME[role]
        return NoHostRolePickView(self.game, spec)

    def reset_per_night_role_panels(self) -> None:
        """معادل declarative ``reset_no_host_per_night_role_state`` (بخش نقش)."""
        from bot.nam10.no_host_mirror_reset import reset_no_host_night_mirror_prompts

        reset_no_host_night_mirror_prompts(self.game)
        self.hunter.reset()
        self.mafia_night1.reset()
        self.mafia_ops.reset()
        for spec in NO_HOST_ROLE_PICK_SPECS:
            NoHostRolePickView(self.game, spec).reset()
        from bot.nam10.roles_night_state import passive_night_state

        g = self.game
        passive_night_state(g).reset_ruintan_night_panel()
        g.nam10_citizen_night_confirmed_uids = []


@dataclass
class NoHostDayStateView:
    game: Game

    @property
    def intro_night_started(self) -> bool:
        return self.game.nam10_intro_night_started

    @intro_night_started.setter
    def intro_night_started(self, value: bool) -> None:
        self.game.nam10_intro_night_started = value

    @property
    def day1_vote_resolved(self) -> bool:
        return self.game.nam10_day1_vote_resolved

    @day1_vote_resolved.setter
    def day1_vote_resolved(self, value: bool) -> None:
        self.game.nam10_day1_vote_resolved = value


@dataclass
class BazporsNarratorStateView:
    """زیرمجموعهٔ state نریتور semi_auto / no_host."""

    game: Game

    @property
    def step(self) -> str | None:
        return self.game.nmnd_narrator_step

    @step.setter
    def step(self, value: str | None) -> None:
        self.game.nmnd_narrator_step = value

    @property
    def night_count(self) -> int:
        return self.game.nmnd_narrator_night_count

    @night_count.setter
    def night_count(self, value: int) -> None:
        self.game.nmnd_narrator_night_count = value

    @property
    def night_substep(self) -> str | None:
        return self.game.nmnd_night_substep

    @night_substep.setter
    def night_substep(self, value: str | None) -> None:
        self.game.nmnd_night_substep = value


def nam10_night_state(game: Game) -> NoHostNightStateView:
    return NoHostNightStateView(game)


def nam10_day_state(game: Game) -> NoHostDayStateView:
    return NoHostDayStateView(game)


def nmnd_narrator_state(game: Game) -> BazporsNarratorStateView:
    return BazporsNarratorStateView(game)


def arm_no_host_role_pick(game: Game, role: str) -> None:
    """اگر پنل قبلاً فرستاده شده ولی flow_active خاموش است، دوباره فعال کن."""
    view = nam10_night_state(game).role_pick(role)
    if view.pick_confirmed:
        return
    if not view.flow_active and view.dm_signature:
        view.flow_active = True


def reset_no_host_per_night_role_state(game: Game) -> None:
    nam10_night_state(game).reset_per_night_role_panels()
    from bot.nam10.mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.mason_night_entry import reset_mason_night_panel_state

        reset_mason_night_panel_state(game)
        game.mason_night_start_prompt_sent = False
