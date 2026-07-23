"""شب مذاکره — readiness پایان شب و پیام‌های نتیجه (خبرنگار/کارآگاه/recruit)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, mozakere_roles_for_count
from bot.models import Phase, Player, Role
from bot.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE, MAFIA_ACTION_SHOT
from bot.no_host_night_ready import (
    _journalist_ready,
    _mafia_night1_parallel_ready,
    all_no_host_parallel_night_ready,
)
from bot.roles import detective as det_mod
from bot.roles.mozakere_journalist import (
    commit_check as commit_journalist_check,
    load_result as load_journalist_result,
)
from bot.roles.mozakere_negotiator import (
    commit_mozakere_negotiation,
    find_alive_negotiator,
)
from bot.roles.registry import get_role_module


def _p(uid: int, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=f"p{uid}",
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_game(gm: GameManager, *, night: int = 2) -> "Game":
    from bot.models import Game

    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    roles = mozakere_roles_for_count(12)
    uid = 100
    role_uids: dict[Role, int] = {}
    for role in roles:
        uid += 1
        gm.add_player(game, _p(uid, role))
        if role not in role_uids:
            role_uids[role] = uid
    game._test_uids = role_uids  # type: ignore[attr-defined]
    game.phase = Phase.NIGHT
    game.bazpors_narrator_step = "night_start"
    game.bazpors_narrator_night_count = night
    game.no_host_night_parallel_collect_active = True
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 999
    game.bazpors_alive_at_night_start = {
        uid: p.is_alive for uid, p in game.players.items()
    }
    return game


def _arm_all_citizens(game) -> None:
    citizens = get_role_module(Role.CITIZEN).alive_simple_citizen_uids(game)
    game.no_host_citizen_night_confirmed_uids = citizens


def _eliminate_mafia_for_negotiation_threshold(game) -> None:
    """۱۲ نفره — حداقل ۲ مافیا باید از بازی خارج شده باشند (نه مذاکره‌کننده)."""
    need = 2 if game.max_players in (12, 13, 15) else 1
    eliminated = 0
    for role in (Role.MAFIA_SIMPLE, Role.MAFIA_SIMPLE_2):
        for p in game.players.values():
            if p.role == role and p.is_alive:
                p.is_alive = False
                eliminated += 1
                if eliminated >= need:
                    return


class MozakereNegotiateNightReadyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_mafia_ready_after_negotiator_without_journalist_pick(self) -> None:
        game = _mozakere_game(self.gm, night=1)
        game.mozakere_negotiation_used = True
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NEGOTIATE
        game.no_host_negotiator_pick_confirmed = True
        game.no_host_journalist_pick_confirmed = False
        self.assertTrue(_mafia_night1_parallel_ready(game))
        self.assertFalse(_journalist_ready(game))

    def test_journalist_not_blocker_after_confirm(self) -> None:
        game = _mozakere_game(self.gm, night=2)
        game.mozakere_negotiation_used = True
        game.no_host_journalist_pick_confirmed = True
        self.assertTrue(_journalist_ready(game))

    def test_night2_shot_all_ready_when_everyone_confirmed(self) -> None:
        game = _mozakere_game(self.gm, night=2)
        game.mozakere_negotiation_used = True
        recruit_uid = game._test_uids[Role.CITIZEN]  # type: ignore[attr-defined]
        game.mozakere_mafia_recruit_ids.add(recruit_uid)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        game.no_host_journalist_pick_confirmed = True
        game.no_host_detective_pick_confirmed = True
        game.no_host_doctor_pick_confirmed = True
        game.no_host_sniper_pick_confirmed = True
        _arm_all_citizens(game)
        self.assertTrue(all_no_host_parallel_night_ready(game))

    def test_negotiate_night_all_ready_after_full_flow(self) -> None:
        game = _mozakere_game(self.gm, night=2)
        _eliminate_mafia_for_negotiation_threshold(game)
        recruit_uid = game._test_uids[Role.CITIZEN]  # type: ignore[attr-defined]
        recruit = game.players[recruit_uid]
        neg = find_alive_negotiator(game)
        assert neg is not None
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NEGOTIATE
        game.mozakere_negotiation_tonight = True
        outcome = commit_mozakere_negotiation(game, neg, recruit)
        self.assertEqual(outcome.outcome.value, "success")
        game.no_host_negotiator_pick_confirmed = True
        jr_uid = game._test_uids[Role.JOURNALIST]  # type: ignore[attr-defined]
        commit_journalist_check(game, recruit_uid)
        game.no_host_journalist_pick_confirmed = True
        det_uid = game._test_uids[Role.DETECTIVE]  # type: ignore[attr-defined]
        det_mod.commit_pick(game, recruit_uid)
        game.no_host_detective_pick_confirmed = True
        game.no_host_doctor_pick_confirmed = True
        game.no_host_sniper_pick_confirmed = True
        _arm_all_citizens(game)
        self.assertTrue(all_no_host_parallel_night_ready(game))
        self.assertIn(recruit_uid, game.mozakere_mafia_recruit_ids)
        jr_result = load_journalist_result(game)
        assert jr_result is not None
        self.assertTrue(jr_result.is_positive)


class MozakereNightResolveDmTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolution_sends_journalist_detective_recruit_dms(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, night=2)
        _eliminate_mafia_for_negotiation_threshold(game)
        recruit_uid = game._test_uids[Role.CITIZEN]  # type: ignore[attr-defined]
        recruit = game.players[recruit_uid]
        neg = find_alive_negotiator(game)
        assert neg is not None
        game.mozakere_negotiation_tonight = True
        outcome = commit_mozakere_negotiation(game, neg, recruit)
        self.assertEqual(outcome.outcome.value, "success")
        commit_journalist_check(game, recruit_uid)
        game.no_host_journalist_pick_confirmed = True
        det_mod.commit_pick(game, recruit_uid)
        game.no_host_detective_pick_confirmed = True

        bot = MagicMock()
        sent: list[tuple[int, str]] = []

        async def _capture(bot_, g, uid, text, **kwargs):
            sent.append((uid, text))

        with patch(
            "bot.no_host_night_resolve.deliver_no_host_player_game_copy",
            new=AsyncMock(side_effect=_capture),
        ), patch(
            "bot.no_host_night_resolve.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.bazpors_night_panel_purge.purge_stale_night_and_day_panel_messages",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_resolve.deliver_night_results_to_eliminated_from_night",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_resolve.deliver_observer_night_end_report",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_resolve.no_host_maybe_end_on_faction_win",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.no_host_table_inquiry.no_host_enter_table_inquiry_before_day",
            new=AsyncMock(),
        ), patch(
            "bot.bazpors_narrator.push_host_step",
            new=AsyncMock(),
        ):
            from bot.no_host_night_resolve import no_host_complete_discipline_and_resolve

            await no_host_complete_discipline_and_resolve(
                bot, game, gm, send_discipline_broadcast=False
            )

        jr_uid = game._test_uids[Role.JOURNALIST]  # type: ignore[attr-defined]
        det_uid = game._test_uids[Role.DETECTIVE]  # type: ignore[attr-defined]
        texts_by_uid = {uid: text for uid, text in sent}
        self.assertIn(jr_uid, texts_by_uid)
        self.assertIn("مثبت", texts_by_uid[jr_uid])
        self.assertIn(det_uid, texts_by_uid)
        self.assertIn("مثبت", texts_by_uid[det_uid])
        self.assertNotIn(recruit_uid, texts_by_uid)

    async def test_failed_negotiation_sends_no_recruit_dm(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, night=2)
        _eliminate_mafia_for_negotiation_threshold(game)
        doctor_uid = game._test_uids[Role.DOCTOR]  # type: ignore[attr-defined]
        doctor = game.players[doctor_uid]
        neg = find_alive_negotiator(game)
        assert neg is not None
        game.mozakere_negotiation_tonight = True
        commit_mozakere_negotiation(game, neg, doctor)

        bot = MagicMock()
        sent: list[tuple[int, str]] = []

        async def _capture(bot_, g, uid, text, **kwargs):
            sent.append((uid, text))

        with patch(
            "bot.no_host_night_resolve.deliver_no_host_player_game_copy",
            new=AsyncMock(side_effect=_capture),
        ), patch(
            "bot.no_host_night_resolve.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.bazpors_night_panel_purge.purge_stale_night_and_day_panel_messages",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_resolve.deliver_night_results_to_eliminated_from_night",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_resolve.deliver_observer_night_end_report",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_resolve.no_host_maybe_end_on_faction_win",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.no_host_table_inquiry.no_host_enter_table_inquiry_before_day",
            new=AsyncMock(),
        ), patch(
            "bot.bazpors_narrator.push_host_step",
            new=AsyncMock(),
        ):
            from bot.no_host_night_resolve import no_host_complete_discipline_and_resolve

            await no_host_complete_discipline_and_resolve(
                bot, game, gm, send_discipline_broadcast=False
            )

        recruit_texts = [
            t
            for _, t in sent
            if "مذاکره با شما موفقیت‌آمیز بود" in t
            or "فرد انتخابی از شب بعد" in t
        ]
        self.assertEqual(recruit_texts, [])


class BazporsRegressionTests(unittest.TestCase):
    def test_bazpors_journalist_ready_unchanged(self) -> None:
        from bot.models import Game

        game = Game(
            room_code="BZ1",
            host_id=1,
            scenario_name="bazpors",
            phase=Phase.NIGHT,
            players={},
        )
        game.bazpors_host_mode = "no_host"
        self.assertTrue(_journalist_ready(game))
