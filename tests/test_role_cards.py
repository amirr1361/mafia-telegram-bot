"""کارت تصویری نقش پس از پخش."""

from __future__ import annotations

import unittest

from bot.models import Role
from bot.role_cards import role_card_image_path


class RoleCardPathTest(unittest.TestCase):
    def test_mafia_boss_card_exists(self) -> None:
        path = role_card_image_path(Role.MAFIA_BOSS)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_detective_card_exists(self) -> None:
        path = role_card_image_path(Role.DETECTIVE)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_interrogator_card_exists(self) -> None:
        path = role_card_image_path(Role.INTERROGATOR)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_nato_card_exists(self) -> None:
        path = role_card_image_path(Role.NATO)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_shiad_card_exists(self) -> None:
        path = role_card_image_path(Role.SHIAD)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_mafia_basic_card_exists(self) -> None:
        path = role_card_image_path(Role.MAFIA_BASIC)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())
        self.assertEqual(
            role_card_image_path(Role.MAFIA_SIMPLE),
            role_card_image_path(Role.MAFIA_BASIC),
        )

    def test_sniper_card_exists(self) -> None:
        path = role_card_image_path(Role.SNIPER)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_doctor_card_exists(self) -> None:
        path = role_card_image_path(Role.DOCTOR)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_ruintan_card_exists(self) -> None:
        path = role_card_image_path(Role.RUINTAN)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_citizen_card_exists(self) -> None:
        path = role_card_image_path(Role.CITIZEN)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_hunter_card_exists(self) -> None:
        path = role_card_image_path(Role.HUNTER)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())

    def test_other_roles_no_card(self) -> None:
        self.assertIsNone(role_card_image_path(Role.MAFIA_NEGOTIATOR))


if __name__ == "__main__":
    unittest.main()
