#!/usr/bin/env python3
"""Live eliminated-player reports — every `گزارش بازی` press rebuilds the
cumulative report from the latest committed history (all scenarios).

Per scenario (mason / bazpors / mozakere / russian_mafia / nam10):
1. Eliminate a player (real flow or real audit event).
2. Press the report button -> report through the then-current history.
3. Commit later events (real night resolution records / real day-2
   elimination records).
4. Press the SAME button again -> the report includes BOTH the old and
   the newly committed history (cumulative, never frozen at elimination).
5. Authorisation, observer access and read-only semantics preserved.
"""

import os
import sys
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_bazpors_elim_report as _bzn
import tests.test_mason_elim_report as _msn
import tests.test_mozakere_elim_report as _mzk
import tests.test_namayande10_day1_elim_report as _nm10
import tests.test_russian_mafia_elim_report as _rmi
from bot.models import Role

_HANDLERS = {
    "mason": (
        _msn,
        "bot.mason_elim_report",
        "handle_mason_elim_report_callback",
        "deliver_mason_elim_report_chunks",
    ),
    "bazpors": (
        _bzn,
        "bot.bazpors_elim_report",
        "handle_bazpors_elim_report_callback",
        "deliver_bazpors_elim_report_chunks",
    ),
    "mozakere": (
        _mzk,
        "bot.mozakere_elim_report",
        "handle_mozakere_elim_report_callback",
        "deliver_mozakere_elim_report_chunks",
    ),
    "russian_mafia": (
        _rmi,
        "bot.russian_mafia_elim_report",
        "handle_russian_mafia_elim_report_callback",
        "deliver_russian_mafia_elim_report_chunks",
    ),
    "nam10": (
        _nm10,
        "bot.nam10.no_host_elim_report",
        "handle_nam10_elim_report_callback",
        "deliver_nam10_elim_report_chunks",
    ),
}


async def press_report(key, game, actor, as_uid, gts):
    """Press the report button through the REAL handler; return html."""
    mod, modname, hname, dname = _HANDLERS[key]
    import importlib

    bot_mod = importlib.import_module(modname)
    handler = getattr(bot_mod, hname)
    cb = MagicMock()
    cb.from_user = MagicMock(id=actor)
    with mock.patch(
        f"{modname}.safe_callback_answer", new=AsyncMock()
    ), mock.patch(
        f"{modname}.{dname}", new=AsyncMock(return_value=True)
    ) as deliver:
        await handler(cb, AsyncMock(), game, as_uid=as_uid, gts=gts)
        if deliver.await_args is None:
            return None
        return deliver.await_args.args[2]


def _audit_line_count(game) -> int:
    with open(game.audit_log_path, encoding="utf-8") as f:
        return len([x for x in f if x.strip()])


class _LiveSkip(type):
    """Shadow inherited test methods so only subclass tests run."""

    def __new__(mcls, name, bases, ns):
        own = set(ns)
        for base_cls in bases:
            for attr in [a for a in vars(base_cls) if a.startswith("test_")]:
                if attr not in own:
                    ns[attr] = None
        return super().__new__(mcls, name, bases, ns)


# ---------------------------------------------------------------------
# Mason
# ---------------------------------------------------------------------
class MasonLiveReportTests(_msn.MasonElimReportCoreTests, metaclass=_LiveSkip):
    def _seed_day1_elim(self, game):
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=70,
            source="day_vote",
            bazpors={
                "host_day": 1,
                "night_count": 0,
                "narrator_step": "day_discuss",
            },
        )
        game.players[70].is_alive = False
        entry = _msn.capture_mason_elim_report_cutoff(game, self.gm, 70)
        assert entry is not None
        return entry

    async def test_report_fresh_cumulative_on_every_press(self):
        game = self._mason()
        entry = self._seed_day1_elim(game)
        gts = entry["game_created_ts"]

        first = await press_report("mason", game, 70, 70, gts)
        self.assertIn("روز ۱", first)
        self.assertNotIn("شب ۲", first)

        # Night 2 resolves (real committed night record).
        from bot.game_audit_log import log_event

        log_event(
            game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🔴 شات مافیا: Det"
            ),
            mason_final_outcome={
                "night": 2,
                "day": 2,
                "day_elim_uids": [],
                "night_elim_uids": [30],
                "finalized": True,
            },
            bazpors={"night_count": 2, "host_day": 2},
        )
        game.players[30].full_name = "CHANGED_LATER"

        second = await press_report("mason", game, 70, 70, gts)
        self.assertNotEqual(first, second)
        self.assertIn("روز ۱", second)  # cumulative: earlier history kept
        self.assertIn("شب ۲", second)  # newly completed night included
        self.assertIn("CHANGED_LATER", second)

        # Night 3 resolves: the same button covers the full chain.
        log_event(
            game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🔴 خشن: Arm"
            ),
            mason_final_outcome={
                "night": 3,
                "day": 3,
                "day_elim_uids": [],
                "night_elim_uids": [],
                "finalized": True,
            },
            bazpors={"night_count": 3, "host_day": 3},
        )
        lines_before = _audit_line_count(game)
        third = await press_report("mason", game, 70, 70, gts)
        self.assertIn("شب ۳", third)
        self.assertIn("شب ۲", third)
        self.assertIn("روز ۱", third)

        # Read-only: presses never touch the audit trail or game state.
        self.assertEqual(_audit_line_count(game), lines_before)
        self.assertFalse(game.players[70].is_alive)
        self.assertTrue(game.roles_dealt)

    async def test_authorization_and_observer_access_preserved(self):
        game = self._mason()
        entry = self._seed_day1_elim(game)
        gts = entry["game_created_ts"]
        # authorised: the eliminated player himself
        self.assertIsNotNone(
            await press_report("mason", game, 70, 70, gts)
        )
        # authorised: the registered observer
        self.assertIsNotNone(
            await press_report("mason", game, 900, 70, gts)
        )
        # rejected: a living player
        living = next(p.user_id for p in game.players.values() if p.is_alive)
        self.assertIsNone(
            await press_report("mason", game, living, 70, gts)
        )
        # rejected: another actor (not the owner, not the observer)
        self.assertIsNone(await press_report("mason", game, 30, 70, gts))
        # rejected: stale gts (foreign room generation)
        self.assertIsNone(
            await press_report("mason", game, 70, 70, gts + 12345)
        )


# ---------------------------------------------------------------------
# Bazpors
# ---------------------------------------------------------------------
class BazporsLiveReportTests(
    _bzn.BazporsElimReportCoreTests, metaclass=_LiveSkip
):
    async def test_report_fresh_cumulative_on_every_press(self):
        game = self._bazpors()
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=60,
            source="day_vote",
            bazpors={
                "host_day": 1,
                "night_count": 0,
                "narrator_step": "day_discuss",
            },
        )
        game.players[60].is_alive = False
        entry = _bzn.capture_bazpors_elim_report_cutoff(game, self.gm, 60)
        assert entry is not None
        gts = entry["game_created_ts"]

        first = await press_report("bazpors", game, 60, 60, gts)
        self.assertIn("روز ۱", first)
        self.assertNotIn("شب ۲", first)

        log_event(
            game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🔴 شات مافیا: Det"
            ),
            bazpors={"night_count": 2, "host_day": 2},
        )
        game.players[30].full_name = "CHANGED_LATER"
        second = await press_report("bazpors", game, 60, 60, gts)
        self.assertNotEqual(first, second)
        self.assertIn("روز ۱", second)
        self.assertIn("شب ۲", second)
        self.assertIn("CHANGED_LATER", second)

        log_event(
            game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🔴 خشن: Arm"
            ),
            bazpors={"night_count": 3, "host_day": 3},
        )
        lines_before = _audit_line_count(game)
        third = await press_report("bazpors", game, 60, 60, gts)
        self.assertIn("شب ۳", third)
        self.assertIn("شب ۲", third)

        # observer mirror still authorised
        self.assertIsNotNone(
            await press_report("bazpors", game, 900, 60, gts)
        )


# ---------------------------------------------------------------------
# Mozakere
# ---------------------------------------------------------------------
class MozakereLiveReportTests(
    _mzk.MozakereElimReportCoreTests, metaclass=_LiveSkip
):
    async def test_report_fresh_cumulative_on_every_press(self):
        game = self._mozakere()
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=60,
            source="day_vote",
            bazpors={
                "host_day": 1,
                "night_count": 0,
                "narrator_step": "day_discuss",
            },
        )
        game.players[60].is_alive = False
        entry = _mzk.capture_mozakere_elim_report_cutoff(game, self.gm, 60)
        assert entry is not None
        gts = entry["game_created_ts"]

        first = await press_report("mozakere", game, 60, 60, gts)
        self.assertIn("روز ۱", first)
        self.assertNotIn("شب ۲", first)

        log_event(
            game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🔴 شات مافیا: Det"
            ),
            bazpors={"night_count": 2, "host_day": 2},
        )
        game.players[30].full_name = "CHANGED_LATER"
        second = await press_report("mozakere", game, 60, 60, gts)
        self.assertNotEqual(first, second)
        self.assertIn("روز ۱", second)
        self.assertIn("شب ۲", second)
        self.assertIn("CHANGED_LATER", second)

        log_event(
            game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🔴 خشن: Arm"
            ),
            bazpors={"night_count": 3, "host_day": 3},
        )
        lines_before = _audit_line_count(game)
        third = await press_report("mozakere", game, 60, 60, gts)
        self.assertIn("شب ۳", third)
        self.assertIn("شب ۲", third)


# ---------------------------------------------------------------------
# Russian Mafia
# ---------------------------------------------------------------------
class RussianMafiaLiveReportTests(
    _rmi.RussianMafiaElimReportTests, metaclass=_LiveSkip
):
    async def test_report_fresh_cumulative_on_every_press(self):
        game = self._game()
        citizens = [
            p.user_id for p in game.players.values() if p.role == Role.CITIZEN
        ]
        _rmi.record_russian_elimination(game, citizens[0], source="day_vote")
        entry = _rmi.capture_russian_mafia_elim_report_cutoff(
            game, self.gm, citizens[0]
        )
        assert entry is not None
        gts = entry["game_created_ts"]
        name1 = game.players[citizens[0]].full_name
        name2 = game.players[citizens[1]].full_name
        name3 = game.players[citizens[2]].full_name

        def exit_line(name):
            return f"خروج روز: {name}"

        first = await press_report(
            "russian_mafia", game, citizens[0], citizens[0], gts
        )
        self.assertIn(exit_line(name1), first)
        self.assertNotIn(exit_line(name2), first)

        # Day 2 (after Night 1): a further real day-vote elimination.
        game.russian_mafia_day_index = 2
        _rmi.record_russian_elimination(game, citizens[1], source="day_vote")
        second = await press_report(
            "russian_mafia", game, citizens[0], citizens[0], gts
        )
        self.assertNotEqual(first, second)
        self.assertIn(exit_line(name1), second)  # history kept
        self.assertIn(exit_line(name2), second)  # latest included

        # Day 3 elimination: the full cumulative chain through Day 3.
        game.russian_mafia_day_index = 3
        _rmi.record_russian_elimination(game, citizens[2], source="day_vote")
        third = await press_report(
            "russian_mafia", game, citizens[0], citizens[0], gts
        )
        self.assertIn(exit_line(name1), third)
        self.assertIn(exit_line(name2), third)
        self.assertIn(exit_line(name3), third)

        # Authorisation unchanged: observer yes, living player no.
        self.assertIsNotNone(
            await press_report(
                "russian_mafia", game, 900, citizens[0], gts
            )
        )
        living = next(p.user_id for p in game.players.values() if p.is_alive)
        self.assertIsNone(
            await press_report(
                "russian_mafia", game, living, citizens[0], gts
            )
        )


# ---------------------------------------------------------------------
# Namayande 10/11/12/13
# ---------------------------------------------------------------------
class Nam10LiveReportTests(_nm10.Nam10Day1ElimReportTest, metaclass=_LiveSkip):
    async def test_report_fresh_cumulative_on_every_press(self):
        from bot.game_audit_log import log_event

        self._fork_room()
        # Day-1 outcome: real flow eliminates the target-vote loser.
        await self._walk_to_outcome(t1=907, t2=_nm10.SYN_UID)
        await self._press(_nm10.ASSIST_UID, "d1o2", _nm10.ASSIST_UID)
        cutoffs = self.game.nmnd_elim_report_cutoffs
        self.assertTrue(cutoffs, "day-1 outcome must capture cutoffs")
        victim = next(iter(cutoffs))
        entry = cutoffs[victim]
        gts = entry["game_created_ts"]

        first = await press_report("nam10", self.game, victim, victim, gts)
        self.assertIsNotNone(first)
        self.assertIn("روز ۱", first)
        self.assertNotIn("شات مافیا", first)
        self.assertNotIn("شب ۲", first)

        # Night 1 completes (real committed night-resolved record).
        log_event(
            self.game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🔴 شات مافیا: بازیکن 9"
            ),
            bazpors={"night_count": 1, "host_day": 2},
        )
        second = await press_report("nam10", self.game, victim, victim, gts)
        self.assertNotEqual(first, second)
        self.assertIn("شات مافیا: بازیکن 9", second)

        # Night 2 completes: cumulative through Night 2.
        log_event(
            self.game,
            "night.resolved",
            night_report_html=(
                "<b>گزارش کامل شب گذشته</b>\n🛡️ نجات: بازیکن 8"
            ),
            bazpors={"night_count": 2, "host_day": 3},
        )
        third = await press_report("nam10", self.game, victim, victim, gts)
        self.assertIn("شات مافیا: بازیکن 9", third)
        self.assertIn("نجات: بازیکن 8", third)

        # Access rules preserved: observer yes, living players no.
        self.assertIsNotNone(
            await press_report(
                "nam10", self.game, _nm10.OBS_UID, victim, gts
            )
        )
        alive = next(
            uid
            for uid, p in self.game.players.items()
            if p.is_alive and uid != _nm10.OBS_UID
        )
        self.assertIsNone(
            await press_report("nam10", self.game, alive, victim, gts)
        )


if __name__ == "__main__":
    unittest.main()
