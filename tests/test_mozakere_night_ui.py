"""پنل‌های شب مذاکره — انتخاب درون‌خطی (آبی/قرمز) + تأیید در همان صفحه."""

from __future__ import annotations

import importlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_role_pick_common import (
    MOZAKERE_CONFIRM_LABEL,
    apply_bazpors_panel_styles,
    build_pick_keyboard,
    build_target_button_rows,
    panel_style_scheme,
    with_inline_confirm_row,
)


def _p(uid: int, name: str, role: Role, *, seat: int | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _mozakere_no_host(gm: GameManager, *, night: int = 1):
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_night_count = night
    return game


def _cast(gm: GameManager, game, boss_role: Role = Role.MAFIA_BOSS) -> None:
    gm.add_player(game, _p(10, "Boss", boss_role, seat=1))
    gm.add_player(game, _p(20, "A", Role.CITIZEN, seat=2))
    gm.add_player(game, _p(30, "B", Role.CITIZEN, seat=3))
    gm.add_player(game, _p(40, "C", Role.CITIZEN, seat=4))


def _buttons(kb):
    return [btn for row in kb.inline_keyboard for btn in row]


def _mods_patchable(module: str, names: list[str]) -> list[str]:
    mod = importlib.import_module(f"bot.{module}")
    return [n for n in names if hasattr(mod, n)]


async def _dispatch(game, gm, module, fn, **kwargs):
    """Dispatch a role-panel callback with mirror/telemetry edges mocked."""
    import inspect

    if "tid" in inspect.signature(fn).parameters:
        kwargs.setdefault("tid", 0)
    callback = MagicMock()
    callback.answer = AsyncMock()
    bot = AsyncMock()
    patchable = _mods_patchable(
        module,
        [
            "update_mirror_prompt_pair",
            "register_mirror_prompt_pair",
            "publish_no_host_night_wait_panel",
            "no_host_after_role_night_pick",
        ],
    )
    ctxs = []
    for name in patchable:
        ctxs.append(patch(f"bot.{module}.{name}", new_callable=AsyncMock))
    if _mods_patchable(module, ["no_host_night_wait_phase_active"]):
        ctxs.append(
            patch(
                f"bot.{module}.no_host_night_wait_phase_active",
                return_value=True,
            )
        )
    with patch("bot.no_host_night_ready.no_host_parallel_night_collect_active", return_value=False), patch(
        "bot.no_host_mafia_shot.apply_mirror_claim_winner", new_callable=AsyncMock
    ), patch(
        "bot.no_host_mafia_shot.no_host_observer_registered", return_value=False
    ):
        async with _exit_stack(ctxs):
            await fn(callback, bot, game, gm, **kwargs)
    return callback


class _exit_stack:
    def __init__(self, ctxs):
        self._ctxs = ctxs
        self._stack = None

    async def __aenter__(self):
        from contextlib import AsyncExitStack

        self._stack = AsyncExitStack()
        for ctx in self._ctxs:
            self._stack.enter_context(ctx)
        return self

    async def __aexit__(self, *exc):
        return await self._stack.__aexit__(*exc)


class PanelStyleSchemeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_scheme_matrix(self) -> None:
        mz = _mozakere_no_host(self.gm)
        self.assertEqual(panel_style_scheme(mz), "mozakere")
        bz = self.gm.create_game(
            host_id=2, scenario_name="bazpors", max_players=10
        )
        assert bz is not None
        self.assertEqual(panel_style_scheme(bz), "bazpors")
        nm = self.gm.create_game(
            host_id=3, scenario_name="namayande", max_players=10
        )
        assert nm is not None
        self.assertIsNone(panel_style_scheme(nm))

    def test_target_rows_blue_unselected_red_selected(self) -> None:
        game = _mozakere_no_host(self.gm)
        _cast(self.gm, game)
        players = [game.players[u] for u in (20, 30, 40)]
        rows = build_target_button_rows(
            game, as_uid=10, pick_act="msk", players=players, selected_uids=[30]
        )
        flat = [btn for row in rows for btn in row]
        self.assertEqual([b.style for b in flat], ["primary", "danger", "primary"])

    def test_none_row_follows_none_selected(self) -> None:
        game = _mozakere_no_host(self.gm)
        _cast(self.gm, game)
        players = [game.players[u] for u in (20, 30, 40)]
        kb_off = build_pick_keyboard(
            game,
            10,
            pick_act="msk",
            players=players,
            none_act="msn",
            none_text="انتخابی ندارم",
        )
        none_btn_off = _buttons(kb_off)[-1]
        self.assertEqual(none_btn_off.style, "primary")
        kb_on = build_pick_keyboard(
            game,
            10,
            pick_act="msk",
            players=players,
            none_act="msn",
            none_text="انتخابی ندارم",
            none_selected=True,
        )
        none_btn_on = _buttons(kb_on)[-1]
        self.assertEqual(none_btn_on.style, "danger")

    def test_inline_confirm_row(self) -> None:
        game = _mozakere_no_host(self.gm)
        _cast(self.gm, game)
        players = [game.players[u] for u in (20, 30, 40)]
        base = build_pick_keyboard(game, 10, pick_act="msk", players=players)
        kb = with_inline_confirm_row(
            game, 10, base, confirm_act="msc"
        )
        confirm_btn = kb.inline_keyboard[-1][0]
        self.assertEqual(confirm_btn.text, MOZAKERE_CONFIRM_LABEL)
        self.assertIn(":msc:", confirm_btn.callback_data)
        self.assertEqual(confirm_btn.style, "primary")
        # ردیف‌های قبلی دست‌نخورده‌اند
        self.assertEqual(
            kb.inline_keyboard[:-1], [list(r) for r in base.inline_keyboard]
        )

    def test_apply_styles_mozakere_default(self) -> None:
        game = _mozakere_no_host(self.gm)
        _cast(self.gm, game)
        kb = build_pick_keyboard(
            game,
            10,
            pick_act="msk",
            players=[game.players[u] for u in (20, 30, 40)],
        )
        styled = apply_bazpors_panel_styles(
            game, kb, pick_acts={"msk"}, selected_uids=[30], ok_acts={"msc"}
        )
        styles = [b.style for b in _buttons(styled)]
        self.assertEqual(styles, ["primary", "danger", "primary"])

    def test_apply_styles_other_scenario_untouched(self) -> None:
        nm = self.gm.create_game(
            host_id=3, scenario_name="namayande", max_players=10
        )
        assert nm is not None
        _cast(self.gm, nm)
        kb = build_pick_keyboard(
            nm,
            10,
            pick_act="msk",
            players=[nm.players[u] for u in (20, 30, 40)],
        )
        styled = apply_bazpors_panel_styles(
            nm, kb, pick_acts={"msk"}, selected_uids=[30]
        )
        self.assertTrue(all(b.style is None for b in _buttons(styled)))


class MafiaMenuPendingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mozakere_no_host(self.gm)
        _cast(self.gm, self.game)
        self.game.no_host_mafia_night1_flow_active = True
        self.game.no_host_mafia_night1_panel_uids = [10]
        self.game.no_host_mafia_night1_done = False

    async def test_pick_is_pending_until_confirm(self) -> None:
        from bot.no_host_mafia_night1 import (
            MAFIA_ACTION_SHOT,
            dispatch_no_host_mafia_night1,
        )

        await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_night1",
            dispatch_no_host_mafia_night1,
            mafia_uid=10,
            actor_uid=10,
            act="nms",
        )
        self.assertEqual(
            self.game.no_host_mafia_night1_pending_action, MAFIA_ACTION_SHOT
        )
        self.assertFalse(self.game.no_host_mafia_night1_done)

    async def test_back_clears_pending(self) -> None:
        from bot.no_host_mafia_night1 import dispatch_no_host_mafia_night1

        self.game.no_host_mafia_night1_pending_action = "shot"
        await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_night1",
            dispatch_no_host_mafia_night1,
            mafia_uid=10,
            actor_uid=10,
            act="nmb",
        )
        self.assertIsNone(self.game.no_host_mafia_night1_pending_action)


class MafiaShotInlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mozakere_no_host(self.gm)
        _cast(self.gm, self.game)
        self.game.no_host_mafia_shot_flow_active = True
        self.game.no_host_mafia_shot_done = False
        self.game.no_host_mafia_night1_panel_uids = [10]

    def test_pick_keyboard_has_confirm_row(self) -> None:
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        self.game.no_host_mafia_shot_pending_uid = 20
        kb = _shot_pick_keyboard(self.game, 10, self.gm)
        confirm_btn = kb.inline_keyboard[-1][0]
        self.assertEqual(confirm_btn.text, MOZAKERE_CONFIRM_LABEL)
        self.assertIn(":msc:", confirm_btn.callback_data)
        target_btns = [b for row in kb.inline_keyboard[:-1] for b in row]
        by_uid = {}
        for b in target_btns:
            parts = b.callback_data.split(":")
            by_uid[int(parts[4])] = b.style
        self.assertEqual(by_uid[20], "danger")
        self.assertEqual(by_uid[30], "primary")

    def test_exactly_one_confirm_button_before_and_after_selection(self) -> None:
        """اتاق ۲۶ — دکمهٔ تأیید تکراری نباید پس از انتخاب ظاهر شود."""
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        def _confirm_count(kb):
            return [
                b
                for row in kb.inline_keyboard
                for b in row
                if ":msc:" in (b.callback_data or "")
            ]

        # قبل از انتخاب
        kb = _shot_pick_keyboard(self.game, 10, self.gm)
        self.assertEqual(len(_confirm_count(kb)), 1)
        # پس از انتخاب هدف
        self.game.no_host_mafia_shot_pending_uid = 20
        kb = _shot_pick_keyboard(self.game, 10, self.gm)
        self.assertEqual(len(_confirm_count(kb)), 1)

    def test_successor_shot_panel_single_confirm(self) -> None:
        """پنل شات با هر عضو مافیا (جانشین) — فقط یک دکمهٔ تأیید."""
        from bot.no_host_mafia_shot import _shot_pick_keyboard

        self.game.no_host_mafia_shot_pending_uid = 30
        kb = _shot_pick_keyboard(self.game, 20, self.gm)
        confirms = [
            b
            for row in kb.inline_keyboard
            for b in row
            if ":msc:" in (b.callback_data or "")
        ]
        self.assertEqual(len(confirms), 1)
        self.assertIn(f":msc:20:", confirms[0].callback_data)

    async def test_reselect_dispatch_renders_single_confirm(self) -> None:
        """مسیر انتخاب/جایگزینی — پنل سینک‌شده دقیقاً یک دکمهٔ تأیید دارد."""
        from bot.no_host_mafia_shot import dispatch_no_host_mafia_shot

        captured_kbs: list = []

        async def _fake_sync(bot, game, mafia_uid, text, kb):
            captured_kbs.append(kb)

        with patch(
            "bot.no_host_mafia_shot._sync_mafia_shot_mirror_panel",
            new_callable=AsyncMock,
            side_effect=_fake_sync,
        ), patch(
            "bot.no_host_mafia_shot.no_host_observer_registered",
            return_value=False,
        ):
            for tid in (20, 30):
                callback = MagicMock()
                callback.answer = AsyncMock()
                await dispatch_no_host_mafia_shot(
                    callback,
                    AsyncMock(),
                    self.game,
                    self.gm,
                    mafia_uid=10,
                    actor_uid=10,
                    act="msk",
                    tid=tid,
                )
        self.assertEqual(self.game.no_host_mafia_shot_pending_uid, 30)
        self.assertEqual(len(captured_kbs), 2)
        for kb in captured_kbs:
            confirms = [
                b
                for row in kb.inline_keyboard
                for b in row
                if ":msc:" in (b.callback_data or "")
            ]
            self.assertEqual(len(confirms), 1)
        self.assertEqual(captured_kbs[0].inline_keyboard[-1][0].style, "primary")

    async def _press(self, act, tid):
        from bot.no_host_mafia_shot import dispatch_no_host_mafia_shot

        callback = MagicMock()
        callback.answer = AsyncMock()
        await dispatch_no_host_mafia_shot(
            callback,
            AsyncMock(),
            self.game,
            self.gm,
            mafia_uid=10,
            actor_uid=10,
            act=act,
            tid=tid,
        )
        return callback

    async def test_confirm_executes_exactly_once(self) -> None:
        from bot.no_host_mafia_shot import dispatch_no_host_mafia_shot
        from bot.roles.night_state import mafia_night_state

        with patch(
            "bot.no_host_mafia_shot._sync_mafia_shot_mirror_panel",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_shot.no_host_observer_registered",
            return_value=False,
        ), patch(
            "bot.no_host_mafia_shot.finalize_no_host_role_pick_message",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_shot.notify_mafia_team_shot_result",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_shot._maybe_redispatch_saboteur_panel_after_mafia_shot",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_night_ready.no_host_parallel_night_collect_active",
            return_value=False,
        ):
            callback = MagicMock()
            callback.answer = AsyncMock()
            for act, tid in (("msk", 20), ("msc", 0), ("msc", 0)):
                await dispatch_no_host_mafia_shot(
                    callback, AsyncMock(), self.game, self.gm,
                    mafia_uid=10, actor_uid=10, act=act, tid=tid,
                )
        state = mafia_night_state(self.game)
        # ثبت هدف دقیقاً یک‌بار — فشاردوم تأیید اثر اضافه نمی‌کند
        self.assertEqual(state.target_uid, 20)
        self.assertTrue(state.shot_registered)
        self.assertTrue(state.no_host_done)
        self.assertTrue(self.game.no_host_mafia_shot_done)
        # فشردن دوبارهٔ تأیید: فلو بسته شده و هیچ ثبت جدیدی رخ نمی‌دهد
        callback.answer.assert_any_call(
            "این مرحله دیگر فعال نیست.", show_alert=True
        )

    async def test_pending_then_replace_then_toggle(self) -> None:
        from bot.no_host_mafia_shot import dispatch_no_host_mafia_shot

        await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_shot",
            dispatch_no_host_mafia_shot,
            mafia_uid=10,
            actor_uid=10,
            act="msk",
            tid=20,
        )
        self.assertEqual(self.game.no_host_mafia_shot_pending_uid, 20)
        self.assertFalse(self.game.no_host_mafia_shot_done)
        # هدف جدید جایگزین می‌شود (تک‌هدف)
        await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_shot",
            dispatch_no_host_mafia_shot,
            mafia_uid=10,
            actor_uid=10,
            act="msk",
            tid=30,
        )
        self.assertEqual(self.game.no_host_mafia_shot_pending_uid, 30)
        # زدن دوباره = لغو
        await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_shot",
            dispatch_no_host_mafia_shot,
            mafia_uid=10,
            actor_uid=10,
            act="msk",
            tid=30,
        )
        self.assertIsNone(self.game.no_host_mafia_shot_pending_uid)

    async def test_confirm_commits_once(self) -> None:
        from bot.no_host_mafia_shot import dispatch_no_host_mafia_shot
        from bot.roles.night_state import mafia_night_state

        await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_shot",
            dispatch_no_host_mafia_shot,
            mafia_uid=10,
            actor_uid=10,
            act="msk",
            tid=20,
        )
        await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_shot",
            dispatch_no_host_mafia_shot,
            mafia_uid=10,
            actor_uid=10,
            act="msc",
        )
        mafia = mafia_night_state(self.game)
        self.assertTrue(mafia.no_host_done)
        self.assertEqual(mafia.target_uid, 20)
        self.assertIsNone(self.game.no_host_mafia_shot_pending_uid)

    async def test_confirm_without_pick_rejected(self) -> None:
        from bot.no_host_mafia_shot import dispatch_no_host_mafia_shot

        callback = await _dispatch(
            self.game,
            self.gm,
            "no_host_mafia_shot",
            dispatch_no_host_mafia_shot,
            mafia_uid=10,
            actor_uid=10,
            act="msc",
        )
        callback.answer.assert_awaited()
        self.assertFalse(self.game.no_host_mafia_shot_done)


class DetectiveInlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mozakere_no_host(self.gm)
        _cast(self.gm, self.game, boss_role=Role.MAFIA_BOSS)
        self.gm.add_player(
            self.game, _p(11, "Det", Role.DETECTIVE, seat=5)
        )
        self.game.no_host_detective_flow_active = True
        self.game.no_host_detective_pick_confirmed = False

    async def test_pending_then_confirm(self) -> None:
        from bot.no_host_detective_night import (
            dispatch_no_host_detective_night,
        )

        await _dispatch(
            self.game,
            self.gm,
            "no_host_detective_night",
            dispatch_no_host_detective_night,
            det_uid=11,
            actor_uid=11,
            act="ndp",
            tid=20,
        )
        self.assertEqual(self.game.no_host_detective_pending_tid, 20)
        self.assertFalse(self.game.no_host_detective_pick_confirmed)
        self.assertNotEqual(self.game.actions.detective_check, 20)
        # تأیید در همان صفحه
        await _dispatch(
            self.game,
            self.gm,
            "no_host_detective_night",
            dispatch_no_host_detective_night,
            det_uid=11,
            actor_uid=11,
            act="ndc",
        )
        self.assertEqual(self.game.actions.detective_check, 20)
        self.assertTrue(self.game.no_host_detective_pick_confirmed)
        self.assertIsNone(self.game.no_host_detective_pending_tid)

    async def test_toggle_deselects(self) -> None:
        from bot.no_host_detective_night import (
            dispatch_no_host_detective_night,
        )

        await _dispatch(
            self.game,
            self.gm,
            "no_host_detective_night",
            dispatch_no_host_detective_night,
            det_uid=11,
            actor_uid=11,
            act="ndp",
            tid=20,
        )
        await _dispatch(
            self.game,
            self.gm,
            "no_host_detective_night",
            dispatch_no_host_detective_night,
            det_uid=11,
            actor_uid=11,
            act="ndp",
            tid=20,
        )
        self.assertIsNone(self.game.no_host_detective_pending_tid)
        self.assertFalse(self.game.no_host_detective_pick_confirmed)

    async def test_confirm_without_pick_rejected(self) -> None:
        from bot.no_host_detective_night import (
            dispatch_no_host_detective_night,
        )

        await _dispatch(
            self.game,
            self.gm,
            "no_host_detective_night",
            dispatch_no_host_detective_night,
            det_uid=11,
            actor_uid=11,
            act="ndc",
        )
        self.assertFalse(self.game.no_host_detective_pick_confirmed)


class SniperInlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mozakere_no_host(self.gm)
        _cast(self.gm, self.game)
        self.gm.add_player(self.game, _p(12, "Snp", Role.SNIPER, seat=5))
        self.game.no_host_sniper_flow_active = True
        self.game.no_host_sniper_pick_confirmed = False

    async def test_single_target_autoreplace_and_none(self) -> None:
        from bot.no_host_sniper_night import dispatch_no_host_sniper_night

        await _dispatch(
            self.game,
            self.gm,
            "no_host_sniper_night",
            dispatch_no_host_sniper_night,
            sn_uid=12,
            actor_uid=12,
            act="skt",
            tid=20,
        )
        self.assertEqual(self.game.no_host_sniper_pending_target_uid, 20)
        # هدف جدید جایگزین (تک‌هدف)
        await _dispatch(
            self.game,
            self.gm,
            "no_host_sniper_night",
            dispatch_no_host_sniper_night,
            sn_uid=12,
            actor_uid=12,
            act="skt",
            tid=30,
        )
        self.assertEqual(self.game.no_host_sniper_pending_target_uid, 30)
        # انتخابی ندارم
        await _dispatch(
            self.game,
            self.gm,
            "no_host_sniper_night",
            dispatch_no_host_sniper_night,
            sn_uid=12,
            actor_uid=12,
            act="skn",
        )
        self.assertTrue(self.game.no_host_sniper_pending_none)
        self.assertIsNone(self.game.no_host_sniper_pending_target_uid)
        self.assertFalse(self.game.no_host_sniper_pick_confirmed)

    async def test_confirm_commits_once(self) -> None:
        from bot.no_host_sniper_night import dispatch_no_host_sniper_night

        await _dispatch(
            self.game,
            self.gm,
            "no_host_sniper_night",
            dispatch_no_host_sniper_night,
            sn_uid=12,
            actor_uid=12,
            act="skt",
            tid=20,
        )
        await _dispatch(
            self.game,
            self.gm,
            "no_host_sniper_night",
            dispatch_no_host_sniper_night,
            sn_uid=12,
            actor_uid=12,
            act="skc",
        )
        self.assertTrue(self.game.no_host_sniper_pick_confirmed)
        self.assertFalse(self.game.no_host_sniper_flow_active)

    async def test_confirm_without_pick_rejected(self) -> None:
        from bot.no_host_sniper_night import dispatch_no_host_sniper_night

        await _dispatch(
            self.game,
            self.gm,
            "no_host_sniper_night",
            dispatch_no_host_sniper_night,
            sn_uid=12,
            actor_uid=12,
            act="skc",
        )
        self.assertFalse(self.game.no_host_sniper_pick_confirmed)


class JournalistInlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mozakere_no_host(self.gm)
        _cast(self.gm, self.game)
        self.gm.add_player(
            self.game, _p(13, "Jr", Role.JOURNALIST, seat=5)
        )
        self.game.no_host_journalist_flow_active = True
        self.game.no_host_journalist_pick_confirmed = False
        # خبرنگار مذاکره فقط پس از مذاکرهٔ انجام‌شده فعال می‌شود
        self.game.mozakere_negotiation_used = True
        self.game.mozakere_negotiation_tonight = True

    async def test_pending_then_confirm(self) -> None:
        from bot.no_host_journalist_night import (
            dispatch_no_host_journalist_night,
        )

        await _dispatch(
            self.game,
            self.gm,
            "no_host_journalist_night",
            dispatch_no_host_journalist_night,
            jr_uid=13,
            actor_uid=13,
            act="jrp",
            tid=20,
        )
        self.assertEqual(self.game.no_host_journalist_pending_tid, 20)
        self.assertFalse(self.game.no_host_journalist_pick_confirmed)
        await _dispatch(
            self.game,
            self.gm,
            "no_host_journalist_night",
            dispatch_no_host_journalist_night,
            jr_uid=13,
            actor_uid=13,
            act="jrc",
        )
        self.assertTrue(self.game.no_host_journalist_pick_confirmed)
        self.assertIsNone(self.game.no_host_journalist_pending_tid)


class NegotiatorInlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mozakere_no_host(self.gm)
        gm2 = self.gm
        gm2.add_player(
            self.game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR, seat=1)
        )
        gm2.add_player(self.game, _p(20, "A", Role.CITIZEN, seat=2))
        gm2.add_player(self.game, _p(30, "B", Role.CITIZEN, seat=3))
        self.game.no_host_negotiator_flow_active = True
        self.game.no_host_negotiator_pick_confirmed = False

    async def test_pending_then_confirm(self) -> None:
        from bot.no_host_mozakere_negotiation import (
            dispatch_no_host_mozakere_negotiator,
        )

        bot = AsyncMock()
        callback = MagicMock()
        callback.answer = AsyncMock()
        with patch(
            "bot.no_host_mozakere_negotiation.sync_role_mirror_panel",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mozakere_negotiation.commit_mozakere_negotiation",
            return_value=MagicMock(succeeded=True),
        ) as commit, patch(
            "bot.no_host_mozakere_negotiation.send_mozakere_negotiation_commit_notifications",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_journalist_night.activate_journalist_after_mozakere_negotiation",
            new_callable=AsyncMock,
        ):
            await dispatch_no_host_mozakere_negotiator(
                callback,
                bot,
                self.game,
                self.gm,
                neg_uid=10,
                actor_uid=10,
                act="negp",
                tid=20,
            )
            self.assertEqual(self.game.no_host_negotiator_pending_tid, 20)
            self.assertFalse(self.game.no_host_negotiator_pick_confirmed)
            await dispatch_no_host_mozakere_negotiator(
                callback,
                bot,
                self.game,
                self.gm,
                neg_uid=10,
                actor_uid=10,
                act="negc",
                tid=0,
            )
        commit.assert_called_once()
        self.assertTrue(self.game.no_host_negotiator_pick_confirmed)
        self.assertFalse(self.game.no_host_negotiator_flow_active)
        self.assertIsNone(self.game.no_host_negotiator_pending_tid)

    async def test_confirm_without_pick_rejected(self) -> None:
        from bot.no_host_mozakere_negotiation import (
            dispatch_no_host_mozakere_negotiator,
        )

        bot = AsyncMock()
        callback = MagicMock()
        callback.answer = AsyncMock()
        with patch(
            "bot.no_host_mozakere_negotiation.sync_role_mirror_panel",
            new_callable=AsyncMock,
        ):
            await dispatch_no_host_mozakere_negotiator(
                callback,
                bot,
                self.game,
                self.gm,
                neg_uid=10,
                actor_uid=10,
                act="negc",
                tid=0,
            )
        self.assertFalse(self.game.no_host_negotiator_pick_confirmed)


class _null_ctx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


class DetectiveConfirmKeyboardTests(unittest.IsolatedAsyncioTestCase):
    """اتاق ۵۶ — دکمهٔ «تأیید انتخاب» باید همیشه روی پنل کارآگاه باشد."""

    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mozakere_no_host(self.gm)
        _cast(self.gm, self.game, boss_role=Role.MAFIA_BOSS)
        self.gm.add_player(self.game, _p(11, "Det", Role.DETECTIVE, seat=5))
        self.game.no_host_detective_flow_active = True
        self.game.no_host_detective_pick_confirmed = False

    def _kb(self):
        from bot.no_host_detective_night import _pick_keyboard

        return _pick_keyboard(self.game, 11, self.gm)

    def _confirm_buttons(self, kb):
        return [
            b
            for b in _buttons(kb)
            if MOZAKERE_CONFIRM_LABEL in (b.text or "")
        ]

    def test_pick_keyboard_always_has_confirm_row(self) -> None:
        kb = self._kb()
        confirms = self._confirm_buttons(kb)
        self.assertEqual(len(confirms), 1)
        self.assertIn(":ndc:", confirms[0].callback_data)
        self.assertEqual(confirms[0].style, "primary")
        # انتخابی نیست — همهٔ دکمه‌های بازیکنان آبی
        player_btns = [
            b for b in _buttons(kb) if ":ndp:" in (b.callback_data or "")
        ]
        self.assertTrue(player_btns)
        for b in player_btns:
            self.assertEqual(b.style, "primary")

    def test_selection_turns_red_and_confirm_stays(self) -> None:
        self.game.no_host_detective_pending_tid = 20
        kb = self._kb()
        self.assertEqual(len(self._confirm_buttons(kb)), 1)
        by_uid = {}
        for b in _buttons(kb):
            if ":ndp:" in (b.callback_data or ""):
                by_uid[int(b.callback_data.split(":")[4])] = b.style
        self.assertEqual(by_uid[20], "danger")
        self.assertEqual(by_uid[30], "primary")

    async def test_reselect_replaces_and_confirm_survives(self) -> None:
        from bot.no_host_detective_night import (
            dispatch_no_host_detective_night,
        )

        await _dispatch(
            self.game, self.gm, "no_host_detective_night",
            dispatch_no_host_detective_night,
            det_uid=11, actor_uid=11, act="ndp", tid=20,
        )
        await _dispatch(
            self.game, self.gm, "no_host_detective_night",
            dispatch_no_host_detective_night,
            det_uid=11, actor_uid=11, act="ndp", tid=30,
        )
        self.assertEqual(self.game.no_host_detective_pending_tid, 30)
        kb = self._kb()
        self.assertEqual(len(self._confirm_buttons(kb)), 1)
        by_uid = {
            int(b.callback_data.split(":")[4]): b.style
            for b in _buttons(kb)
            if ":ndp:" in (b.callback_data or "")
        }
        self.assertEqual(by_uid[20], "primary")
        self.assertEqual(by_uid[30], "danger")

    async def test_confirm_via_button_marks_ready_and_mirrors(self) -> None:
        from bot.no_host_detective_night import (
            dispatch_no_host_detective_night,
        )

        with patch(
            "bot.no_host_detective_night.sync_role_mirror_panel",
            new_callable=AsyncMock,
        ) as mirror:
            await _dispatch(
                self.game, self.gm, "no_host_detective_night",
                dispatch_no_host_detective_night,
                det_uid=11, actor_uid=11, act="ndp", tid=20,
            )
            # پنل آینه/سینک باید شامل دکمهٔ تأیید باشد
            kb_arg = mirror.await_args_list[-1].args[-1]
            self.assertEqual(len(self._confirm_buttons(kb_arg)), 1)
            await _dispatch(
                self.game, self.gm, "no_host_detective_night",
                dispatch_no_host_detective_night,
                det_uid=11, actor_uid=11, act="ndc",
            )
        self.assertEqual(self.game.actions.detective_check, 20)
        self.assertTrue(self.game.no_host_detective_pick_confirmed)
        self.assertFalse(self.game.no_host_detective_flow_active)
        self.assertIsNone(self.game.no_host_detective_pending_tid)

    def test_bazpors_pick_keyboard_has_single_green_confirm_row(self) -> None:
        """جداسازی سناریو — بازپرس: دقیقاً یک تأیید سبز روی پنل انتخاب."""
        from bot.no_host_detective_night import _pick_keyboard

        game = self.gm.create_game(
            host_id=1, scenario_name="bazpors", max_players=12,
            bazpors_host_mode="no_host",
        )
        self.gm.add_player(game, _p(11, "Det", Role.DETECTIVE, seat=1))
        self.gm.add_player(game, _p(20, "A", Role.CITIZEN, seat=2))
        kb = _pick_keyboard(game, 11, self.gm)
        confirms = [b for b in _buttons(kb) if ":ndc:" in (b.callback_data or "")]
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0].style, "success")


if __name__ == "__main__":
    unittest.main()
