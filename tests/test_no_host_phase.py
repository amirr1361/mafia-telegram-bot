"""ماژول no_host_phase — نقطهٔ ورود یکپارچه."""

from __future__ import annotations

import unittest


class NoHostPhaseModuleTest(unittest.TestCase):
    def test_exports(self) -> None:
        from bot import no_host_phase as m

        for name in (
            "dispatch_no_host_role_night_panels",
            "run_no_host_night1_phase",
            "no_host_night1_open_hunter_night_action",
            "no_host_night1_open_mafia_team_night_action",
            "no_host_run_mafia_shot_operation",
            "no_host_run_mafia_yaku_operation",
            "no_host_run_mafia_nato_operation",
            "no_host_run_day1_end_vote_flow",
            "no_host_advance_narrator_after_night_work",
            "no_host_send_doctor_night_selection_if_alive",
            "no_host_send_detective_night_selection_if_in_game",
            "no_host_send_shiad_night_selection_if_alive",
            "no_host_send_interrogator_night_selection_if_alive",
            "no_host_send_sniper_night_selection_if_alive",
        ):
            self.assertTrue(callable(getattr(m, name)))


if __name__ == "__main__":
    unittest.main()
