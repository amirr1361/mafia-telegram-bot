"""Room 68 — Night 4 stuck with Sniper at 0 bullets, Commander dead (Mason only).

Reconstructed from audit log 68_20260624_070811.jsonl:
- 18-player masoon, Night 4, 4 alive (NATO, Gunman, Doctor, Sniper)
- Sniper spent all 3 bullets on Nights 1–2; Commander eliminated Night 2
- Mafia shot (NATO → Sniper) completed; parallel_night_collect_finished never fired
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_ready import (
    all_mason_parallel_night_ready,
    explain_mason_night_stuck,
    maybe_finish_mason_parallel_night,
)
from bot.mason_night_role import dispatch_mason_sniper_panel
from bot.models import Player, Role
from bot.roles import mason_sniper as ms_sn


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int = 0) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _room68_night4_game(gm: GameManager):
    """Four alive at Night 4 — matches Room 68 end state before resolution."""
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=18,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "68"
    game.bot_assistant_user_id = 900
    game.observer_user_id = 999
    game.observer_prompt_status = "registered"
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 4
    game.no_host_night_parallel_collect_active = True
    game.mason_nato_used = True
    game.mason_sniper_bullets_spent = 3
    game.mason_gun_spent = True

    dead = (
        (-920001, "امین - گادفادر", Role.GODFATHER, 14),
        (-920014, "عرفان - محافظ", Role.BODYGUARD, 6),
        (-920009, "بهنام - تایلر", Role.TAILOR, 18),
        (-920008, "هاکان - خرابکار", Role.SABOTEUR, 8),
        (-920010, "ابوالفضل - آپاچی", Role.APACHE, 5),
        (-920002, "فراهانی - ناتاشا", Role.NATASHA, 9),
        (-920012, "امیر - فرمانده", Role.COMMANDER, 12),
        (-920004, "حسن - جاسوس", Role.SPY, 4),
        (-920016, "کاوه - کاراگاه", Role.DETECTIVE, 7),
        (-920015, "رامین - کابوی", Role.COWBOY, 3),
        (-920003, "بابک - کشیش", Role.PRIEST, 16),
        (-920017, "رایان - ماسون", Role.MASON, 15),
        (-920005, "فریدونی - شهر ساده", Role.TOWN_SIMPLE, 11),
        (-920013, "علیرضا - رویین تن", Role.RUINTAN, 2),
    )
    for uid, name, role, seat in dead:
        gm.add_player(game, _p(uid, name, role, alive=False, seat=seat))

    gm.add_player(game, _p(108214166, "Amir Latifi", Role.NATO, seat=1))
    gm.add_player(game, _p(-920011, "احسان - تفنگدار", Role.GUNMAN, seat=10))
    gm.add_player(game, _p(-920006, "قاسم - پزشک", Role.DOCTOR, seat=13))
    gm.add_player(game, _p(-920007, "رهنما - اسنایپر", Role.SNIPER, seat=17))
    return game


def _arm_mafia_doctor_gunner(game) -> None:
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True
    game.mason_night_doctor_confirmed = True
    game.mason_night_gunner_confirmed = True


class Room68Night4DiagnosticTests(unittest.TestCase):
    def test_diagnostic_identifies_sniper_ok_blocker_before_fix(self) -> None:
        gm = GameManager()
        game = _room68_night4_game(gm)
        _arm_mafia_doctor_gunner(game)
        game.mason_night_sniper_confirmed = False

        report = explain_mason_night_stuck(game, gm)
        self.assertIn("night 4", report.lower())
        self.assertIn("Waiting for Sniper", report)
        self.assertIn("mason_night_sniper_confirmed=False", report)
        self.assertIn("رهنما - اسنایپر", report)
        self.assertIn("Completed responsibilities:", report)
        self.assertIn("Mafia shot", report)
        self.assertIn("Commander", report)
        self.assertIn("skipped", report)
        self.assertFalse(all_mason_parallel_night_ready(game))

    def test_dead_commander_does_not_block(self) -> None:
        gm = GameManager()
        game = _room68_night4_game(gm)
        _arm_mafia_doctor_gunner(game)
        game.mason_night_sniper_confirmed = True

        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Night readiness complete", report)
        self.assertTrue(all_mason_parallel_night_ready(game))

    def test_independent_mafia_shot_vs_sniper_role(self) -> None:
        gm = GameManager()
        game = _room68_night4_game(gm)
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_night1_done = True
        game.mason_night_sniper_confirmed = False

        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Mafia action complete", report)
        self.assertIn("saboteur role", report.lower())
        self.assertIn("Sniper", report)


class Room68Night4DispatchFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_sniper_zero_bullets_commander_dead_auto_satisfied_on_dispatch(
        self,
    ) -> None:
        gm = GameManager()
        game = _room68_night4_game(gm)
        _arm_mafia_doctor_gunner(game)
        bot = MagicMock()
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as reg, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            finish,
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)

        reg.assert_not_awaited()
        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertTrue(game.mason_night_commander_confirmed)
        self.assertTrue(all_mason_parallel_night_ready(game))
        finish.assert_awaited()

    async def test_maybe_finish_resolves_when_all_alive_actions_done(self) -> None:
        gm = GameManager()
        game = _room68_night4_game(gm)
        _arm_mafia_doctor_gunner(game)
        bot = MagicMock()
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            finish,
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)
            await maybe_finish_mason_parallel_night(bot, game, gm)

        self.assertTrue(all_mason_parallel_night_ready(game))
        self.assertGreaterEqual(finish.await_count, 1)


    async def test_sniper_does_not_receive_duplicate_wait_panel_night4(self) -> None:
        """Seat 17 must not get generic wait when sniper role panel already handles 0 bullets."""
        gm = GameManager()
        game = _room68_night4_game(gm)
        bot = MagicMock()
        sent: list[tuple[int, str]] = []

        async def capture(_bot, _game, uid, ui_key, _text, _kb, **kw):
            sent.append((uid, ui_key))

        with patch(
            "bot.observer_delivery.safe_send_message_return",
            new=AsyncMock(return_value=MagicMock(message_id=1)),
        ), patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=capture,
        ), patch(
            "bot.mason_night_entry.register_mirror_prompt_pair",
            side_effect=capture,
        ), patch(
            "bot.no_host_mafia_night1.start_no_host_night1_mafia_flow",
            new=AsyncMock(),
        ):
            from bot.mason_night_entry import dispatch_mason_night_entry_panels

            await dispatch_mason_night_entry_panels(bot, game, gm)

        sniper_uid = -920007
        sniper_keys = [k for u, k in sent if u == sniper_uid]
        self.assertNotIn(
            f"mason_night_wait:68:{sniper_uid}",
            sniper_keys,
            "generic wait panel must not duplicate sniper no-action handling",
        )
        self.assertTrue(game.mason_night_sniper_confirmed)

    async def test_clicking_wait_only_does_not_satisfy_sniper_role(self) -> None:
        """Pre-fix trap: mok on wait panel left mason_night_sniper_confirmed False."""
        gm = GameManager()
        game = _room68_night4_game(gm)
        _arm_mafia_doctor_gunner(game)
        game.mason_night_sniper_confirmed = False
        game.mason_night_wait_ok_uids = [-920007]
        self.assertFalse(all_mason_parallel_night_ready(game))
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("mason_night_sniper_confirmed", report)
        self.assertIn("Waiting for Sniper", report)


class Room68RegressionIsolationTests(unittest.TestCase):
    def test_sniper_still_needs_ok_when_commander_alive(self) -> None:
        gm = GameManager()
        game = _room68_night4_game(gm)
        gm.add_player(game, _p(-920012, "Cmd", Role.COMMANDER))
        game.players[-920012].is_alive = True
        game.mason_sniper_bullets_spent = 3
        self.assertFalse(ms_sn.mason_sniper_needs_night_pick(game))
        game.mason_night_sniper_confirmed = False
        self.assertFalse(all_mason_parallel_night_ready(game))

    def test_bazpors_unchanged(self) -> None:
        from bot.roles.doctor import doctor_save_capacity

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertEqual(doctor_save_capacity(game), 1)

    def test_mozakere_unchanged(self) -> None:
        from bot.no_host_mafia_night1 import build_mozakere_mafia_operation_menu_html

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertIn("مذاکره", build_mozakere_mafia_operation_menu_html(game))


if __name__ == "__main__":
    unittest.main()
