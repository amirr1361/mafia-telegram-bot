"""تست نقش‌های سناریوی ماسون — ظرفیت ۱۲ تا ۱۸."""

from __future__ import annotations

import unittest

from bot.game import (
    GameManager,
    bazpors_roles_for_count,
    is_mafia_team,
    mozakere_roles_for_count,
    role_label_fa,
    role_roster_banner_text,
)
from bot.mason_roles import (
    MASON_PLAYER_COUNTS,
    masoon_roles_for_count,
    mason_mafia_roles_for_count,
    mason_town_roles_for_count,
)


def _labels(roles: list) -> list[str]:
    return [role_label_fa(r) for r in roles]


MASON_EXPECTED_BY_COUNT: dict[int, dict[str, list[str]]] = {
    12: {
        "mafia": ["گادفادر", "خرابکار", "جاسوس", "آپاچی"],
        "town": [
            "پزشک",
            "رویین تن",
            "کابوی",
            "اسنایپر",
            "فرمانده",
            "تفنگدار",
            "محافظ",
            "ماسون",
        ],
    },
    13: {
        "mafia": ["گادفادر", "خرابکار", "جاسوس", "آپاچی"],
        "town": [
            "پزشک",
            "رویین تن",
            "کابوی",
            "اسنایپر",
            "فرمانده",
            "تفنگدار",
            "محافظ",
            "ماسون",
            "شهر ساده",
        ],
    },
    14: {
        "mafia": ["گادفادر", "خرابکار", "جاسوس", "آپاچی", "ناتو"],
        "town": [
            "پزشک",
            "رویین تن",
            "کابوی",
            "اسنایپر",
            "فرمانده",
            "تفنگدار",
            "محافظ",
            "ماسون",
            "شهر ساده",
        ],
    },
    15: {
        "mafia": ["گادفادر", "خرابکار", "جاسوس", "آپاچی", "ناتو"],
        "town": [
            "پزشک",
            "رویین تن",
            "کابوی",
            "اسنایپر",
            "فرمانده",
            "تفنگدار",
            "محافظ",
            "ماسون",
            "تایلر",
            "شهر ساده",
        ],
    },
    16: {
        "mafia": [
            "گادفادر",
            "خرابکار",
            "جاسوس",
            "آپاچی",
            "ناتو",
            "مافیا ساده",
        ],
        "town": [
            "پزشک",
            "رویین تن",
            "کابوی",
            "اسنایپر",
            "فرمانده",
            "تفنگدار",
            "محافظ",
            "ماسون",
            "تایلر",
            "کاراگاه",
        ],
    },
    17: {
        "mafia": [
            "گادفادر",
            "خرابکار",
            "جاسوس",
            "آپاچی",
            "ناتو",
            "مافیا ساده",
        ],
        "town": [
            "پزشک",
            "رویین تن",
            "کابوی",
            "اسنایپر",
            "فرمانده",
            "تفنگدار",
            "محافظ",
            "ماسون",
            "تایلر",
            "کاراگاه",
            "شهر ساده",
        ],
    },
    18: {
        "mafia": [
            "گادفادر",
            "خرابکار",
            "جاسوس",
            "آپاچی",
            "ناتو",
            "ناتاشا",
        ],
        "town": [
            "پزشک",
            "رویین تن",
            "کابوی",
            "اسنایپر",
            "فرمانده",
            "تفنگدار",
            "محافظ",
            "ماسون",
            "تایلر",
            "کاراگاه",
            "کشیش",
            "شهر ساده",
        ],
    },
}


class MasonRolesForCountTests(unittest.TestCase):
    def test_supported_counts(self) -> None:
        self.assertEqual(MASON_PLAYER_COUNTS, frozenset(range(12, 19)))

    def test_invalid_count_raises(self) -> None:
        with self.subTest(n=11):
            with self.assertRaises(ValueError):
                masoon_roles_for_count(11)
        with self.subTest(n=19):
            with self.assertRaises(ValueError):
                masoon_roles_for_count(19)

    def test_all_counts_match_official_lists(self) -> None:
        for n, expected in MASON_EXPECTED_BY_COUNT.items():
            with self.subTest(players=n):
                roles = masoon_roles_for_count(n)
                self.assertEqual(len(roles), n)
                self.assertEqual(_labels(mason_mafia_roles_for_count(n)), expected["mafia"])
                self.assertEqual(_labels(mason_town_roles_for_count(n)), expected["town"])
                self.assertEqual(
                    _labels(roles),
                    expected["mafia"] + expected["town"],
                )

    def test_mafia_town_partition(self) -> None:
        for n in MASON_PLAYER_COUNTS:
            with self.subTest(players=n):
                roles = masoon_roles_for_count(n)
                mafia = [r for r in roles if is_mafia_team(r)]
                town = [r for r in roles if not is_mafia_team(r)]
                self.assertEqual(len(mafia) + len(town), n)
                self.assertEqual(mafia, mason_mafia_roles_for_count(n))
                self.assertEqual(town, mason_town_roles_for_count(n))

    def test_18_uses_natasha_not_simple_mafia(self) -> None:
        roles = masoon_roles_for_count(18)
        from bot.models import Role

        self.assertIn(Role.NATASHA, roles)
        self.assertNotIn(Role.MAFIA_BASIC, roles)
        self.assertIn(Role.PRIEST, roles)


class MasonRolePoolIntegrationTests(unittest.TestCase):
    def test_game_manager_uses_mason_lists(self) -> None:
        gm = GameManager()
        for n in MASON_PLAYER_COUNTS:
            with self.subTest(players=n):
                roles = gm.intended_roles_for_room("masoon", n)
                self.assertEqual(roles, masoon_roles_for_count(n))

    def test_roster_banner_includes_mason_labels(self) -> None:
        gm = GameManager()
        plain = role_roster_banner_text("masoon", 18, gm)
        for label in ("ناتاشا", "کشیش", "گادفادر", "شهر ساده"):
            self.assertIn(label, plain)


class BazporsMozakereRoleRegressionTests(unittest.TestCase):
    def test_bazpors_10p_unchanged(self) -> None:
        roles = bazpors_roles_for_count(10)
        self.assertEqual(len(roles), 10)
        from bot.models import Role

        self.assertIn(Role.MAFIA_BOSS, roles)
        self.assertIn(Role.DETECTIVE, roles)
        self.assertNotIn(Role.GODFATHER, roles)

    def test_bazpors_13p_unchanged(self) -> None:
        roles = bazpors_roles_for_count(13)
        self.assertEqual(len(roles), 13)
        from bot.models import Role

        self.assertIn(Role.HUNTER, roles)
        self.assertNotIn(Role.NATASHA, roles)

    def test_mozakere_12p_unchanged(self) -> None:
        roles = mozakere_roles_for_count(12)
        self.assertEqual(len(roles), 12)
        from bot.models import Role

        self.assertIn(Role.MAFIA_NEGOTIATOR, roles)
        self.assertIn(Role.JOURNALIST, roles)
        self.assertNotIn(Role.GODFATHER, roles)

    def test_mozakere_15p_unchanged(self) -> None:
        from bot.models import Role

        roles = mozakere_roles_for_count(15)
        self.assertEqual(len(roles), 15)
        self.assertEqual(roles.count(Role.CITIZEN), 6)
