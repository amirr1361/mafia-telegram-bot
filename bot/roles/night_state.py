"""Phase D — typed accessors for scattered night-role state on ``Game``.

Compatibility-first: all reads/writes go through legacy flat fields on ``Game``.
No new persisted fields — safe for SQLite snapshots and in-flight games.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.game_state import (
        NoHostHunterNight1View,
        NoHostMafiaNight1View,
        NoHostMafiaOpsView,
        NoHostRolePickView,
    )
    from bot.models import Game, Role


@dataclass
class DoctorNightState:
    """Doctor night pick + self-save counters — legacy field shim."""

    game: Game

    def get_save_uids(self) -> list[int]:
        return list(self.game.bazpors_doctor_save_uids)

    def save_uid_set_raw(self) -> set[int]:
        if self.game.bazpors_doctor_save_uids:
            return set(self.game.bazpors_doctor_save_uids)
        if self.game.actions.doctor_save is not None:
            return {self.game.actions.doctor_save}
        return set()

    def set_save_target(self, target_uid: int) -> None:
        self.game.bazpors_doctor_save_uids = [target_uid]
        self.game.actions.doctor_save = target_uid

    def add_save_target(self, target_uid: int) -> bool:
        """افزودن هدف نجات تا سقف ظرفیت؛ برای مذاکره (چند نجات در یک شب)."""
        from bot.roles.doctor import doctor_save_capacity

        uids = list(self.game.bazpors_doctor_save_uids)
        if target_uid in uids:
            return True
        if len(uids) >= doctor_save_capacity(self.game):
            return False
        uids.append(target_uid)
        self.game.bazpors_doctor_save_uids = uids
        if self.game.actions.doctor_save is None:
            self.game.actions.doctor_save = target_uid
        return True

    def clear_save(self) -> None:
        self.game.bazpors_doctor_save_uids = []
        self.game.actions.doctor_save = None
        self.clear_pending_self_save()

    @property
    def self_save_count(self) -> int:
        if self.game.scenario_name == "mozakere":
            return self.game.mozakere_doctor_self_save_count
        return self.game.bazpors_doctor_self_save_count

    @self_save_count.setter
    def self_save_count(self, value: int) -> None:
        if self.game.scenario_name == "mozakere":
            self.game.mozakere_doctor_self_save_count = value
        else:
            self.game.bazpors_doctor_self_save_count = value

    @property
    def pending_self_save(self) -> bool:
        return bool(self.game.bazpors_night_pending_doctor_self_save)

    @pending_self_save.setter
    def pending_self_save(self, value: bool) -> None:
        self.game.bazpors_night_pending_doctor_self_save = value

    @property
    def baseline_self_saves(self) -> int:
        if self.game.scenario_name == "mozakere":
            return self.game.mozakere_night_baseline_doctor_self_saves
        return self.game.bazpors_night_baseline_doctor_self_saves

    @baseline_self_saves.setter
    def baseline_self_saves(self, value: int) -> None:
        if self.game.scenario_name == "mozakere":
            self.game.mozakere_night_baseline_doctor_self_saves = value
        else:
            self.game.bazpors_night_baseline_doctor_self_saves = value

    def mark_pending_self_save(self) -> None:
        self.pending_self_save = True

    def clear_pending_self_save(self) -> None:
        self.pending_self_save = False

    def snapshot_night_baseline(self) -> None:
        self.baseline_self_saves = self.self_save_count
        self.clear_pending_self_save()

    def rollback_self_save_count_to_baseline(self) -> None:
        if self.self_save_count > self.baseline_self_saves:
            self.self_save_count = self.baseline_self_saves

    def commit_pending_self_save(self) -> None:
        if not self.pending_self_save:
            return
        self.self_save_count += 1
        self.clear_pending_self_save()

    @property
    def no_host_pending_save_uids(self) -> list[int]:
        return self.game.no_host_doctor_pending_save_uids

    def set_no_host_pending_save_uids(self, uids: list[int]) -> None:
        self.game.no_host_doctor_pending_save_uids = list(uids)

    def clear_no_host_pending_save_uids(self) -> None:
        self.game.no_host_doctor_pending_save_uids = []

    @property
    def no_host_nato_blocked_panel(self) -> bool:
        return bool(self.game.no_host_doctor_nato_blocked_panel)

    @no_host_nato_blocked_panel.setter
    def no_host_nato_blocked_panel(self, value: bool) -> None:
        self.game.no_host_doctor_nato_blocked_panel = value

    def no_host_pick(self) -> NoHostRolePickView:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).role_pick("doctor")


@dataclass
class DetectiveNightState:
    """Detective inquiry — committed target/result on legacy flat fields."""

    game: Game

    @property
    def no_inquiry(self) -> bool:
        return bool(self.game.bazpors_det_no_inquiry)

    @property
    def blocked(self) -> bool:
        return bool(self.game.bazpors_detective_blocked)

    @blocked.setter
    def blocked(self, value: bool) -> None:
        self.game.bazpors_detective_blocked = value

    @property
    def ack_positive(self) -> bool:
        return bool(self.game.bazpors_det_ack_positive)

    @property
    def last_answer(self) -> str | None:
        return self.game.bazpors_detective_last_answer

    @last_answer.setter
    def last_answer(self, value: str | None) -> None:
        self.game.bazpors_detective_last_answer = value

    @property
    def target_uid(self) -> int | None:
        if self.no_inquiry:
            return None
        return self.game.actions.detective_check

    def set_committed(
        self,
        target_uid: int,
        *,
        positive: bool,
        last_answer: str,
    ) -> None:
        self.game.bazpors_det_no_inquiry = False
        self.game.actions.detective_check = target_uid
        self.game.bazpors_det_ack_positive = positive
        self.game.bazpors_detective_last_answer = last_answer

    def void_pick(self) -> None:
        self.game.actions.detective_check = None
        self.game.bazpors_det_no_inquiry = False
        self.game.bazpors_det_ack_positive = False
        self.game.bazpors_detective_last_answer = None

    def mark_no_inquiry(self) -> None:
        self.game.bazpors_det_no_inquiry = True
        self.game.actions.detective_check = None
        self.game.bazpors_det_ack_positive = False
        self.game.bazpors_detective_last_answer = "کارآگاه استعلام نگرفت."

    def block_by_shiad(self) -> None:
        self.blocked = True
        self.game.bazpors_det_ack_positive = False
        self.game.bazpors_detective_last_answer = None

    def commit_shiad_voided_note(self) -> None:
        self.game.bazpors_det_no_inquiry = False
        self.game.bazpors_det_ack_positive = False
        self.last_answer = "استعلام منفی (شیاد کارآگاه را شناسایی کرد)."

    @property
    def no_host_pending_tid(self) -> int | None:
        return self.game.no_host_detective_pending_tid

    @no_host_pending_tid.setter
    def no_host_pending_tid(self, value: int | None) -> None:
        self.game.no_host_detective_pending_tid = value

    @property
    def result_pending(self) -> bool:
        return bool(self.game.no_host_detective_result_pending)

    @result_pending.setter
    def result_pending(self, value: bool) -> None:
        self.game.no_host_detective_result_pending = value

    @property
    def result_sent_night(self) -> int | None:
        return self.game.no_host_detective_result_sent_night

    @result_sent_night.setter
    def result_sent_night(self, value: int | None) -> None:
        self.game.no_host_detective_result_sent_night = value

    def no_host_pick(self) -> NoHostRolePickView:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).role_pick("detective")


@dataclass
class ShiadNightState:
    """Shiad guess target + detective block side-effects."""

    game: Game

    @property
    def target_uid(self) -> int | None:
        return self.game.bazpors_shiad_target_uid

    @target_uid.setter
    def target_uid(self, value: int | None) -> None:
        self.game.bazpors_shiad_target_uid = value

    def clear_pick(self) -> None:
        self.target_uid = None
        detective_night_state(self.game).blocked = False

    @property
    def no_host_pending_tid(self) -> int | None:
        return self.game.no_host_shiad_pending_tid

    @no_host_pending_tid.setter
    def no_host_pending_tid(self, value: int | None) -> None:
        self.game.no_host_shiad_pending_tid = value

    @property
    def result_pending(self) -> bool:
        return bool(self.game.no_host_shiad_result_pending)

    @result_pending.setter
    def result_pending(self, value: bool) -> None:
        self.game.no_host_shiad_result_pending = value

    @property
    def result_sent_night(self) -> int | None:
        return self.game.no_host_shiad_result_sent_night

    @result_sent_night.setter
    def result_sent_night(self, value: int | None) -> None:
        self.game.no_host_shiad_result_sent_night = value

    def no_host_pick(self) -> NoHostRolePickView:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).role_pick("shiad")


@dataclass
class SniperNightState:
    """Sniper bullet + night target."""

    game: Game

    @property
    def bullet_used(self) -> bool:
        return bool(self.game.bazpors_sniper_shot_used)

    def mark_bullet_used(self) -> None:
        self.game.bazpors_sniper_shot_used = True

    @property
    def night_target_uid(self) -> int | None:
        return self.game.bazpors_sniper_night_target_uid

    @night_target_uid.setter
    def night_target_uid(self, value: int | None) -> None:
        self.game.bazpors_sniper_night_target_uid = value

    @property
    def hero_mafia_kill(self) -> bool:
        return bool(self.game.bazpors_sniper_hero_mafia_kill)

    @hero_mafia_kill.setter
    def hero_mafia_kill(self, value: bool) -> None:
        self.game.bazpors_sniper_hero_mafia_kill = value

    @property
    def no_host_pending_target_uid(self) -> int | None:
        return self.game.no_host_sniper_pending_target_uid

    @no_host_pending_target_uid.setter
    def no_host_pending_target_uid(self, value: int | None) -> None:
        self.game.no_host_sniper_pending_target_uid = value

    @property
    def result_pending(self) -> bool:
        return bool(self.game.no_host_sniper_result_pending)

    @result_pending.setter
    def result_pending(self, value: bool) -> None:
        self.game.no_host_sniper_result_pending = value

    @property
    def result_sent_night(self) -> int | None:
        return self.game.no_host_sniper_result_sent_night

    @result_sent_night.setter
    def result_sent_night(self, value: int | None) -> None:
        self.game.no_host_sniper_result_sent_night = value

    def no_host_pick(self) -> NoHostRolePickView:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).role_pick("sniper")


@dataclass
class HunterNightState:
    """Hunter link + report snapshot + no_host night1 panel."""

    game: Game

    @property
    def link_uid(self) -> int | None:
        return self.game.bazpors_hunter_link_uid

    @link_uid.setter
    def link_uid(self, value: int | None) -> None:
        self.game.bazpors_hunter_link_uid = value

    @property
    def linked_this_night(self) -> bool:
        return bool(self.game.bazpors_hunter_linked_this_night)

    @linked_this_night.setter
    def linked_this_night(self, value: bool) -> None:
        self.game.bazpors_hunter_linked_this_night = value

    @property
    def report_link_uid(self) -> int | None:
        return self.game.bazpors_hunter_report_link_uid

    @report_link_uid.setter
    def report_link_uid(self, value: int | None) -> None:
        self.game.bazpors_hunter_report_link_uid = value

    @property
    def report_chain_line(self) -> str | None:
        return self.game.bazpors_hunter_report_chain_line

    @report_chain_line.setter
    def report_chain_line(self, value: str | None) -> None:
        self.game.bazpors_hunter_report_chain_line = value

    def commit_pick(self, target_uid: int) -> None:
        self.link_uid = target_uid
        self.linked_this_night = True
        self.report_link_uid = target_uid
        self.report_chain_line = None

    def commit_no_link(self) -> None:
        self.linked_this_night = False
        self.report_link_uid = None

    def clear_link_state(self) -> None:
        self.link_uid = None
        self.linked_this_night = False

    def night1_view(self) -> NoHostHunterNight1View:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).hunter


@dataclass
class NatoNightState:
    """NATO guess — shared semi_auto + no_host mafia panel flow."""

    game: Game

    @property
    def used(self) -> bool:
        return bool(self.game.bazpors_nato_used)

    @used.setter
    def used(self, value: bool) -> None:
        self.game.bazpors_nato_used = value

    @property
    def action_registered(self) -> bool:
        return bool(self.game.bazpors_nato_action_registered)

    @action_registered.setter
    def action_registered(self, value: bool) -> None:
        self.game.bazpors_nato_action_registered = value

    @property
    def success(self) -> bool | None:
        return self.game.bazpors_nato_success

    @success.setter
    def success(self, value: bool | None) -> None:
        self.game.bazpors_nato_success = value

    @property
    def kill_target_uid(self) -> int | None:
        return self.game.bazpors_nato_kill_target_uid

    @kill_target_uid.setter
    def kill_target_uid(self, value: int | None) -> None:
        self.game.bazpors_nato_kill_target_uid = value

    @property
    def guess_target_uid(self) -> int | None:
        return self.game.bazpors_nato_guess_target_uid

    @guess_target_uid.setter
    def guess_target_uid(self, value: int | None) -> None:
        self.game.bazpors_nato_guess_target_uid = value

    @property
    def guess_role(self) -> str | None:
        return self.game.bazpors_nato_guess_role

    @guess_role.setter
    def guess_role(self, value: str | None) -> None:
        self.game.bazpors_nato_guess_role = value

    @property
    def multi_uids(self) -> str | None:
        return self.game.bazpors_nato_multi_uids

    @multi_uids.setter
    def multi_uids(self, value: str | None) -> None:
        self.game.bazpors_nato_multi_uids = value

    def clear_pending_role(self) -> None:
        self.guess_role = None
        self.game.bazpors_narrator_pending_uid = None
        self.multi_uids = None

    def commit_guess(
        self,
        guess_role: Role,
        target_uid: int,
        *,
        success: bool,
    ) -> None:
        self.guess_role = guess_role.value
        self.guess_target_uid = target_uid
        self.action_registered = True
        self.used = True
        self.success = success
        self.kill_target_uid = target_uid if success else None
        self.multi_uids = None
        self.game.bazpors_narrator_pending_uid = None

    def commit_confirm_result(self, target_uid: int, *, success: bool) -> None:
        self.action_registered = True
        self.used = True
        self.success = success
        self.kill_target_uid = target_uid if success else None
        self.guess_target_uid = target_uid

    def commit_multi_pick_fail(self) -> None:
        self.action_registered = True
        self.used = True
        self.success = False
        self.multi_uids = None

    def commit_multi_pick_success(self, target_uid: int) -> None:
        self.action_registered = True
        self.used = True
        self.success = True
        self.kill_target_uid = target_uid
        self.guess_target_uid = target_uid
        self.multi_uids = None

    @property
    def no_host_flow_active(self) -> bool:
        return bool(self.game.no_host_mafia_nato_flow_active)

    @no_host_flow_active.setter
    def no_host_flow_active(self, value: bool) -> None:
        self.game.no_host_mafia_nato_flow_active = value

    @property
    def no_host_done(self) -> bool:
        return bool(self.game.no_host_mafia_nato_done)

    @no_host_done.setter
    def no_host_done(self, value: bool) -> None:
        self.game.no_host_mafia_nato_done = value

    @property
    def no_host_phase(self) -> str | None:
        return self.game.no_host_mafia_nato_phase

    @no_host_phase.setter
    def no_host_phase(self, value: str | None) -> None:
        self.game.no_host_mafia_nato_phase = value

    @property
    def no_host_pending_role(self) -> str | None:
        return self.game.no_host_mafia_nato_pending_role

    @no_host_pending_role.setter
    def no_host_pending_role(self, value: str | None) -> None:
        self.game.no_host_mafia_nato_pending_role = value

    @property
    def no_host_pending_target_uid(self) -> int | None:
        return self.game.no_host_mafia_nato_pending_target_uid

    @no_host_pending_target_uid.setter
    def no_host_pending_target_uid(self, value: int | None) -> None:
        self.game.no_host_mafia_nato_pending_target_uid = value


@dataclass
class InterrogatorNightState:
    """Interrogator nominees + no_host pick panel."""

    game: Game

    @property
    def once_done(self) -> bool:
        return bool(self.game.bazpors_interrog_once_done)

    @once_done.setter
    def once_done(self, value: bool) -> None:
        self.game.bazpors_interrog_once_done = value

    @property
    def pick_uid(self) -> int | None:
        return self.game.bazpors_interrog_pick_uid

    @pick_uid.setter
    def pick_uid(self, value: int | None) -> None:
        self.game.bazpors_interrog_pick_uid = value

    @property
    def first_uid(self) -> int | None:
        return self.game.bazpors_interrog_first_uid

    @first_uid.setter
    def first_uid(self, value: int | None) -> None:
        self.game.bazpors_interrog_first_uid = value

    @property
    def second_uid(self) -> int | None:
        return self.game.bazpors_interrog_second_uid

    @second_uid.setter
    def second_uid(self, value: int | None) -> None:
        self.game.bazpors_interrog_second_uid = value

    @property
    def night_finished(self) -> bool:
        return bool(self.game.bazpors_interrog_night_finished)

    @night_finished.setter
    def night_finished(self, value: bool) -> None:
        self.game.bazpors_interrog_night_finished = value

    @property
    def ready_for_day(self) -> bool:
        return bool(self.game.bazpors_interrog_ready_for_day)

    @ready_for_day.setter
    def ready_for_day(self, value: bool) -> None:
        self.game.bazpors_interrog_ready_for_day = value

    @property
    def cancel_next_day(self) -> bool:
        return bool(self.game.bazpors_interrog_cancel_next_day)

    @cancel_next_day.setter
    def cancel_next_day(self, value: bool) -> None:
        self.game.bazpors_interrog_cancel_next_day = value

    def commit_first_nominee(self, target_uid: int) -> None:
        self.pick_uid = target_uid
        self.first_uid = target_uid

    def commit_second_nominee(self, target_uid: int) -> None:
        self.second_uid = target_uid
        self.pick_uid = None
        self.night_finished = True

    def clear_night_pick(self) -> None:
        self.pick_uid = None
        self.first_uid = None
        self.second_uid = None
        self.night_finished = False

    def clear_day_targets(self) -> None:
        self.first_uid = None
        self.second_uid = None
        self.night_finished = False

    @property
    def no_host_ui_phase(self) -> str | None:
        return self.game.no_host_interrog_ui_phase

    @no_host_ui_phase.setter
    def no_host_ui_phase(self, value: str | None) -> None:
        self.game.no_host_interrog_ui_phase = value

    def no_host_pick(self) -> NoHostRolePickView:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).role_pick("interrog")


@dataclass
class MafiaNightState:
    """Mafia shot target + no_host shot flow."""

    game: Game

    @property
    def shot_registered(self) -> bool:
        return bool(self.game.bazpors_mafia_shot_registered)

    @shot_registered.setter
    def shot_registered(self, value: bool) -> None:
        self.game.bazpors_mafia_shot_registered = value

    @property
    def target_uid(self) -> int | None:
        return self.game.actions.mafia_target

    @target_uid.setter
    def target_uid(self, value: int | None) -> None:
        self.game.actions.mafia_target = value

    def commit_shot(self, target_uid: int) -> None:
        self.target_uid = target_uid
        self.shot_registered = True

    @property
    def no_host_flow_active(self) -> bool:
        return bool(self.game.no_host_mafia_shot_flow_active)

    @no_host_flow_active.setter
    def no_host_flow_active(self, value: bool) -> None:
        self.game.no_host_mafia_shot_flow_active = value

    @property
    def no_host_done(self) -> bool:
        return bool(self.game.no_host_mafia_shot_done)

    @no_host_done.setter
    def no_host_done(self, value: bool) -> None:
        self.game.no_host_mafia_shot_done = value

    @property
    def no_host_pending_uid(self) -> int | None:
        return self.game.no_host_mafia_shot_pending_uid

    @no_host_pending_uid.setter
    def no_host_pending_uid(self, value: int | None) -> None:
        self.game.no_host_mafia_shot_pending_uid = value

    @property
    def no_host_awaiting_confirm(self) -> bool:
        return bool(self.game.no_host_mafia_shot_awaiting_confirm)

    @no_host_awaiting_confirm.setter
    def no_host_awaiting_confirm(self, value: bool) -> None:
        self.game.no_host_mafia_shot_awaiting_confirm = value

    def finalize_no_host_shot(self) -> None:
        self.no_host_flow_active = False
        self.no_host_done = True
        self.no_host_pending_uid = None
        self.no_host_awaiting_confirm = False

    def night1_view(self) -> NoHostMafiaNight1View:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).mafia_night1

    def ops_view(self) -> NoHostMafiaOpsView:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).mafia_ops


@dataclass
class YakuNightState:
    """Yakuzai recruit — shared semi_auto + no_host mafia night ops."""

    game: Game

    @property
    def used(self) -> bool:
        return bool(self.game.bazpors_yakuzai_used)

    @used.setter
    def used(self, value: bool) -> None:
        self.game.bazpors_yakuzai_used = value

    @property
    def sac_uid(self) -> int | None:
        return self.game.bazpors_yaku_sac_uid

    @sac_uid.setter
    def sac_uid(self, value: int | None) -> None:
        self.game.bazpors_yaku_sac_uid = value

    @property
    def sac_elim_uid(self) -> int | None:
        return self.game.bazpors_yaku_sac_elim_uid

    @sac_elim_uid.setter
    def sac_elim_uid(self, value: int | None) -> None:
        self.game.bazpors_yaku_sac_elim_uid = value

    @property
    def night_civilian_uid(self) -> int | None:
        return self.game.bazpors_yaku_night_civilian_uid

    @night_civilian_uid.setter
    def night_civilian_uid(self, value: int | None) -> None:
        self.game.bazpors_yaku_night_civilian_uid = value

    @property
    def night_success(self) -> bool | None:
        return self.game.bazpors_yaku_night_success

    @night_success.setter
    def night_success(self, value: bool | None) -> None:
        self.game.bazpors_yaku_night_success = value

    @property
    def no_host_flow_active(self) -> bool:
        return bool(self.game.no_host_mafia_yaku_flow_active)

    @no_host_flow_active.setter
    def no_host_flow_active(self, value: bool) -> None:
        self.game.no_host_mafia_yaku_flow_active = value

    @property
    def no_host_done(self) -> bool:
        return bool(self.game.no_host_mafia_yaku_done)

    @no_host_done.setter
    def no_host_done(self, value: bool) -> None:
        self.game.no_host_mafia_yaku_done = value

    @property
    def no_host_phase(self) -> str | None:
        return self.game.no_host_mafia_yaku_phase

    @no_host_phase.setter
    def no_host_phase(self, value: str | None) -> None:
        self.game.no_host_mafia_yaku_phase = value

    @property
    def no_host_pending_sac_uid(self) -> int | None:
        return self.game.no_host_mafia_yaku_pending_sac_uid

    @no_host_pending_sac_uid.setter
    def no_host_pending_sac_uid(self, value: int | None) -> None:
        self.game.no_host_mafia_yaku_pending_sac_uid = value

    @property
    def no_host_pending_civ_uid(self) -> int | None:
        return self.game.no_host_mafia_yaku_pending_civ_uid

    @no_host_pending_civ_uid.setter
    def no_host_pending_civ_uid(self, value: int | None) -> None:
        self.game.no_host_mafia_yaku_pending_civ_uid = value

    @property
    def report_sac_uid(self) -> int | None:
        return self.sac_elim_uid or self.sac_uid

    @property
    def civilian_picked_this_night(self) -> bool:
        return self.night_civilian_uid is not None

    @property
    def successful_recruit_pending(self) -> bool:
        return bool(self.night_success and self.night_civilian_uid is not None)

    def reset_narrator_assist_start(self) -> None:
        self.used = False
        self.clear_pick_state()

    def clear_pick_state(self) -> None:
        self.sac_uid = None
        self.sac_elim_uid = None
        self.night_civilian_uid = None
        self.night_success = None

    def clear_civilian_pick_state(self) -> None:
        self.night_civilian_uid = None
        self.night_success = None

    def back_from_civilian_to_sac(self) -> None:
        self.sac_uid = None
        self.clear_civilian_pick_state()

    def back_from_sac_to_menu(self) -> None:
        self.clear_pick_state()

    def commit_sac_pick(self, sac_uid: int) -> None:
        self.sac_uid = sac_uid

    def commit_outcome(
        self,
        *,
        civ_uid: int,
        sac_uid: int,
        success: bool,
    ) -> None:
        self.night_civilian_uid = civ_uid
        self.night_success = success
        self.sac_elim_uid = sac_uid

    def mark_used(self) -> None:
        self.used = True

    def clear_sac_uid_after_ack(self) -> None:
        self.sac_uid = None

    def clear_handoff_night_pick(self) -> None:
        """پس از handoff به semi_auto — فقط state انتخاب همان شب."""
        self.night_civilian_uid = None
        self.night_success = None
        self.sac_uid = None

    def start_no_host_flow(self) -> None:
        self.no_host_flow_active = True
        self.no_host_phase = "sac"
        self.no_host_pending_sac_uid = None
        self.no_host_pending_civ_uid = None

    def finalize_no_host_sac(self, sac_uid: int) -> None:
        self.sac_uid = sac_uid
        self.no_host_phase = "civ"
        self.no_host_pending_sac_uid = None

    def finalize_no_host_flow(self) -> None:
        self.no_host_flow_active = False
        self.no_host_done = True
        self.no_host_phase = None
        self.no_host_pending_civ_uid = None

    def reset_no_host_ops(self) -> None:
        self.no_host_done = False
        self.no_host_flow_active = False
        self.no_host_phase = None
        self.no_host_pending_sac_uid = None
        self.no_host_pending_civ_uid = None

    def sacrifice_elimination_uid(self) -> int | None:
        if not self.used:
            return None
        su = self.sac_elim_uid
        if su is not None and su in self.game.players:
            return su
        return None

    def ops_view(self) -> NoHostMafiaOpsView:
        from bot.game_state import no_host_night_state

        return no_host_night_state(self.game).mafia_ops


@dataclass
class PassiveNightState:
    """Ruintan ack + citizen batch confirm — no_host passive panels."""

    game: Game

    @property
    def ruintan_night_confirmed(self) -> bool:
        return bool(self.game.no_host_ruintan_night_confirmed)

    @ruintan_night_confirmed.setter
    def ruintan_night_confirmed(self, value: bool) -> None:
        self.game.no_host_ruintan_night_confirmed = value

    @property
    def ruintan_dm_signature(self) -> str | None:
        return self.game.no_host_ruintan_dm_signature

    @ruintan_dm_signature.setter
    def ruintan_dm_signature(self, value: str | None) -> None:
        self.game.no_host_ruintan_dm_signature = value

    @property
    def ruintan_rules_sent_night(self) -> int | None:
        return self.game.no_host_ruintan_rules_sent_night

    @ruintan_rules_sent_night.setter
    def ruintan_rules_sent_night(self, value: int | None) -> None:
        self.game.no_host_ruintan_rules_sent_night = value

    @property
    def citizen_confirmed_uids(self) -> list[int]:
        return self.game.no_host_citizen_night_confirmed_uids

    def citizen_is_confirmed(self, uid: int) -> bool:
        return uid in self.citizen_confirmed_uids

    def citizen_confirm(self, uid: int) -> None:
        if uid not in self.citizen_confirmed_uids:
            self.game.no_host_citizen_night_confirmed_uids.append(uid)

    def reset_citizen_batch(self, signature: str) -> None:
        self.game.no_host_citizen_night_batch_signature = signature
        self.game.no_host_citizen_night_confirmed_uids = []

    @property
    def citizen_batch_signature(self) -> str | None:
        return self.game.no_host_citizen_night_batch_signature

    @citizen_batch_signature.setter
    def citizen_batch_signature(self, value: str | None) -> None:
        self.game.no_host_citizen_night_batch_signature = value

    def reset_ruintan_night_panel(self) -> None:
        self.ruintan_night_confirmed = False


@dataclass
class NightRoleState:
    """Root accessor for per-role night state views."""

    game: Game

    @property
    def doctor(self) -> DoctorNightState:
        return DoctorNightState(self.game)

    @property
    def detective(self) -> DetectiveNightState:
        return DetectiveNightState(self.game)

    @property
    def shiad(self) -> ShiadNightState:
        return ShiadNightState(self.game)

    @property
    def sniper(self) -> SniperNightState:
        return SniperNightState(self.game)

    @property
    def hunter(self) -> HunterNightState:
        return HunterNightState(self.game)

    @property
    def nato(self) -> NatoNightState:
        return NatoNightState(self.game)

    @property
    def interrogator(self) -> InterrogatorNightState:
        return InterrogatorNightState(self.game)

    @property
    def mafia(self) -> MafiaNightState:
        return MafiaNightState(self.game)

    @property
    def yaku(self) -> YakuNightState:
        return YakuNightState(self.game)

    @property
    def passive(self) -> PassiveNightState:
        return PassiveNightState(self.game)


def night_role_state(game: Game) -> NightRoleState:
    return NightRoleState(game)


def doctor_night_state(game: Game) -> DoctorNightState:
    return DoctorNightState(game)


def detective_night_state(game: Game) -> DetectiveNightState:
    return DetectiveNightState(game)


def shiad_night_state(game: Game) -> ShiadNightState:
    return ShiadNightState(game)


def sniper_night_state(game: Game) -> SniperNightState:
    return SniperNightState(game)


def hunter_night_state(game: Game) -> HunterNightState:
    return HunterNightState(game)


def nato_night_state(game: Game) -> NatoNightState:
    return NatoNightState(game)


def interrogator_night_state(game: Game) -> InterrogatorNightState:
    return InterrogatorNightState(game)


def mafia_night_state(game: Game) -> MafiaNightState:
    return MafiaNightState(game)


def yaku_night_state(game: Game) -> YakuNightState:
    return YakuNightState(game)


def passive_night_state(game: Game) -> PassiveNightState:
    return PassiveNightState(game)


@dataclass
class MozakereNegotiationNightState:
    """مذاکرهٔ تیم مافیا — فقط سناریوی مذاکره."""

    game: Game

    @property
    def used(self) -> bool:
        return bool(self.game.mozakere_negotiation_used)

    @used.setter
    def used(self, value: bool) -> None:
        self.game.mozakere_negotiation_used = value

    @property
    def tonight(self) -> bool:
        return bool(self.game.mozakere_negotiation_tonight)

    @tonight.setter
    def tonight(self, value: bool) -> None:
        self.game.mozakere_negotiation_tonight = value

    @property
    def target_uid(self) -> int | None:
        return self.game.mozakere_negotiation_target_uid

    @target_uid.setter
    def target_uid(self, value: int | None) -> None:
        self.game.mozakere_negotiation_target_uid = value

    @property
    def night_success(self) -> bool | None:
        return self.game.mozakere_negotiation_success

    @night_success.setter
    def night_success(self, value: bool | None) -> None:
        self.game.mozakere_negotiation_success = value

    def clear_tonight(self) -> None:
        self.tonight = False
        self.target_uid = None
        self.night_success = None


def mozakere_negotiation_night_state(game: Game) -> MozakereNegotiationNightState:
    return MozakereNegotiationNightState(game)


@dataclass
class MozakereJournalistNightState:
    """استعلام خبرنگار — فقط سناریوی مذاکره."""

    game: Game

    @property
    def target_uid(self) -> int | None:
        return self.game.mozakere_journalist_target_uid

    @target_uid.setter
    def target_uid(self, value: int | None) -> None:
        self.game.mozakere_journalist_target_uid = value

    @property
    def ack_positive(self) -> bool:
        return bool(self.game.mozakere_journalist_ack_positive)

    @ack_positive.setter
    def ack_positive(self, value: bool) -> None:
        self.game.mozakere_journalist_ack_positive = value

    def clear_night(self) -> None:
        self.target_uid = None
        self.ack_positive = False


def mozakere_journalist_night_state(game: Game) -> MozakereJournalistNightState:
    return MozakereJournalistNightState(game)
