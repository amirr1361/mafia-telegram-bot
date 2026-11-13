"""Bazpors — inline green-confirm selection panel contract (full suite).

Ten required coverage areas:
 1. Exactly ONE green «✅ تأیید انتخاب» confirm visible from the INITIAL
    render of every Bazpors selection panel (act suffix `c`).
 2. Selection styling: unselected buttons blue (primary); the tentative
    selection red (danger); toggling before confirm.
 3. All eligible buttons remain visible after selection (no hiding).
 4. Selection limits unchanged (doctor save capacity=1 for bazpors,
    interrogator exactly two nominees).
 5. Yakuza (yakuzai) mechanics preserved (stage confirm acts + pendings).
 6. Interrogator unified panel: two-target flow + confirmed opt-out.
 7. Tentative picks do not READY/commit anything until confirm.
 8. Stale/duplicate confirms rejected (post-commit dispatch no-ops).
 9. Observer/synthetic mirrors keep the synthetic-actor dispatch path.
10. Other scenarios (mozakere/masoon/namayande) keep unstyled panels.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.bazpors_narrator import NIGHT_START
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


def _game(scenario_name: str = "bazpors") -> tuple[Game, GameManager]:
    game = Game(
        room_code="42",
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
    return game, GameManager()


def _buttons_by_act(kb, act: str) -> list[tuple]:
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


def _assert_single_green_confirm(testcase, kb, confirm_act: str) -> None:
    confirms = _buttons_by_act(kb, confirm_act)
    testcase.assertEqual(len(confirms), 1)
    btn, _cb = confirms[0]
    testcase.assertEqual(btn.style, "success")
    testcase.assertIn("تأیید انتخاب", btn.text)


# ---------------------------------------------------------------------------
# 1. One green confirm from the initial render
# ---------------------------------------------------------------------------


class SingleGreenConfirmInitialTests(unittest.TestCase):
    """Every Bazpors selection panel shows exactly one green confirm first."""

    def test_detective(self) -> None:
        from bot.no_host_detective_night import _pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.DETECTIVE
        _assert_single_green_confirm(self, _pick_keyboard(game, 1, gm), "ndc")

    def test_sniper(self) -> None:
        from bot.no_host_sniper_night import _pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.SNIPER
        _assert_single_green_confirm(self, _pick_keyboard(game, 1, gm), "skc")

    def test_doctor(self) -> None:
        from bot.no_host_doctor_night import _pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.DOCTOR
        _assert_single_green_confirm(self, _pick_keyboard(game, 1, gm), "dkc")

    def test_shiad(self) -> None:
        from bot.no_host_shiad_night import _pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.SHIAD
        _assert_single_green_confirm(self, _pick_keyboard(game, 1, gm), "sgc")

    def test_hunter(self) -> None:
        from bot.no_host_night1 import _hunter_pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.HUNTER
        _assert_single_green_confirm(
            self, _hunter_pick_keyboard(game, 1, gm), "hnc"
        )

    def test_mafia_menu_and_shot(self) -> None:
        from bot.no_host_mafia_night1 import _mafia_menu_keyboard
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.MAFIA_BOSS
        _assert_single_green_confirm(
            self, _mafia_menu_keyboard(game, 1, gm), "nmc"
        )
        _assert_single_green_confirm(
            self, _shot_pick_keyboard(game, 1, gm), "msc"
        )

    def test_interrogator(self) -> None:
        from bot.no_host_interrogator_night import _int1_keyboard

        game, gm = _game()
        game.players[1].role = Role.INTERROGATOR
        _assert_single_green_confirm(
            self, _int1_keyboard(game, 1, gm), "niisk"
        )


# ---------------------------------------------------------------------------
# 2. Red/blue selection + toggling
# ---------------------------------------------------------------------------


class RedBlueSelectionTests(unittest.TestCase):
    def test_detective(self) -> None:
        from bot.no_host_detective_night import _pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.DETECTIVE
        game.no_host_detective_pending_tid = 2
        for btn, cb in _buttons_by_act(_pick_keyboard(game, 1, gm), "ndp"):
            self.assertEqual(btn.style, "danger" if cb.tid == 2 else "primary")

    def test_sniper(self) -> None:
        from bot.no_host_sniper_night import _pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.SNIPER
        game.no_host_sniper_pending_target_uid = 3
        kb = _pick_keyboard(game, 1, gm)
        for btn, cb in _buttons_by_act(kb, "skt"):
            self.assertEqual(btn.style, "danger" if cb.tid == 3 else "primary")
        none = _buttons_by_act(kb, "skn")
        self.assertTrue(none)
        self.assertEqual(none[0][0].style, "primary")

    def test_doctor(self) -> None:
        from bot.no_host_doctor_night import _pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.DOCTOR
        game.no_host_doctor_pending_save_uids = [2]
        kb = _pick_keyboard(game, 1, gm)
        for btn, cb in _buttons_by_act(kb, "dkt"):
            self.assertEqual(btn.style, "danger" if cb.tid == 2 else "primary")

    def test_hunter(self) -> None:
        from bot.no_host_night1 import _hunter_pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.HUNTER
        game.no_host_hunter_pending_pick_uid = 4
        kb = _hunter_pick_keyboard(game, 1, gm)
        for btn, cb in _buttons_by_act(kb, "hnp"):
            self.assertEqual(btn.style, "danger" if cb.tid == 4 else "primary")

    def test_mafia_shot(self) -> None:
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.MAFIA_BOSS
        game.no_host_mafia_shot_pending_uid = 3
        kb = _shot_pick_keyboard(game, 1, gm)
        for btn, cb in _buttons_by_act(kb, "msk"):
            self.assertEqual(btn.style, "danger" if cb.tid == 3 else "primary")

    def test_interrogator_two_picks(self) -> None:
        from bot.no_host_interrogator_night import _int1_keyboard

        game, gm = _game()
        game.players[1].role = Role.INTERROGATOR
        game.no_host_interrog_pending_uids = [2, 4]
        kb = _int1_keyboard(game, 1, gm)
        red = {cb.tid for b, cb in _buttons_by_act(kb, "nii1") if b.style == "danger"}
        self.assertEqual(red, {2, 4})

    def test_interrogator_optout_pending_red(self) -> None:
        from bot.no_host_interrogator_night import _int1_keyboard

        game, gm = _game()
        game.players[1].role = Role.INTERROGATOR
        game.no_host_interrog_pending_skip = True
        kb = _int1_keyboard(game, 1, gm)
        optout = _buttons_by_act(kb, "nii1s")
        self.assertEqual(optout[0][0].style, "danger")
        for btn, _cb in _buttons_by_act(kb, "nii1"):
            self.assertEqual(btn.style, "primary")


# ---------------------------------------------------------------------------
# 3. All eligible buttons remain visible
# ---------------------------------------------------------------------------


class ButtonsRemainVisibleTests(unittest.TestCase):
    def test_all_panels_keep_full_pool_and_optout(self) -> None:
        from bot.no_host_interrogator_night import _int1_keyboard
        from bot.no_host_night1 import _hunter_pick_keyboard
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        game, gm = _game()
        game.players[1].role = Role.INTERROGATOR
        game.players[2].role = Role.HUNTER  # role uniqueness not needed here
        fresh, gm2 = _game()
        fresh.players[1].role = Role.MAFIA_BOSS
        fresh.players[4].role = Role.DOCTOR

        game.no_host_interrog_pending_uids = [2]
        ikb = _int1_keyboard(game, 1, gm)
        self.assertEqual(len(_buttons_by_act(ikb, "nii1")), 4)
        self.assertEqual(len(_buttons_by_act(ikb, "nii1s")), 1)
        _assert_single_green_confirm(self, ikb, "niisk")

        game.no_host_hunter_pending_pick_uid = 3
        hkb = _hunter_pick_keyboard(game, 1, gm)
        self.assertEqual(len(_buttons_by_act(hkb, "hnp")), 3)
        self.assertEqual(len(_buttons_by_act(hkb, "hns")), 1)

        fresh.no_host_mafia_shot_pending_uid = 3
        skb = _shot_pick_keyboard(fresh, 1, gm2)
        self.assertTrue(len(_buttons_by_act(skb, "msk")) > 0)
        _assert_single_green_confirm(self, skb, "msc")


# ---------------------------------------------------------------------------
# 4. Limits unchanged
# ---------------------------------------------------------------------------


class LimitsUnchangedTests(unittest.IsolatedAsyncioTestCase):
    def test_doctor_bazpors_capacity_one(self) -> None:
        from bot.no_host_doctor_night import _doctor_capacity
        from bot.roles.doctor import doctor_save_capacity

        game, _gm = _game()
        game.players[1].role = Role.DOCTOR
        self.assertEqual(_doctor_capacity(game), 1)
        self.assertEqual(doctor_save_capacity(game), 1)

    def test_doctor_mozakere_capacity_not_regressed(self) -> None:
        from bot.no_host_doctor_night import _doctor_capacity
        from bot.roles.mozakere_doctor import mozakere_doctor_save_capacity

        game, _gm = _game("mozakere")
        self.assertEqual(_doctor_capacity(game), mozakere_doctor_save_capacity(game))

    async def test_interrogator_requires_exactly_two(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _game()
        game.players[1].role = Role.INTERROGATOR
        game.bazpors_host_mode = "no_host"
        game.no_host_interrog_flow_active = True
        game.no_host_interrog_dm_signature = "1:interrog:flow"
        game.no_host_interrog_ui_phase = "int1"
        game.bazpors_narrator_step = NIGHT_START
        game.bot_assistant_user_id = 9999
        game.no_host_assistant_narrator_active = True
        game.observer_user_id = None

        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            for try_pending in ([2], [2, 2], [2, 3, 4]):  # one / duplicate / three
                game.no_host_interrog_pending_uids = list(try_pending)
                cb = _StubCallback()
                await dispatch_no_host_interrogator_night(
                    cb, _EditBot(), game, gm, int_uid=1, actor_uid=1,
                    act="niisk", tid=0,
                )
                self.assertIn("ابتدا دو بازیکن", cb.alerts[-1])
                self.assertFalse(game.no_host_interrog_pick_confirmed)


# ---------------------------------------------------------------------------
# 5. Yakuza mechanics preserved
# ---------------------------------------------------------------------------


class YakuzaMechanicsTests(unittest.TestCase):
    def _mafia_game(self, scenario_name: str = "bazpors") -> tuple[Game, GameManager]:
        game, gm = _game(scenario_name)
        game.players[1].role = Role.MAFIA_BOSS
        game.players[2].role = Role.MAFIA
        game.players[3].role = Role.CITIZEN
        game.players[4].role = Role.DOCTOR
        game.mafia_ids = {1, 2}
        return game, gm

    def test_stage_confirm_acts(self) -> None:
        from bot.no_host_mafia_yaku import _pick_keyboard

        game, gm = self._mafia_game()
        sac_kb = _pick_keyboard(game, 1, gm, [game.players[4]], "ysp")
        _assert_single_green_confirm(self, sac_kb, "ysc")
        civ_kb = _pick_keyboard(game, 1, gm, [game.players[3]], "ycp")
        _assert_single_green_confirm(self, civ_kb, "ycc")

    def test_pending_fields_survive_rebuild(self) -> None:
        from bot.no_host_mafia_yaku import _pick_keyboard

        game, gm = self._mafia_game()
        game.no_host_mafia_yaku_pending_sac_uid = 4
        game.no_host_mafia_yaku_pending_civ_uid = 3
        sac_kb = _pick_keyboard(game, 1, gm, [game.players[4]], "ysp")
        self.assertEqual(
            {cb.tid for b, cb in _buttons_by_act(sac_kb, "ysp") if b.style == "danger"},
            {4},
        )
        civ_kb = _pick_keyboard(game, 1, gm, [game.players[3]], "ycp")
        self.assertEqual(
            {cb.tid for b, cb in _buttons_by_act(civ_kb, "ycp") if b.style == "danger"},
            {3},
        )

    def test_masoon_yaku_unstyled(self) -> None:
        from bot.no_host_mafia_yaku import _pick_keyboard

        game, gm = self._mafia_game("masoon")
        kb = _pick_keyboard(game, 1, gm, [game.players[4]], "ysp")
        for row in kb.inline_keyboard:
            for btn in row:
                self.assertIsNone(btn.style)


# ---------------------------------------------------------------------------
# 6. Interrogator two-target flow + confirmed opt-out (dispatch level)
# ---------------------------------------------------------------------------


class _StubCallback:
    def __init__(self) -> None:
        self.alerts: list[str] = []

    async def answer(self, text: str, show_alert: bool = False) -> None:
        self.alerts.append(text)


class _EditBot:
    """Mirror edits only when refs exist; fresh games never reach the bot.

    Observer-registered games do reach bot.send_message (observer mirror
    copy) — record instead of raising there."""

    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def edit_message_text(self, *a, **k):  # pragma: no cover
        raise AssertionError("unexpected bot call")

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append((chat_id, text))
        return type("_Msg", (), {"message_id": 1, "chat": type("_C", (), {"id": chat_id})()})()


def _interrog_game() -> tuple[Game, GameManager]:
    game, gm = _game()
    game.players[1].role = Role.INTERROGATOR
    game.bazpors_host_mode = "no_host"
    game.no_host_interrog_flow_active = True
    game.no_host_interrog_dm_signature = "1:interrog:flow"
    game.no_host_interrog_ui_phase = "int1"
    game.bazpors_narrator_step = NIGHT_START
    game.bot_assistant_user_id = 9999
    game.no_host_assistant_narrator_active = True
    game.observer_user_id = None
    return game, gm


class InterrogatorCommitFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_picks_then_confirm_commits_both(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ) as after:
            cb1 = _StubCallback()
            await dispatch_no_host_interrogator_night(
                cb1, _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1", tid=2,
            )
            cb2 = _StubCallback()
            await dispatch_no_host_interrogator_night(
                cb2, _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1", tid=3,
            )
            self.assertEqual(game.no_host_interrog_pending_uids, [2, 3])
            self.assertFalse(game.no_host_interrog_pick_confirmed)
            cf = _StubCallback()
            await dispatch_no_host_interrogator_night(
                cf, _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="niisk", tid=0,
            )
        self.assertIn("بازپرسی ثبت شد.", cf.alerts)
        self.assertEqual(game.bazpors_interrog_first_uid, 2)
        self.assertEqual(game.bazpors_interrog_second_uid, 3)
        self.assertTrue(game.no_host_interrog_pick_confirmed)
        self.assertEqual(game.no_host_interrog_pending_uids, [])
        from bot.roles.night_state import interrogator_night_state

        ist = interrogator_night_state(game)
        self.assertEqual(ist.first_uid, 2)
        self.assertEqual(ist.second_uid, 3)
        self.assertTrue(ist.night_finished)
        after.assert_awaited()

    async def test_toggling_deselect_and_reselect(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            # pick, then deselect (re-press), then pick again
            await dispatch_no_host_interrogator_night(
                _StubCallback(), _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1", tid=2,
            )
            self.assertEqual(game.no_host_interrog_pending_uids, [2])
            await dispatch_no_host_interrogator_night(
                _StubCallback(), _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1", tid=2,
            )
            self.assertEqual(game.no_host_interrog_pending_uids, [])
            await dispatch_no_host_interrogator_night(
                _StubCallback(), _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1", tid=4,
            )
            self.assertEqual(game.no_host_interrog_pending_uids, [4])
            self.assertFalse(game.bazpors_interrog_once_done)

    async def test_optout_requires_confirm(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            await dispatch_no_host_interrogator_night(
                _StubCallback(), _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1s", tid=0,
            )
            self.assertTrue(game.no_host_interrog_pending_skip)
            self.assertFalse(game.no_host_interrog_pick_confirmed)
            # pending uids cleared by opting out
            self.assertEqual(game.no_host_interrog_pending_uids, [])
            # confirm commits the skip
            cf = _StubCallback()
            await dispatch_no_host_interrogator_night(
                cf, _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="niisk", tid=0,
            )
        self.assertIn("ثبت شد.", cf.alerts)
        self.assertTrue(game.no_host_interrog_pick_confirmed)
        self.assertIsNone(game.bazpors_interrog_first_uid)
        self.assertIsNone(game.bazpors_interrog_second_uid)

    async def test_optout_toggle_cleared_by_new_pick(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            await dispatch_no_host_interrogator_night(
                _StubCallback(), _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1s", tid=0,
            )
            self.assertTrue(game.no_host_interrog_pending_skip)
            await dispatch_no_host_interrogator_night(
                _StubCallback(), _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="nii1", tid=2,
            )
            self.assertFalse(game.no_host_interrog_pending_skip)
            self.assertEqual(game.no_host_interrog_pending_uids, [2])

    async def test_commit_without_valid_selection_rejected(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            cb = _StubCallback()
            await dispatch_no_host_interrogator_night(
                cb, _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="niisk", tid=0,
            )
        self.assertFalse(game.no_host_interrog_pick_confirmed)
        self.assertIn("ابتدا دو بازیکن", cb.alerts[-1])

    async def test_duplicate_same_uid_rejected_at_confirm(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        game.no_host_interrog_pending_uids = [2, 2]
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            cb = _StubCallback()
            await dispatch_no_host_interrogator_night(
                cb, _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="niisk", tid=0,
            )
        self.assertFalse(game.no_host_interrog_pick_confirmed)


# ---------------------------------------------------------------------------
# 7. Tentative picks do not READY anything
# ---------------------------------------------------------------------------


class TentativePickDoesNotReadyTests(unittest.TestCase):
    def test_pending_fields_only(self) -> None:
        game, _gm = _game()
        game.players[1].role = Role.DETECTIVE
        game.players[2].role = Role.DOCTOR
        game.no_host_detective_pending_tid = 2
        game.no_host_doctor_pending_save_uids = [3]
        self.assertFalse(game.no_host_detective_pick_confirmed)
        self.assertFalse(game.no_host_doctor_pick_confirmed)

        game, _gm = _game()
        game.players[1].role = Role.INTERROGATOR
        game.no_host_interrog_pending_uids = [2, 3]
        self.assertFalse(game.no_host_interrog_pick_confirmed)
        self.assertFalse(game.bazpors_interrog_once_done)

        game, _gm = _game()
        game.players[1].role = Role.HUNTER
        game.no_host_hunter_pending_pick_uid = 3
        self.assertFalse(getattr(game, "no_host_hunter_pick_confirmed", False))


# ---------------------------------------------------------------------------
# 8. Stale/duplicate confirms rejected
# ---------------------------------------------------------------------------


class StaleDuplicateConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_after_commit_rejected(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        game.bazpors_interrog_first_uid = 2
        game.bazpors_interrog_second_uid = 3
        game.no_host_interrog_pick_confirmed = True
        game.no_host_interrog_flow_active = False
        cb = _StubCallback()
        await dispatch_no_host_interrogator_night(
            cb, _EditBot(), game, gm, int_uid=1, actor_uid=1,
            act="niisk", tid=0,
        )
        self.assertEqual(cb.alerts, ["این مرحله دیگر فعال نیست."])

    async def test_commit_idempotent_state_unchanged(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        game.no_host_interrog_pending_uids = [2, 3]
        # first confirm succeeds
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            await dispatch_no_host_interrogator_night(
                _StubCallback(), _EditBot(), game, gm, int_uid=1, actor_uid=1,
                act="niisk", tid=0,
            )
        snapshot = (
            game.bazpors_interrog_first_uid,
            game.bazpors_interrog_second_uid,
            game.no_host_interrog_pick_confirmed,
        )
        cb2 = _StubCallback()
        await dispatch_no_host_interrogator_night(
            cb2, _EditBot(), game, gm, int_uid=1, actor_uid=1,
            act="niisk", tid=0,
        )
        self.assertEqual(
            (
                game.bazpors_interrog_first_uid,
                game.bazpors_interrog_second_uid,
                game.no_host_interrog_pick_confirmed,
            ),
            snapshot,
        )


# ---------------------------------------------------------------------------
# 9. Observer / synthetic mirrors
# ---------------------------------------------------------------------------


class ObserverSyntheticMirrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_observer_may_act_on_synthetic_interrogator(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        # synthetic interrogator seat (test health room ids are negative)
        synthetic_uid = -1_000_001
        game.players = dict(game.players)
        game.players[synthetic_uid] = _p(
            synthetic_uid, 10, "بازپرس مصنوعی", Role.INTERROGATOR
        )
        del game.players[1]
        game.observer_user_id = 777
        game.no_host_interrog_ui_phase = "int1"
        with patch(
            "bot.no_host_interrogator_night._after_interrog_commit",
            new=AsyncMock(),
        ):
            cb = _StubCallback()
            await dispatch_no_host_interrogator_night(
                cb, _EditBot(), game, gm, int_uid=synthetic_uid,
                actor_uid=777, act="nii1", tid=2,
            )
        self.assertIn("انتخاب شد؛ تأیید کنید.", cb.alerts[0])
        self.assertEqual(game.no_host_interrog_pending_uids, [2])

    async def test_non_observer_actor_rejected_on_synthetic_panel(self) -> None:
        from bot.no_host_interrogator_night import dispatch_no_host_interrogator_night

        game, gm = _interrog_game()
        synthetic_uid = -1_000_002
        game.players = dict(game.players)
        game.players[synthetic_uid] = _p(
            synthetic_uid, 10, "بازپرس مصنوعی", Role.INTERROGATOR
        )
        del game.players[1]
        game.observer_user_id = 777
        cb = _StubCallback()
        await dispatch_no_host_interrogator_night(
            cb, _EditBot(), game, gm, int_uid=synthetic_uid,
            actor_uid=424242, act="nii1", tid=2,
        )
        self.assertEqual(
            cb.alerts, ["فقط بازپرس می‌تواند این انتخاب را انجام دهد."]
        )
        self.assertEqual(game.no_host_interrog_pending_uids, [])


# ---------------------------------------------------------------------------
# 10. Other scenarios unchanged
# ---------------------------------------------------------------------------


class OtherScenariosUnchangedTests(unittest.TestCase):
    def test_masoon_panels_unstyled(self) -> None:
        from bot.no_host_detective_night import _pick_keyboard
        from bot.no_host_doctor_night import _pick_keyboard as _doctor_kb
        from bot.no_host_interrogator_night import _int1_keyboard
        from bot.no_host_sniper_night import _pick_keyboard as _sniper_kb

        game, gm = _game("masoon")
        game.players[1].role = Role.DETECTIVE
        for kb in (_pick_keyboard(game, 1, gm),):
            self.assertTrue(
                all(
                    btn.style is None
                    for row in kb.inline_keyboard
                    for btn in row
                )
            )
        game.players[1].role = Role.DOCTOR
        game.no_host_doctor_pending_save_uids = [3]
        for row in _doctor_kb(game, 1, gm).inline_keyboard:
            for btn in row:
                self.assertIsNone(btn.style)
        game.players[1].role = Role.SNIPER
        for row in _sniper_kb(game, 1, gm).inline_keyboard:
            for btn in row:
                self.assertIsNone(btn.style)
        game.players[1].role = Role.INTERROGATOR
        for row in _int1_keyboard(game, 1, gm).inline_keyboard:
            for btn in row:
                self.assertIsNone(btn.style)

    def test_namayande_hunter_unstyled(self) -> None:
        from bot.no_host_night1 import _hunter_pick_keyboard

        game, gm = _game("namayande")
        game.players[1].role = Role.HUNTER
        kb = _hunter_pick_keyboard(game, 1, gm)
        self.assertTrue(
            all(btn.style is None for row in kb.inline_keyboard for btn in row)
        )

    def test_mozakere_keeps_part_c_scheme(self) -> None:
        """Mozakere keeps its own (pre-existing) inline confirm scheme."""
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        game, gm = _game("mozakere")
        game.players[1].role = Role.MAFIA_BOSS
        kb = _shot_pick_keyboard(game, 1, gm)
        confirms = _buttons_by_act(kb, "msc")
        self.assertEqual(len(confirms), 1)  # mozakere contract already inline
        self.assertEqual(confirms[0][0].style, "primary")


if __name__ == "__main__":
    unittest.main()
