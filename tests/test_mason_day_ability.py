"""تست قابلیت روزانهٔ آپاچی و کابوی — سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_day_ability import (
    MASON_APACHE_CONFIRM_ACT,
    MASON_APACHE_SOLO_ELIM_BROADCAST_FA,
    MASON_COWBOY_CONFIRM_ACT,
    MASON_COWBOY_PICK_ACT,
    MASON_DAY_GUN_CONFIRM_ACT,
    MASON_DAY_GUN_EXPIRED_ALERT_FA,
    MASON_DAY_GUN_EXPIRED_PANEL_FA,
    MASON_DAY_GUN_PICK_ACT,
    MASON_DAY_PANEL_INACTIVE_ALERT_FA,
    MASON_DAY_PANEL_INACTIVE_FA,
    _eliminate_apache_and_target,
    _eliminate_cowboy_and_target,
    build_mason_apache_elim_broadcast_html,
    build_mason_apache_solo_elim_broadcast_html,
    build_mason_cowboy_elim_broadcast_html,
    dismiss_mason_day_ability_panel_for_eliminated,
    dismiss_mason_day_ability_panels,
    dispatch_mason_day_ability,
    expire_mason_day_gun_panel_at_vote_start,
)
from bot.mason_role_descriptions import mason_role_description_fa
from bot.models import Player, Role
from bot.roles import mason_guardian as ms_gd


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
    return game


class MasonRoleDescriptionTextTests(unittest.TestCase):
    def test_apache_description_mentions_guardian_outcomes(self) -> None:
        desc = mason_role_description_fa(Role.APACHE)
        self.assertIn("محافظ محافظت نشده باشد", desc)
        self.assertIn("به همراه شما از بازی خارج خواهد شد", desc)
        self.assertIn("فقط شما از بازی خارج می‌شوید", desc)
        self.assertIn("پنل شلیک مافیا", desc)

    def test_cowboy_description_mentions_both_exit(self) -> None:
        desc = mason_role_description_fa(Role.COWBOY)
        self.assertIn("به همراه شما از بازی خارج خواهد شد", desc)
        self.assertNotIn("تنها", desc)


class MasonApacheEliminationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unprotected_target_eliminates_both(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        bot = MagicMock()
        broadcasts: list[str] = []

        async def _capture(_bot, _game, text, **kw):
            broadcasts.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_capture,
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=20
            )
        self.assertFalse(game.players[10].is_alive)
        self.assertFalse(game.players[20].is_alive)
        self.assertEqual(len(broadcasts), 1)
        self.assertIn("به همراه آپاچی", broadcasts[0])
        self.assertIn("شهروندان", broadcasts[0])
        self.assertNotIn("شهروند ساده", broadcasts[0])

    async def test_protected_target_eliminates_only_apache(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        ms_gd.commit_mason_guardian_night_pick(game, 20)
        ms_gd.activate_mason_guardian_day_protection(game)
        bot = MagicMock()
        broadcasts: list[str] = []

        async def _capture(_bot, _game, text, **kw):
            broadcasts.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_capture,
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=20
            )
        self.assertFalse(game.players[10].is_alive)
        self.assertTrue(game.players[20].is_alive)
        self.assertEqual(broadcasts, [MASON_APACHE_SOLO_ELIM_BROADCAST_FA])
        self.assertNotIn("T", broadcasts[0])
        self.assertNotIn("شهروند", broadcasts[0])

    def test_solo_broadcast_exact_text(self) -> None:
        self.assertEqual(
            build_mason_apache_solo_elim_broadcast_html(),
            "آپاچی به تنهایی از بازی خارج می‌شود.",
        )


class MasonCowboyEliminationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cowboy_eliminates_both(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        gm.add_player(game, _p(30, "Spy", Role.SPY))
        bot = MagicMock()
        broadcasts: list[str] = []

        async def _capture(_bot, _game, text, **kw):
            broadcasts.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_capture,
        ):
            await _eliminate_cowboy_and_target(
                bot, game, gm, cowboy_uid=40, target_uid=30
            )
        self.assertFalse(game.players[40].is_alive)
        self.assertFalse(game.players[30].is_alive)
        self.assertIn("به همراه کابوی", broadcasts[0])
        self.assertIn("تیم مافیا", broadcasts[0])
        self.assertNotIn("جاسوس", broadcasts[0])

    def test_cowboy_broadcast_team_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        msg = build_mason_cowboy_elim_broadcast_html(game, gm, 20)
        self.assertIn("شهروندان", msg)
        self.assertNotIn("شهروند ساده", msg)


class MasonApacheBroadcastTests(unittest.TestCase):
    def test_dual_broadcast_team_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(30, "Spy", Role.SPY))
        msg = build_mason_apache_elim_broadcast_html(game, gm, 30)
        self.assertIn("تیم مافیا", msg)
        self.assertNotIn("جاسوس", msg)


class MasonApacheCowboyCrossElimTests(unittest.IsolatedAsyncioTestCase):
    def _open_day_panels(self, game) -> None:
        game.mason_intro_day_ability_open = True
        game.mason_intro_day_ability_locked = False
        game.mason_apache_day_flow_active = True
        game.mason_cowboy_day_flow_active = True

    async def test_apache_targets_cowboy_disables_cowboy_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        bot = MagicMock()
        locked: list[tuple[int, str | None]] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append((uid, kb))

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=40
            )

        self.assertFalse(game.players[10].is_alive)
        self.assertFalse(game.players[40].is_alive)
        self.assertFalse(game.mason_cowboy_day_flow_active)
        self.assertFalse(game.mason_apache_day_flow_active)
        cowboy_lock = next(
            (kb for uid, kb in locked if uid == 40),
            "missing",
        )
        self.assertIsNone(cowboy_lock)

    async def test_cowboy_targets_apache_disables_apache_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        bot = MagicMock()
        locked: list[tuple[int, str | None]] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append((uid, kb))

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ):
            await _eliminate_cowboy_and_target(
                bot, game, gm, cowboy_uid=40, target_uid=10
            )

        self.assertFalse(game.players[10].is_alive)
        self.assertFalse(game.players[40].is_alive)
        apache_lock = next(
            (kb for uid, kb in locked if uid == 10),
            "missing",
        )
        self.assertIsNone(apache_lock)

    async def test_dead_cowboy_callback_rejected_after_apache_elim(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        game.players[10].is_alive = False
        game.players[40].is_alive = False
        self._open_day_panels(game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        await dispatch_mason_day_ability(
            cb,
            bot,
            game,
            gm,
            as_uid=40,
            actor_uid=40,
            act=MASON_COWBOY_PICK_ACT,
            tid=10,
        )
        cb.answer.assert_awaited_once_with(
            MASON_DAY_PANEL_INACTIVE_ALERT_FA,
            show_alert=True,
        )

    async def test_dead_apache_callback_rejected_after_cowboy_elim(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        game.players[10].is_alive = False
        game.players[40].is_alive = False
        self._open_day_panels(game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        await dispatch_mason_day_ability(
            cb,
            bot,
            game,
            gm,
            as_uid=10,
            actor_uid=10,
            act=MASON_APACHE_CONFIRM_ACT,
            tid=40,
        )
        cb.answer.assert_awaited_once_with(
            MASON_DAY_PANEL_INACTIVE_ALERT_FA,
            show_alert=True,
        )

    async def test_observer_cannot_act_for_dead_synthetic_cowboy(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn_cowboy = -920040
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(syn_cowboy, "SynCw", Role.COWBOY))
        game.players[syn_cowboy].is_alive = False
        self._open_day_panels(game)
        self.assertTrue(is_synthetic_player_uid(syn_cowboy))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        await dispatch_mason_day_ability(
            cb,
            bot,
            game,
            gm,
            as_uid=syn_cowboy,
            actor_uid=999,
            act=MASON_COWBOY_CONFIRM_ACT,
            tid=10,
        )
        cb.answer.assert_awaited_once_with(
            MASON_DAY_PANEL_INACTIVE_ALERT_FA,
            show_alert=True,
        )

    def test_eliminated_roles_drop_from_target_pools(self) -> None:
        from bot.roles import mason_apache as ms_ap
        from bot.roles import mason_cowboy as ms_cw

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        game.players[40].is_alive = False

        apache_pool = {p.user_id for p in ms_ap.mason_apache_day_target_pool(game)}
        self.assertNotIn(40, apache_pool)
        self.assertIn(20, apache_pool)

        game.players[10].is_alive = False
        gm.add_player(game, _p(50, "Cw2", Role.COWBOY))
        cowboy_pool = {p.user_id for p in ms_cw.mason_cowboy_day_target_pool(game)}
        self.assertNotIn(10, cowboy_pool)
        self.assertIn(20, cowboy_pool)


class MasonDayGunBroadcastTests(unittest.IsolatedAsyncioTestCase):
    def _setup_gun(self, gm: GameManager, *, sabotaged: bool = False):
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Amir", Role.TOWN_SIMPLE)
        sab = _p(40, "Sb", Role.SABOTEUR)
        victim = _p(30, "Hasan", Role.SPY)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, sab)
        gm.add_player(game, victim)
        from bot.roles import mason_gunner as ms_gn
        from bot.roles import mason_saboteur as ms_sb

        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        if sabotaged:
            ms_sb.commit_mason_saboteur_target(game, sab, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        return game, holder, victim

    async def test_normal_shot_eliminates_target_and_broadcasts(self) -> None:
        gm = GameManager()
        game, holder, victim = self._setup_gun(gm)
        bot = MagicMock()
        broadcasts: list[str] = []

        async def _capture(_bot, _game, text, **kw):
            broadcasts.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_capture,
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ):
            from bot.mason_day_ability import _eliminate_day_gun_shot

            await _eliminate_day_gun_shot(
                bot,
                game,
                gm,
                holder_uid=holder.user_id,
                target_uid=victim.user_id,
            )

        self.assertFalse(game.players[victim.user_id].is_alive)
        self.assertTrue(game.players[holder.user_id].is_alive)
        self.assertEqual(len(broadcasts), 1)
        self.assertIn("با شلیک تفنگدار از بازی خارج شد", broadcasts[0])
        self.assertIn("Hasan", broadcasts[0])
        self.assertIn("ساید: مافیا", broadcasts[0])
        self.assertNotIn("جاسوس", broadcasts[0])

    async def test_sabotaged_shot_eliminates_holder_and_broadcasts(self) -> None:
        gm = GameManager()
        game, holder, victim = self._setup_gun(gm, sabotaged=True)
        bot = MagicMock()
        broadcasts: list[str] = []

        async def _capture(_bot, _game, text, **kw):
            broadcasts.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_capture,
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ):
            from bot.mason_day_ability import _eliminate_day_gun_shot

            await _eliminate_day_gun_shot(
                bot,
                game,
                gm,
                holder_uid=holder.user_id,
                target_uid=victim.user_id,
            )

        self.assertFalse(game.players[holder.user_id].is_alive)
        self.assertTrue(game.players[victim.user_id].is_alive)
        self.assertIn(
            "خرابکاری شده بود و بنابراین خودش از بازی خارج می‌شود",
            broadcasts[0],
        )
        self.assertIn("Amir", broadcasts[0])
        self.assertIn("ساید: شهروند", broadcasts[0])
        self.assertNotIn("شهروند ساده", broadcasts[0])

    def test_normal_broadcast_side_only(self) -> None:
        from bot.mason_day_ability import build_mason_day_gun_normal_shot_broadcast_html

        gm = GameManager()
        game, _, victim = self._setup_gun(gm)
        msg = build_mason_day_gun_normal_shot_broadcast_html(game, gm, victim.user_id)
        self.assertIn("ساید: مافیا", msg)
        self.assertNotIn("جاسوس", msg)

    def test_sabotaged_broadcast_side_only(self) -> None:
        from bot.mason_day_ability import build_mason_day_gun_sabotaged_broadcast_html

        gm = GameManager()
        game, holder, _ = self._setup_gun(gm, sabotaged=True)
        msg = build_mason_day_gun_sabotaged_broadcast_html(game, gm, holder.user_id)
        self.assertIn("ساید: شهروند", msg)
        self.assertNotIn("شهروند ساده", msg)

    def test_eliminated_removed_from_gun_shot_pool(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game, holder, victim = self._setup_gun(gm)
        ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        game.players[victim.user_id].is_alive = False
        pool_ids = {p.user_id for p in ms_gn.mason_day_gun_shot_pool(game, holder.user_id)}
        self.assertNotIn(victim.user_id, pool_ids)

    async def test_observer_receives_broadcast_via_alive_players(self) -> None:
        gm = GameManager()
        game, holder, victim = self._setup_gun(gm)
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        gm.add_player(game, _p(999, "Obs", Role.TOWN_SIMPLE))
        bot = MagicMock()
        sends: list[tuple[int, str]] = []

        async def _capture(_bot, uid, text, **kw):
            sends.append((uid, text))

        with patch(
            "bot.observer_delivery.safe_send_message",
            side_effect=_capture,
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ):
            from bot.mason_day_ability import _eliminate_day_gun_shot

            await _eliminate_day_gun_shot(
                bot,
                game,
                gm,
                holder_uid=holder.user_id,
                target_uid=victim.user_id,
            )

        observer_msgs = [text for uid, text in sends if uid == 999]
        self.assertTrue(observer_msgs)
        self.assertTrue(
            any("با شلیک تفنگدار از بازی خارج شد" in text for text in observer_msgs)
        )


class MasonDayGunPanelTargetPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_day_gun_panel_includes_natasha_and_mafia_except_holder(self) -> None:
        from bot.mason_day_ability import _dispatch_mason_day_gun_panel
        from bot.observer_delivery import unpack_player_mirror_cb
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        guardian = _p(11, "Guard", Role.BODYGUARD)
        natasha = _p(12, "Nat", Role.NATASHA)
        godfather = _p(13, "Gf", Role.GODFATHER)
        spy = _p(14, "Spy", Role.SPY)
        saboteur = _p(15, "Sab", Role.SABOTEUR)
        apache = _p(16, "Ap", Role.APACHE)
        nato = _p(17, "Nato", Role.NATO)
        for pl in (gunner, guardian, natasha, godfather, spy, saboteur, apache, nato):
            gm.add_player(game, pl)

        ms_gn.commit_mason_gunner_target(game, gunner, guardian)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        pool_ids = {p.user_id for p in ms_gn.mason_day_gun_shot_pool(game, guardian.user_id)}
        self.assertIn(natasha.user_id, pool_ids)
        self.assertIn(godfather.user_id, pool_ids)
        self.assertIn(spy.user_id, pool_ids)
        self.assertIn(saboteur.user_id, pool_ids)
        self.assertIn(apache.user_id, pool_ids)
        self.assertIn(nato.user_id, pool_ids)
        self.assertNotIn(guardian.user_id, pool_ids)

        bot = MagicMock()
        button_tids: list[int] = []

        async def _capture(_bot, _game, _uid, _ui, _text, kb, **kw):
            for row in kb.inline_keyboard:
                for btn in row:
                    cb = unpack_player_mirror_cb(btn.callback_data)
                    if cb is not None:
                        button_tids.append(cb.tid)

        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await _dispatch_mason_day_gun_panel(bot, game, gm)

        self.assertEqual(set(button_tids), pool_ids)

    def test_dead_natasha_not_in_gun_pool(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.BODYGUARD)
        natasha = _p(30, "Nat", Role.NATASHA, alive=False)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, natasha)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        pool_ids = {p.user_id for p in ms_gn.mason_day_gun_shot_pool(game, holder.user_id)}
        self.assertNotIn(natasha.user_id, pool_ids)

    def test_alive_natasha_in_gun_pool(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.BODYGUARD)
        natasha = _p(30, "Nat", Role.NATASHA)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, natasha)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        pool_ids = {p.user_id for p in ms_gn.mason_day_gun_shot_pool(game, holder.user_id)}
        self.assertIn(natasha.user_id, pool_ids)

    def test_day_gun_pool_excludes_only_holder(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.BODYGUARD)
        natasha = _p(30, "Nat", Role.NATASHA)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, natasha)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        alive_ids = {p.user_id for p in game.players.values() if p.is_alive}
        pool_ids = {p.user_id for p in ms_gn.mason_day_gun_shot_pool(game, holder.user_id)}
        self.assertEqual(pool_ids, alive_ids - {holder.user_id})


class MasonDayPanelCleanupTests(unittest.IsolatedAsyncioTestCase):
    def _open_day_panels(self, game) -> None:
        game.mason_intro_day_ability_open = True
        game.mason_intro_day_ability_locked = False
        game.mason_apache_day_flow_active = True
        game.mason_cowboy_day_flow_active = True

    async def test_apache_panel_disabled_when_apache_dies(self) -> None:
        from bot.mason_day_ability import _apache_ui_key

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        self._open_day_panels(game)
        game.mirror_prompt_messages[_apache_ui_key(game, 10)] = {"text": "panel"}
        bot = MagicMock()
        locked: list[tuple[int, str, object | None]] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append((uid, text, kb))

        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ), patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            new=AsyncMock(),
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=20
            )

        apache_locks = [row for row in locked if row[0] == 10]
        self.assertTrue(apache_locks)
        self.assertTrue(
            any(row[1] == MASON_DAY_PANEL_INACTIVE_FA for row in apache_locks)
        )

    async def test_cowboy_panel_disabled_when_cowboy_dies(self) -> None:
        from bot.mason_day_ability import _cowboy_ui_key

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        gm.add_player(game, _p(30, "Spy", Role.SPY))
        self._open_day_panels(game)
        game.mirror_prompt_messages[_cowboy_ui_key(game, 40)] = {"text": "panel"}
        bot = MagicMock()
        locked: list[tuple[int, str, object | None]] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append((uid, text, kb))

        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ), patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            new=AsyncMock(),
        ):
            await _eliminate_cowboy_and_target(
                bot, game, gm, cowboy_uid=40, target_uid=30
            )

        cowboy_locks = [row for row in locked if row[0] == 40]
        self.assertTrue(cowboy_locks)
        self.assertTrue(
            any(row[1] == MASON_DAY_PANEL_INACTIVE_FA for row in cowboy_locks)
        )

    async def test_gun_panel_disabled_when_holder_dies(self) -> None:
        from bot.mason_day_ability import _day_gun_ui_key

        gm = GameManager()
        game = _mason_game(gm)
        holder = _p(20, "Holder", Role.BODYGUARD)
        gm.add_player(game, holder)
        self._open_day_panels(game)
        game.mirror_prompt_messages[_day_gun_ui_key(game, 20)] = {"text": "panel"}
        game.players[20].is_alive = False
        bot = MagicMock()
        locked: list[str] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append(text)

        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ):
            await dismiss_mason_day_ability_panel_for_eliminated(bot, game, 20)

        self.assertEqual(locked, [MASON_DAY_PANEL_INACTIVE_FA])

    async def test_vote_elim_disables_active_panel(self) -> None:
        from bot.mason_day_ability import _apache_ui_key

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        self._open_day_panels(game)
        game.mirror_prompt_messages[_apache_ui_key(game, 10)] = {"text": "panel"}
        game.players[10].is_alive = False
        bot = MagicMock()
        locked: list[str] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append(text)

        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ):
            await dismiss_mason_day_ability_panel_for_eliminated(bot, game, 10)

        self.assertEqual(locked, [MASON_DAY_PANEL_INACTIVE_FA])

    async def test_late_callback_after_panel_dismissed_is_safe(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        game.players[10].is_alive = False
        self._open_day_panels(game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        await dispatch_mason_day_ability(
            cb,
            bot,
            game,
            gm,
            as_uid=10,
            actor_uid=10,
            act=MASON_APACHE_CONFIRM_ACT,
            tid=20,
        )
        cb.answer.assert_awaited_once_with(
            MASON_DAY_PANEL_INACTIVE_ALERT_FA,
            show_alert=True,
        )


class MasonDayGunVoteExpiryTests(unittest.IsolatedAsyncioTestCase):
    def _setup_unused_gun(self, gm: GameManager):
        from bot.roles import mason_gunner as ms_gn

        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Guard", Role.BODYGUARD)
        victim = _p(30, "Victim", Role.SPY)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, victim)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        game.mason_intro_day_ability_open = True
        game.mason_intro_day_ability_locked = False
        return game, holder, victim

    def test_gun_active_before_vote_starts(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game, holder, _ = self._setup_unused_gun(gm)
        self.assertTrue(ms_gn.mason_day_gun_available(game))
        self.assertEqual(ms_gn.mason_day_gun_holder_uid(game), holder.user_id)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(game.mason_intro_day_ability_locked)

    async def test_vote_start_clears_unused_gun_state(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game, holder, _ = self._setup_unused_gun(gm)
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ):
            await dismiss_mason_day_ability_panels(bot, game)
        self.assertIsNone(ms_gn.mason_day_gun_holder_uid(game))
        self.assertFalse(game.mason_day_gun_sabotaged)
        self.assertTrue(game.mason_day_gun_used)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertIsNone(game.mason_day_gun_shot_target_uid)
        self.assertTrue(game.mason_intro_day_ability_locked)

    async def test_vote_start_locks_gun_panel_without_buttons(self) -> None:
        gm = GameManager()
        game, holder, _ = self._setup_unused_gun(gm)
        bot = MagicMock()
        locked: list[tuple[int, str, object | None]] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append((uid, text, kb))

        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ):
            await expire_mason_day_gun_panel_at_vote_start(bot, game)

        gun_lock = next((row for row in locked if row[0] == holder.user_id), None)
        self.assertIsNotNone(gun_lock)
        _, text, kb = gun_lock
        self.assertEqual(text, MASON_DAY_GUN_EXPIRED_PANEL_FA)
        self.assertIsNone(kb)

    async def test_late_gun_callback_does_not_kill(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game, holder, victim = self._setup_unused_gun(gm)
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ):
            await dismiss_mason_day_ability_panels(bot, game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            new=AsyncMock(),
        ) as broadcast:
            await dispatch_mason_day_ability(
                cb,
                bot,
                game,
                gm,
                as_uid=holder.user_id,
                actor_uid=holder.user_id,
                act=MASON_DAY_GUN_PICK_ACT,
                tid=victim.user_id,
            )
        broadcast.assert_not_awaited()
        self.assertTrue(game.players[victim.user_id].is_alive)
        cb.answer.assert_awaited_once_with(
            MASON_DAY_GUN_EXPIRED_ALERT_FA,
            show_alert=True,
        )
        self.assertFalse(ms_gn.mason_day_gun_available(game))

    async def test_after_vote_holder_no_longer_has_gun(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game, holder, _ = self._setup_unused_gun(gm)
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ):
            await dismiss_mason_day_ability_panels(bot, game)
        self.assertIsNone(ms_gn.mason_day_gun_holder_uid(game))
        self.assertFalse(ms_gn.mason_day_gun_available(game))

    def test_gun_does_not_carry_to_next_day(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game, holder, _ = self._setup_unused_gun(gm)
        ms_gn.expire_mason_day_gun_for_vote_start(game)
        new_holder = _p(40, "Next", Role.TOWN_SIMPLE)
        gm.add_player(game, new_holder)
        game.mason_gunner_night_target_uid = new_holder.user_id
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        self.assertIsNone(ms_gn.mason_day_gun_holder_uid(game))
        self.assertFalse(ms_gn.mason_day_gun_available(game))
        self.assertTrue(ms_gn.mason_gun_is_spent(game))

    async def test_expire_skipped_when_gun_already_used(self) -> None:
        from bot.roles import mason_gunner as ms_gn

        gm = GameManager()
        game, holder, victim = self._setup_unused_gun(gm)
        result = ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        self.assertIsNotNone(result)
        before = (
            game.mason_day_gun_holder_uid,
            game.mason_day_gun_used,
            game.mason_gun_spent,
            game.mason_day_gun_shot_target_uid,
        )
        bot = MagicMock()
        locked: list[int] = []

        async def _capture(_bot, _game, ui_key, uid, text, kb):
            locked.append(uid)

        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_capture,
        ):
            expired_holder = ms_gn.expire_mason_day_gun_for_vote_start(game)
            await expire_mason_day_gun_panel_at_vote_start(bot, game)
        self.assertIsNone(expired_holder)
        self.assertEqual(
            (
                game.mason_day_gun_holder_uid,
                game.mason_day_gun_used,
                game.mason_gun_spent,
                game.mason_day_gun_shot_target_uid,
            ),
            before,
        )
        self.assertNotIn(holder.user_id, locked)

    async def test_late_confirm_callback_does_not_kill(self) -> None:
        gm = GameManager()
        game, holder, victim = self._setup_unused_gun(gm)
        game.mason_day_gun_shot_target_uid = victim.user_id
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            new=AsyncMock(),
        ):
            await dismiss_mason_day_ability_panels(bot, game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.mason_day_ability._eliminate_day_gun_shot",
            new=AsyncMock(),
        ) as elim:
            await dispatch_mason_day_ability(
                cb,
                bot,
                game,
                gm,
                as_uid=holder.user_id,
                actor_uid=holder.user_id,
                act=MASON_DAY_GUN_CONFIRM_ACT,
                tid=victim.user_id,
            )
        elim.assert_not_awaited()
        self.assertTrue(game.players[victim.user_id].is_alive)
        cb.answer.assert_awaited_once_with(
            MASON_DAY_GUN_EXPIRED_ALERT_FA,
            show_alert=True,
        )


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_bazpors_narrator_untouched_by_mason_gun_broadcast(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "bot"
        for rel in ("bazpors_narrator.py", "handlers/no_host_player.py"):
            text = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn("build_mason_day_gun_normal_shot_broadcast_html", text)
            self.assertNotIn("build_mason_day_gun_sabotaged_broadcast_html", text)
            self.assertNotIn("_eliminate_day_gun_shot", text)
            self.assertNotIn("expire_mason_day_gun_for_vote_start", text)
            self.assertNotIn("expire_mason_day_gun_panel_at_vote_start", text)

    def test_mozakere_descriptions_untouched(self) -> None:
        from bot.mozakere_role_descriptions import MOZAKERE_ROLE_DESCRIPTIONS_FA

        self.assertNotIn(Role.APACHE, MOZAKERE_ROLE_DESCRIPTIONS_FA)
        self.assertNotIn(Role.COWBOY, MOZAKERE_ROLE_DESCRIPTIONS_FA)

    def test_mozakere_modules_untouched_by_mason_gun_vote_expiry(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "bot"
        for rel in (
            "mozakere_role_descriptions.py",
            "roles/mozakere_doctor.py",
            "roles/mozakere_negotiator.py",
        ):
            path = root / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("expire_mason_day_gun_for_vote_start", text)
            self.assertNotIn("MASON_DAY_GUN_EXPIRED", text)
