"""Mozakere negotiation suspension + selection UI — regression tests.

Room 44 fixes:
* Initiation: live doctor/detective/sniper pick panels (player + observer
  mirrors) are edited IN PLACE to a keyboard-less neutral state; pick
  state is preserved (voiding stays at commit).
* Callback guard: doctor/detective/sniper dispatchers reject actions
  while the negotiation is pending, before any state mutation.
* Commit: existing reset rules run; suspended unconfirmed detective/sniper
  panels are re-delivered actionable.
* Force-finish with pending negotiation unblocks the guard without voiding.
* Negotiator target selection: selected target RED, others BLUE, green
  inline confirm, same-message edits, no duplicate panels.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.observer_delivery import PlayerMirrorCb

MAF = 202
NEG = 201
DOC = 301
DET = 302
SNIP = 303
JR = 304
CIT = 401
CIT2 = 402
OBS = 999
ASSISTANT = 108214166

SUSPENDED_TEXT = "در حال مذاکره"


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


class StubBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, object]] = []
        self.edits: list[tuple[int, int, object, object]] = []
        self.deleted: list[tuple[int, int]] = []
        self._mid = 5000

    async def send_message(self, chat_id, text=None, reply_markup=None, **kw):  # noqa: ANN001
        self._mid += 1
        self.sent.append((int(chat_id), str(text), reply_markup))
        return SimpleNamespace(message_id=self._mid, chat=SimpleNamespace(id=chat_id))

    async def edit_message_text(self, chat_id, message_id, text=None, reply_markup=None, **kw):  # noqa: ANN001
        self.edits.append((int(chat_id), int(message_id), text, reply_markup))
        return True

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None, **kw):  # noqa: ANN001
        self.edits.append((int(chat_id), int(message_id), None, reply_markup))
        return True

    async def delete_message(self, chat_id, message_id):  # noqa: ANN001
        self.deleted.append((int(chat_id), int(message_id)))
        return True


class Cb:
    def __init__(self, uid: int, msg_id: int) -> None:
        self.from_user = SimpleNamespace(id=uid)
        self.message = SimpleNamespace(message_id=msg_id)
        self.alerts: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False, **kw):  # noqa: ANN001
        self.alerts.append((text, show_alert))


def make_game(*, with_observer: bool = False) -> tuple[GameManager, Game]:
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=11,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "RM9"
    game.roles_dealt = True
    roster = (
        (MAF, 1, "مافیا ساده", Role.MAFIA_SIMPLE),
        (NEG, 2, "مذاکره‌کننده", Role.MAFIA_NEGOTIATOR),
        (DOC, 3, "پزشک", Role.DOCTOR),
        (DET, 4, "کارآگاه", Role.DETECTIVE),
        (SNIP, 5, "تک‌تیرانداز", Role.SNIPER),
        (JR, 6, "خبرنگار", Role.JOURNALIST),
        (CIT, 7, "شهروند", Role.CITIZEN),
        (CIT2, 8, "شهروند۲", Role.CITIZEN),
    )
    for uid, seat, name, role in roster:
        gm.add_player(game, _p(uid, seat, name, role))
    # negotiation threshold (11 players → 1 eliminated original mafia)
    game.players[MAF].is_alive = False
    game.bot_assistant_user_id = ASSISTANT
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = "night_actions"
    game.bazpors_narrator_night_count = 1
    if with_observer:
        game.observer_user_id = OBS
        game.observer_full_name = "ناظر"
        game.observer_prompt_status = "registered"
    return gm, game


def tracked(game: Game, ui_key: str, role: str = "player"):
    ref = (game.mirror_prompt_messages.get(ui_key) or {}).get(role)
    return tuple(int(x) for x in ref) if isinstance(ref, tuple) else None


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def start_role_panels(bot: StubBot, game: Game, gm: GameManager) -> dict[str, int]:
    from bot.no_host_detective_night import start_no_host_detective_night_flow
    from bot.no_host_doctor_night import start_no_host_doctor_night_flow
    from bot.no_host_sniper_night import start_no_host_sniper_night_flow

    msgs: dict[str, int] = {}
    assert run(start_no_host_doctor_night_flow(bot, game, gm, at_night_entry=True))
    assert run(start_no_host_detective_night_flow(bot, game, gm, at_night_entry=True))
    assert run(start_no_host_sniper_night_flow(bot, game, gm, at_night_entry=True))
    msgs["doc"] = tracked(game, _ui_key(game, "doctor"))[1]
    msgs["det"] = tracked(game, _ui_key(game, "detective"))[1]
    msgs["snip"] = tracked(game, _ui_key(game, "sniper"))[1]
    return msgs


def _ui_key(game: Game, role: str) -> str:
    from bot.observer_delivery import mirror_ui_claim_key

    kind = {"doc": "doctor", "doctor": "doctor", "det": "detective",
            "detective": "detective", "snip": "sniper", "sniper": "sniper"}[role]
    uid = {"doctor": DOC, "detective": DET, "sniper": SNIP}[kind]
    return mirror_ui_claim_key(game.room_code, f"no_host_{kind}", uid)


def negotiate_start(bot: StubBot, game: Game, gm: GameManager) -> None:
    from bot.no_host_mafia_night1 import _finalize_mozakere_negotiate_action

    with patch(
        "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
        new=AsyncMock(),
    ), patch(
        "bot.no_host_mozakere_negotiation.broadcast_to_alive_players",
        new=AsyncMock(),
    ):
        run(
            _finalize_mozakere_negotiate_action(
                bot, game, gm, mafia_uid=MAF, actor_uid=MAF
            )
        )


def commit_negotiation(bot: StubBot, game: Game, gm: GameManager, target: int) -> None:
    from bot.no_host_mozakere_negotiation import (
        _negotiator_ui_key,
        dispatch_no_host_mozakere_negotiator,
    )

    neg_msg = tracked(game, _negotiator_ui_key(game, NEG))[1]
    game.no_host_negotiator_pending_tid = target
    with patch(
        "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
        new=AsyncMock(),
    ):
        run(
            dispatch_no_host_mozakere_negotiator(
                Cb(NEG, neg_msg),
                bot,
                game,
                gm,
                neg_uid=NEG,
                actor_uid=NEG,
                act="negc",
                tid=0,
            )
        )


def buttons(kb) -> list:
    if kb is None:
        return []
    return [b for row in kb.inline_keyboard for b in row]


def find_btn(kb, act: str, tid: int | None = None):
    for b in buttons(kb):
        try:
            cb = PlayerMirrorCb.unpack(b.callback_data)
        except Exception:
            continue
        if cb.act == act and (tid is None or cb.tid == tid):
            return b
    return None


def latest_edit_kb(bot: StubBot, chat_id: int, message_id: int):
    for c, m, _text, kb in reversed(bot.edits):
        if c == chat_id and m == message_id and kb is not None:
            return kb
    return None


class SuspensionTests(unittest.TestCase):
    def test_suspension_closes_unconfirmed_panels_in_place(self) -> None:
        from bot.no_host_mozakere_negotiation_reset import (
            suspend_mozakere_town_panels_for_negotiation,
        )
        from bot.roles.night_state import mozakere_negotiation_night_state

        gm, game = make_game()
        bot = StubBot()
        msgs = start_role_panels(bot, game, gm)
        game.no_host_detective_pending_tid = NEG  # pending pick preserved
        sends_before = len(bot.sent)
        mozakere_negotiation_night_state(game).tonight = True

        count = run(suspend_mozakere_town_panels_for_negotiation(bot, game))
        self.assertEqual(count, 3)
        for role, uid in (("doc", DOC), ("det", DET), ("snip", SNIP)):
            # edited in place, no new messages, refs preserved
            self.assertNotIn((uid, msgs[role]), bot.deleted)
            self.assertTrue(
                any(c == uid and m == msgs[role] for c, m, *_ in bot.edits)
            )
            entry = game.mirror_prompt_messages.get(_ui_key(game, role)) or {}
            self.assertIsNotNone(entry.get("player"))
            self.assertIn(SUSPENDED_TEXT, str(entry.get("text") or ""))
        self.assertEqual(len(bot.sent), sends_before)
        # pick state untouched
        self.assertFalse(game.no_host_doctor_pick_confirmed)
        self.assertFalse(game.no_host_detective_pick_confirmed)
        self.assertFalse(game.no_host_sniper_pick_confirmed)
        self.assertEqual(game.no_host_detective_pending_tid, NEG)
        # signatures untouched → reconcile will not re-deliver
        self.assertEqual(game.no_host_detective_dm_signature, "1:det:mozakere_pick")

    def test_confirmed_doctor_excluded_from_suspension(self) -> None:
        from bot.no_host_mozakere_negotiation_reset import (
            suspend_mozakere_town_panels_for_negotiation,
        )
        from bot.roles.night_state import mozakere_negotiation_night_state

        gm, game = make_game()
        bot = StubBot()
        msgs = start_role_panels(bot, game, gm)
        game.no_host_doctor_pick_confirmed = True
        mozakere_negotiation_night_state(game).tonight = True
        count = run(suspend_mozakere_town_panels_for_negotiation(bot, game))
        self.assertEqual(count, 2)
        self.assertFalse(
            any(c == DOC and m == msgs["doc"] for c, m, *_ in bot.edits)
        )

    def test_observer_mirror_suspended_too(self) -> None:
        from bot.no_host_mozakere_negotiation_reset import (
            suspend_mozakere_town_panels_for_negotiation,
        )
        from bot.roles.night_state import mozakere_negotiation_night_state

        gm, game = make_game(with_observer=True)
        bot = StubBot()
        start_role_panels(bot, game, gm)
        det_key = _ui_key(game, "detective")
        obs_msg = tracked(game, det_key, "observer")
        self.assertIsNotNone(obs_msg)
        mozakere_negotiation_night_state(game).tonight = True
        count = run(suspend_mozakere_town_panels_for_negotiation(bot, game))
        self.assertEqual(count, 3)
        self.assertTrue(
            any(c == OBS and m == obs_msg[1] for c, m, *_ in bot.edits)
        )
        # synthetic sniper: the suspension edit reaches its mirror chat too
        snip_key = _ui_key(game, "sniper")
        snip_ref = tracked(game, snip_key)
        self.assertTrue(
            any(c == snip_ref[0] and m == snip_ref[1] for c, m, *_ in bot.edits)
        )

    def test_initiation_path_suspends_and_keeps_state(self) -> None:
        from bot.roles.night_state import mozakere_negotiation_night_state

        gm, game = make_game()
        bot = StubBot()
        start_role_panels(bot, game, gm)
        negotiate_start(bot, game, gm)
        self.assertTrue(mozakere_negotiation_night_state(game).tonight)
        self.assertFalse(game.no_host_negotiator_pick_confirmed)
        det_key = _ui_key(game, "detective")
        entry = game.mirror_prompt_messages.get(det_key) or {}
        self.assertIn(SUSPENDED_TEXT, str(entry.get("text") or ""))
        self.assertIsNotNone(tracked(game, det_key))
        # detective panel is keyboard-less now (kb=None suspension edit)
        det_edits = [e for e in bot.edits if e[0] == DET and e[1] == tracked(game, det_key)[1]]
        self.assertTrue(det_edits)
        text, kb = det_edits[-1][2], det_edits[-1][3]
        self.assertIn(SUSPENDED_TEXT, str(text))
        self.assertTrue(kb is None or buttons(kb) == [])


class PendingGuardTests(unittest.TestCase):
    def test_doctor_detective_sniper_rejected_during_pending(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        start_role_panels(bot, game, gm)
        negotiate_start(bot, game, gm)
        game.no_host_doctor_pick_confirmed = False

        from bot.no_host_detective_night import dispatch_no_host_detective_night
        from bot.no_host_doctor_night import dispatch_no_host_doctor_night
        from bot.no_host_sniper_night import dispatch_no_host_sniper_night

        det_msg = tracked(game, _ui_key(game, "detective"))[1]
        cb = Cb(DET, det_msg)
        run(
            dispatch_no_host_detective_night(
                cb, bot, game, gm, det_uid=DET, actor_uid=DET, act="ndp", tid=CIT
            )
        )
        self.assertTrue(any("مذاکره" in (a[0] or "") for a in cb.alerts))
        self.assertIsNone(game.no_host_detective_pending_tid)

        doc_msg = tracked(game, _ui_key(game, "doctor"))[1]
        cb2 = Cb(DOC, doc_msg)
        run(
            dispatch_no_host_doctor_night(
                cb2, bot, game, gm, doc_uid=DOC, actor_uid=DOC, act="dkt", tid=CIT
            )
        )
        self.assertTrue(any("مذاکره" in (a[0] or "") for a in cb2.alerts))

        snip_msg = tracked(game, _ui_key(game, "sniper"))[1]
        cb3 = Cb(SNIP, snip_msg)
        run(
            dispatch_no_host_sniper_night(
                cb3, bot, game, gm, sn_uid=SNIP, actor_uid=SNIP, act="skt", tid=CIT
            )
        )
        self.assertTrue(any("مذاکره" in (a[0] or "") for a in cb3.alerts))

    def test_guard_lifts_after_commit_and_replacement_actionable(self) -> None:
        from bot.no_host_detective_night import dispatch_no_host_detective_night
        from bot.no_host_mozakere_negotiation_reset import (
            mozakere_negotiation_pending,
        )
        from bot.roles.night_state import mozakere_negotiation_night_state

        gm, game = make_game()
        bot = StubBot()
        start_role_panels(bot, game, gm)
        negotiate_start(bot, game, gm)
        commit_negotiation(bot, game, gm, CIT)
        self.assertTrue(mozakere_negotiation_night_state(game).used)
        self.assertFalse(mozakere_negotiation_pending(game))

        # detective was unconfirmed → suspended panel replaced by a fresh
        # actionable panel
        det_key = _ui_key(game, "detective")
        old_msg = None
        new_ref = tracked(game, det_key)
        self.assertIsNotNone(new_ref)
        cb = Cb(DET, new_ref[1])
        run(
            dispatch_no_host_detective_night(
                cb, bot, game, gm, det_uid=DET, actor_uid=DET, act="ndp", tid=CIT
            )
        )
        self.assertFalse(any("مذاکره" in (a[0] or "") for a in cb.alerts))
        self.assertEqual(game.no_host_detective_pending_tid, CIT)

        # doctor (unconfirmed) received the negotiation-skip panel
        from bot.no_host_mozakere_negotiation_reset import (
            mozakere_doctor_negotiation_skip_active,
        )

        self.assertTrue(mozakere_doctor_negotiation_skip_active(game))

    def test_commit_replaces_suspended_sniper_panel(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        start_role_panels(bot, game, gm)
        negotiate_start(bot, game, gm)
        old_snip = tracked(game, _ui_key(game, "sniper"))
        commit_negotiation(bot, game, gm, CIT)
        new_snip = tracked(game, _ui_key(game, "sniper"))
        self.assertIsNotNone(new_snip)
        self.assertNotEqual(new_snip[1], old_snip[1])
        self.assertIn((SNIP, old_snip[1]), bot.deleted)
        # fresh sniper panel is actionable
        from bot.no_host_sniper_night import dispatch_no_host_sniper_night

        cb = Cb(SNIP, new_snip[1])
        run(
            dispatch_no_host_sniper_night(
                cb, bot, game, gm, sn_uid=SNIP, actor_uid=SNIP, act="skt", tid=CIT
            )
        )
        self.assertFalse(any("مذاکره" in (a[0] or "") for a in cb.alerts))

    def test_confirmed_doctor_voided_only_at_commit(self) -> None:
        from bot.no_host_mozakere_negotiation_reset import (
            mozakere_doctor_negotiation_skip_active,
            mozakere_doctor_negotiation_skip_signature,
        )

        gm, game = make_game()
        bot = StubBot()
        msgs = start_role_panels(bot, game, gm)
        # doctor confirmed a save BEFORE negotiation started
        game.no_host_doctor_pick_confirmed = True
        game.no_host_doctor_dm_signature = "1:doc:night_entry"
        negotiate_start(bot, game, gm)
        # preserved through the pending window (skip state not yet applied)
        self.assertFalse(mozakere_doctor_negotiation_skip_active(game))
        commit_negotiation(bot, game, gm, CIT)
        # now voided + skip signature applied, same message cleared
        self.assertTrue(mozakere_doctor_negotiation_skip_active(game))
        self.assertEqual(
            game.no_host_doctor_dm_signature,
            mozakere_doctor_negotiation_skip_signature(game),
        )
        # the skip panel replaces the old panel in place (edit may be
        # keyboard-less, since the skip state carries no buttons)
        self.assertTrue(
            any(c == DOC and m == msgs["doc"] for c, m, *_ in bot.edits)
        )


class AbandonTests(unittest.TestCase):
    def test_force_finish_pending_unblocks_without_voiding(self) -> None:
        from bot.mozakere_force_finish_night import (
            _normalize_pending_mozakere_mafia_actions,
        )
        from bot.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE
        from bot.no_host_mozakere_negotiation_reset import (
            mozakere_negotiation_pending,
        )
        from bot.roles.night_state import mozakere_negotiation_night_state

        gm, game = make_game()
        bot = StubBot()
        start_role_panels(bot, game, gm)
        negotiate_start(bot, game, gm)
        game.no_host_detective_pending_tid = NEG
        self.assertTrue(mozakere_negotiation_pending(game))

        forced = _normalize_pending_mozakere_mafia_actions(game)
        self.assertIn("negotiator", forced)
        self.assertFalse(mozakere_negotiation_night_state(game).tonight)
        self.assertFalse(mozakere_negotiation_pending(game))
        # prior pending pick preserved (not voided by force-finish)
        self.assertEqual(game.no_host_detective_pending_tid, NEG)
        self.assertFalse(game.no_host_detective_pick_confirmed)

    def test_reconcile_does_not_reopen_suspended_panels(self) -> None:
        from bot.no_host_night_reconcile import _restore_missing_actionable_panels

        gm, game = make_game()
        bot = StubBot()
        start_role_panels(bot, game, gm)
        negotiate_start(bot, game, gm)
        before = len(bot.sent)
        run(_restore_missing_actionable_panels(bot, game, gm))
        for uid in (DOC, DET, SNIP):
            self.assertEqual(
                len([s for s in bot.sent if s[0] == uid]),
                len([s for s in bot.sent if s[0] == uid and True])  # sanity
                if False else len([1 for s in bot.sent[:before] if s[0] == uid]),
            )


class SelectionUITests(unittest.TestCase):
    def _flow(self):
        from bot.no_host_mozakere_negotiation import (
            start_no_host_mozakere_negotiator_flow,
        )

        gm, game = make_game()
        bot = StubBot()
        self.assertTrue(run(start_no_host_mozakere_negotiator_flow(bot, game, gm)))
        neg_msg = tracked(game, _negotiator_key(game))[1]
        return gm, game, bot, neg_msg

    def _dispatch(self, gm, game, bot, neg_msg, act, tid):
        from bot.no_host_mozakere_negotiation import (
            dispatch_no_host_mozakere_negotiator,
        )

        cb = Cb(NEG, neg_msg)
        run(
            dispatch_no_host_mozakere_negotiator(
                cb, bot, game, gm, neg_uid=NEG, actor_uid=NEG, act=act, tid=tid
            )
        )
        return cb

    def test_selected_target_red_others_blue_confirm_green(self) -> None:
        gm, game, bot, neg_msg = self._flow()
        sends_before = len(bot.sent)
        self._dispatch(gm, game, bot, neg_msg, "negp", CIT)
        # same message edited, no duplicate panel
        self.assertEqual(len(bot.sent), sends_before)
        kb = latest_edit_kb(bot, NEG, neg_msg)
        self.assertIsNotNone(kb)
        self.assertEqual(getattr(find_btn(kb, "negp", CIT), "style", None), "danger")
        self.assertEqual(getattr(find_btn(kb, "negp", DET), "style", None), "primary")
        self.assertEqual(getattr(find_btn(kb, "negc"), "style", None), "success")
        # not committed yet
        from bot.roles.night_state import mozakere_negotiation_night_state

        self.assertFalse(mozakere_negotiation_night_state(game).used)
        self.assertEqual(game.no_host_negotiator_pending_tid, CIT)

    def test_moving_selection_moves_red_highlight(self) -> None:
        gm, game, bot, neg_msg = self._flow()
        self._dispatch(gm, game, bot, neg_msg, "negp", CIT)
        self._dispatch(gm, game, bot, neg_msg, "negp", DET)
        kb = latest_edit_kb(bot, NEG, neg_msg)
        self.assertEqual(getattr(find_btn(kb, "negp", DET), "style", None), "danger")
        self.assertEqual(getattr(find_btn(kb, "negp", CIT), "style", None), "primary")
        self.assertEqual(len(bot.sent), 1)  # still the original panel only

    def test_repress_deselects(self) -> None:
        gm, game, bot, neg_msg = self._flow()
        self._dispatch(gm, game, bot, neg_msg, "negp", CIT)
        self._dispatch(gm, game, bot, neg_msg, "negp", CIT)  # toggle off
        kb = latest_edit_kb(bot, NEG, neg_msg)
        for b in buttons(kb):
            if getattr(b, "style", None) is not None and b.callback_data.find("negc") == -1:
                self.assertEqual(b.style, "primary")
        self.assertIsNone(game.no_host_negotiator_pending_tid)


def _negotiator_key(game: Game) -> str:
    from bot.no_host_mozakere_negotiation import _negotiator_ui_key

    return _negotiator_ui_key(game, NEG)


class OtherScenarioTests(unittest.TestCase):
    def test_suspension_noop_for_non_mozakere(self) -> None:
        from bot.no_host_mozakere_negotiation_reset import (
            mozakere_negotiation_pending,
            suspend_mozakere_town_panels_for_negotiation,
        )
        from bot.roles.night_state import mozakere_negotiation_night_state

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        mozakere_negotiation_night_state(game).tonight = True
        self.assertFalse(mozakere_negotiation_pending(game))
        self.assertEqual(
            run(suspend_mozakere_town_panels_for_negotiation(StubBot(), game)), 0
        )


if __name__ == "__main__":
    unittest.main()
