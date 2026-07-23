"""تست جریان اصلی بازی — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_day_ability import (
    MASON_APACHE_PICK_ACT,
    _eliminate_apache_and_target,
    dispatch_mason_day_start_panels,
    mason_day_ability_panels_open,
)
from bot.mason_helper_flow import (
    MasonHelperCb,
    build_mason_mafia_consult_html,
    build_mason_midday_step_html,
    build_mason_team_consult_html,
    handle_mason_helper_action,
    mason_on_no_host_entered_night,
    mason_team_consult_required,
    mason_team_consult_should_prompt,
    send_mason_team_consult_prompt,
)
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.models import Player, Role
from bot.no_host_interrog_day import should_enter_no_host_interrog_day
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_sniper as ms_sn
from bot.roles.night_state import mafia_night_state


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.no_host_assistant_narrator_active = True
    return game


class MasonHelperPanelTextTests(unittest.TestCase):
    def test_consult_and_midday_text(self) -> None:
        self.assertIn("مشورت", build_mason_mafia_consult_html())
        self.assertIn("تیم ماسون", build_mason_team_consult_html())
        self.assertIn("نیمروزی", build_mason_midday_step_html())

    def test_helper_callback_kinds(self) -> None:
        self.assertTrue(MasonHelperCb(code="X", kind="consult").pack().startswith("msh:"))
        self.assertTrue(
            MasonHelperCb(code="X", kind="team_consult").pack().startswith("msh:")
        )
        self.assertTrue(MasonHelperCb(code="X", kind="midday").pack().startswith("msh:"))

    def test_team_consult_required_from_night_two(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 1
        self.assertFalse(mason_team_consult_required(game))
        game.bazpors_narrator_night_count = 2
        self.assertTrue(mason_team_consult_required(game))
        game.bazpors_narrator_night_count = 3
        self.assertTrue(mason_team_consult_required(game))


class MasonNightResolutionTests(unittest.TestCase):
    def test_mafia_shot_respects_mason_doctor_save(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        ms_doc.commit_mason_doctor_save(game, 20)
        mafia_night_state(game).commit_shot(20)
        apply_mason_night_resolution(game, gm)
        self.assertTrue(game.players[20].is_alive)
        self.assertTrue(game.mason_night_resolution_applied)

    def test_sniper_kills_applied_on_resolution(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [20])
        game.mason_commander_night_approved_uids = [20]
        apply_mason_night_resolution(game, gm)
        self.assertFalse(game.players[20].is_alive)


class MasonNightReportTests(unittest.TestCase):
    def test_collapse_line_in_outcome(self) -> None:
        from bot.bazpors_narrator import _night_report_outcome_section

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(60, "Mason", Role.MASON))
        game.mason_last_night_had_collapse = True
        snap = {60: True}
        lines = _night_report_outcome_section(game, gm, snap)
        joined = "\n".join(lines)
        self.assertIn("مرگ ماسونی", joined)


class MasonFlowHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_entered_night_sends_consult_not_night(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_mafia_consult_prompt",
            new=AsyncMock(),
        ) as consult, patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new=AsyncMock(),
        ) as night:
            await mason_on_no_host_entered_night(bot, game, gm)
        consult.assert_awaited_once()
        night.assert_not_awaited()

    async def test_consult_ok_triggers_night_start_before_night_one(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 1
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new=AsyncMock(),
        ) as night, patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new=AsyncMock(),
        ) as team:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="consult",
            )
        night.assert_awaited_once()
        team.assert_not_awaited()
        self.assertTrue(game.mason_mafia_consult_done)

    async def test_consult_ok_triggers_team_consult_before_night_two(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 2
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new=AsyncMock(),
        ) as night, patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new=AsyncMock(),
        ) as team:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="consult",
            )
        team.assert_awaited_once()
        night.assert_not_awaited()
        self.assertTrue(game.mason_mafia_consult_done)

    async def test_consult_ok_falls_through_to_night_when_team_consult_suppressed(
        self,
    ) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        game.mason_team_consultation_retired = True
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new=AsyncMock(),
        ) as night, patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new=AsyncMock(),
        ) as team:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="consult",
            )
        self.assertFalse(mason_team_consult_should_prompt(game))
        team.assert_not_awaited()
        night.assert_awaited_once()
        self.assertTrue(game.mason_mafia_consult_done)

    async def test_team_consult_ok_triggers_night_start(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new=AsyncMock(),
        ) as night:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="team_consult",
            )
        night.assert_awaited_once()
        self.assertTrue(game.mason_team_consult_done)

    async def test_team_consult_prompt_not_sent_before_night_two(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 1
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await send_mason_team_consult_prompt(bot, game)
        register.assert_not_awaited()

    async def test_vote_ok_dismisses_apache_cowboy_panels(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.mason_intro_day_ability_open = True
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.dismiss_mason_day_ability_panels",
            new=AsyncMock(),
        ) as dismiss, patch(
            "bot.no_host_phase.no_host_run_day1_end_vote_flow",
            new=AsyncMock(),
        ):
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="vote",
            )
        dismiss.assert_awaited_once()
        self.assertFalse(game.mason_intro_day_ability_open)

    async def test_midday_ok_goes_to_discipline(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_game_flow.mason_after_midday_step_confirmed",
            new=AsyncMock(),
        ) as route:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="midday",
            )
        route.assert_awaited_once()
        self.assertTrue(game.mason_midday_step_done)


class MasonDayStartPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_day_start_dispatches_apache_and_gun(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "Holder", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Gn", Role.GUNMAN))
        ms_gn.commit_mason_gunner_target(game, game.players[30], game.players[20])
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        bot = MagicMock()
        registered: list[str] = []

        async def _capture(bot_, game_, uid, ui_key, text, kb, **kw):
            registered.append(ui_key)

        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_day_start_panels(bot, game, gm)
        kinds = {k.split(":")[-2] if ":" in k else k for k in registered}
        self.assertTrue(
            any("mason_apache_day" in k for k in registered)
            or any("apache" in k for k in registered)
        )
        self.assertTrue(any("mason_day_gun" in k for k in registered))


class MasonApacheAutoContinueFlowTests(unittest.IsolatedAsyncioTestCase):
    async def _run_auto_flow_and_capture(
        self, *, guardian_protected: bool
    ) -> tuple[GameManager, object, list[tuple[str, str, object | None]], list[tuple[str, str]]]:
        from bot.main import _no_host_day1_defense_pick_ui_key
        from bot.mason_helper_flow import _vote_ui_key, build_mason_mafia_consult_html
        from bot.roles import mason_guardian as ms_gd

        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_host_day = 2
        game.bazpors_narrator_night_count = 1
        game.mason_intro_day_ability_open = True
        game.mason_vote_start_prompt_sent = True
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        if guardian_protected:
            target_uid = 30
        else:
            target_uid = 20
        # پنل‌های قدیمیِ فعال که باید قفل شوند.
        vote_key = _vote_ui_key(game, 900)
        def_key = _no_host_day1_defense_pick_ui_key(game, 900)
        game.mirror_prompt_messages[vote_key] = {
            "text": "برای شروع رأی‌گیری دکمه زیر را فشار دهید.",
            "player": (900, 1),
            "observer": (999, 2),
        }
        # محافظت روزانه (اختیاری) — برای قیاس حالت آپاچی تنها.
        ms_gd.clear_mason_guardian_day_protection(game)
        ms_gd.clear_mason_guardian_night_pick(game)
        if guardian_protected:
            ms_gd.commit_mason_guardian_night_pick(game, 20)
            ms_gd.activate_mason_guardian_day_protection(game)

        bot = MagicMock()
        updates: list[tuple[str, str, object | None]] = []
        registers: list[tuple[str, str]] = []

        async def _capture_update(
            _bot,
            _game,
            ui_key,
            text,
            reply_markup,
            **kwargs,
        ):
            updates.append((ui_key, text, reply_markup))

        async def _capture_helper_register(
            _bot, _game, uid, ui_key, text, kb, **kwargs
        ):
            registers.append((ui_key, text))
            _game.mirror_prompt_messages[ui_key] = {
                "text": text,
                "player": (uid, 100 + len(registers)),
            }

        async def _capture_defense_publish(
            _bot, _game, uid, ui_key, text, kb, **kwargs
        ):
            _game.mirror_prompt_messages[ui_key] = {
                "text": text,
                "player": (uid, 200),
                "observer": (999, 201),
            }

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.observer_delivery.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ), patch(
            "bot.mason_day_ability.dismiss_mason_day_ability_panels",
            new=AsyncMock(),
        ), patch(
            "bot.observer_delivery.update_mirror_prompt_pair",
            side_effect=_capture_update,
        ), patch(
            "bot.observer_delivery.publish_mirror_prompt_pair",
            side_effect=_capture_defense_publish,
        ), patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            side_effect=_capture_helper_register,
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=target_uid
            )

        # باید روی پنل مشورت مافیا متوقف شود (نه تأیید خودکار).
        self.assertTrue(game.mason_mafia_consult_prompt_sent)
        self.assertFalse(game.mason_mafia_consult_done)
        self.assertTrue(any(t == build_mason_mafia_consult_html() for _, t in registers))
        # پنل‌های قبلی باید قفل شوند (بدون دکمه).
        self.assertTrue(any(k == vote_key and kb is None for k, _, kb in updates))
        self.assertTrue(any(k == def_key and kb is None for k, _, kb in updates))
        return gm, game, updates, registers

    async def test_apache_kills_target_auto_continues_to_mafia_consult(self) -> None:
        _, game, _, _ = await self._run_auto_flow_and_capture(guardian_protected=False)
        self.assertFalse(game.players[10].is_alive)
        self.assertFalse(game.players[20].is_alive)
        self.assertTrue(game.players[30].is_alive)

    async def test_apache_alone_auto_continues_to_mafia_consult(self) -> None:
        _, game, _, _ = await self._run_auto_flow_and_capture(guardian_protected=True)
        self.assertFalse(game.players[10].is_alive)
        self.assertTrue(game.players[30].is_alive)
        self.assertTrue(game.players[20].is_alive)

    async def test_manual_helper_consult_flow_still_manual(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 2
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new=AsyncMock(),
        ) as team:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="consult",
            )
        team.assert_awaited_once()
        self.assertTrue(game.mason_mafia_consult_done)


class MasonIsolationRegressionTests(unittest.TestCase):
    def test_bazpors_interrog_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 900
        game.no_host_assistant_narrator_active = True
        game.bazpors_interrog_ready_for_day = True
        self.assertTrue(should_enter_no_host_interrog_day(game))

    def test_mozakere_scenario_unchanged(self) -> None:
        from bot.main import build_no_host_intro_night_mafia_dm_html

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        boss = _p(10, "Boss", Role.MAFIA_BOSS)
        gm.add_player(game, boss)
        self.assertIn("مافیا", build_no_host_intro_night_mafia_dm_html(game))


class MasonNightReadyRegressionTests(unittest.TestCase):
    def test_parallel_ready_still_requires_wait_ok(self) -> None:
        from bot.bazpors_narrator import NIGHT_START

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.mason_night_saboteur_confirmed = True
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_guardian_confirmed = True
        game.mason_night_mason_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_natasha_confirmed = True
        game.mason_night_priest_confirmed = True
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        self.assertFalse(all_mason_parallel_night_ready(game))


if __name__ == "__main__":
    unittest.main()
