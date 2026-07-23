"""شبیه‌سازی راه‌اندازی اتاق ماسون — ظرفیت ۱۲ تا ۱۸."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, role_label_fa, scenario_role_label_fa
from bot.mason_role_descriptions import mason_role_description_fa
from bot.mason_roles import (
    MASON_PLAYER_COUNTS,
    masoon_roles_for_count,
    mason_mafia_roles_for_count,
    mason_town_roles_for_count,
)
from bot.mason_synthetic_names import MASON_SYNTHETIC_NAME_SEP
from bot.models import Role
from bot.room_mode import is_mason_scenario

from tests.mason_simulation_harness import (
    MASON_CORE_NIGHT_ROLES,
    MASON_COUNTS,
    MasonSimHarness,
)


class MasonSimulationSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_role_list_length_matches_count(self) -> None:
        for n in MASON_COUNTS:
            with self.subTest(players=n):
                roles = masoon_roles_for_count(n)
                self.assertEqual(len(roles), n)

    def test_core_roles_present_every_count(self) -> None:
        for n in MASON_COUNTS:
            with self.subTest(players=n):
                roles = set(masoon_roles_for_count(n))
                for core in MASON_CORE_NIGHT_ROLES:
                    self.assertIn(core, roles)

    def test_detective_from_16(self) -> None:
        for n in MASON_COUNTS:
            roles = set(masoon_roles_for_count(n))
            with self.subTest(players=n):
                if n >= 16:
                    self.assertIn(Role.DETECTIVE, roles)
                else:
                    self.assertNotIn(Role.DETECTIVE, roles)

    def test_natasha_priest_only_at_18(self) -> None:
        for n in MASON_COUNTS:
            roles = set(masoon_roles_for_count(n))
            with self.subTest(players=n):
                if n >= 18:
                    self.assertIn(Role.NATASHA, roles)
                    self.assertIn(Role.PRIEST, roles)
                else:
                    self.assertNotIn(Role.NATASHA, roles)
                    self.assertNotIn(Role.PRIEST, roles)

    def test_mafia_town_partition_covers_all_roles(self) -> None:
        for n in MASON_COUNTS:
            with self.subTest(players=n):
                all_roles = masoon_roles_for_count(n)
                mafia = mason_mafia_roles_for_count(n)
                town = mason_town_roles_for_count(n)
                self.assertEqual(len(mafia) + len(town), len(all_roles))
                self.assertEqual(set(mafia) | set(town), set(all_roles))

    def test_synthetic_names_get_role_suffix(self) -> None:
        for n in (12, 16, 18):
            with self.subTest(players=n):
                h = MasonSimHarness.build(self.gm, max_players=n)
                for p in MasonSimHarness.synthetic_players(h.game):
                    self.assertIsNotNone(p.role)
                    label = scenario_role_label_fa(h.game, p.role)
                    self.assertIn(MASON_SYNTHETIC_NAME_SEP, p.full_name)
                    self.assertTrue(p.full_name.endswith(label))

    def test_real_creator_name_unchanged(self) -> None:
        h = MasonSimHarness.build(self.gm, max_players=16)
        self.assertEqual(h.game.players[h.creator_uid].full_name, "امیر")

    def test_each_dealt_role_has_description(self) -> None:
        h = MasonSimHarness.build(self.gm, max_players=16)
        for p in h.game.players.values():
            if p.role is None:
                continue
            desc = mason_role_description_fa(p.role)
            self.assertIn("نقش شما", desc)
            self.assertGreater(len(desc), 40)

    def test_only_mason_scenario(self) -> None:
        h = MasonSimHarness.build(self.gm, max_players=16)
        self.assertTrue(is_mason_scenario(h.game))


class MasonSimulationRoleDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_intro_delivery_sends_to_players(self) -> None:
        from bot.mason_intro_flow import deliver_mason_intro_night_started_messages

        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=12)
        player_sends: list[int] = []

        async def _safe_send(bot, uid, text, **kw):
            if uid != h.observer_uid:
                player_sends.append(uid)

        with patch("bot.mason_intro_flow.safe_send_message", side_effect=_safe_send):
            await deliver_mason_intro_night_started_messages(h.bot, h.game)

        self.assertGreater(len(player_sends), 0)

    async def test_private_role_messages_for_all_counts(self) -> None:
        from bot.main import build_private_role_message_html

        gm = GameManager()
        for n in MASON_COUNTS:
            with self.subTest(players=n):
                h = MasonSimHarness.build(gm, max_players=n)
                for p in h.game.players.values():
                    if p.role is None:
                        continue
                    html = build_private_role_message_html(h.game, p.role)
                    self.assertTrue(html.startswith("<tg-spoiler>"))


class MasonSimulationAssignRegressionTests(unittest.TestCase):
    def test_bazpors_counts_unchanged(self) -> None:
        from bot.game import bazpors_roles_for_count

        self.assertEqual(len(bazpors_roles_for_count(12)), 12)

    def test_mozakere_counts_unchanged(self) -> None:
        from bot.game import mozakere_roles_for_count

        roles = mozakere_roles_for_count(12)
        self.assertEqual(len(roles), 12)
        self.assertNotIn(Role.MASON, roles)
