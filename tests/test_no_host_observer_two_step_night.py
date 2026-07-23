"""تأیید دو مرحله‌ای شب — ناظر روی میز مصنوعی."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.models import Player, Role
from bot.no_host_doctor_night import (
    _doctor_ui_key,
    build_no_host_doctor_waiting_html,
    dispatch_no_host_doctor_night,
)
from bot.no_host_night_common import (
    arm_no_host_role_pick_flow,
    publish_no_host_night_wait_panel,
)
from bot.observer_delivery import mirror_ui_claim_key


class NoHostObserverTwoStepNightTest(unittest.IsolatedAsyncioTestCase):
    def _game_with_observer(self) -> tuple:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.observer_user_id = 300
        game.observer_prompt_status = "registered"
        game.bot_assistant_user_id = 200
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_step = "night_start"
        game.bazpors_narrator_night_count = 1
        doc_uid = -920008
        doc = Player(
            user_id=doc_uid,
            full_name="Doc",
            username=None,
            role=Role.DOCTOR,
            seat=1,
            is_alive=True,
        )
        cit = Player(
            user_id=-920001,
            full_name="Cit",
            username=None,
            role=Role.CITIZEN,
            seat=2,
            is_alive=True,
        )
        gm.add_player(game, doc)
        gm.add_player(game, cit)
        game.roles_dealt = True
        return gm, game, doc_uid

    def test_arm_flow_when_signature_set_but_flow_inactive(self) -> None:
        _, game, doc_uid = self._game_with_observer()
        game.no_host_doctor_dm_signature = "1:doc:night_entry"
        game.no_host_doctor_flow_active = False
        arm_no_host_role_pick_flow(
            game,
            flow_active_attr="no_host_doctor_flow_active",
            pick_confirmed_attr="no_host_doctor_pick_confirmed",
            dm_signature_attr="no_host_doctor_dm_signature",
        )
        self.assertTrue(game.no_host_doctor_flow_active)

    async def test_wait_panel_updates_observer_for_synthetic_doctor(self) -> None:
        gm, game, doc_uid = self._game_with_observer()
        self.assertTrue(is_synthetic_player_uid(doc_uid))
        ui_key = _doctor_ui_key(game, doc_uid)
        game.mirror_prompt_messages[ui_key] = {
            "text": "قدیمی",
            "observer": (300, 111),
        }
        bot = AsyncMock()
        wait_text = build_no_host_doctor_waiting_html(game, gm)
        with patch(
            "bot.no_host_night_common.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as update_pair:
            await publish_no_host_night_wait_panel(
                bot, game, doc_uid, ui_key, wait_text
            )
            update_pair.assert_awaited_once()
            self.assertEqual(update_pair.await_args.kwargs["assistant_uid"], doc_uid)
            self.assertIn("نجات", update_pair.await_args.args[3])

    async def test_observer_confirm_after_pick_succeeds(self) -> None:
        gm, game, doc_uid = self._game_with_observer()
        game.no_host_doctor_flow_active = True
        game.no_host_doctor_dm_signature = "1:doc:night_entry"
        game.no_host_doctor_pending_save_uids = [-920001]

        callback = AsyncMock()
        callback.from_user.id = 300
        callback.answer = AsyncMock()
        bot = AsyncMock()

        with patch(
            "bot.no_host_night_common.finalize_no_host_role_pick_message",
            new_callable=AsyncMock,
        ) as wait_panel:
            with patch(
                "bot.no_host_doctor_night.no_host_after_role_night_pick",
                new_callable=AsyncMock,
            ):
                with patch(
                    "bot.no_host_doctor_night._sync_panel",
                    new_callable=AsyncMock,
                ):
                    await dispatch_no_host_doctor_night(
                        callback,
                        bot,
                        game,
                        gm,
                        doc_uid=doc_uid,
                        actor_uid=300,
                        act="dkc",
                        tid=0,
                    )

        self.assertTrue(game.no_host_doctor_pick_confirmed)
        self.assertFalse(game.no_host_doctor_flow_active)
        callback.answer.assert_awaited_with("ثبت شد.")
        wait_panel.assert_awaited_once()

    def test_doctor_ui_key_stable(self) -> None:
        _, game, doc_uid = self._game_with_observer()
        expected = mirror_ui_claim_key(game.room_code, "no_host_doctor", doc_uid)
        self.assertEqual(_doctor_ui_key(game, doc_uid), expected)


if __name__ == "__main__":
    unittest.main()
