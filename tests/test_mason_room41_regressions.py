"""رگرسیون باگ‌های Room 41 — تایم‌لاین، تفنگدار، مرگ ماسونی."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.main import _build_bazpors_timeline_html
from bot.mason_day_ability import (
    MASON_DAY_GUN_EXPIRED_PANEL_FA,
    _dispatch_mason_day_gun_panel,
    dispatch_mason_day_ability,
    expire_mason_day_gun_panel_at_vote_start,
)
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.models import Phase, Player, Role
from bot.post_game_flow import build_post_session_recap_snapshot
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_fraternity as ms_mf
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
    game.no_host_assistant_narrator_active = True
    return game


class MasonTimelineDayAbilityTests(unittest.TestCase):
    def test_apache_elim_no_vote_line(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_host_day = 2
        gm.add_player(game, _p(10, "Apache", Role.APACHE))
        gm.add_player(game, _p(20, "Victim", Role.DOCTOR))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            log_path = Path(f.name)
            f.write(
                json.dumps(
                    {
                        "event": "no_host.mason_apache_day",
                        "host_day": 2,
                        "target_uid": 20,
                        "apache_uid": 10,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "event": "player.eliminated",
                        "uid": 20,
                        "source": "eliminate_player",
                        "bazpors": {
                            "host_day": 2,
                            "night_count": 1,
                            "narrator_step": "day_discuss",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        game.audit_log_path = str(log_path)
        try:
            snap = build_post_session_recap_snapshot(game, "citizen")
            html = _build_bazpors_timeline_html(snap)
            self.assertIn("آپاچی", html)
            self.assertNotIn("به اتفاق آرا از بازی خارج شد", html)
        finally:
            log_path.unlink(missing_ok=True)

    def test_cowboy_elim_no_vote_line(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_host_day = 2
        gm.add_player(game, _p(11, "Cowboy", Role.COWBOY))
        gm.add_player(game, _p(21, "Victim", Role.SPY))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            log_path = Path(f.name)
            f.write(
                json.dumps(
                    {
                        "event": "no_host.mason_cowboy_day",
                        "host_day": 2,
                        "target_uid": 21,
                        "cowboy_uid": 11,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "event": "player.eliminated",
                        "uid": 21,
                        "source": "eliminate_player",
                        "bazpors": {
                            "host_day": 2,
                            "night_count": 1,
                            "narrator_step": "day_discuss",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        game.audit_log_path = str(log_path)
        try:
            snap = build_post_session_recap_snapshot(game, "citizen")
            html = _build_bazpors_timeline_html(snap)
            self.assertIn("کابوی", html)
            self.assertNotIn("به اتفاق آرا از بازی خارج شد", html)
        finally:
            log_path.unlink(missing_ok=True)

    def test_vote_elim_still_shown(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_host_day = 2
        gm.add_player(game, _p(30, "Voted", Role.TOWN_SIMPLE))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            log_path = Path(f.name)
            f.write(
                json.dumps(
                    {
                        "event": "no_host.day1_defense_elim_confirmed",
                        "host_day": 2,
                        "eliminated_uid": 30,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        game.audit_log_path = str(log_path)
        try:
            snap = build_post_session_recap_snapshot(game, "citizen")
            html = _build_bazpors_timeline_html(snap)
            self.assertIn("به اتفاق آرا از بازی خارج شد", html)
        finally:
            log_path.unlink(missing_ok=True)


class MasonGunnerDeliverySpentTests(unittest.IsolatedAsyncioTestCase):
    async def test_gun_spent_on_panel_delivery(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        self.assertFalse(ms_gn.mason_gun_is_spent(game))
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair",
            new=AsyncMock(),
        ):
            await _dispatch_mason_day_gun_panel(bot, game, gm)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))

    async def test_gunner_cannot_give_second_gun_after_delivery(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "H1", Role.TOWN_SIMPLE)
        other = _p(30, "H2", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, other)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair",
            new=AsyncMock(),
        ):
            await _dispatch_mason_day_gun_panel(bot, game, gm)
        game.bazpors_narrator_night_count = 2
        ms_gn.clear_mason_gunner_night_pick(game)
        self.assertFalse(ms_gn.commit_mason_gunner_target(game, gunner, other))

    def test_recipient_never_firing_keeps_gun_spent(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        ms_gn.expire_mason_day_gun_for_vote_start(game)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))

    def test_holder_death_after_delivery_does_not_restore_gun(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        holder.is_alive = False
        ms_gn.refresh_mason_day_gun_holder_if_eliminated(game)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))


class MasonDayGunSpentVsActiveTests(unittest.IsolatedAsyncioTestCase):
    """مصرف تفنگدار (mason_gun_spent) جدا از فعال بودن تفنگ روز (mason_day_gun_available)."""

    def _delivered_unused_gun(self, gm: GameManager):
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        victim = _p(30, "Victim", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, victim)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        game.mason_intro_day_ability_open = True
        game.mason_intro_day_ability_locked = False
        return game, gunner, holder, victim

    def test_delivery_spent_without_consuming_day_gun(self) -> None:
        gm = GameManager()
        game, _, holder, _ = self._delivered_unused_gun(gm)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertTrue(ms_gn.mason_day_gun_available(game))
        self.assertFalse(ms_gn.mason_day_gun_is_used(game))

    def test_holder_can_shoot_while_gunner_spent_before_vote(self) -> None:
        gm = GameManager()
        game, _, holder, victim = self._delivered_unused_gun(gm)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertTrue(
            ms_gn.mason_day_gun_holder_can_shoot(game, holder, victim)
        )
        result = ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        self.assertIsNotNone(result)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertTrue(ms_gn.mason_day_gun_is_used(game))

    def test_vote_start_expiry_runs_when_gunner_already_spent(self) -> None:
        gm = GameManager()
        game, _, holder, _ = self._delivered_unused_gun(gm)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        expired_holder = ms_gn.expire_mason_day_gun_for_vote_start(game)
        self.assertEqual(expired_holder, holder.user_id)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertTrue(ms_gn.mason_day_gun_is_used(game))
        self.assertIsNone(ms_gn.mason_day_gun_holder_uid(game))
        self.assertFalse(ms_gn.mason_day_gun_available(game))

    async def test_vote_start_disables_panel_when_gunner_already_spent(self) -> None:
        from bot.mason_day_ability import MASON_DAY_GUN_PICK_ACT

        gm = GameManager()
        game, _, holder, victim = self._delivered_unused_gun(gm)
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

    def test_expired_gun_does_not_carry_to_next_day_while_spent(self) -> None:
        gm = GameManager()
        game, gunner, holder, _ = self._delivered_unused_gun(gm)
        ms_gn.expire_mason_day_gun_for_vote_start(game)
        new_holder = _p(40, "Next", Role.TOWN_SIMPLE)
        gm.add_player(game, new_holder)
        game.mason_gunner_night_target_uid = new_holder.user_id
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertIsNone(ms_gn.mason_day_gun_holder_uid(game))
        self.assertFalse(ms_gn.mason_day_gun_available(game))
        self.assertFalse(ms_gn.commit_mason_gunner_target(game, gunner, new_holder))


class MasonCollapsePendingDeathTests(unittest.TestCase):
    def _room41_night1_game(self, gm: GameManager):
        game = _mason_game(gm, n=14)
        mason = _p(12, "Mason", Role.MASON)
        sab = _p(2, "Kaveh", Role.SABOTEUR)
        town = _p(14, "Hasan", Role.TOWN_SIMPLE)
        sniper = _p(8, "Sn", Role.SNIPER)
        cmd = _p(9, "Cmd", Role.COMMANDER)
        gm.add_player(game, mason)
        gm.add_player(game, sab)
        gm.add_player(game, town)
        gm.add_player(game, sniper)
        gm.add_player(game, cmd)
        ms_mf.initialize_mason_team_for_new_game(game)
        game.bazpors_narrator_night_count = 1
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        return game, mason, sab, town

    def test_mafia_recruit_then_sniper_kill_still_collapses(self) -> None:
        gm = GameManager()
        game, mason, sab, town = self._room41_night1_game(gm)
        ms_mf.commit_mason_recruit(game, mason, sab)
        ms_sn.commit_mason_sniper_night_selection(game, [sab.user_id])
        ms_cmd.commit_mason_commander_approval(game, [sab.user_id])
        apply_mason_night_resolution(game, gm)
        self.assertTrue(game.mason_last_night_had_collapse)
        self.assertFalse(mason.is_alive)
        self.assertFalse(sab.is_alive)

    def test_town_team_member_also_eliminated_on_collapse(self) -> None:
        gm = GameManager()
        game, mason, sab, town = self._room41_night1_game(gm)
        ms_mf.commit_mason_recruit(game, mason, town)
        ms_mf.clear_mason_recruit_night_state(game)
        ms_mf.commit_mason_recruit(game, mason, sab)
        ms_sn.commit_mason_sniper_night_selection(game, [sab.user_id])
        ms_cmd.commit_mason_commander_approval(game, [sab.user_id])
        apply_mason_night_resolution(game, gm)
        self.assertTrue(game.mason_last_night_had_collapse)
        self.assertFalse(mason.is_alive)
        self.assertFalse(town.is_alive)
        self.assertFalse(sab.is_alive)

    def test_spy_recruit_no_collapse_even_if_later_killed(self) -> None:
        gm = GameManager()
        game, mason, _, _ = self._room41_night1_game(gm)
        spy = _p(3, "Spy", Role.SPY)
        gm.add_player(game, spy)
        game.bazpors_alive_at_night_start[spy.user_id] = True
        ms_mf.commit_mason_recruit(game, mason, spy)
        ms_sn.commit_mason_sniper_night_selection(game, [spy.user_id])
        ms_cmd.commit_mason_commander_approval(game, [spy.user_id])
        apply_mason_night_resolution(game, gm)
        self.assertFalse(game.mason_last_night_had_collapse)

    def test_pending_death_mafia_counts_for_collapse_detection(self) -> None:
        gm = GameManager()
        game, mason, sab, _ = self._room41_night1_game(gm)
        ms_mf.commit_mason_recruit(game, mason, sab)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertTrue(result.collapsed)
        self.assertEqual(result.pending_recruit_uid, sab.user_id)

    def test_dead_at_night_start_recruit_no_collapse(self) -> None:
        gm = GameManager()
        game, mason, _, _ = self._room41_night1_game(gm)
        mafia = _p(30, "Boss", Role.GODFATHER)
        gm.add_player(game, mafia)
        game.bazpors_alive_at_night_start[mafia.user_id] = False
        mafia.is_alive = False
        game.mason_pending_recruit_uid = mafia.user_id
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)


class Room41NightStuckAfterGunSpentTests(unittest.TestCase):
    """Room 41 — پس از تحویل تفنگ، تفنگدار نباید روی پنل انتظار عمومی گیر کند."""

    def _room41_night_after_gun_delivery(self, gm: GameManager):
        from bot.bazpors_narrator import NIGHT_START

        game = _mason_game(gm, n=14)
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 2
        game.no_host_night_parallel_collect_active = True
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 900
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.mason_gun_spent = True
        game.mason_day_gun_used = True
        game.mason_day_gun_holder_uid = None

        gm.add_player(game, _p(2, "Kaveh", Role.SABOTEUR))
        gm.add_player(game, _p(10, "Gn", Role.GUNMAN))
        gm.add_player(game, _p(1, "Boss", Role.GODFATHER))
        gm.add_player(game, _p(30, "Town", Role.TOWN_SIMPLE))
        return game

    def test_gunner_unconfirmed_does_not_block_wait_ok_when_gun_spent(self) -> None:
        from bot.mason_night_ready import _gunner_ready, _waiters_ready

        gm = GameManager()
        game = self._room41_night_after_gun_delivery(gm)
        game.mason_night_gunner_confirmed = False
        game.mason_night_saboteur_confirmed = True
        game.mason_night_wait_ok_uids = [30]

        self.assertTrue(_gunner_ready(game))
        self.assertTrue(_waiters_ready(game))

    def test_explain_shows_saboteur_ok_not_false_gunner_skip(self) -> None:
        from bot.mason_night_ready import explain_mason_night_stuck

        gm = GameManager()
        game = self._room41_night_after_gun_delivery(gm)
        game.mason_night_saboteur_confirmed = False
        game.mason_night_gunner_confirmed = False
        game.mason_night_wait_ok_uids = [30]

        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Saboteur", report)
        self.assertIn("mason_night_saboteur_confirmed = False", report)
        self.assertIn("خرابکار — اوکی", report)
        self.assertNotIn("Gunner cannot give gun, skipped", report)
        self.assertNotIn("Gn: alive — needs generic wait-panel", report)

    def test_night_ready_after_saboteur_ok_without_gunner_wait_ok(self) -> None:
        from bot.mason_night_ready import all_mason_parallel_night_ready

        gm = GameManager()
        game = self._room41_night_after_gun_delivery(gm)
        game.mason_night_saboteur_confirmed = True
        game.mason_night_gunner_confirmed = False
        game.mason_night_wait_ok_uids = [30]

        self.assertTrue(all_mason_parallel_night_ready(game))

    def test_dead_saboteur_does_not_block_after_gun_spent(self) -> None:
        from bot.mason_night_ready import all_mason_parallel_night_ready, explain_mason_night_stuck

        gm = GameManager()
        game = self._room41_night_after_gun_delivery(gm)
        game.players[2].is_alive = False
        game.mason_night_saboteur_confirmed = False
        game.mason_night_gunner_confirmed = False
        game.mason_night_wait_ok_uids = [30]

        self.assertTrue(all_mason_parallel_night_ready(game))
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Saboteur is dead, skipped", report)


class Room41NightStuckFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_saboteur_ok_unblocks_night_after_gun_spent(self) -> None:
        from bot.bazpors_narrator import NIGHT_START
        from bot.mason_night_ready import all_mason_parallel_night_ready
        from bot.mason_night_role import MSB_OK, dispatch_mason_night_role

        gm = GameManager()
        game = _mason_game(gm, n=14)
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 2
        game.no_host_night_parallel_collect_active = True
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 900
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_shot_done = True
        game.mason_gun_spent = True
        gm.add_player(game, _p(2, "Kaveh", Role.SABOTEUR))
        gm.add_player(game, _p(10, "Gn", Role.GUNMAN))
        gm.add_player(game, _p(1, "Boss", Role.GODFATHER))
        gm.add_player(game, _p(30, "Town", Role.TOWN_SIMPLE))
        game.mason_night_gunner_confirmed = False
        game.mason_night_wait_ok_uids = [30]

        self.assertFalse(all_mason_parallel_night_ready(game))

        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            finish,
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=2, actor_uid=2, act=MSB_OK, tid=0
            )

        self.assertTrue(game.mason_night_saboteur_confirmed)
        self.assertTrue(all_mason_parallel_night_ready(game))
        finish.assert_awaited()
