"""Phase D — night role state helpers (legacy compatibility)."""

from __future__ import annotations

import json
import unittest

from bot.game import GameManager
from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict
from bot.models import Game, NightActions, Player, Role
from bot.roles.doctor import (
    clear_pick,
    commit_pending_self_save,
    commit_pick,
    save_uid_set,
    void_night_pick,
)
from bot.roles.detective import (
    block_inquiry_by_shiad,
    commit_pick as det_commit_pick,
    load_result,
    mark_no_inquiry,
    void_pick as det_void_pick,
)
from bot.roles.hunter import commit_no_link, commit_pick as hunter_commit_pick
from bot.roles.interrogator import (
    commit_first_nominee,
    commit_second_nominee,
    first_nominee_uid,
)
from bot.roles.nato import commit_guess, already_used
from bot.roles.night_state import (
    detective_night_state,
    doctor_night_state,
    hunter_night_state,
    interrogator_night_state,
    mafia_night_state,
    nato_night_state,
    night_role_state,
    passive_night_state,
    shiad_night_state,
    sniper_night_state,
    yaku_night_state,
)
from bot.roles.shiad import commit_pick as shiad_commit_pick, clear_pick as shiad_clear
from bot.roles.sniper import commit_pick as sniper_commit_pick, night_target_uid


def _minimal_game(**kwargs: object) -> Game:
    defaults = dict(
        room_code="d1",
        host_id=1,
        scenario_name="bazpors",
        players={
            10: Player(10, "Doc", None, Role.DOCTOR, seat=1, is_alive=True),
            20: Player(20, "Cit", None, Role.CITIZEN, seat=2, is_alive=True),
        },
        max_players=10,
        bazpors_host_mode="no_host",
        no_host_assistant_narrator_active=True,
        bot_assistant_user_id=99,
        actions=NightActions(),
    )
    defaults.update(kwargs)
    return Game(**defaults)  # type: ignore[arg-type]


class DoctorNightStateHelperTests(unittest.TestCase):
    def test_save_target_syncs_legacy_fields(self) -> None:
        game = _minimal_game()
        state = doctor_night_state(game)
        state.set_save_target(20)
        self.assertEqual(game.bazpors_doctor_save_uids, [20])
        self.assertEqual(game.actions.doctor_save, 20)
        self.assertEqual(state.save_uid_set_raw(), {20})
        self.assertEqual(save_uid_set(game), {20})

    def test_clear_save_resets_legacy_fields(self) -> None:
        game = _minimal_game()
        state = doctor_night_state(game)
        state.set_save_target(20)
        state.mark_pending_self_save()
        state.clear_save()
        self.assertEqual(game.bazpors_doctor_save_uids, [])
        self.assertIsNone(game.actions.doctor_save)
        self.assertFalse(state.pending_self_save)

    def test_commit_pick_via_role_module(self) -> None:
        game = _minimal_game()
        commit_pick(game, 10)
        state = doctor_night_state(game)
        self.assertTrue(state.pending_self_save)
        self.assertEqual(state.get_save_uids(), [10])

    def test_void_night_pick_rolls_back_self_save_count(self) -> None:
        game = _minimal_game()
        game.bazpors_nato_action_registered = True
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 0
        commit_pick(game, 10)
        void_night_pick(game)
        self.assertEqual(doctor_night_state(game).self_save_count, 0)
        self.assertEqual(game.bazpors_doctor_save_uids, [])

    def test_snapshot_night_baseline(self) -> None:
        game = _minimal_game()
        game.bazpors_doctor_self_save_count = 2
        game.bazpors_night_pending_doctor_self_save = True
        doctor_night_state(game).snapshot_night_baseline()
        state = doctor_night_state(game)
        self.assertEqual(state.baseline_self_saves, 2)
        self.assertFalse(state.pending_self_save)

    def test_no_host_pending_save_uids(self) -> None:
        game = _minimal_game()
        state = doctor_night_state(game)
        state.set_no_host_pending_save_uids([20])
        self.assertEqual(game.no_host_doctor_pending_save_uids, [20])
        state.clear_no_host_pending_save_uids()
        self.assertEqual(game.no_host_doctor_pending_save_uids, [])

    def test_no_host_pick_view_aliases_legacy_fields(self) -> None:
        game = _minimal_game()
        pick = doctor_night_state(game).no_host_pick()
        pick.flow_active = True
        pick.pick_confirmed = True
        pick.dm_signature = "1:doc:night_entry"
        self.assertTrue(game.no_host_doctor_flow_active)
        self.assertTrue(game.no_host_doctor_pick_confirmed)
        self.assertEqual(game.no_host_doctor_dm_signature, "1:doc:night_entry")

    def test_night_role_state_root(self) -> None:
        game = _minimal_game()
        root = night_role_state(game)
        self.assertEqual(root.doctor.game, game)
        self.assertEqual(root.doctor.self_save_count, 0)

    def test_legacy_only_snapshot_loads_through_helpers(self) -> None:
        game = _minimal_game()
        game.bazpors_doctor_save_uids = [20]
        game.actions.doctor_save = 20
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.no_host_doctor_pending_save_uids = [20]
        game.no_host_doctor_nato_blocked_panel = True
        payload = game_to_snapshot_dict(game)
        loaded = game_from_snapshot_dict(json.loads(json.dumps(payload)))
        state = doctor_night_state(loaded)
        self.assertEqual(state.get_save_uids(), [20])
        self.assertEqual(state.self_save_count, 1)
        self.assertEqual(state.no_host_pending_save_uids, [20])
        self.assertTrue(state.no_host_nato_blocked_panel)

    def test_commit_pending_self_save_respects_nato_block(self) -> None:
        game = _minimal_game()
        commit_pick(game, 10)
        game.bazpors_nato_action_registered = True
        commit_pending_self_save(game)
        self.assertFalse(doctor_night_state(game).pending_self_save)
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

    def test_clear_pick_via_role_module(self) -> None:
        game = _minimal_game()
        commit_pick(game, 20)
        clear_pick(game)
        self.assertEqual(game.bazpors_doctor_save_uids, [])


class DoctorNightStateSemiAutoHandoffTests(unittest.TestCase):
    def test_handoff_commits_pending_self_save(self) -> None:
        from bot.bazpors_semi_auto_state import sync_bazpors_semi_auto_after_handoff

        game = _minimal_game(bazpors_host_mode="semi_auto", no_host_assistant_narrator_active=False)
        commit_pick(game, 10)
        sync_bazpors_semi_auto_after_handoff(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 1)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)
        self.assertEqual(game.bazpors_night_baseline_doctor_self_saves, 1)


class DetectiveNightStateHelperTests(unittest.TestCase):
    def test_committed_target_syncs_legacy_fields(self) -> None:
        game = _minimal_game(
            players={
                10: Player(10, "Det", None, Role.DETECTIVE, seat=1, is_alive=True),
                20: Player(20, "Cit", None, Role.CITIZEN, seat=2, is_alive=True),
            }
        )
        det_commit_pick(game, 20)
        state = detective_night_state(game)
        self.assertEqual(state.target_uid, 20)
        self.assertEqual(game.actions.detective_check, 20)
        self.assertFalse(state.no_inquiry)
        result = load_result(game)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.target_uid, 20)

    def test_void_pick_clears_legacy(self) -> None:
        game = _minimal_game(
            players={
                10: Player(10, "Det", None, Role.DETECTIVE, seat=1, is_alive=True),
                20: Player(20, "Cit", None, Role.CITIZEN, seat=2, is_alive=True),
            }
        )
        det_commit_pick(game, 20)
        det_void_pick(game)
        self.assertIsNone(game.actions.detective_check)
        self.assertIsNone(load_result(game))

    def test_mark_no_inquiry(self) -> None:
        game = _minimal_game()
        mark_no_inquiry(game)
        self.assertTrue(game.bazpors_det_no_inquiry)
        self.assertIsNone(detective_night_state(game).target_uid)

    def test_block_by_shiad(self) -> None:
        game = _minimal_game()
        block_inquiry_by_shiad(game)
        self.assertTrue(game.bazpors_detective_blocked)
        self.assertFalse(game.bazpors_det_ack_positive)

    def test_legacy_snapshot_loads_detective(self) -> None:
        game = _minimal_game()
        game.actions.detective_check = 20
        game.bazpors_det_ack_positive = True
        game.bazpors_detective_blocked = False
        payload = game_to_snapshot_dict(game)
        loaded = game_from_snapshot_dict(json.loads(json.dumps(payload)))
        self.assertEqual(detective_night_state(loaded).target_uid, 20)
        self.assertTrue(detective_night_state(loaded).ack_positive)


class ShiadNightStateHelperTests(unittest.TestCase):
    def test_commit_and_clear(self) -> None:
        game = _minimal_game(
            players={
                10: Player(10, "Sh", None, Role.SHIAD, seat=1, is_alive=True),
                20: Player(20, "Cit", None, Role.CITIZEN, seat=2, is_alive=True),
            }
        )
        shiad_commit_pick(game, 20)
        self.assertEqual(shiad_night_state(game).target_uid, 20)
        shiad_clear(game)
        self.assertIsNone(game.bazpors_shiad_target_uid)


class SniperNightStateHelperTests(unittest.TestCase):
    def test_commit_pick_and_bullet(self) -> None:
        game = _minimal_game(
            players={
                10: Player(10, "Sn", None, Role.SNIPER, seat=1, is_alive=True),
                20: Player(20, "Maf", None, Role.MAFIA, seat=2, is_alive=True),
            }
        )
        sniper_commit_pick(game, 20)
        self.assertEqual(night_target_uid(game), 20)
        state = sniper_night_state(game)
        state.mark_bullet_used()
        self.assertTrue(game.bazpors_sniper_shot_used)


class HunterNightStateHelperTests(unittest.TestCase):
    def test_commit_and_no_link(self) -> None:
        game = _minimal_game(
            players={
                10: Player(10, "Hu", None, Role.HUNTER, seat=1, is_alive=True),
                20: Player(20, "Maf", None, Role.MAFIA, seat=2, is_alive=True),
            }
        )
        hunter_commit_pick(game, 20)
        state = hunter_night_state(game)
        self.assertEqual(state.link_uid, 20)
        self.assertTrue(state.linked_this_night)
        commit_no_link(game)
        self.assertFalse(state.linked_this_night)


class NatoNightStateHelperTests(unittest.TestCase):
    def test_commit_guess_via_role_module(self) -> None:
        game = _minimal_game(
            players={
                10: Player(10, "Nato", None, Role.NATO, seat=1, is_alive=True),
                20: Player(20, "Doc", None, Role.DOCTOR, seat=2, is_alive=True),
            }
        )
        commit_guess(game, Role.DOCTOR, 20)
        state = nato_night_state(game)
        self.assertTrue(state.used)
        self.assertTrue(state.action_registered)
        self.assertTrue(state.success)
        self.assertEqual(state.kill_target_uid, 20)
        self.assertTrue(already_used(game))

    def test_legacy_snapshot_loads_nato(self) -> None:
        game = _minimal_game()
        game.bazpors_nato_used = True
        game.bazpors_nato_success = False
        game.bazpors_nato_guess_target_uid = 20
        payload = game_to_snapshot_dict(game)
        loaded = game_from_snapshot_dict(json.loads(json.dumps(payload)))
        state = nato_night_state(loaded)
        self.assertTrue(state.used)
        self.assertFalse(state.success)
        self.assertEqual(state.guess_target_uid, 20)


class InterrogatorNightStateHelperTests(unittest.TestCase):
    def test_nominee_flow(self) -> None:
        game = _minimal_game(
            players={
                10: Player(10, "Int", None, Role.INTERROGATOR, seat=1, is_alive=True),
                20: Player(20, "A", None, Role.CITIZEN, seat=2, is_alive=True),
                30: Player(30, "B", None, Role.CITIZEN, seat=3, is_alive=True),
            }
        )
        commit_first_nominee(game, 20)
        self.assertEqual(first_nominee_uid(game), 20)
        commit_second_nominee(game, 30)
        state = interrogator_night_state(game)
        self.assertEqual(state.second_uid, 30)
        self.assertTrue(state.night_finished)
        self.assertIsNone(state.pick_uid)


class MafiaNightStateHelperTests(unittest.TestCase):
    def test_commit_shot(self) -> None:
        game = _minimal_game()
        mafia_night_state(game).commit_shot(20)
        self.assertTrue(game.bazpors_mafia_shot_registered)
        self.assertEqual(game.actions.mafia_target, 20)

    def test_finalize_no_host_shot(self) -> None:
        game = _minimal_game()
        game.no_host_mafia_shot_flow_active = True
        game.no_host_mafia_shot_pending_uid = 20
        mafia_night_state(game).finalize_no_host_shot()
        self.assertTrue(game.no_host_mafia_shot_done)
        self.assertFalse(game.no_host_mafia_shot_flow_active)


class YakuNightStateHelperTests(unittest.TestCase):
    def _yaku_game(self) -> Game:
        return _minimal_game(
            players={
                10: Player(10, "Boss", None, Role.MAFIA_BOSS, seat=1, is_alive=True),
                20: Player(20, "Sac", None, Role.CITIZEN, seat=2, is_alive=True),
                30: Player(30, "Civ", None, Role.CITIZEN, seat=3, is_alive=True),
            }
        )

    def test_property_sync_with_legacy_fields(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.used = True
        state.sac_uid = 20
        state.sac_elim_uid = 20
        state.night_civilian_uid = 30
        state.night_success = True
        state.no_host_flow_active = True
        state.no_host_done = False
        state.no_host_phase = "civ"
        state.no_host_pending_sac_uid = 20
        state.no_host_pending_civ_uid = 30
        self.assertTrue(game.bazpors_yakuzai_used)
        self.assertEqual(game.bazpors_yaku_sac_uid, 20)
        self.assertEqual(game.bazpors_yaku_sac_elim_uid, 20)
        self.assertEqual(game.bazpors_yaku_night_civilian_uid, 30)
        self.assertTrue(game.bazpors_yaku_night_success)
        self.assertTrue(game.no_host_mafia_yaku_flow_active)
        self.assertFalse(game.no_host_mafia_yaku_done)
        self.assertEqual(game.no_host_mafia_yaku_phase, "civ")
        self.assertEqual(game.no_host_mafia_yaku_pending_sac_uid, 20)
        self.assertEqual(game.no_host_mafia_yaku_pending_civ_uid, 30)

    def test_reset_narrator_assist_start(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.used = True
        state.commit_sac_pick(20)
        state.commit_outcome(civ_uid=30, sac_uid=20, success=True)
        state.reset_narrator_assist_start()
        self.assertFalse(game.bazpors_yakuzai_used)
        self.assertIsNone(game.bazpors_yaku_sac_uid)
        self.assertIsNone(game.bazpors_yaku_sac_elim_uid)
        self.assertIsNone(game.bazpors_yaku_night_civilian_uid)
        self.assertIsNone(game.bazpors_yaku_night_success)

    def test_commit_outcome_and_mark_used(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.commit_outcome(civ_uid=30, sac_uid=20, success=True)
        state.mark_used()
        self.assertTrue(state.successful_recruit_pending)
        self.assertTrue(state.used)
        self.assertEqual(state.report_sac_uid, 20)
        self.assertEqual(state.sacrifice_elimination_uid(), 20)

    def test_once_per_game_sacrifice_elimination(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.sac_elim_uid = 20
        self.assertIsNone(state.sacrifice_elimination_uid())
        state.mark_used()
        self.assertEqual(state.sacrifice_elimination_uid(), 20)

    def test_semi_auto_back_navigation(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.commit_sac_pick(20)
        state.commit_outcome(civ_uid=30, sac_uid=20, success=False)
        state.back_from_civilian_to_sac()
        self.assertIsNone(game.bazpors_yaku_sac_uid)
        self.assertIsNone(game.bazpors_yaku_night_civilian_uid)
        state.commit_sac_pick(20)
        state.back_from_sac_to_menu()
        self.assertIsNone(game.bazpors_yaku_sac_uid)

    def test_clear_sac_uid_after_ack(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.commit_sac_pick(20)
        state.clear_sac_uid_after_ack()
        self.assertIsNone(game.bazpors_yaku_sac_uid)

    def test_clear_handoff_night_pick(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.commit_sac_pick(20)
        state.commit_outcome(civ_uid=30, sac_uid=20, success=True)
        state.clear_handoff_night_pick()
        self.assertIsNone(game.bazpors_yaku_sac_uid)
        self.assertIsNone(game.bazpors_yaku_night_civilian_uid)
        self.assertIsNone(game.bazpors_yaku_night_success)
        self.assertEqual(game.bazpors_yaku_sac_elim_uid, 20)

    def test_no_host_flow_lifecycle(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        state.start_no_host_flow()
        self.assertTrue(game.no_host_mafia_yaku_flow_active)
        self.assertEqual(game.no_host_mafia_yaku_phase, "sac")
        state.finalize_no_host_sac(20)
        self.assertEqual(game.bazpors_yaku_sac_uid, 20)
        self.assertEqual(game.no_host_mafia_yaku_phase, "civ")
        state.finalize_no_host_flow()
        self.assertFalse(game.no_host_mafia_yaku_flow_active)
        self.assertTrue(game.no_host_mafia_yaku_done)
        self.assertIsNone(game.no_host_mafia_yaku_phase)
        state.reset_no_host_ops()
        self.assertFalse(game.no_host_mafia_yaku_done)
        self.assertFalse(game.no_host_mafia_yaku_flow_active)

    def test_legacy_snapshot_loads_yaku(self) -> None:
        game = self._yaku_game()
        game.bazpors_yakuzai_used = True
        game.bazpors_yaku_sac_elim_uid = 20
        game.bazpors_yaku_night_civilian_uid = 30
        game.bazpors_yaku_night_success = True
        game.no_host_mafia_yaku_done = True
        payload = game_to_snapshot_dict(game)
        loaded = game_from_snapshot_dict(json.loads(json.dumps(payload)))
        state = yaku_night_state(loaded)
        self.assertTrue(state.used)
        self.assertEqual(state.sac_elim_uid, 20)
        self.assertEqual(state.night_civilian_uid, 30)
        self.assertTrue(state.night_success)
        self.assertTrue(state.no_host_done)
        self.assertTrue(state.successful_recruit_pending)

    def test_civilian_picked_this_night(self) -> None:
        game = self._yaku_game()
        state = yaku_night_state(game)
        self.assertFalse(state.civilian_picked_this_night)
        state.night_civilian_uid = 30
        self.assertTrue(state.civilian_picked_this_night)


class PassiveNightStateHelperTests(unittest.TestCase):
    def test_citizen_confirm_batch(self) -> None:
        game = _minimal_game()
        passive = passive_night_state(game)
        passive.reset_citizen_batch("1:citizen:NIGHT_START")
        passive.citizen_confirm(20)
        self.assertIn(20, game.no_host_citizen_night_confirmed_uids)
        self.assertTrue(passive.citizen_is_confirmed(20))

    def test_ruintan_confirm(self) -> None:
        game = _minimal_game()
        passive = passive_night_state(game)
        passive.ruintan_night_confirmed = True
        self.assertTrue(game.no_host_ruintan_night_confirmed)


class NightRoleStateRootTests(unittest.TestCase):
    def test_all_role_views_on_root(self) -> None:
        game = _minimal_game()
        root = night_role_state(game)
        self.assertEqual(root.detective.game, game)
        self.assertEqual(root.shiad.game, game)
        self.assertEqual(root.sniper.game, game)
        self.assertEqual(root.hunter.game, game)
        self.assertEqual(root.nato.game, game)
        self.assertEqual(root.interrogator.game, game)
        self.assertEqual(root.mafia.game, game)
        self.assertEqual(root.yaku.game, game)
        self.assertEqual(root.passive.game, game)


if __name__ == "__main__":
    unittest.main()
