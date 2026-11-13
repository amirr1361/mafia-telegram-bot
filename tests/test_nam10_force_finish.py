"""اتمام اجباری شب نماینده (nam10) — کمک‌کننده ربات."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Phase, Player, Role
from bot.nam10.night2 import (
    BOSS_PHASE_DONE,
    BOSS_PHASE_NATO_ROLE,
    BOSS_PHASE_SHOT_TARGET,
    GRANT_STATUS_DELIVERED,
    GRANT_STATUS_PENDING,
    GRANT_STATUS_VOID,
    PENDING_COLLECTED,
    PENDING_COLLECTING,
    PENDING_RESOLVED,
    nam10_night2_mode,
    night2_required_keys,
)

NAM10_FORCE_FINISH_ACTS = frozenset({"n2fft", "n2ffy", "n2ffn"})


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int = 0) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _nam10_night_game(gm: GameManager, *players: Player, assistant_uid: int = 900) -> Game:
    game = gm.create_game(
        host_id=1,
        scenario_name="namayande",
        max_players=10,
        nam10_no_host=True,
    )
    assert game is not None
    for player in players:
        err = gm.add_player(game, player)
        assert err is None, err
    game.phase = Phase.NIGHT
    game.bot_assistant_user_id = assistant_uid
    game.nam10_assistant_narrator_active = True
    game.nmnd_narrator_night_count = 2
    game.nmnd_night2_mode = True
    game.nmnd_night2_night_count = 2
    game.nmnd_night2_entry_dispatched = True
    game.nmnd_night2_phase = PENDING_COLLECTING
    return game


def _normalize_sync(game: Game) -> dict:
    """Run the async normalize step synchronously for unit tests."""
    from bot.nam10.night_force_finish import (
        _normalize_pending_nam10_night_actions,
    )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _normalize_pending_nam10_night_actions(AsyncMock(), game)
        )
    finally:
        loop.close()


def _collection_active(game: Game) -> bool:
    from bot.nam10.night_force_finish import (
        nam10_night_force_finish_collection_active,
    )

    return nam10_night_force_finish_collection_active(game)


class AccessTests(unittest.TestCase):
    def test_collection_active_matrix(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(gm)
        self.assertTrue(nam10_night2_mode(game))
        self.assertTrue(_collection_active(game))
        game.nmnd_night2_phase = PENDING_COLLECTED
        self.assertFalse(_collection_active(game))
        game.nmnd_night2_phase = PENDING_COLLECTING
        game.nmnd_night2_entry_dispatched = False
        self.assertFalse(_collection_active(game))

    def test_acts_in_night2_acts(self) -> None:
        from bot.nam10.night2 import NIGHT2_ACTS

        for act in NAM10_FORCE_FINISH_ACTS:
            self.assertIn(act, NIGHT2_ACTS)

    def test_button_keyboard_guarded(self) -> None:
        from bot.nam10.night_force_finish import (
            nam10_force_finish_button_keyboard,
        )

        gm = GameManager()
        game = _nam10_night_game(gm)
        kb = nam10_force_finish_button_keyboard(game)
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])
        data = kb.inline_keyboard[0][0].callback_data
        self.assertTrue(data.startswith("pmr:"))
        game.nmnd_night2_phase = PENDING_COLLECTED
        self.assertIsNone(nam10_force_finish_button_keyboard(game))


class NormalizeTests(unittest.TestCase):
    """هر تست بازی تازه می‌سازد؛ بازیکنان در فاز لابی اضافه می‌شوند."""

    def test_shooter_pending_becomes_no_shot(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(gm, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        game.nmnd_night2_boss_phase = BOSS_PHASE_SHOT_TARGET
        game.nmnd_night2_shot_pending_uid = 20
        dispositions = _normalize_sync(game)
        self.assertEqual(game.nmnd_night2_boss_phase, BOSS_PHASE_DONE)
        self.assertIsNone(game.nmnd_night2_shot_pending_uid)
        self.assertIsNone(game.nmnd_night2_shot_target_uid)
        self.assertIn("shot", dispositions)

    def test_nato_incomplete_cancelled_but_activation_kept(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(13, "Doc", Role.DOCTOR, seat=4),
        )
        game.nmnd_night2_boss_phase = BOSS_PHASE_NATO_ROLE
        game.nmnd_night2_nato_used = True
        game.nmnd_night2_nato_used_night = 2
        game.nmnd_night2_nato_pending_role_idx = 1
        game.nmnd_night2_doctor_cancelled = True
        game.nmnd_night2_doctor_cancel_reason = "nato"
        dispositions = _normalize_sync(game)
        self.assertEqual(game.nmnd_night2_boss_phase, BOSS_PHASE_DONE)
        self.assertIsNone(game.nmnd_night2_nato_pending_role_idx)
        self.assertIsNone(game.nmnd_night2_nato_target_uid)
        self.assertTrue(game.nmnd_night2_nato_used)  # فعال‌سازی حفظ می‌شود
        self.assertTrue(game.nmnd_night2_doctor_cancelled)  # لغو پزشک حفظ می‌شود
        self.assertIn("nato_cancelled", dispositions)

    def test_doctor_incomplete_cancelled_force_finished(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(13, "Doc", Role.DOCTOR, seat=4),
        )
        game.nmnd_night2_doctor_pending_uid = 20
        dispositions = _normalize_sync(game)
        self.assertTrue(game.nmnd_night2_doctor_cancelled)
        self.assertEqual(game.nmnd_night2_doctor_cancel_reason, "force_finished")
        self.assertIsNone(game.nmnd_night2_doctor_pending_uid)
        self.assertIn("doctor", dispositions)
        keys = night2_required_keys(game)
        self.assertNotIn("DOCTOR", keys)

    def test_hacker_incomplete_no_interference(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(11, "Hacker", Role.SHIAD, seat=2),
        )
        game.nmnd_night2_hacker_stage = "dst"
        game.nmnd_night2_hacker_src_pending = 10
        game.nmnd_night2_hacker_dst_pending = None
        dispositions = _normalize_sync(game)
        self.assertEqual(game.nmnd_night2_hacker_uids, [])
        self.assertIn("hacker", dispositions)
        # required key با disposition حل می‌شود
        keys = night2_required_keys(game)
        self.assertNotIn("SHIAD", keys)

    def test_hacker_confirmed_pair_preserved(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(11, "Hacker", Role.SHIAD, seat=2),
        )
        game.nmnd_night2_hacker_uids = [10, 20]
        _normalize_sync(game)
        self.assertEqual(game.nmnd_night2_hacker_uids, [10, 20])

    def test_guide_incomplete_no_recipient(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(12, "Guide", Role.INTERROGATOR, seat=3),
        )
        game.nmnd_night2_guide_pending_uid = 20
        dispositions = _normalize_sync(game)
        self.assertIsNone(game.nmnd_night2_guide_uids.get(2))
        self.assertIsNone(game.nmnd_night2_guide_pending_uid)
        self.assertIn("guide", dispositions)
        keys = night2_required_keys(game)
        self.assertNotIn("INTERROGATOR", keys)

    def test_guardian_incomplete_no_armor(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(12, "Guard", Role.DETECTIVE, seat=3),
        )
        game.nmnd_night2_guardian_pending_uid = 20
        dispositions = _normalize_sync(game)
        self.assertIsNone(game.nmnd_night2_guardian_uid)
        self.assertIsNone(game.nmnd_night2_guardian_pending_uid)
        self.assertIn("guardian", dispositions)
        keys = night2_required_keys(game)
        self.assertNotIn("DETECTIVE", keys)

    def test_mine_used_forced_ack(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(15, "Mine", Role.RUINTAN, seat=6),
        )
        game.nmnd_night2_mine_used = True
        dispositions = _normalize_sync(game)
        self.assertIn(15, game.nmnd_night2_waiting_acked.get("RUINTAN", []))
        self.assertIn("mine_ack", dispositions)

    def test_mine_incomplete_no_mine(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(15, "Mine", Role.RUINTAN, seat=6),
        )
        game.nmnd_night2_mine_pending_uid = 20
        dispositions = _normalize_sync(game)
        self.assertIsNone(game.nmnd_night2_mine_uid)
        self.assertIn("mine", dispositions)
        keys = night2_required_keys(game)
        self.assertNotIn("RUINTAN", keys)

    def test_citizens_forced_acked(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(20, "C1", Role.CITIZEN, seat=2),
            _p(21, "C2", Role.CITIZEN, seat=3),
        )
        dispositions = _normalize_sync(game)
        acked = game.nmnd_night2_waiting_acked.get("CITIZEN", [])
        self.assertTrue({20, 21}.issubset(set(acked)))
        self.assertIn("citizen_ack", dispositions)

    def test_soldier_unconfirmed_forfeited_permanently(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(16, "Soldier", Role.SOLDIER, seat=7),
        )
        game.nmnd_night2_soldier_pending_uid = 20
        dispositions = _normalize_sync(game)
        self.assertTrue(game.nmnd_night2_soldier_used)
        self.assertEqual(game.nmnd_night2_soldier_used_night, 2)
        self.assertEqual(game.nmnd_night2_soldier_grant_status, GRANT_STATUS_VOID)
        self.assertTrue(game.nmnd_night2_soldier_forfeited)
        self.assertIsNone(game.nmnd_night2_soldier_pending_uid)
        self.assertIn("soldier_forfeited_panel_unavailable", dispositions)
        # پنل تحویل نشده بود → مسیر امن: سرباز حذف نمی‌شود
        self.assertTrue(game.players[16].is_alive)
        keys = night2_required_keys(game)
        self.assertNotIn("SOLDIER", keys)

    def test_soldier_forfeiture_is_permanent_across_nights(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(16, "Soldier", Role.SOLDIER, seat=7),
        )
        game.nmnd_night2_soldier_pending_uid = 20
        _normalize_sync(game)
        # شب بعد — فقط اوکی (بدون انتخاب گیرنده)
        game.nmnd_night2_night_count = 3
        game.nmnd_narrator_night_count = 3
        keys = night2_required_keys(game)
        self.assertIn("SOLDIER", keys)  # اوکی انتظار بدهکار است

    def test_soldier_used_spent_ack_forced(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(16, "Soldier", Role.SOLDIER, seat=7),
        )
        game.nmnd_night2_soldier_used = True
        game.nmnd_night2_soldier_used_night = 1
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_DELIVERED
        dispositions = _normalize_sync(game)
        self.assertIn(16, game.nmnd_night2_waiting_acked.get("SOLDIER", []))
        self.assertIn("soldier_ack", dispositions)

    def test_pending_grant_voided(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(16, "Soldier", Role.SOLDIER, seat=7),
        )
        game.nmnd_night2_soldier_used = True
        game.nmnd_night2_soldier_used_night = 2
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_PENDING
        dispositions = _normalize_sync(game)
        self.assertEqual(game.nmnd_night2_soldier_grant_status, GRANT_STATUS_VOID)
        self.assertIn("soldier_grant_void", dispositions)
        keys = night2_required_keys(game)
        self.assertNotIn("n2grant", keys)

    def test_delivered_sniper_pending_forced_no_shot(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(17, "Snp", Role.CITIZEN, seat=8),
        )
        game.nmnd_night2_soldier_used = True
        game.nmnd_night2_soldier_used_night = 2
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_DELIVERED
        game.nmnd_night2_soldier_uid = 17
        game.nmnd_night2_sniper_night = 2
        game.nmnd_night2_sniper_pending_uid = 20
        dispositions = _normalize_sync(game)
        self.assertTrue(game.nmnd_night2_sniper_skipped)
        self.assertTrue(game.nmnd_night2_sniper_resolved)
        self.assertIsNone(game.nmnd_night2_sniper_pending_uid)
        self.assertIn("sniper_no_shot_panel_unavailable", dispositions)
        # پنل تحویل نشده بود → مسیر امن: گیرنده حذف نمی‌شود
        self.assertTrue(game.players[17].is_alive)
        keys = night2_required_keys(game)
        self.assertNotIn("n2sniper", keys)


class ForceFinishFlowTests(unittest.IsolatedAsyncioTestCase):
    async def _run_force_finish(self, game: Game, gm: GameManager):
        from bot.nam10.night_force_finish import force_finish_nam10_night

        with patch(
            "bot.nam10.night2_publish.nam10_night2_publish_tick",
            new_callable=AsyncMock,
        ) as tick, patch(
            "bot.nam10.night_force_finish.lock_nam10_night_mirror_panels",
            new_callable=AsyncMock,
        ), patch(
            "bot.night_helper_reminder.cleanup_night_helper_reminder",
            new_callable=AsyncMock,
        ):
            await force_finish_nam10_night(AsyncMock(), game, gm)
        return tick

    async def test_force_finish_resolves_and_publishes(self) -> None:
        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(20, "C1", Role.CITIZEN, seat=2),
        )
        game.nmnd_night2_boss_phase = BOSS_PHASE_SHOT_TARGET
        game.nmnd_night2_shot_pending_uid = 20
        tick = await self._run_force_finish(game, gm)
        self.assertTrue(game.nmnd_night2_force_finished)
        # جمع‌آوری بسته و محاسبهٔ قطعی اجرا شده است
        self.assertIn(
            game.nmnd_night2_phase, (PENDING_COLLECTED, PENDING_RESOLVED)
        )
        self.assertTrue(game.nmnd_night2_resolved)
        tick.assert_awaited_once()

    async def test_rebel_ack_forced_when_not_shooter(self) -> None:
        from bot.nam10.night_force_finish import (
            _normalize_pending_nam10_night_actions,
        )

        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
            _p(14, "Rebel", Role.NATO, seat=5),
        )
        game.nmnd_night2_boss_phase = BOSS_PHASE_DONE
        dispositions = await _normalize_pending_nam10_night_actions(
            AsyncMock(), game
        )
        self.assertIn(14, game.nmnd_night2_waiting_acked.get("NATO", []))
        self.assertIn("rebel_ack", dispositions)

    async def test_cancel_act_changes_nothing(self) -> None:
        from bot.nam10.night_force_finish import dispatch_nam10_force_finish_act

        gm = GameManager()
        game = _nam10_night_game(
            gm,
            _p(10, "Boss", Role.MAFIA_BOSS, seat=1),
        )
        game.nmnd_night2_boss_phase = BOSS_PHASE_SHOT_TARGET
        callback = AsyncMock()
        callback.message = AsyncMock()
        await dispatch_nam10_force_finish_act(
            callback, AsyncMock(), game, gm, actor_uid=900, act="n2ffn"
        )
        self.assertFalse(game.nmnd_night2_force_finished)
        self.assertEqual(game.nmnd_night2_phase, PENDING_COLLECTING)
        self.assertEqual(game.nmnd_night2_boss_phase, BOSS_PHASE_SHOT_TARGET)


if __name__ == "__main__":
    unittest.main()
