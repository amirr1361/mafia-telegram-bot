#!/usr/bin/env python3
"""Namayande — native button colour contract (blue/red/green).

Contract under test (Namayande only, cosmetic — callbacks, authorisation,
selection limits and flows are unchanged):
- Unselected actionable options: BLUE (primary)
- Selected options: RED (danger), incl. replacement & deselect
- Final confirmations: GREEN (success)
- Hacker «⏭️ مرحله بعد»: GREEN (success); never a premature completion.
- Other scenarios (Bazpors / Mozakere): these helpers leave buttons unstyled.

Task §6 item coverage:
- 1  green confirms here + real-flow tests
- 2  blue initial options here + real-flow/config tests
- 3  red selected here + real-flow tests
- 4  deselect & replacement here (builder) + real-flow tests
- 5  multi-selected red: covered by tests.test_namayande10_day1_representative
     (two simultaneous selections) — suite updated to the new contract
- 6  exactly one confirmation per panel: real-flow/config tests
- 7  hacker «مرحله بعد» green: hacker tests + config sweep
- 8  hacker navigation works unchanged: hacn press → stage 2
- 9  hacker not prematurely READY after «مرحله بعد»: state assertions
- 10 colours after panel editing + observer mirroring: shot mirror test
- 11 all 10/11/12/13 configurations: config sweep
- 12 other scenarios unchanged: cross-scenario helper tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup  # noqa: E402

from bot.models import Game, Player, Role  # noqa: E402
from bot.nam10.no_host_role_pick_common import (  # noqa: E402
    apply_bazpors_panel_styles,
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
)
from bot.nam10.semi_auto_role_pick_common import (  # noqa: E402
    build_narrator_confirm_back_rows,
    build_narrator_pick_rows,
)
from bot.observer_delivery import PlayerMirrorCb  # noqa: E402
import tests.test_namayande10_expansion as _exp  # noqa: E402
from tests.test_namayande10_night_publish import (  # noqa: E402
    _SkipInheritedTests,
)
from tests.test_namayande10_night_v2 import (  # noqa: E402
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    OBS_UID,
    SHIAD_UID,
    SYN_UID,
)

HACK_1 = "مرحله ۱ از ۲"
HACK_2 = "مرحله ۲ از ۲"
GUARD_MARK = "انتخاب محافظ"
GUARD_PICK_ACT = "gdnp"
DOCTOR_MARK = "انتخاب پزشک"
DOCTOR_PICK_ACT = "docp"
DOC_PICK_UID = DOC_UID
NEXT_TEXT = "مرحله بعد"
HAC_NEXT_ACT = "hacn"
CONFIRM_TEXT = "✅ تأیید"
SHOT_MARK = "انتخاب هدف شات"
BOSS_ASSIST_UID = 80012

PRIMARY = "primary"
DANGER = "danger"
SUCCESS = "success"


def _btn_styles(kb):
    return [getattr(b, "style", None) for row in kb.inline_keyboard for b in row]


def _iter_kb_buttons(kb):
    for row in kb.inline_keyboard:
        for b in row:
            yield b


def _act_style_map(kb):
    """{(act, tid): style} for every PlayerMirrorCb button in a keyboard."""
    out = {}
    if kb is None:
        return out
    for b in _iter_kb_buttons(kb):
        if not (b.callback_data or ""):
            continue
        try:
            cb = PlayerMirrorCb.unpack(b.callback_data)
        except Exception:
            continue
        if cb is not None:
            out[(cb.act, cb.tid)] = getattr(b, "style", None)
    return out


def _styles_for_act(kb, act):
    return {
        tid: style
        for (a, tid), style in _act_style_map(kb).items()
        if a == act
    }


def _act_from_btn(btn):
    try:
        return PlayerMirrorCb.unpack(btn.callback_data or "").act
    except Exception:
        return None


class _SkipAllInheritedTests(_SkipInheritedTests):
    """Shadow inherited test methods across the whole base MRO."""

    def __new__(mcls, name, bases, ns):
        own = set(ns)
        add = []
        for base_cls in bases:
            for ancestor in base_cls.__mro__:
                for attr in [a for a in vars(ancestor) if a.startswith("test_")]:
                    if attr not in own:
                        own.add(attr)
                        add.append(attr)
        for attr in add:
            ns[attr] = None
        return super().__new__(mcls, name, bases, ns)


# ===========================================================================
# Real-flow tests (night-v2 panels through the real aiogram dispatcher)
# ===========================================================================


class _MarkKbMixin:
    """Latest-named-panel keyboard extraction from the recording bot."""

    def _latest_mark_kb(self, mark, chat_id=None):
        chunks = []
        for rec in self.bot.calls:
            tname = type(rec).__name__
            cls = getattr(rec, "_cls", None)
            if tname in ("SendMessage", "EditMessageText"):
                chat = getattr(rec, "chat_id", None)
                text = getattr(rec, "text", "") or ""
                kb = getattr(rec, "reply_markup", None)
            elif cls in ("send_message", "edit_message_text", "edit_text"):
                args = getattr(rec, "_rec_args", ())
                kw = getattr(rec, "_rec_kwargs", {}) or {}
                chat = kw.get("chat_id", args[0] if args else None)
                text = kw.get("text", args[1] if len(args) > 1 else "") or ""
                kb = kw.get("reply_markup", args[3] if len(args) > 3 else None)
            else:
                continue
            if kb is not None and mark in text and (
                chat_id is None or chat == chat_id
            ):
                chunks.append(kb)
        return chunks[-1] if chunks else None


class NamButtonStyleRealFlowTests(
    _MarkKbMixin, _exp.NamExpansionRoomTest, metaclass=_SkipAllInheritedTests
):
    """Native button colours on live night-v2 panels (10-player room)."""

    async def test_shot_panel_blue_red_replacement_and_observer_mirror(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        # Item 2: all targets initially blue
        styles = self._shot_button_styles()
        self.assertTrue(styles)
        self.assertTrue(all(s == PRIMARY for s in styles.values()), styles)
        # Item 3: selecting turns the target red
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=DOC_UID)
        styles = self._shot_button_styles()
        self.assertEqual(styles.get(DOC_UID), DANGER)
        self.assertTrue(
            all(s == PRIMARY for u, s in styles.items() if u != DOC_UID)
        )
        # Item 10: the observer mirror copy shows identical colours
        obs = _styles_for_act(
            self._latest_mark_kb(SHOT_MARK, OBS_UID), "sht"
        )
        self.assertEqual(obs.get(DOC_UID), DANGER)
        self.assertTrue(all(s == PRIMARY for s in obs.values() if s != DANGER))
        self.assertEqual(
            {u for u, s in obs.items() if s == DANGER}, {DOC_UID}
        )
        # Item 4: replacement — previous red returns to blue, new red
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        styles = self._shot_button_styles()
        self.assertEqual(styles.get(CIT1_UID), DANGER)
        self.assertEqual(styles.get(DOC_UID), PRIMARY)
        self.assertEqual(
            [u for u, s in styles.items() if s == DANGER], [CIT1_UID]
        )
        # Styling presses did not commit anything
        self.assertIsNone(self.game.nmnd_night2_shot_target_uid)

    async def test_hacker_stage1_options_blue_red_deselect_next_green(self):
        self._fork_room()
        await self._enter_night()
        kb = self._latest_mark_kb(HACK_1)
        self.assertIsNotNone(kb)
        hacp = _styles_for_act(kb, "hacp")
        self.assertTrue(len(hacp) >= 2)  # town pool: Boss/Rebel excluded
        self.assertTrue(all(s == PRIMARY for s in hacp.values()))
        # Item 7: exactly one green «⏭️ مرحله بعد» progression button
        nexts = [
            b
            for b in _iter_kb_buttons(kb)
            if _act_from_btn(b) == HAC_NEXT_ACT
        ]
        self.assertEqual(len(nexts), 1)
        self.assertEqual(getattr(nexts[0], "style", None), SUCCESS)
        self.assertIn(NEXT_TEXT, nexts[0].text)
        # Item 3: selection red; single-selection replacement red
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        hacp = _styles_for_act(self._latest_mark_kb(HACK_1), "hacp")
        self.assertEqual(hacp[DOC_UID], DANGER)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        hacp = _styles_for_act(self._latest_mark_kb(HACK_1), "hacp")
        self.assertEqual(hacp[CIT1_UID], DANGER)
        self.assertEqual(hacp[DOC_UID], PRIMARY)
        # Item 4: deselect restores blue
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        hacp = _styles_for_act(self._latest_mark_kb(HACK_1), "hacp")
        self.assertTrue(all(s == PRIMARY for s in hacp.values()))

    async def test_hacker_next_green_navigation_not_prematurely_done(self):
        self._fork_room()
        await self._enter_night()
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        # Item 8: Hacker next-stage navigation keeps working unchanged
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        self.assertEqual(self.game.nmnd_night2_hacker_stage, "dst")
        # Item 9: «مرحله بعد» alone does NOT mark the action committed
        self.assertEqual(self.game.nmnd_night2_hacker_uids, [])
        kb = self._latest_mark_kb(HACK_2)
        self.assertIsNotNone(kb)
        # Stage 2 has no duplicated «مرحله بعد»; exactly one green confirm
        self.assertEqual(
            [b for b in _iter_kb_buttons(kb) if NEXT_TEXT in b.text], []
        )
        confirms = [b for b in _iter_kb_buttons(kb) if b.text == CONFIRM_TEXT]
        self.assertEqual(len(confirms), 1)
        self.assertEqual(getattr(confirms[0], "style", None), SUCCESS)
        # Item 2/3: stage-2 targets blue → red on selection
        hacp = _styles_for_act(kb, "hacp")
        self.assertTrue(hacp)
        self.assertTrue(all(s == PRIMARY for s in hacp.values()))
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        hacp = _styles_for_act(self._latest_mark_kb(HACK_2), "hacp")
        self.assertEqual(hacp[SYN_UID], DANGER)
        self.assertTrue(all(s == PRIMARY for u, s in hacp.items() if u != SYN_UID))
        # The final green confirm completes the Hacker action
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        self.assertEqual(self.game.nmnd_night2_hacker_uids, [DOC_UID, SYN_UID])

    async def test_role_panels_green_confirm_blue_options(self):
        self._fork_room()
        await self._enter_night()
        for mark, pick_act in (
            (GUARD_MARK, GUARD_PICK_ACT),
            (DOCTOR_MARK, DOCTOR_PICK_ACT),
        ):
            kb = self._latest_mark_kb(mark)
            self.assertIsNotNone(kb, mark)
            confirms = [b for b in _iter_kb_buttons(kb) if b.text == CONFIRM_TEXT]
            # Item 6: exactly one final confirmation per panel
            self.assertEqual(len(confirms), 1, mark)
            # Item 1: final confirmation green
            self.assertEqual(getattr(confirms[0], "style", None), SUCCESS, mark)
            # Item 2: pick options blue
            self.assertEqual(
                set(_styles_for_act(kb, pick_act).values()), {PRIMARY}, mark
            )

    async def test_boss_menu_options_unselected_blue(self):
        self._fork_room()
        await self._enter_night()
        kb = self._latest_mark_kb("رئیس مافیا")
        self.assertIsNotNone(kb)  # boss capability menu sent at night start
        styles = set(
            getattr(b, "style", None)
            for b in _iter_kb_buttons(kb)
            if b.callback_data
        )
        self.assertEqual(styles, {PRIMARY})


# ===========================================================================
# Config sweep (item 11): identical contract on 10/11/12/13 rooms
# ===========================================================================


class NamButtonStyleConfigSweepTests(
    _MarkKbMixin, _exp.NamExpansionRoomTest, metaclass=_SkipAllInheritedTests
):
    def _fork11(self):
        """11-player room: classic roster + one extra soldier seat."""
        from bot.game_audit_log import init_audit_log
        from bot.models import Phase, Player
        from bot.nam10.nmnd_narrator import Role

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=11,
            nam10_no_host=True,
        )
        assert game is not None
        roster = [
            BOSS_UID, 912, SHIAD_UID, _exp.SOL_UID, 904,
            905, 906, DOC_UID, 908, CIT1_UID, SYN_UID,
        ]
        team_map = {
            BOSS_UID: Role.MAFIA_BOSS,
            912: Role.NATO,
            SHIAD_UID: Role.SHIAD,
            _exp.SOL_UID: Role.SOLDIER,
            904: Role.HUNTER,
            905: Role.INTERROGATOR,
            906: Role.DETECTIVE,
            DOC_UID: Role.DOCTOR,
            908: Role.RUINTAN,
            CIT1_UID: Role.CITIZEN,
            SYN_UID: Role.CITIZEN,
        }
        seat = 0
        for uid in roster:
            seat += 1
            err = self.manager.add_player(
                game,
                Player(
                    user_id=uid,
                    full_name=f"بازیکن {seat}",
                    username=None,
                    role=None,
                    is_alive=True,
                    seat=seat,
                ),
            )
            assert err is None, err
        for uid, pl in game.players.items():
            pl.role = team_map[uid]
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = BOSS_ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nam10_intro_night_started = True
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_night_count = 1
        game.observer_user_id = OBS_UID
        game.observer_prompt_status = "registered"
        init_audit_log(game)
        self.game = game

    def _fork13(self):
        self._fork12(players_13=True)

    async def test_all_configs_night_start_button_styles(self):
        for builder in (self._fork_room, self._fork11, self._fork12, self._fork13):
            builder()
            await self._enter_night()
            # Hacker stage 1: blue pool + exactly one green «مرحله بعد»
            kb = self._latest_mark_kb(HACK_1)
            self.assertIsNotNone(kb, builder.__name__)
            nexts = [b for b in _iter_kb_buttons(kb) if _act_from_btn(b) == HAC_NEXT_ACT]
            self.assertEqual(len(nexts), 1, builder.__name__)
            self.assertEqual(getattr(nexts[0], "style", None), SUCCESS, builder.__name__)
            self.assertEqual(
                set(_styles_for_act(kb, "hacp").values()), {PRIMARY}, builder.__name__
            )
            # Guard/Doctor: blue options + single green confirmation
            for mark, pick_act in ((GUARD_MARK, GUARD_PICK_ACT), (DOCTOR_MARK, DOCTOR_PICK_ACT)):
                kb2 = self._latest_mark_kb(mark)
                self.assertIsNotNone(kb2, f"{mark} in {builder.__name__}")
                confirms = [b for b in _iter_kb_buttons(kb2) if b.text == CONFIRM_TEXT]
                self.assertEqual(len(confirms), 1, f"{mark} {builder.__name__}")
                self.assertEqual(getattr(confirms[0], "style", None), SUCCESS)
                self.assertEqual(
                    set(_styles_for_act(kb2, pick_act).values()),
                    {PRIMARY},
                    f"{mark} {builder.__name__}",
                )


# ===========================================================================
# Builder-level tests for the central helpers
# ===========================================================================


def _bp(uid, seat, name):
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=Role.CITIZEN,
        seat=seat,
        is_alive=True,
    )


def _model_game(scenario_name, code="77"):
    return Game(
        room_code=code,
        host_id=9301,
        scenario_name=scenario_name,
        players={
            1: _bp(1, 1, "بازیکن یک"),
            2: _bp(2, 2, "بازیکن دو"),
            3: _bp(3, 3, "بازیکن سه"),
        },
    )


class _SkipAllInheritedTests(_SkipInheritedTests):
    """Shadow inherited test methods across the whole base MRO."""

    def __new__(mcls, name, bases, ns):
        own = set(ns)
        add = []
        for base_cls in bases:
            for ancestor in base_cls.__mro__:
                for attr in [a for a in vars(ancestor) if a.startswith("test_")]:
                    if attr not in own:
                        own.add(attr)
                        add.append(attr)
        for attr in add:
            ns[attr] = None
        return super().__new__(mcls, name, bases, ns)


class CentralHelperButtonStylesTests(unittest.TestCase):
    """Namayande contract on the central no-host role-panel helpers."""

    def setUp(self):
        self.game = _model_game("namayande")
        self.pool = list(self.game.players.values())

    def test_pick_keyboard_blue_unselected_red_selected(self):
        # Item 2: unselected options blue
        kb = build_pick_keyboard(self.game, 1, pick_act="xtp", players=self.pool)
        self.assertEqual(set(_btn_styles(kb)), {PRIMARY})
        # Item 3: selected option red
        kb2 = build_pick_keyboard(
            self.game, 1, pick_act="xtp", players=self.pool, selected_uids=[2]
        )
        self.assertEqual(_styles_for_act(kb2, "xtp")[2], DANGER)
        self.assertTrue(
            all(
                s == PRIMARY
                for t, s in _styles_for_act(kb2, "xtp").items()
                if t != 2
            )
        )
        # Item 4: builder-level replacement (new red, previous blue)
        kb3 = build_pick_keyboard(
            self.game, 1, pick_act="xtp", players=self.pool, selected_uids=[3]
        )
        self.assertEqual(_styles_for_act(kb3, "xtp")[3], DANGER)
        self.assertEqual(_styles_for_act(kb3, "xtp")[2], PRIMARY)

    def test_confirm_cancel_keyboard_green_confirm_blue_back(self):
        kb = build_confirm_cancel_keyboard(
            self.game,
            1,
            confirm_act="xok",
            back_act="xback",
            confirm_text="✅ تأیید",
            back_text="↩️ بازگشت",
        )
        self.assertEqual(len(kb.inline_keyboard), 2)
        self.assertEqual(getattr(kb.inline_keyboard[0][0], "style", None), SUCCESS)
        self.assertEqual(getattr(kb.inline_keyboard[1][0], "style", None), PRIMARY)

    def test_apply_panel_styles_pick_ok_green_acts(self):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="بازیکن 1",
                        callback_data=PlayerMirrorCb(
                            code=self.game.room_code, act="yat", as_uid=7, tid=1
                        ).pack(),
                    ),
                    InlineKeyboardButton(
                        text="بازیکن 2",
                        callback_data=PlayerMirrorCb(
                            code=self.game.room_code, act="yat", as_uid=7, tid=2
                        ).pack(),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="✅ تأیید",
                        callback_data=PlayerMirrorCb(
                            code=self.game.room_code, act="yok", as_uid=7
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ بازگشت",
                        callback_data=PlayerMirrorCb(
                            code=self.game.room_code, act="yback", as_uid=7
                        ).pack(),
                    )
                ],
            ]
        )
        styled = apply_bazpors_panel_styles(
            self.game,
            kb,
            pick_acts={"yat"},
            selected_uids={2},
            ok_acts={"yback"},
            green_acts={"yok"},
        )
        self.assertEqual(_styles_for_act(styled, "yat")[1], PRIMARY)
        self.assertEqual(_styles_for_act(styled, "yat")[2], DANGER)
        self.assertEqual(_styles_for_act(styled, "yok")[0], SUCCESS)
        self.assertEqual(_styles_for_act(styled, "yback")[0], PRIMARY)


class CentralHelperCrossScenarioTests(unittest.TestCase):
    """Item 12: Bazpors/Mozakere rooms keep the helpers' output unstyled."""

    def setUp(self):
        self._codes = []

    def _model(self, scenario_name, code):
        g = _model_game(scenario_name, code)
        self._codes.append(code)
        return g

    def tearDown(self):
        from bot import app_state

        for code in self._codes:
            app_state.manager.games.pop(code, None)

    def test_pick_and_confirm_unstyled_for_other_scenarios(self):
        for scenario, code in (("bazpors", "701"), ("mozakere", "702")):
            g = self._model(scenario, code)
            players = list(g.players.values())
            kb = build_pick_keyboard(g, 1, pick_act="xtp", players=players)
            self.assertEqual(
                _btn_styles(kb), [None] * len(_btn_styles(kb)), scenario
            )
            kb2 = build_confirm_cancel_keyboard(
                g,
                1,
                confirm_act="xok",
                back_act="xback",
                confirm_text="✅ تأیید",
                back_text="↩️ بازگشت",
            )
            self.assertEqual(
                _btn_styles(kb2), [None] * len(_btn_styles(kb2)), scenario
            )
            stamped = apply_bazpors_panel_styles(
                g,
                kb2,
                pick_acts={"xok", "xback"},
                green_acts={"xok"},
            )
            self.assertEqual(
                getattr(stamped.inline_keyboard[0][0], "style", None), None
            )

    def test_narrator_helpers_style_only_namayande(self):
        from bot import app_state
        from bot.game import GameManager

        gm = GameManager()
        for scenario, code, styled in (
            ("namayande", "801", True),
            ("mozakere", "802", False),
        ):
            g = self._model(scenario, code)
            app_state.manager.games[code] = g
            try:
                rows = build_narrator_pick_rows(
                    code, "npick", list(g.players.values()), gm, "🎯"
                )
                flat = [getattr(b, "style", None) for row in rows for b in row]
                self.assertEqual(
                    flat, [PRIMARY] * len(flat) if styled else [None] * len(flat),
                    scenario,
                )
                crows = build_narrator_confirm_back_rows(
                    code,
                    confirm_act="xok",
                    confirm_text="✅ تأیید",
                    back_act="xback",
                    back_text="↩️ بازگشت",
                )
                cflat = [
                    getattr(b, "style", None) for row in crows for b in row
                ]
                if styled:
                    self.assertEqual(cflat, [SUCCESS, PRIMARY])
                else:
                    self.assertEqual(cflat, [None, None])
            finally:
                app_state.manager.games.pop(code, None)


if __name__ == "__main__":
    unittest.main()
