"""پنل شب پزشک — سناریوی مذاکره (انتظار چندانتخابی + تأیید نهایی)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_doctor_night import (
    _pick_pool_for_keyboard,
    build_no_host_doctor_finalized_pick_html,
    build_no_host_doctor_pick_html,
    dispatch_no_host_doctor_night,
)
from bot.roles import doctor as dr
from bot.roles.night_state import doctor_night_state


def _p(uid: int, name: str, role: Role, *, seat: int | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _mozakere_no_host(gm: GameManager, *, night: int = 1, max_players: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=max_players,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_night_count = night
    game.no_host_doctor_flow_active = True
    return game


def _full_cast(gm: GameManager, game) -> None:
    gm.add_player(game, _p(10, "Doc", Role.DOCTOR, seat=1))
    gm.add_player(game, _p(20, "A", Role.CITIZEN, seat=2))
    gm.add_player(game, _p(30, "B", Role.CITIZEN, seat=3))
    for i in range(6):
        gm.add_player(game, _p(40 + i, f"F{i}", Role.CITIZEN))


def _small_cast(gm: GameManager, game) -> None:
    """۷ نفر زنده → ظرفیت نجات ۱ (doctor_save_capacity_for_alive_count)."""
    gm.add_player(game, _p(10, "Doc", Role.DOCTOR, seat=1))
    for i in range(6):
        gm.add_player(game, _p(20 + i, f"P{i}", Role.CITIZEN, seat=2 + i))


class MozakereDoctorNightPanelHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_unified_multi_select_text(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        _full_cast(self.gm, game)
        html_msg = build_no_host_doctor_pick_html(game)
        self.assertIn("شب اول", html_msg)
        self.assertIn("۲ نفر", html_msg)
        self.assertNotIn("نفر اول", html_msg)
        self.assertNotIn("نفر دوم", html_msg)

    def test_single_capacity_text(self) -> None:
        game = _mozakere_no_host(self.gm, night=4, max_players=10)
        _small_cast(self.gm, game)
        html_msg = build_no_host_doctor_pick_html(game)
        self.assertIn("شب ۴", html_msg)
        self.assertIn("یک نفر", html_msg)
        self.assertNotIn("نفر اول", html_msg)


class MozakereDoctorNightPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_pending_target_stays_in_pool(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        _full_cast(self.gm, game)
        game.no_host_doctor_pending_save_uids = [20]
        pool_ids = {p.user_id for p in _pick_pool_for_keyboard(game)}
        self.assertIn(20, pool_ids)
        self.assertIn(10, pool_ids)
        self.assertIn(30, pool_ids)

    def test_full_pool_includes_all_alive(self) -> None:
        game = _mozakere_no_host(self.gm, night=3)
        _full_cast(self.gm, game)
        pool_ids = {p.user_id for p in _pick_pool_for_keyboard(game)}
        self.assertEqual(pool_ids, {10, 20, 30, 40, 41, 42, 43, 44, 45})


class BazporsDoctorPanelUnchangedTests(unittest.TestCase):
    def test_bazpors_pick_html_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 1
        html_msg = build_no_host_doctor_pick_html(game)
        self.assertIn("یک نفر", html_msg)
        self.assertIn("حداکثر دو بار", html_msg)
        self.assertNotIn("نفر اول", html_msg)
        self.assertNotIn("تا ۲ نفر", html_msg)


class MozakereDoctorNightDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def _dispatch(
        self,
        game,
        *,
        act: str,
        tid: int = 0,
        doc_uid: int = 10,
    ) -> None:
        callback = MagicMock()
        callback.answer = AsyncMock()
        bot = AsyncMock()
        with patch(
            "bot.no_host_doctor_night.publish_no_host_night_wait_panel",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_doctor_night.no_host_after_role_night_pick",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_doctor_night.no_host_night_wait_phase_active",
            return_value=True,
        ), patch(
            "bot.no_host_doctor_night.find_alive_role_holder",
            return_value=game.players[doc_uid],
        ):
            await dispatch_no_host_doctor_night(
                callback,
                bot,
                game,
                self.gm,
                doc_uid=doc_uid,
                actor_uid=doc_uid,
                act=act,
                tid=tid,
            )
        return callback

    async def test_pick_stays_pending_until_confirm(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        _full_cast(self.gm, game)
        await self._dispatch(game, act="dkt", tid=20)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [20])
        self.assertFalse(game.no_host_doctor_pick_confirmed)
        self.assertEqual(doctor_night_state(game).get_save_uids(), [])

    async def test_two_picks_pending_then_confirm_commits_once(self) -> None:
        game = _mozakere_no_host(self.gm, night=3)
        _full_cast(self.gm, game)
        await self._dispatch(game, act="dkt", tid=20)
        await self._dispatch(game, act="dkt", tid=30)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [20, 30])
        self.assertFalse(game.no_host_doctor_pick_confirmed)
        await self._dispatch(game, act="dkc")
        self.assertEqual(doctor_night_state(game).get_save_uids(), [20, 30])
        self.assertTrue(game.no_host_doctor_pick_confirmed)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [])

    async def test_toggle_deselects(self) -> None:
        game = _mozakere_no_host(self.gm, night=3)
        _full_cast(self.gm, game)
        await self._dispatch(game, act="dkt", tid=20)
        await self._dispatch(game, act="dkt", tid=30)
        await self._dispatch(game, act="dkt", tid=20)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [30])

    async def test_capacity_two_rejects_third(self) -> None:
        # ۱۰ بازیکن زنده → ظرفیت ۲ (doctor_save_capacity_for_alive_count)
        game = _mozakere_no_host(self.gm, night=3)
        _full_cast(self.gm, game)
        await self._dispatch(game, act="dkt", tid=20)
        await self._dispatch(game, act="dkt", tid=30)
        callback = await self._dispatch(game, act="dkt", tid=40)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [20, 30])
        callback.answer.assert_called()

    async def test_capacity_three_accepts_three(self) -> None:
        # ۱۲ بازیکن زنده → ظرفیت ۳
        game = _mozakere_no_host(self.gm, night=3)
        self.gm.add_player(game, _p(10, "Doc", Role.DOCTOR, seat=1))
        for i in range(11):
            self.gm.add_player(game, _p(20 + i, f"P{i}", Role.CITIZEN, seat=2 + i))
        await self._dispatch(game, act="dkt", tid=20)
        await self._dispatch(game, act="dkt", tid=21)
        await self._dispatch(game, act="dkt", tid=22)
        callback = await self._dispatch(game, act="dkt", tid=23)
        self.assertEqual(
            game.no_host_doctor_pending_save_uids, [20, 21, 22]
        )
        callback.answer.assert_called()

    async def test_capacity_one_replaces(self) -> None:
        game = _mozakere_no_host(self.gm, night=4, max_players=10)
        _small_cast(self.gm, game)
        await self._dispatch(game, act="dkt", tid=20)
        await self._dispatch(game, act="dkt", tid=21)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [21])

    async def test_none_pending_then_confirm(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        _full_cast(self.gm, game)
        await self._dispatch(game, act="dkt", tid=20)
        await self._dispatch(game, act="dkn")
        self.assertTrue(game.no_host_doctor_pending_none)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [])
        await self._dispatch(game, act="dkc")
        self.assertEqual(doctor_night_state(game).get_save_uids(), [])
        self.assertTrue(game.no_host_doctor_pick_confirmed)

    async def test_target_clears_none_pending(self) -> None:
        game = _mozakere_no_host(self.gm, night=3)
        _full_cast(self.gm, game)
        await self._dispatch(game, act="dkn")
        self.assertTrue(game.no_host_doctor_pending_none)
        await self._dispatch(game, act="dkt", tid=20)
        self.assertFalse(game.no_host_doctor_pending_none)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [20])

    async def test_confirm_without_selection_alerts(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        _full_cast(self.gm, game)
        callback = await self._dispatch(game, act="dkc")
        self.assertFalse(game.no_host_doctor_pick_confirmed)
        callback.answer.assert_called()

    async def test_no_readiness_from_tentative_selection(self) -> None:
        from bot.no_host_night_ready import _doctor_ready

        game = _mozakere_no_host(self.gm, night=3)
        _full_cast(self.gm, game)
        await self._dispatch(game, act="dkt", tid=20)
        await self._dispatch(game, act="dkt", tid=30)
        self.assertFalse(_doctor_ready(game))
        await self._dispatch(game, act="dkc")
        self.assertTrue(_doctor_ready(game))


class MozakereDoctorFinalizedPickHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_two_picks_show_both_names_without_roles(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        self.gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        self.gm.add_player(game, _p(20, "رضا", Role.SNIPER))
        self.gm.add_player(game, _p(30, "امیر", Role.CITIZEN))
        for i in range(6):
            self.gm.add_player(game, _p(40 + i, f"F{i}", Role.CITIZEN))
        dr.commit_pick(game, 20)
        dr.commit_pick(game, 30)
        html_msg = build_no_host_doctor_finalized_pick_html(game)
        self.assertIn("✅ انتخاب شما ثبت شد", html_msg)
        self.assertIn("انتخاب:", html_msg)
        self.assertIn("رضا", html_msg)
        self.assertIn("امیر", html_msg)
        self.assertNotIn("تک تیرانداز", html_msg)
        self.assertNotIn("شهروند", html_msg)
        self.assertNotIn("✅ انتخاب شما:", html_msg)

    def test_first_pick_only_when_second_is_none(self) -> None:
        game = _mozakere_no_host(self.gm, night=2)
        self.gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        self.gm.add_player(game, _p(20, "رضا", Role.CITIZEN))
        dr.commit_pick(game, 20)
        html_msg = build_no_host_doctor_finalized_pick_html(game)
        self.assertIn("انتخاب:", html_msg)
        self.assertIn("رضا", html_msg)
        self.assertNotIn("امیر", html_msg)

    def test_no_selection_message(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        html_msg = build_no_host_doctor_finalized_pick_html(game)
        self.assertIn("انتخابی ندارم", html_msg)
        self.assertNotIn("انتخاب:", html_msg)


class MozakereDoctorFinalizedPanelDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_complete_pick_publishes_dual_name_message(self) -> None:
        game = _mozakere_no_host(self.gm, night=1)
        self.gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        self.gm.add_player(game, _p(20, "رضا", Role.SNIPER))
        self.gm.add_player(game, _p(30, "امیر", Role.CITIZEN))
        for i in range(6):
            self.gm.add_player(game, _p(40 + i, f"F{i}", Role.CITIZEN))
        callback = MagicMock()
        callback.answer = AsyncMock()
        with patch(
            "bot.no_host_doctor_night.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as update_panel, patch(
            "bot.no_host_doctor_night.no_host_after_role_night_pick",
            new_callable=AsyncMock,
        ):
            await self._complete(game, callback, [20, 30])
        update_panel.assert_awaited_once()
        body = update_panel.await_args.args[3]
        self.assertIn("رضا", body)
        self.assertIn("امیر", body)
        self.assertNotIn("تک تیرانداز", body)

    async def _complete(self, game, callback, uids: list[int]) -> None:
        from bot.no_host_doctor_night import _complete_no_host_doctor_pick

        for uid in uids:
            dr.commit_pick(game, uid)
        await _complete_no_host_doctor_pick(
            callback, AsyncMock(), game, self.gm, doc_uid=10
        )


class BazporsDoctorFinalizedPickUnchangedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_bazpors_still_uses_generic_wait_panel(self) -> None:
        from bot.no_host_doctor_night import _publish_doctor_pick_finalized_panel

        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        self.gm.add_player(game, _p(20, "A", Role.CITIZEN))
        dr.commit_pick(game, 20)
        with patch(
            "bot.no_host_doctor_night.publish_no_host_night_wait_panel",
            new_callable=AsyncMock,
        ) as wait_panel, patch(
            "bot.no_host_doctor_night.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as update_panel:
            await _publish_doctor_pick_finalized_panel(
                AsyncMock(), game, self.gm, 10
            )
        wait_panel.assert_awaited_once()
        update_panel.assert_not_awaited()


class MozakereNightReportDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _mozakere_game(self, *, night: int = 1):
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = night
        self.gm.add_player(game, _p(10, "Doc", Role.DOCTOR, seat=1))
        return game

    def test_night_report_shows_both_saves_without_roles(self) -> None:
        from bot.bazpors_narrator import _compose_full_night_report

        game = self._mozakere_game(night=1)
        self.gm.add_player(game, _p(20, "فریدونی", Role.SNIPER, seat=2))
        self.gm.add_player(game, _p(30, "امیر", Role.CITIZEN, seat=3))
        for i in range(6):
            self.gm.add_player(game, _p(40 + i, f"F{i}", Role.CITIZEN))
        dr.commit_pick(game, 20)
        dr.commit_pick(game, 30)
        alive_before = {uid: True for uid in game.players}

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("💉 نجات پزشک:", report)
        self.assertIn("فریدونی", report)
        self.assertIn("امیر", report)
        self.assertNotIn("تک تیرانداز", report)
        self.assertNotIn("تک‌تیرانداز", report)
        self.assertNotIn("شهروند", report)

    def test_night_report_single_save(self) -> None:
        from bot.bazpors_narrator import _compose_full_night_report

        game = self._mozakere_game(night=2)
        self.gm.add_player(game, _p(20, "رضا", Role.CITIZEN, seat=2))
        dr.commit_pick(game, 20)
        alive_before = {uid: True for uid in game.players}

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("💉 نجات پزشک: رضا", report)
        self.assertNotIn("\n-", report.split("نجات پزشک")[1].split("⚖️")[0])

    def test_night_report_omits_doctor_when_no_saves(self) -> None:
        from bot.bazpors_narrator import _compose_full_night_report

        game = self._mozakere_game(night=1)
        alive_before = {uid: True for uid in game.players}

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertNotIn("نجات پزشک", report)

    def test_bazpors_doctor_report_unchanged(self) -> None:
        from bot.bazpors_narrator import _compose_full_night_report

        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(10, "Doc", Role.DOCTOR, seat=1))
        self.gm.add_player(game, _p(20, "A", Role.CITIZEN, seat=2))
        game.actions.doctor_save = 20
        game.bazpors_doctor_save_uids = [20]
        alive_before = {uid: True for uid in game.players}

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("💉 نجات پزشک:", report)
        self.assertIn("A", report)


if __name__ == "__main__":
    unittest.main()
