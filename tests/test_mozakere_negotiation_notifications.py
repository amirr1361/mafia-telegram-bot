"""پیام‌های موفقیت مذاکره — فقط سناریوی مذاکره."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, mozakere_roles_for_count
from bot.models import Phase, Player, Role
from bot.no_host_mafia_yaku import build_no_host_yaku_converted_player_html
from bot.no_host_mozakere_negotiation import (
    MOZAKERE_NEGOTIATION_EXISTING_MAFIA_SUCCESS_TEXT,
    MOZAKERE_NEGOTIATION_RECRUIT_SUCCESS_TEXT,
    send_mozakere_negotiation_commit_notifications,
)
from bot.roles.mozakere_negotiator import (
    commit_mozakere_negotiation,
    find_alive_negotiator,
)


def _p(uid: int, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=f"p{uid}",
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_game(gm: GameManager) -> "Game":
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
    game.bazpors_narrator_night_count = 2
    game.mozakere_negotiation_tonight = True
    return game


def _eliminate_mafia_for_negotiation_threshold(game) -> None:
    need = 2 if game.max_players in (12, 13, 15) else 1
    eliminated = 0
    for role in (Role.MAFIA_SIMPLE, Role.MAFIA_SIMPLE_2):
        for p in game.players.values():
            if p.role == role and p.is_alive:
                p.is_alive = False
                eliminated += 1
                if eliminated >= need:
                    return


class MozakereNegotiationNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def _capture_notifications(
        self, game, *, target_uid: int, succeeded: bool
    ) -> list[tuple[int, str]]:
        sent: list[tuple[int, str]] = []

        async def _capture(bot_, g, uid, text, **kwargs):
            sent.append((uid, text))

        with patch(
            "bot.no_host_mozakere_negotiation.deliver_no_host_player_game_copy",
            new=AsyncMock(side_effect=_capture),
        ):
            await send_mozakere_negotiation_commit_notifications(
                bot=MagicMock(),
                game=game,
                target_uid=target_uid,
                succeeded=succeeded,
            )
        return sent

    async def test_success_notifies_recruit_with_exact_message_only(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm)
        _eliminate_mafia_for_negotiation_threshold(game)
        recruit_uid = game._test_uids[Role.CITIZEN]  # type: ignore[attr-defined]
        recruit = game.players[recruit_uid]
        neg = find_alive_negotiator(game)
        assert neg is not None
        outcome = commit_mozakere_negotiation(game, neg, recruit)
        self.assertTrue(outcome.succeeded)

        sent = await self._capture_notifications(
            game, target_uid=recruit_uid, succeeded=True
        )
        recruit_msgs = [text for uid, text in sent if uid == recruit_uid]
        self.assertEqual(recruit_msgs, [MOZAKERE_NEGOTIATION_RECRUIT_SUCCESS_TEXT])
        self.assertNotIn("اعضای تیم مافیا", recruit_msgs[0])
        self.assertNotIn("📋", recruit_msgs[0])

    async def test_success_notifies_alive_mafia_with_generic_message(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm)
        _eliminate_mafia_for_negotiation_threshold(game)
        recruit_uid = game._test_uids[Role.CITIZEN]  # type: ignore[attr-defined]
        recruit = game.players[recruit_uid]
        neg = find_alive_negotiator(game)
        boss_uid = game._test_uids[Role.MAFIA_BOSS]  # type: ignore[attr-defined]
        assert neg is not None
        commit_mozakere_negotiation(game, neg, recruit)

        sent = await self._capture_notifications(
            game, target_uid=recruit_uid, succeeded=True
        )
        texts_by_uid = {uid: text for uid, text in sent}
        self.assertEqual(
            texts_by_uid[recruit_uid],
            MOZAKERE_NEGOTIATION_RECRUIT_SUCCESS_TEXT,
        )
        self.assertIn(neg.user_id, texts_by_uid)
        self.assertIn(boss_uid, texts_by_uid)
        for uid in (neg.user_id, boss_uid):
            self.assertEqual(
                texts_by_uid[uid],
                MOZAKERE_NEGOTIATION_EXISTING_MAFIA_SUCCESS_TEXT,
            )
            self.assertNotIn(recruit.full_name, texts_by_uid[uid])
            self.assertNotIn("اعضای تیم مافیا", texts_by_uid[uid])
            self.assertNotIn(MOZAKERE_NEGOTIATION_RECRUIT_SUCCESS_TEXT, texts_by_uid[uid])

    async def test_failed_negotiation_notifies_mafia_but_not_target(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm)
        _eliminate_mafia_for_negotiation_threshold(game)
        doctor_uid = game._test_uids[Role.DOCTOR]  # type: ignore[attr-defined]
        neg = find_alive_negotiator(game)
        boss_uid = game._test_uids[Role.MAFIA_BOSS]  # type: ignore[attr-defined]
        assert neg is not None
        outcome = commit_mozakere_negotiation(game, neg, game.players[doctor_uid])
        self.assertFalse(outcome.succeeded)

        sent = await self._capture_notifications(
            game, target_uid=doctor_uid, succeeded=False
        )
        texts_by_uid = {uid: text for uid, text in sent}
        self.assertNotIn(doctor_uid, texts_by_uid)
        self.assertIn(neg.user_id, texts_by_uid)
        self.assertIn(boss_uid, texts_by_uid)
        for uid in (neg.user_id, boss_uid):
            self.assertEqual(
                texts_by_uid[uid],
                MOZAKERE_NEGOTIATION_EXISTING_MAFIA_SUCCESS_TEXT,
            )

    async def test_night_resolve_does_not_send_negotiation_dms(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm)
        _eliminate_mafia_for_negotiation_threshold(game)
        recruit_uid = game._test_uids[Role.CITIZEN]  # type: ignore[attr-defined]
        recruit = game.players[recruit_uid]
        neg = find_alive_negotiator(game)
        assert neg is not None
        commit_mozakere_negotiation(game, neg, recruit)

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
                MagicMock(), game, gm, send_discipline_broadcast=False
            )

        negotiation_texts = [
            t
            for _, t in sent
            if MOZAKERE_NEGOTIATION_RECRUIT_SUCCESS_TEXT in t
            or MOZAKERE_NEGOTIATION_EXISTING_MAFIA_SUCCESS_TEXT in t
        ]
        self.assertEqual(negotiation_texts, [])


class BazporsNegotiationRegressionTests(unittest.TestCase):
    def test_bazpors_yaku_converted_player_still_includes_mafia_list(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(10, Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, Role.MAFIA_SIMPLE))
        gm.add_player(game, _p(30, Role.CITIZEN))
        game.mafia_ids.update({10, 20})
        body = build_no_host_yaku_converted_player_html(game, gm, 30)
        self.assertIn("اعضای زنده تیم مافیا", body)
