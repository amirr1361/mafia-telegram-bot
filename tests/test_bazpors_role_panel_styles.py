"""Bazpors — unified selection-panel contract (blue/red + inline green confirm).

Contract (mirrors the Hunter styling in tests/test_bazpors_hunter_panel_styles.py
and the Mozakere Part-C scheme):
- Bazpors: pick buttons blue (primary); tentative selection red (danger);
  exactly ONE green (success) «✅ تأیید انتخاب» confirm button visible from
  the INITIAL rendering of every actionable selection panel.
- Committing only happens via the confirm act; tentative picks do not
  finalize anything.
- Passive OK-only panels (acks) stay blue and unaffected.
- Every other scenario keeps the previous default (unstyled) keyboards.
- Texts, callback payloads, authorization gates and layouts are unchanged.
"""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_night_common import (
    no_host_role_ack_keyboard,
    no_host_simple_ok_keyboard,
)
from bot.no_host_role_pick_common import (
    build_confirm_cancel_keyboard,
    build_single_action_keyboard,
)
from bot.observer_delivery import PlayerMirrorCb


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _base_game(scenario_name: str) -> Game:
    game = Game(
        room_code="77",
        host_id=9301,
        scenario_name=scenario_name,
        players={
            1: _p(1, 1, "بازیکن یک", Role.CITIZEN),
            2: _p(2, 2, "بازیکن دو", Role.CITIZEN),
            3: _p(3, 3, "بازیکن سه", Role.CITIZEN),
            4: _p(4, 4, "بازیکن چهار", Role.CITIZEN),
        },
    )
    game.bazpors_narrator_night_count = 1
    return game


def _buttons_by_act(kb, act: str) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            try:
                cb = PlayerMirrorCb.unpack(btn.callback_data)
            except Exception:
                continue
            if cb.act == act:
                out.append((btn, cb))
    return out


def _all_styles(kb) -> list:
    return [btn.style for row in kb.inline_keyboard for btn in row]


def _assert_single_green_confirm(self, kb, confirm_act: str):
    """دقیقاً یک دکمهٔ تأیید سبز «✅ تأیید انتخاب» از رندر اولیه."""
    confirms = _buttons_by_act(kb, confirm_act)
    self.assertEqual(len(confirms), 1)
    btn, cb = confirms[0]
    self.assertEqual(btn.style, "success")
    self.assertIn("تأیید انتخاب", btn.text)


class PickPanelStyleBase:
    """Shared helpers for per-role pick panel assertions (mixin only)."""

    SCENARIO_ROLE = Role.CITIZEN
    PICK_ACT = ""
    PENDING_UID = 0
    CONFIRM_ACT = ""

    def _game(self, scenario_name: str = "bazpors", role_at_1: Role | None = None):
        game = _base_game(scenario_name)
        if role_at_1 is not None:
            game.players = dict(game.players)
            game.players[1].role = role_at_1
        return game, GameManager()

    def _build_pick(self, game, gm):  # overridden per role
        raise NotImplementedError

    def set_pending(self, game):
        raise NotImplementedError

    def test_bazpors_initial_all_picks_blue(self):
        game, gm = self._game(role_at_1=self.SCENARIO_ROLE)
        kb = self._build_pick(game, gm)
        entries = _buttons_by_act(kb, self.PICK_ACT)
        self.assertTrue(entries, "pick pool should not be empty")
        for btn, _cb in entries:
            self.assertEqual(btn.style, "primary")
        if self.CONFIRM_ACT:
            _assert_single_green_confirm(self, kb, self.CONFIRM_ACT)

    def test_pending_selection_red_others_blue(self):
        game, gm = self._game(role_at_1=self.SCENARIO_ROLE)
        self.set_pending(game)
        kb = self._build_pick(game, gm)
        entries = _buttons_by_act(kb, self.PICK_ACT)
        self.assertTrue(entries, "pick pool should not be empty")
        for btn, cb in entries:
            if cb.tid == self.PENDING_UID:
                self.assertEqual(btn.style, "danger")
            else:
                self.assertEqual(btn.style, "primary")

    def test_other_scenario_not_styled(self):
        game, gm = self._game("masoon", role_at_1=self.SCENARIO_ROLE)
        self.set_pending(game)
        kb = self._build_pick(game, gm)
        for btn in (b for b, _ in _buttons_by_act(kb, self.PICK_ACT)):
            self.assertIsNone(btn.style)


class DetectivePanelStyleTests(PickPanelStyleBase, unittest.TestCase):
    SCENARIO_ROLE = Role.DETECTIVE
    PICK_ACT = "ndp"
    PENDING_UID = 2
    CONFIRM_ACT = "ndc"

    def _build_pick(self, game, gm):
        from bot.no_host_detective_night import _pick_keyboard

        return _pick_keyboard(game, 1, gm)

    def set_pending(self, game):
        game.no_host_detective_pending_tid = self.PENDING_UID

    def test_legacy_confirm_keyboard_blue(self):
        game, gm = self._game(role_at_1=Role.DETECTIVE)
        from bot.no_host_detective_night import _confirm_keyboard

        kb = _confirm_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(kb, "ndc")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(kb, "ndb")[0][0].style, "primary")


class DoctorPanelStyleTests(PickPanelStyleBase, unittest.TestCase):
    SCENARIO_ROLE = Role.DOCTOR
    PICK_ACT = "dkt"
    PENDING_UID = 3
    CONFIRM_ACT = "dkc"

    def _build_pick(self, game, gm):
        from bot.no_host_doctor_night import _pick_keyboard

        return _pick_keyboard(game, 1, gm)

    def set_pending(self, game):
        game.no_host_doctor_pending_save_uids = [3]

    def test_none_blue_and_legacy_confirm_keyboard_blue(self):
        game, gm = self._game(role_at_1=Role.DOCTOR)
        from bot.no_host_doctor_night import _confirm_keyboard

        kb = self._build_pick(game, gm)
        none_entries = _buttons_by_act(kb, "dkn")
        self.assertTrue(none_entries)
        self.assertEqual(none_entries[0][0].style, "primary")
        ck = _confirm_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(ck, "dkc")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(ck, "dkb")[0][0].style, "primary")
        # exactly one confirm in the unified pick panel (the inline one)
        confirms = _buttons_by_act(kb, "dkc")
        self.assertEqual(len(confirms), 1)

    def test_single_action_ack_blue(self):
        game, gm = self._game(role_at_1=Role.DOCTOR)
        kb = build_single_action_keyboard(game, 1, act="dko", text="✅ اوکی")
        self.assertEqual(kb.inline_keyboard[0][0].style, "primary")
        other = build_single_action_keyboard(
            self._game("mozakere")[0], 1, act="dkng", text="✅ اوکی"
        )
        self.assertIsNone(other.inline_keyboard[0][0].style)


class JournalistPanelStyleTests(PickPanelStyleBase, unittest.TestCase):
    # Journalist night pick flow is a Mozakere-only feature; in Bazpors the
    # central styling contract still applies wherever the panel is rendered.
    SCENARIO_ROLE = Role.JOURNALIST
    PICK_ACT = "jrp"
    PENDING_UID = 2
    CONFIRM_ACT = ""  # no bazpors panel: no inline confirm expected

    def _build_pick(self, game, gm):
        from bot.no_host_journalist_night import _pick_keyboard

        return _pick_keyboard(game, 1, gm)

    def set_pending(self, game):
        game.no_host_journalist_pending_tid = self.PENDING_UID

    def test_idle_ack_blue_and_isolated(self):
        game, _gm = self._game(role_at_1=Role.JOURNALIST)
        kb = no_host_role_ack_keyboard(game, 1, "jic")
        self.assertEqual(kb.inline_keyboard[0][0].style, "primary")
        kb2 = no_host_role_ack_keyboard(self._game("masoon")[0], 1, "jic")
        self.assertIsNone(kb2.inline_keyboard[0][0].style)


class ShiadPanelStyleTests(PickPanelStyleBase, unittest.TestCase):
    SCENARIO_ROLE = Role.SHIAD
    PICK_ACT = "sgt"
    PENDING_UID = 2
    CONFIRM_ACT = "sgc"

    def _build_pick(self, game, gm):
        from bot.no_host_shiad_night import _pick_keyboard

        return _pick_keyboard(game, 1, gm)

    def set_pending(self, game):
        game.no_host_shiad_pending_tid = self.PENDING_UID

    def test_legacy_confirm_keyboard_blue(self):
        game, gm = self._game(role_at_1=Role.SHIAD)
        from bot.no_host_shiad_night import _confirm_keyboard

        kb = _confirm_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(kb, "sgc")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(kb, "sgb")[0][0].style, "primary")


class SniperPanelStyleTests(PickPanelStyleBase, unittest.TestCase):
    SCENARIO_ROLE = Role.SNIPER
    PICK_ACT = "skt"
    PENDING_UID = 3
    CONFIRM_ACT = "skc"

    def _build_pick(self, game, gm):
        from bot.no_host_sniper_night import _pick_keyboard

        return _pick_keyboard(game, 1, gm)

    def set_pending(self, game):
        game.no_host_sniper_pending_target_uid = self.PENDING_UID

    def test_none_blue_and_legacy_confirm_keyboard_blue(self):
        game, gm = self._game(role_at_1=Role.SNIPER)
        from bot.no_host_sniper_night import _confirm_keyboard

        kb = self._build_pick(game, gm)
        none_entries = _buttons_by_act(kb, "skn")
        self.assertTrue(none_entries)
        self.assertEqual(none_entries[0][0].style, "primary")
        ck = _confirm_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(ck, "skc")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(ck, "skb")[0][0].style, "primary")
        # exactly one confirm in the unified pick panel (the inline one)
        confirms = _buttons_by_act(kb, "skc")
        self.assertEqual(len(confirms), 1)


class InterrogatorNightPanelStyleTests(unittest.TestCase):
    def _game(self, scenario_name: str = "bazpors"):
        game = _base_game(scenario_name)
        game.players[1].role = Role.INTERROGATOR
        return game, GameManager()

    def test_int1_initial_all_blue_with_green_confirm(self):
        from bot.no_host_interrogator_night import _int1_keyboard

        game, gm = self._game()
        kb = _int1_keyboard(game, 1, gm)
        picks = _buttons_by_act(kb, "nii1")
        self.assertTrue(picks)
        for btn, _cb in picks:
            self.assertEqual(btn.style, "primary")
        self.assertEqual(_buttons_by_act(kb, "nii1s")[0][0].style, "primary")
        confirms = _buttons_by_act(kb, "niisk")
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0][0].style, "success")
        self.assertIn("تأیید انتخاب", confirms[0][0].text)

    def test_int1_pending_targets_red(self):
        from bot.no_host_interrogator_night import _int1_keyboard

        game, gm = self._game()
        game.no_host_interrog_pending_uids = [2]
        kb = _int1_keyboard(game, 1, gm)
        for btn, cb in _buttons_by_act(kb, "nii1"):
            self.assertEqual(btn.style, "danger" if cb.tid == 2 else "primary")

    def test_int1_two_pending_both_red(self):
        from bot.no_host_interrogator_night import _int1_keyboard

        game, gm = self._game()
        game.no_host_interrog_pending_uids = [2, 3]
        kb = _int1_keyboard(game, 1, gm)
        red = {cb.tid for b, cb in _buttons_by_act(kb, "nii1") if b.style == "danger"}
        self.assertEqual(red, {2, 3})

    def test_int1_pending_skip_makes_optout_red(self):
        from bot.no_host_interrogator_night import _int1_keyboard

        game, gm = self._game()
        game.no_host_interrog_pending_skip = True
        kb = _int1_keyboard(game, 1, gm)
        optout = _buttons_by_act(kb, "nii1s")
        self.assertEqual(len(optout), 1)
        self.assertEqual(optout[0][0].style, "danger")
        for btn, _cb in _buttons_by_act(kb, "nii1"):
            self.assertEqual(btn.style, "primary")
        confirms = _buttons_by_act(kb, "niisk")
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0][0].style, "success")

    def test_legacy_int2_and_skip_ack_blue(self):
        from bot.no_host_interrogator_night import (
            _int2_keyboard,
            _skip_ack_keyboard,
        )

        game, gm = self._game()
        kb = _int2_keyboard(game, 1, gm)
        for btn, _cb in _buttons_by_act(kb, "nii2"):
            self.assertEqual(btn.style, "primary")
        self.assertEqual(_buttons_by_act(kb, "nii2a")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(kb, "nii2r")[0][0].style, "primary")
        self.assertEqual(_skip_ack_keyboard(game, 1).inline_keyboard[0][0].style, "primary")

    def test_masoon_not_styled(self):
        from bot.no_host_interrogator_night import _int1_keyboard, _skip_ack_keyboard

        game, gm = self._game("masoon")
        for btn in (b for b, _ in _buttons_by_act(_int1_keyboard(game, 1, gm), "nii1")):
            self.assertIsNone(btn.style)
        self.assertIsNone(_skip_ack_keyboard(game, 1).inline_keyboard[0][0].style)


class MafiaFamilyPanelStyleTests(unittest.TestCase):
    def _mafia_game(self, scenario_name: str = "bazpors"):
        game = _base_game(scenario_name)
        game.players[1].role = Role.MAFIA_BOSS
        game.players[2].role = Role.MAFIA
        game.players[3].role = Role.CITIZEN
        game.players[4].role = Role.DOCTOR
        game.mafia_ids = {1, 2}
        return game, GameManager()

    def test_mafia_menu_blue_with_inline_green_confirm(self):
        from bot.no_host_mafia_night1 import (
            _mafia_confirm_keyboard,
            _mafia_menu_keyboard,
        )

        game, gm = self._mafia_game()
        kb = _mafia_menu_keyboard(game, 1, gm)
        menu_acts = set()
        for row in kb.inline_keyboard:
            for btn in row:
                cb = PlayerMirrorCb.unpack(btn.callback_data)
                menu_acts.add(cb.act)
        self.assertIn("nms", menu_acts)
        self.assertEqual(_buttons_by_act(kb, "nms")[0][0].style, "primary")
        _assert_single_green_confirm(self, kb, "nmc")
        # legacy confirm screen keyboard is still blue
        ck = _mafia_confirm_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(ck, "nmc")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(ck, "nmb")[0][0].style, "primary")

    def test_mafia_menu_pending_action_red(self):
        from bot.no_host_mafia_night1 import (
            MAFIA_ACTION_SHOT,
            _mafia_menu_keyboard,
        )

        game, gm = self._mafia_game()
        game.no_host_mafia_night1_pending_action = MAFIA_ACTION_SHOT
        kb = _mafia_menu_keyboard(game, 1, gm)
        self.assertEqual(_buttons_by_act(kb, "nms")[0][0].style, "danger")
        for act in ("nmy", "nmn"):
            entries = _buttons_by_act(kb, act)
            if entries:  # action groups beyond the shot are scenario-gated
                self.assertEqual(entries[0][0].style, "primary")

    def test_mafia_shot_pick_red_and_inline_green_confirm(self):
        from bot.no_host_mafia_shot import _shot_pick_keyboard, _shot_confirm_keyboard

        game, gm = self._mafia_game()
        game.no_host_mafia_shot_pending_uid = 4
        kb = _shot_pick_keyboard(game, 1, gm)
        picked, others = 0, 0
        for row in kb.inline_keyboard:
            for btn in row:
                cb = PlayerMirrorCb.unpack(btn.callback_data)
                if cb.act != "msk":
                    continue
                if cb.tid == 4:
                    self.assertEqual(btn.style, "danger")
                    picked += 1
                else:
                    self.assertEqual(btn.style, "primary")
                    others += 1
        self.assertEqual(picked, 1)
        self.assertGreater(others, 0)
        _assert_single_green_confirm(self, kb, "msc")
        ck = _shot_confirm_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(ck, "msc")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(ck, "msb")[0][0].style, "primary")

    def test_mafia_shot_initial_preserves_green_confirm(self):
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        game, gm = self._mafia_game()
        kbs = [_shot_pick_keyboard(game, 1, gm) for _ in range(1)]
        for kb in kbs:
            _assert_single_green_confirm(self, kb, "msc")

    def test_mafia_nato_role_panels(self):
        from bot.no_host_mafia_nato import (
            _nato_denied_keyboard,
            _player_pick_keyboard,
            _role_pick_keyboard,
        )

        game, gm = self._mafia_game()
        if "NATO" not in dir(Role):  # pragma: no cover
            self.skipTest("NATO role missing")
        game.players[1].role = Role.NATO
        rk = _role_pick_keyboard(game, 1)
        for row in rk.inline_keyboard:
            for btn in row:
                cb = PlayerMirrorCb.unpack(btn.callback_data)
                if cb.act.startswith("n1r-"):
                    self.assertEqual(btn.style, "primary")
        _assert_single_green_confirm(self, rk, "n1c")
        game.no_host_mafia_nato_pending_target_uid = 4
        pk = _player_pick_keyboard(game, 1, gm)
        n2p = _buttons_by_act(pk, "n2p")
        self.assertTrue(n2p)
        for btn, cb in n2p:
            self.assertEqual(btn.style, "danger" if cb.tid == 4 else "primary")
        _assert_single_green_confirm(self, pk, "n2c")
        dk = _nato_denied_keyboard(game, 1)
        self.assertEqual(dk.inline_keyboard[0][0].style, "primary")

    def test_mafia_nato_pending_role_red(self):
        from bot.no_host_mafia_nato import _role_pick_keyboard

        game, gm = self._mafia_game()
        if "NATO" not in dir(Role):  # pragma: no cover
            self.skipTest("NATO role missing")
        game.players[1].role = Role.NATO
        roles_seen = _buttons_by_act(_role_pick_keyboard(game, 1), "n1r-journalist")
        if not roles_seen:
            # use whatever first role the room contains
            probe = _role_pick_keyboard(game, 1)
            acts = [
                PlayerMirrorCb.unpack(b.callback_data).act
                for row in probe.inline_keyboard
                for b in row
            ]
            role_acts = [a for a in acts if a.startswith("n1r-")]
            self.assertTrue(role_acts)
            role_act = role_acts[0]
        else:
            role_act = "n1r-journalist"
        game.no_host_mafia_nato_pending_role = role_act[4:]
        kb = _role_pick_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(kb, role_act)[0][0].style, "danger")
        _assert_single_green_confirm(self, kb, "n1c")

    def test_mafia_yaku_picks_pending_red_with_green_confirms(self):
        from bot.no_host_mafia_yaku import (
            _confirm_keyboard,  # noqa: F401
            _pick_keyboard,
            _yaku_denied_keyboard,
        )

        game, gm = self._mafia_game()
        game.no_host_mafia_yaku_pending_sac_uid = 4
        kb = _pick_keyboard(game, 1, gm, [game.players[3], game.players[4]], "ysp")
        sees_ysp = _buttons_by_act(kb, "ysp")
        self.assertTrue(sees_ysp)
        for btn, cb in sees_ysp:
            self.assertEqual(btn.style, "danger" if cb.tid == 4 else "primary")
        _assert_single_green_confirm(self, kb, "ysc")
        dk = _yaku_denied_keyboard(game, 1)
        self.assertEqual(dk.inline_keyboard[0][0].style, "primary")
        ck = _confirm_keyboard(game, 1, "ysc", "ysb")
        self.assertEqual(_buttons_by_act(ck, "ysc")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(ck, "ysb")[0][0].style, "primary")

    def test_mafia_yaku_civ_stage_green_confirm(self):
        from bot.no_host_mafia_yaku import _pick_keyboard

        game, gm = self._mafia_game()
        game.no_host_mafia_yaku_pending_civ_uid = 3
        kb = _pick_keyboard(game, 1, gm, [game.players[3], game.players[4]], "ycp")
        sees_ycp = _buttons_by_act(kb, "ycp")
        self.assertTrue(sees_ycp)
        for btn, cb in sees_ycp:
            self.assertEqual(btn.style, "danger" if cb.tid == 3 else "primary")
        _assert_single_green_confirm(self, kb, "ycc")


class InterrogDayAckStyleTests(unittest.TestCase):
    def _game(self, scenario_name: str = "bazpors"):
        game = _base_game(scenario_name)
        game.players[1].role = Role.INTERROGATOR
        return game

    def test_wait_ok_and_interrogator_decision_blue(self):
        from bot.no_host_interrog_day import _interrogator_keyboard, _wait_ok_keyboard

        game = self._game()
        self.assertEqual(_wait_ok_keyboard(game, 3).inline_keyboard[0][0].style, "primary")
        kb = _interrogator_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(kb, "ihco")[0][0].style, "primary")
        self.assertEqual(_buttons_by_act(kb, "ihdi")[0][0].style, "primary")

    def test_acks_not_styled_outside_bazpors(self):
        from bot.no_host_interrog_day import _interrogator_keyboard, _wait_ok_keyboard

        game = self._game("namayande")
        self.assertIsNone(_wait_ok_keyboard(game, 3).inline_keyboard[0][0].style)
        self.assertIsNone(_interrogator_keyboard(game, 1).inline_keyboard[0][0].style)


class SharedHelperAndReadinessTests(unittest.TestCase):
    def test_ack_and_simple_ok_blue_only_bazpors(self):
        game = _base_game("bazpors")
        self.assertEqual(no_host_role_ack_keyboard(game, 5, "ruc").inline_keyboard[0][0].style, "primary")
        self.assertEqual(no_host_simple_ok_keyboard(game, 5).inline_keyboard[0][0].style, "primary")
        for scenario in ("mozakere", "masoon"):
            other = _base_game(scenario)
            self.assertIsNone(no_host_role_ack_keyboard(other, 5, "cic").inline_keyboard[0][0].style)
            self.assertIsNone(no_host_simple_ok_keyboard(other, 5).inline_keyboard[0][0].style)

    def test_confirm_cancel_shared_builder(self):
        game = _base_game("bazpors")
        kb = build_confirm_cancel_keyboard(
            game, 1, confirm_act="ndc", back_act="ndb",
            confirm_text="✅ تأیید انتخاب", back_text="↩️ بازگشت",
        )
        self.assertEqual(kb.inline_keyboard[0][0].style, "primary")
        self.assertEqual(kb.inline_keyboard[1][0].style, "primary")
        other = build_confirm_cancel_keyboard(
            _base_game("masoon"), 1, confirm_act="ndc", back_act="ndb",
            confirm_text="x", back_text="y",
        )
        self.assertIsNone(other.inline_keyboard[0][0].style)

    def test_hunter_pending_red_and_inline_green_confirm(self):
        from bot.no_host_night1 import _hunter_pick_keyboard

        game = _base_game("bazpors")
        game.players = {u: p for u, p in game.players.items()}
        game.players[1].role = Role.HUNTER
        gm = GameManager()
        kb = _hunter_pick_keyboard(game, 1, gm)
        for btn, _cb in _buttons_by_act(kb, "hnp"):
            self.assertEqual(btn.style, "primary")
        _assert_single_green_confirm(self, kb, "hnc")
        game.no_host_hunter_pending_pick_uid = 2
        kb2 = _hunter_pick_keyboard(game, 1, gm)
        for btn, cb in _buttons_by_act(kb2, "hnp"):
            self.assertEqual(btn.style, "danger" if cb.tid == 2 else "primary")
        _assert_single_green_confirm(self, kb2, "hnc")

    def test_callback_data_and_text_preserved(self):
        from bot.no_host_detective_night import _pick_keyboard

        gm = GameManager()
        game_baz = _base_game("bazpors")
        game_baz.players[1].role = Role.DETECTIVE
        game_mas = _base_game("masoon")
        game_mas.players[1].role = Role.DETECTIVE
        kb_baz = _pick_keyboard(game_baz, 1, gm)
        kb_mas = _pick_keyboard(game_mas, 1, gm)
        by_tid_baz = {cb.tid: (b.text, b.callback_data)
                      for b, cb in _buttons_by_act(kb_baz, "ndp")}
        by_tid_mas = {cb.tid: (b.text, b.callback_data)
                      for b, cb in _buttons_by_act(kb_mas, "ndp")}
        common = set(by_tid_baz) & set(by_tid_mas)
        self.assertTrue(common)
        for tid in common:
            self.assertEqual(by_tid_baz[tid], by_tid_mas[tid])


if __name__ == "__main__":
    unittest.main()
