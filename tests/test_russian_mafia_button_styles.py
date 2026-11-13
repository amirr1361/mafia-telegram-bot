"""مافیای روسی — استایل آبی/قرمز/سبز، پنل یکپارچه با تأیید همیشه‌نمایان،
ترورِ سه‌مرحله‌ای، اسپویلر پیام خصوصی نقش، و پیام اطلاعی شلیک مافیا."""

from __future__ import annotations

import html
import unittest
from unittest.mock import AsyncMock, patch

from bot.models import Phase, Role
from bot.player_role_pick_common import inline_button_supports_style
from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict
from bot.russian_mafia import (
    ROLE_GODFATHER,
    ROLE_TERROR,
    ensure_russian_doctor_night_capacity,
    mafia_shot_holder,
    required_waiting_player_ids,
    reset_russian_night_actions,
    russian_alive_player_count,
    russian_doctor_heal_capacity,
    russian_doctor_save_uids,
    russian_roles_for_count,
    russian_role_description_fa,
    russian_role_label_fa,
)
from bot.russian_mafia_flow import (
    _TERROR_STAGE1_TEXT,
    _TERROR_STAGE2_TEXT,
    _confirm_keyboard,
    _emit_russian_night_slot,
    _night_slot_text,
    _open_terror_day_panel,
    _send_terror_stage_panel,
    _terror_panel_keyboard,
    _terror_stage_text,
    action_keyboard,
    notify_mafia_shot_team,
    present_russian_target_confirmation,
    restore_russian_target_selection,
    route_russian_player_callback,
    russian_intro_confirm_keyboard,
    send_russian_citizen_wait_panels,
)
from tests.test_russian_mafia_workflow import _alive, _prep, _run

STAGE_CONFIRM_ACTS = {
    "zok_shot",
    "zok_doc",
    "zok_det",
    "zok_ter",
    "zfin_ter",
    "zcn_ter",
    "zrt_go",
    "zbk_shot",
    "zbk_doc",
    "zbk_det",
    "zbk_ter",
}


def _flat(kb) -> list:
    return [btn for row in kb.inline_keyboard for btn in row]


def _is_grid_button(btn) -> bool:
    data = btn.callback_data or ""
    if not data.startswith("rmf:"):
        return False
    return data.split(":")[2] not in STAGE_CONFIRM_ACTS


def _grid_buttons(kb) -> list:
    return [btn for btn in _flat(kb) if _is_grid_button(btn)]


def _cb_parts(btn) -> tuple[str, ...]:
    return tuple((btn.callback_data or "").split(":"))


def _style_of(btn) -> str | None:
    return getattr(btn, "style", None) if inline_button_supports_style() else None


def _day(n: int = 8):
    _gm, game = _prep(n, real=n, observer=True)
    game.phase = Phase.DAY_DISCUSSION
    game.russian_mafia_day_index = 1
    game.bazpors_narrator_host_day = 1
    game.russian_mafia_terror_day_active = True
    return game


class RussianButtonStyleTests(unittest.TestCase):
    def _armed(self, n: int = 8):
        _gm, game = _prep(n, observer=True)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        holder = mafia_shot_holder(game)
        game.russian_mafia_mafia_action_holder = holder.user_id
        return game

    def test_initial_panel_blue_grid_with_single_green_confirm(self) -> None:
        game = self._armed()
        holder = game.russian_mafia_mafia_action_holder
        kb = action_keyboard(
            game, act="zrm_shot", as_uid=holder, exclude=None, mirror=False
        )
        flat = _flat(kb)
        grid = _grid_buttons(kb)
        self.assertEqual(len(grid), 8)
        if inline_button_supports_style():
            self.assertEqual({btn.style for btn in grid}, {"primary"})
        confirm = flat[-1]
        self.assertEqual(confirm.text, "✅ تأیید انتخاب")
        self.assertEqual(_cb_parts(confirm)[2], "zok_shot")
        self.assertEqual(_cb_parts(confirm)[4], "0")
        self.assertEqual(_style_of(confirm), "success")
        self.assertTrue(_is_grid_button(flat[0]))
        # no back button exists anywhere on the panel
        self.assertFalse(
            any(btn.text == "↩️ بازگشت" for btn in flat)
        )

    def test_selected_target_red_others_blue_confirm_carries_target(self) -> None:
        game = self._armed()
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)
        kb = _confirm_keyboard(
            game, slot="mafia", as_uid=holder, target_uid=citizen, mirror=False
        )
        flat = _flat(kb)
        grid = _grid_buttons(kb)
        self.assertEqual(len(grid), 8)
        if inline_button_supports_style():
            self.assertEqual({btn.style for btn in grid}, {"primary", "danger"})
        reds = [btn for btn in grid if _style_of(btn) == "danger"]
        self.assertEqual(len(reds), 1)
        self.assertEqual(_cb_parts(reds[0])[4], str(citizen))
        confirm = flat[-1]
        self.assertEqual(_style_of(confirm), "success")
        self.assertEqual(_cb_parts(confirm)[4], str(citizen))

    def test_citizen_ok_single_green_button(self) -> None:
        game = self._armed()
        captures: list[tuple[int, object]] = []

        async def cap(bot, game_, uid, key, text, markup, **kwargs):
            captures.append((uid, markup))
            return None

        async def run():
            with patch(
                "bot.russian_mafia_flow.register_mirror_prompt_pair", new=cap
            ):
                await send_russian_citizen_wait_panels(AsyncMock(), game)

        _run(run())
        waiting = set(required_waiting_player_ids(game))
        self.assertTrue(waiting)
        self.assertTrue({uid for uid, _m in captures} <= waiting)
        for _uid, markup in captures:
            flat = _flat(markup)
            self.assertEqual([btn.text for btn in flat], ["✅ اوکی"])
            self.assertEqual(_style_of(flat[0]), "success")

    def test_intro_confirm_keyboard_styles(self) -> None:
        game = self._armed()
        kb = russian_intro_confirm_keyboard(game)
        cont, back = _flat(kb)
        self.assertEqual(cont.text, "✅ ادامه")
        self.assertEqual(back.text, "↩️ بازگشت")
        self.assertEqual(_style_of(cont), "success")
        self.assertEqual(_style_of(back), "primary")

    def test_snapshot_roundtrip_keeps_stage_and_pending(self) -> None:
        game = self._armed()
        game.russian_mafia_panels_pending["mafia"] = 12345
        game.russian_mafia_shot_notify_night = 1
        game.russian_mafia_terror_stage = 2
        restored = game_from_snapshot_dict(game_to_snapshot_dict(game))
        self.assertEqual(restored.russian_mafia_panels_pending, {"mafia": 12345})
        self.assertEqual(restored.russian_mafia_shot_notify_night, 1)
        self.assertEqual(restored.russian_mafia_terror_stage, 2)

    def test_night_reset_clears_pending(self) -> None:
        game = self._armed()
        game.russian_mafia_panels_pending["mafia"] = 101
        reset_russian_night_actions(game)
        self.assertEqual(dict(game.russian_mafia_panels_pending), {})


class OrdinaryPanelWorkflowTests(unittest.TestCase):
    def test_selection_replace_and_deselect_flow(self) -> None:
        _gm, game = _prep(8, observer=True)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        holder = mafia_shot_holder(game).user_id
        game.russian_mafia_mafia_action_holder = holder
        citizen1 = _alive(game, Role.CITIZEN)
        citizen2 = [
            p.user_id
            for p in game.players.values()
            if p.role == Role.CITIZEN and p.user_id != citizen1
        ][0]
        seen: list[int | None] = []

        async def refresh(bot, game_, slot, as_uid, text, *, confirm_target):
            seen.append(confirm_target)

        async def run():
            with patch("bot.russian_mafia_flow._refresh_slot_markup", new=refresh):
                first = await present_russian_target_confirmation(
                    AsyncMock(),
                    game,
                    slot="mafia",
                    actor_uid=holder,
                    as_uid=holder,
                    target_uid=citizen1,
                    generation=1,
                )
                self.assertEqual(first, "pending")
                self.assertEqual(game.russian_mafia_panels_pending["mafia"], citizen1)
                replaced = await present_russian_target_confirmation(
                    AsyncMock(),
                    game,
                    slot="mafia",
                    actor_uid=holder,
                    as_uid=holder,
                    target_uid=citizen2,
                    generation=1,
                )
                self.assertEqual(replaced, "pending")
                self.assertEqual(game.russian_mafia_panels_pending["mafia"], citizen2)
                deselected = await present_russian_target_confirmation(
                    AsyncMock(),
                    game,
                    slot="mafia",
                    actor_uid=holder,
                    as_uid=holder,
                    target_uid=citizen2,
                    generation=1,
                )
                self.assertEqual(deselected, "deselect")
                self.assertNotIn("mafia", game.russian_mafia_panels_pending)
                again = await present_russian_target_confirmation(
                    AsyncMock(),
                    game,
                    slot="mafia",
                    actor_uid=holder,
                    as_uid=holder,
                    target_uid=citizen1,
                    generation=1,
                )
                self.assertEqual(again, "pending")
                back = await restore_russian_target_selection(
                    AsyncMock(),
                    game,
                    slot="mafia",
                    actor_uid=holder,
                    as_uid=holder,
                    generation=1,
                )
                self.assertEqual(back, "back")
                self.assertNotIn("mafia", game.russian_mafia_panels_pending)

        _run(run())
        self.assertIn(citizen1, seen)

    def test_confirm_without_selection_rejected_and_not_committed(self) -> None:
        game = OrdinaryPanelWorkflowTests._arm(8)
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)

        async def run():
            result = await route_russian_player_callback(
                AsyncMock(),
                game,
                act="zok_shot",
                as_uid=holder,
                actor_uid=holder,
                target_uid=0,
                generation=1,
            )
            self.assertEqual(result, "rejected")

        _run(run())
        self.assertFalse(game.russian_mafia_mafia_confirmed)
        self.assertIsNone(game.russian_mafia_mafia_target)
        self.assertTrue(game.players[citizen].is_alive)

    def test_nine_player_panel_same_behavior(self) -> None:
        game = OrdinaryPanelWorkflowTests._arm(9)
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)
        kb = action_keyboard(
            game, act="zrm_shot", as_uid=holder, exclude=None, mirror=False
        )
        self.assertEqual(len(_grid_buttons(kb)), 9)
        confirm = _flat(kb)[-1]
        self.assertEqual(confirm.text, "✅ تأیید انتخاب")
        self.assertEqual(_style_of(confirm), "success")
        selected_kb = _confirm_keyboard(
            game, slot="mafia", as_uid=holder, target_uid=citizen, mirror=False
        )
        self.assertEqual(
            _cb_parts(_flat(selected_kb)[-1])[4], str(citizen)
        )

    @staticmethod
    def _arm(n: int):
        _gm, game = _prep(n, observer=True)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        holder = mafia_shot_holder(game)
        game.russian_mafia_mafia_action_holder = holder.user_id
        return game

    def test_doctor_and_detective_panels_include_confirm(self) -> None:
        game = self._arm(8)
        doctor = _alive(game, Role.DOCTOR)
        detective = _alive(game, Role.DETECTIVE)
        for slot, as_uid, ok_act in (
            ("doctor", doctor, "zok_doc"),
            ("detective", detective, "zok_det"),
        ):
            kb = action_keyboard(
                game, act=f"zrm_{slot[:3]}" if slot == "detective" else "zrm_doc",
                as_uid=as_uid, exclude=None, mirror=False,
            )
            confirm = _flat(kb)[-1]
            self.assertEqual(confirm.text, "✅ تأیید انتخاب", slot)
            self.assertEqual(_cb_parts(confirm)[2], ok_act, slot)
            self.assertTrue(
                _is_grid_button(_flat(kb)[0]), slot
            )


class TerrorStageTests(unittest.TestCase):
    def test_stage1_red_ability_button(self) -> None:
        game = _day()
        terror = _alive(game, ROLE_TERROR)
        kb = _terror_panel_keyboard(game, terror, 0, mirror=False)
        flat = _flat(kb)
        self.assertEqual(len(flat), 1)
        btn = flat[0]
        self.assertEqual(btn.text, "🎯 استفاده از قابلیت ترور")
        self.assertEqual(_cb_parts(btn)[2], "zrt_go")
        self.assertEqual(_style_of(btn), "danger")
        mirror_kb = _terror_panel_keyboard(game, terror, 0, mirror=True)
        mirror_btn = _flat(mirror_kb)[0]
        self.assertEqual(_cb_parts(mirror_btn)[0], "pmr")
        self.assertEqual(_cb_parts(mirror_btn)[2], "zrt_go")
        self.assertEqual(_cb_parts(mirror_btn)[5], "1")

    def test_stage1_to_stage2_without_consuming_ability(self) -> None:
        game = _day()
        terror = _alive(game, ROLE_TERROR)
        result = _run(
            route_russian_player_callback(
                AsyncMock(), game, act="zrt_go", as_uid=terror,
                actor_uid=terror, target_uid=0, generation=1,
            )
        )
        self.assertEqual(result, "stage2")
        self.assertEqual(game.russian_mafia_terror_stage, 1)
        self.assertFalse(game.russian_mafia_terror_confirmed)
        self.assertTrue(game.russian_mafia_terror_day_active)
        self.assertTrue(game.players[terror].is_alive)

    def test_stage2_grid_confirm_cancel(self) -> None:
        game = _day()
        terror = _alive(game, ROLE_TERROR)
        citizen = _alive(game, Role.CITIZEN)
        _run(
            route_russian_player_callback(
                AsyncMock(), game, act="zrt_go", as_uid=terror,
                actor_uid=terror, target_uid=0, generation=1,
            )
        )
        kb = _terror_panel_keyboard(game, terror, 1, mirror=False)
        flat = _flat(kb)
        grid = _grid_buttons(kb)
        self.assertEqual(len(grid), 7)  # self excluded
        confirm = flat[-2]
        cancel = flat[-1]
        self.assertEqual(confirm.text, "✅ تأیید")
        self.assertEqual(_cb_parts(confirm)[2], "zok_ter")
        self.assertEqual(_style_of(confirm), "success")
        self.assertEqual(cancel.text, "↩️ انصراف")
        self.assertEqual(_cb_parts(cancel)[2], "zcn_ter")
        # confirm without a pending selection is rejected and stays on stage 2
        _run(
            route_russian_player_callback(
                AsyncMock(), game, act="zok_ter", as_uid=terror,
                actor_uid=terror, target_uid=0, generation=1,
            )
        )
        self.assertEqual(game.russian_mafia_terror_stage, 1)
        self.assertFalse(game.russian_mafia_terror_confirmed)

    def test_stage2_cancellation_returns_to_stage1(self) -> None:
        game = _day()
        terror = _alive(game, ROLE_TERROR)
        citizen = _alive(game, Role.CITIZEN)
        seq = (
            ("zrt_go", 0),
            ("zrm_ter", citizen),
        )
        for act, target in seq:
            _run(
                route_russian_player_callback(
                    AsyncMock(), game, act=act, as_uid=terror, actor_uid=terror,
                    target_uid=target, generation=1,
                )
            )
        self.assertEqual(game.russian_mafia_panels_pending["terror"], citizen)
        result = _run(
            route_russian_player_callback(
                AsyncMock(), game, act="zcn_ter", as_uid=terror,
                actor_uid=terror, target_uid=0, generation=1,
            )
        )
        self.assertEqual(result, "cancel")
        self.assertEqual(game.russian_mafia_terror_stage, 0)
        self.assertNotIn("terror", game.russian_mafia_panels_pending)
        self.assertFalse(game.russian_mafia_terror_confirmed)
        self.assertTrue(game.russian_mafia_terror_day_active)
        self.assertTrue(game.players[terror].is_alive)
        self.assertTrue(game.players[citizen].is_alive)

    def test_stage3_confirm_and_cancel_returns_to_stage1(self) -> None:
        game = _day()
        terror = _alive(game, ROLE_TERROR)
        citizen = _alive(game, Role.CITIZEN)
        for act, target in (("zrt_go", 0), ("zrm_ter", citizen), ("zok_ter", citizen)):
            _run(
                route_russian_player_callback(
                    AsyncMock(), game, act=act, as_uid=terror, actor_uid=terror,
                    target_uid=target, generation=1,
                )
            )
        self.assertEqual(game.russian_mafia_terror_stage, 2)
        kb = _terror_panel_keyboard(game, terror, 2, mirror=False)
        final, cancel = _flat(kb)
        self.assertEqual(final.text, "✅ تأیید نهایی")
        self.assertEqual(_cb_parts(final)[2], "zfin_ter")
        self.assertEqual(_style_of(final), "success")
        self.assertEqual(_cb_parts(final)[4], str(citizen))
        self.assertEqual(cancel.text, "↩️ انصراف")
        self.assertEqual(_cb_parts(cancel)[2], "zcn_ter")
        text = _terror_stage_text(game, 2)
        self.assertIn("تأیید نهایی ترور", text)
        self.assertIn("از بازی خارج می‌شوید", text)
        self.assertIn(game.players[citizen].full_name, text)
        result = _run(
            route_russian_player_callback(
                AsyncMock(), game, act="zcn_ter", as_uid=terror,
                actor_uid=terror, target_uid=0, generation=1,
            )
        )
        self.assertEqual(result, "cancel")
        self.assertEqual(game.russian_mafia_terror_stage, 0)
        self.assertNotIn("terror", game.russian_mafia_panels_pending)
        self.assertTrue(game.players[terror].is_alive)
        self.assertTrue(game.players[citizen].is_alive)
        # stage 2 → 3 keeps the pending selection in the final button
        for act, target in (("zrt_go", 0), ("zrm_ter", citizen), ("zok_ter", citizen)):
            _run(
                route_russian_player_callback(
                    AsyncMock(), game, act=act, as_uid=terror, actor_uid=terror,
                    target_uid=target, generation=1,
                )
            )

    def test_final_commit_eliminates_once_with_existing_rules(self) -> None:
        game = _day()
        terror = _alive(game, ROLE_TERROR)
        citizen = _alive(game, Role.CITIZEN)

        async def run():
            with patch(
                "bot.russian_mafia_flow.open_night", new=AsyncMock()
            ), patch(
                "bot.russian_mafia_flow.safe_send_message", new=AsyncMock()
            ), patch(
                "bot.game_snapshot.persist_game_snapshot", new=lambda *a, **k: None
            ):
                for act, target in (
                    ("zrt_go", 0),
                    ("zrm_ter", citizen),
                    ("zok_ter", citizen),
                    ("zfin_ter", citizen),
                ):
                    result = await route_russian_player_callback(
                        AsyncMock(), game, act=act, as_uid=terror,
                        actor_uid=terror, target_uid=target, generation=1,
                    )
                self.assertEqual(result, "ok")
                duplicate = await route_russian_player_callback(
                    AsyncMock(), game, act="zfin_ter", as_uid=terror,
                    actor_uid=terror, target_uid=citizen, generation=1,
                )
                self.assertEqual(duplicate, "rejected")

        _run(run())
        self.assertFalse(game.players[terror].is_alive)
        self.assertFalse(game.players[citizen].is_alive)

    def test_open_terror_day_panel_sends_stage1_only(self) -> None:
        game = _day()
        terror = _alive(game, ROLE_TERROR)
        captures: list[object] = []

        async def cap(bot, game_, uid, key, text, markup, **kwargs):
            captures.append((uid, text, markup))
            return None

        async def run():
            with patch(
                "bot.russian_mafia_flow.register_mirror_prompt_pair", new=cap
            ):
                await _open_terror_day_panel(AsyncMock(), game)

        _run(run())
        self.assertTrue(captures)
        for uid, text, markup in captures:
            self.assertEqual(uid, terror)
            self.assertEqual(text, _TERROR_STAGE1_TEXT)
            flat = _flat(markup)
            self.assertEqual([btn.text for btn in flat], ["🎯 استفاده از قابلیت ترور"])
            self.assertEqual(_style_of(flat[0]), "danger")

    def test_synthetic_terror_mirrored_to_observer(self) -> None:
        _gm, game = _prep(8, real=7, observer=True)
        game.phase = Phase.DAY_DISCUSSION
        game.russian_mafia_day_index = 1
        game.bazpors_narrator_host_day = 1
        game.russian_mafia_terror_day_active = True
        from bot.game import SEMI_AUTO_SYNTHETIC_UID_BASE

        syn_uid = SEMI_AUTO_SYNTHETIC_UID_BASE
        self.assertIn(syn_uid, game.players)
        # make the synthetic player the terror
        real_terror = _alive(game, ROLE_TERROR)
        self.assertNotEqual(real_terror, syn_uid)
        game.players[syn_uid].role = ROLE_TERROR
        game.players[real_terror].role = Role.CITIZEN
        terror = syn_uid
        captures: list[tuple[str, object]] = []

        async def cap(bot, game_, uid, key, text, markup, **kwargs):
            captures.append((key, markup))
            return None

        async def run():
            with patch(
                "bot.russian_mafia_flow.register_mirror_prompt_pair", new=cap
            ):
                await _send_terror_stage_panel(AsyncMock(), game)

        _run(run())
        keys = [k for k, _markup in captures]
        self.assertEqual(len(captures), 2)
        self.assertIn(_ui_key_of(game, "terror"), keys)
        self.assertIn(_ui_key_of(game, "terror") + ":obs", keys)
        for key, markup in captures:
            flat = _flat(markup)
            self.assertEqual(
                [btn.text for btn in flat], ["🎯 استفاده از قابلیت ترور"], key
            )
            self.assertEqual(_cb_parts(flat[0])[2], "zrt_go", key)
            self.assertEqual(_style_of(flat[0]), "danger", key)
        self.assertTrue([k for k in keys if k.endswith(":obs")])

    def test_nine_player_has_no_terror_role(self) -> None:
        game = _day(9)
        game.russian_mafia_terror_day_active = False
        self.assertFalse(
            any(p.role == ROLE_TERROR for p in game.players.values())
        )
        self.assertEqual(len(russian_roles_for_count(9)), 9)


def _ui_key_of(game, slot) -> str:
    from bot.russian_mafia_flow import _ui_key as _uk

    return _uk(game, slot)


class RoleSpoilerDeliveryTests(unittest.TestCase):
    def test_russian_role_name_and_description_spoilered(self) -> None:
        _gm, game = _prep(8, real=8)
        from bot.main import build_private_role_message_html

        for role in (ROLE_GODFATHER, ROLE_TERROR, Role.DOCTOR, Role.DETECTIVE, Role.CITIZEN):
            label = russian_role_label_fa(role)
            desc = russian_role_description_fa(role, game)
            text = build_private_role_message_html(game, role)
            self.assertEqual(text.count("<tg-spoiler>"), 2, role)
            self.assertIn(html.escape(label), text, role)
            self.assertIn(html.escape(desc), text, role)
            self.assertTrue(text.startswith("🎭 نقش شما: <b><tg-spoiler>"), role)

    def test_stage_texts_preserved(self) -> None:
        self.assertIn("قابلیت ترور", _TERROR_STAGE1_TEXT)
        self.assertIn("پیش از تأیید بازیکنان دفاعیه", _TERROR_STAGE1_TEXT)
        self.assertIn("انتخاب هدف ترور", _TERROR_STAGE2_TEXT)
        self.assertIn("«✅ تأیید»", _TERROR_STAGE2_TEXT)


class MafiaShotNotificationTests(unittest.TestCase):
    def test_notification_sent_after_confirm_only_and_once(self) -> None:
        game = OrdinaryPanelWorkflowTests._arm(8)
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)
        terror = _alive(game, ROLE_TERROR)
        sent: list[tuple[int, str]] = []

        async def fake_send(bot, uid, text, **kwargs):
            sent.append((uid, text))
            return True

        async def run():
            with patch(
                "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
            ), patch("bot.russian_mafia_flow.safe_send_message", new=fake_send):
                result = await route_russian_player_callback(
                    AsyncMock(),
                    game,
                    act="zok_shot",
                    as_uid=holder,
                    actor_uid=holder,
                    target_uid=citizen,
                    generation=1,
                )
                self.assertEqual(result, "ok")
                duplicate = await route_russian_player_callback(
                    AsyncMock(),
                    game,
                    act="zok_shot",
                    as_uid=holder,
                    actor_uid=holder,
                    target_uid=citizen,
                    generation=1,
                )
                self.assertEqual(duplicate, "stale")

        _run(run())
        self.assertTrue(game.russian_mafia_mafia_confirmed)
        self.assertEqual(game.russian_mafia_shot_notify_night, 1)
        target_name = game.players[citizen].full_name
        expected = (
            f"🔴 شلیک امشب تیم مافیا ثبت شد.\n\n🎯 هدف انتخاب‌شده: {target_name}"
        )
        observer = game.observer_user_id
        self.assertEqual({uid for uid, _text in sent}, {terror, observer})
        self.assertIn((terror, expected), sent)
        self.assertIn((observer, f"ناظر — {expected}"), sent)

    def test_no_notification_before_confirmation(self) -> None:
        game = OrdinaryPanelWorkflowTests._arm(8)
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)
        sent: list[tuple[int, str]] = []

        async def fake_send(bot, uid, text, **kwargs):
            sent.append((uid, text))
            return True

        async def run():
            with patch(
                "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
            ), patch("bot.russian_mafia_flow.safe_send_message", new=fake_send):
                result = await route_russian_player_callback(
                    AsyncMock(),
                    game,
                    act="zrm_shot",
                    as_uid=holder,
                    actor_uid=holder,
                    target_uid=citizen,
                    generation=1,
                )
                self.assertEqual(result, "pending")

        _run(run())
        self.assertEqual(sent, [])
        self.assertFalse(game.russian_mafia_mafia_confirmed)


class RussianDayDefenseKeyboardStyleTests(unittest.TestCase):
    def _game(self):
        _gm, game = _prep(8, real=8)
        return game

    def _unstyled(self, kb) -> bool:
        if not inline_button_supports_style():
            return True
        return all(
            getattr(btn, "style", None) is None
            for row in kb.inline_keyboard
            for btn in row
        )

    def test_russian_day_panels_styled_other_scenarios_unstyled(self) -> None:
        from bot.main import (
            _no_host_day1_confirm_elim_keyboard,
            _no_host_day1_defense_outcome_keyboard,
            _no_host_day1_defense_pick_keyboard,
            _no_host_day1_pick_elim_keyboard,
        )

        game = self._game()
        citizen = _alive(game, Role.CITIZEN)
        pool = list(game.players.values())
        with patch(
            "bot.main.day_vote_pick_uids", new=lambda g: {citizen}
        ), patch(
            "bot.main._day1_defense_pool_players", new=lambda g: list(pool)
        ):
            pick = _no_host_day1_defense_pick_keyboard(game, 100, mirror=False)
            outcome = _no_host_day1_defense_outcome_keyboard(game, 100, mirror=False)
            elim = _no_host_day1_pick_elim_keyboard(game, 100, mirror=False)
            confirm = _no_host_day1_confirm_elim_keyboard(game, 100, mirror=False)

        if inline_button_supports_style():
            picked_btn = [
                btn for row in pick.inline_keyboard for btn in row
                if str(citizen) in btn.callback_data
            ]
            self.assertEqual(len(picked_btn), 1)
            self.assertEqual(picked_btn[0].style, "danger")
            self.assertTrue(
                all(
                    btn.style == "primary"
                    for row in pick.inline_keyboard
                    for btn in row
                    if str(citizen) not in btn.callback_data
                    and btn.text is not None
                    and not btn.text.startswith("⏭️")
                    and not btn.text.startswith("🌙")
                )
            )
            yes = [btn for row in confirm.inline_keyboard for btn in row]
            self.assertEqual(
                [btn.text for btn in yes],
                ["🔹 بله، تأیید و حذف از بازی", "🔹 خیر، بازگشت به انتخاب"],
            )
            self.assertEqual(yes[0].style, "success")
            self.assertTrue(
                all(
                    btn.style == "primary"
                    for row in elim.inline_keyboard
                    for btn in row
                    if not btn.text.startswith("↩️")
                )
            )
            self.assertTrue(
                all(
                    btn.style == "primary"
                    for row in outcome.inline_keyboard
                    for btn in row
                    if btn.text.startswith("خروج (")
                )
            )

        game.scenario_name = "mozakere"
        with patch("bot.main.day_vote_pick_uids", new=lambda g: {citizen}):
            for kb in (
                _no_host_day1_defense_pick_keyboard(game, 100, mirror=False),
                _no_host_day1_defense_outcome_keyboard(game, 100, mirror=False),
                _no_host_day1_pick_elim_keyboard(game, 100, mirror=False),
                _no_host_day1_confirm_elim_keyboard(game, 100, mirror=False),
            ):
                self.assertTrue(self._unstyled(kb))
        game.scenario_name = "russian_mafia"


class _DoctorNightMixin:
    @staticmethod
    def _night(n: int):
        _gm, game = _prep(n, real=n, observer=True)
        game.phase = Phase.NIGHT
        game.russian_mafia_night_index = 1
        game.russian_mafia_mafia_action_holder = mafia_shot_holder(game).user_id
        return game

    @staticmethod
    def _doctor_uid(game) -> int:
        return _alive(game, Role.DOCTOR)

    @staticmethod
    def _select(game, doctor: int, target: int) -> str:
        return _run(
            present_russian_target_confirmation(
                AsyncMock(),
                game,
                slot="doctor",
                actor_uid=doctor,
                as_uid=doctor,
                target_uid=target,
                generation=1,
            )
        )

    @staticmethod
    def _confirm(game, doctor: int, target: int = 0) -> str:
        return _run(
            route_russian_player_callback(
                AsyncMock(),
                game,
                act="zok_doc",
                as_uid=doctor,
                actor_uid=doctor,
                target_uid=target,
                generation=1,
            )
        )


class DoctorMultiSelectPanelTests(_DoctorNightMixin, unittest.TestCase):
    def test_nine_alive_two_pending_both_red_and_blue_others(self) -> None:
        game = self._night(9)
        doctor = self._doctor_uid(game)
        a = _alive(game, Role.CITIZEN)
        b = _alive(game, Role.DETECTIVE)
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self.assertEqual(self._select(game, doctor, a), "pending")
            self.assertEqual(
                list(game.russian_mafia_panels_pending["doctor"]), [a]
            )
            self.assertEqual(self._select(game, doctor, b), "pending")
            self.assertEqual(
                list(game.russian_mafia_panels_pending["doctor"]), [a, b]
            )
        kb = action_keyboard(
            game,
            act="zrm_doc",
            as_uid=doctor,
            exclude=None,
            mirror=False,
            selected_uids=list(game.russian_mafia_panels_pending["doctor"]),
        )
        grid = _grid_buttons(kb)
        reds = [btn for btn in grid if _style_of(btn) == "danger"]
        self.assertEqual(len(reds), 2)
        self.assertEqual(
            {_cb_parts(btn)[4] for btn in reds}, {str(a), str(b)}
        )
        self.assertTrue(
            all(_style_of(btn) == "primary" for btn in grid if btn not in reds)
        )
        confirm = _flat(kb)[-1]
        self.assertEqual(confirm.text, "✅ تأیید انتخاب")
        self.assertEqual(_style_of(confirm), "success")
        self.assertEqual(_cb_parts(confirm)[4], str(min(a, b)))

    def test_nine_alive_third_selection_rejected_and_deselect_toggles(self) -> None:
        game = self._night(9)
        doctor = self._doctor_uid(game)
        a = _alive(game, Role.CITIZEN)
        b = _alive(game, Role.DETECTIVE)
        c = next(
            p.user_id
            for p in game.players.values()
            if p.user_id not in (doctor, a, b) and p.is_alive
        )
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self._select(game, doctor, a)
            self._select(game, doctor, b)
            self.assertEqual(self._select(game, doctor, c), "rejected")
            self.assertEqual(
                list(game.russian_mafia_panels_pending["doctor"]), [a, b]
            )
            self.assertEqual(self._select(game, doctor, a), "deselect")
            self.assertEqual(
                list(game.russian_mafia_panels_pending["doctor"]), [b]
            )
            self.assertEqual(self._select(game, doctor, a), "pending")
            self.assertEqual(
                list(game.russian_mafia_panels_pending["doctor"]), [b, a]
            )

    def test_nine_alive_confirm_commits_two_targets(self) -> None:
        game = self._night(9)
        doctor = self._doctor_uid(game)
        a = _alive(game, Role.CITIZEN)
        b = _alive(game, Role.DETECTIVE)
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self._select(game, doctor, a)
            self._select(game, doctor, b)
            self.assertEqual(self._confirm(game, doctor), "ok")
        self.assertEqual(
            sorted(game.russian_mafia_doctor_targets), sorted([a, b])
        )
        self.assertEqual(game.russian_mafia_doctor_target, a)
        self.assertTrue(game.russian_mafia_doctor_confirmed)
        self.assertEqual(int(game.russian_mafia_doctor_night_capacity), 2)
        self.assertNotIn("doctor", game.russian_mafia_panels_pending)
        self.assertTrue(game.players[a].is_alive)
        self.assertTrue(game.players[b].is_alive)
        self.assertEqual(self._confirm(game, doctor, b), "stale")

    def test_nine_alive_confirm_without_pending_rejected(self) -> None:
        game = self._night(9)
        doctor = self._doctor_uid(game)
        self.assertEqual(self._confirm(game, doctor), "rejected")
        self.assertFalse(game.russian_mafia_doctor_confirmed)
        self.assertEqual(game.russian_mafia_doctor_targets, [])

    def test_eight_alive_single_target_replaces_then_commits(self) -> None:
        game = self._night(8)
        doctor = self._doctor_uid(game)
        a = _alive(game, Role.CITIZEN)
        b = _alive(game, Role.DETECTIVE)
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self._select(game, doctor, a)
            self.assertEqual(self._select(game, doctor, b), "pending")
            self.assertEqual(
                list(game.russian_mafia_panels_pending["doctor"]), [b]
            )
        kb = action_keyboard(
            game,
            act="zrm_doc",
            as_uid=doctor,
            exclude=None,
            mirror=False,
            selected_uids=list(game.russian_mafia_panels_pending["doctor"]),
        )
        reds = [btn for btn in _grid_buttons(kb) if _style_of(btn) == "danger"]
        self.assertEqual(len(reds), 1)
        self.assertEqual(_cb_parts(reds[0])[4], str(b))
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self.assertEqual(self._confirm(game, doctor), "ok")
        self.assertEqual(game.russian_mafia_doctor_targets, [b])
        self.assertTrue(game.russian_mafia_doctor_confirmed)
        self.assertEqual(int(game.russian_mafia_doctor_night_capacity), 1)

    def test_eight_alive_rejects_selection_over_confirmed_capacity(self) -> None:
        game = self._night(8)
        doctor = self._doctor_uid(game)
        game.russian_mafia_doctor_targets = [_alive(game, Role.CITIZEN)]
        other = _alive(game, Role.DETECTIVE)
        self.assertEqual(self._select(game, doctor, other), "rejected")
        self.assertIsNone(game.russian_mafia_panels_pending.get("doctor"))

    def test_doctor_pending_list_survives_snapshot_roundtrip(self) -> None:
        game = self._night(9)
        doctor = self._doctor_uid(game)
        a = _alive(game, Role.CITIZEN)
        b = _alive(game, Role.DETECTIVE)
        game.russian_mafia_panels_pending["doctor"] = [a, b]
        restored = game_from_snapshot_dict(game_to_snapshot_dict(game))
        self.assertEqual(
            list(restored.russian_mafia_panels_pending.get("doctor") or []),
            [a, b],
        )
        kb = action_keyboard(
            restored,
            act="zrm_doc",
            as_uid=doctor,
            exclude=None,
            mirror=False,
            selected_uids=list(restored.russian_mafia_panels_pending["doctor"]),
        )
        reds = [btn for btn in _grid_buttons(kb) if _style_of(btn) == "danger"]
        self.assertEqual(len(reds), 2)

    def test_capacity_helper_matches_alive_count(self) -> None:
        game = self._night(9)
        game.russian_mafia_doctor_night_capacity = 0
        self.assertEqual(
            ensure_russian_doctor_night_capacity(game),
            russian_doctor_heal_capacity(game),
        )
        self.assertEqual(russian_doctor_heal_capacity(game), 2)
        game8 = self._night(8)
        self.assertEqual(russian_doctor_heal_capacity(game8), 1)


class RussianPanelTextTests(_DoctorNightMixin, unittest.TestCase):
    def test_mafia_panel_text_numbered_heading(self) -> None:
        game = self._night(9)
        game.russian_mafia_night_index = 2
        text = _night_slot_text(game, "mafia")
        self.assertIn("شلیک شب", text)
        self.assertIn("شلیک شب ۲", text)
        self.assertIn(
            "یک بازیکن را به‌عنوان هدف شلیک امشب مافیا انتخاب کنید", text
        )
        self.assertNotIn("شلیک مافیا", text)

    def test_detective_panel_text(self) -> None:
        game = self._night(8)
        text = _night_slot_text(game, "detective")
        self.assertIn("🔎 استعلام کارآگاه", text)
        self.assertIn("یک بازیکن را برای گرفتن استعلام انتخاب کنید", text)
        self.assertNotIn("یک بازیکن زنده", text)

    def test_emit_uses_new_texts(self) -> None:
        game = self._night(9)
        sent: list[tuple[str, str]] = []

        async def fake_pair(
            bot, game_, *, player_uid, slot, text, act, exclude, exclude_uids=None
        ):
            sent.append((slot, text))

        async def run():
            with patch(
                "bot.russian_mafia_flow._send_pair", new=fake_pair
            ), patch(
                "bot.russian_mafia_flow.safe_send_message", new=AsyncMock()
            ), patch(
                "bot.game_snapshot.persist_game_snapshot", new=lambda *a, **k: None
            ):
                await _emit_russian_night_slot(AsyncMock(), game, "mafia")
                await _emit_russian_night_slot(AsyncMock(), game, "detective")

        _run(run())
        per_slot = dict(sent)
        self.assertIn("شلیک شب", per_slot["mafia"])
        self.assertIn("استعلام کارآگاه", per_slot["detective"])
        self.assertIn("گرفتن استعلام", per_slot["detective"])
        self.assertNotIn("شلیک مافیا", per_slot["mafia"])


class RussianCompletionMessageTests(_DoctorNightMixin, unittest.TestCase):
    def _mirror_entries(self, game) -> None:
        game.mirror_prompt_messages = {}
        for slot in ("mafia", "doctor", "detective"):
            key = (
                f"russian:{game.room_code}:night:"
                f"{game.russian_mafia_night_index}:{slot}"
            )
            game.mirror_prompt_messages[key] = {
                "text": "open",
                "player": (123, 11),
                "observer": (900, 12),
            }

    def test_mafia_completion_text(self) -> None:
        from bot.russian_mafia_flow import _slot_completion_text

        game = self._night(8)
        holder = game.russian_mafia_mafia_action_holder
        citizen = _alive(game, Role.CITIZEN)
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self.assertEqual(
                _run(
                    route_russian_player_callback(
                        AsyncMock(),
                        game,
                        act="zok_shot",
                        as_uid=holder,
                        actor_uid=holder,
                        target_uid=citizen,
                        generation=1,
                    )
                ),
                "ok",
            )
        self.assertTrue(game.russian_mafia_mafia_confirmed)
        self.assertEqual(
            _slot_completion_text(game, "mafia", citizen),
            f"✅ شلیک شما به {game.players[citizen].full_name} ثبت شد.",
        )

    def test_doctor_completion_text_lists_both_or_one_name(self) -> None:
        from bot.russian_mafia_flow import _slot_completion_text

        game = self._night(9)
        doctor = self._doctor_uid(game)
        a = _alive(game, Role.CITIZEN)
        b = _alive(game, Role.DETECTIVE)
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self._select(game, doctor, a)
            self._select(game, doctor, b)
            self.assertEqual(self._confirm(game, doctor), "ok")
        name_a = game.players[a].full_name
        name_b = game.players[b].full_name
        self.assertEqual(
            _slot_completion_text(game, "doctor", a),
            f"✅ انتخاب شما برای نجات {name_a} و {name_b} ثبت شد.",
        )
        game8 = self._night(8)
        doctor8 = self._doctor_uid(game8)
        target8 = _alive(game8, Role.CITIZEN)
        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ):
            self._select(game8, doctor8, target8)
            self.assertEqual(self._confirm(game8, doctor8), "ok")
        self.assertEqual(
            _slot_completion_text(game8, "doctor", target8),
            f"✅ انتخاب شما برای نجات {game8.players[target8].full_name} ثبت شد.",
        )

    def test_detective_completion_text_includes_result(self) -> None:
        from bot.russian_mafia_flow import _slot_completion_text

        game = self._night(9)
        detective = _alive(game, Role.DETECTIVE)
        citizen = _alive(game, Role.CITIZEN)
        dm: list[tuple[int, str]] = []

        async def fake_dm(bot, uid, text, **kwargs):
            dm.append((uid, text))
            return True

        with patch(
            "bot.russian_mafia_flow._refresh_slot_markup", new=AsyncMock()
        ), patch("bot.russian_mafia_flow.safe_send_message", new=fake_dm):
            self.assertEqual(
                _run(
                    route_russian_player_callback(
                        AsyncMock(),
                        game,
                        act="zok_det",
                        as_uid=detective,
                        actor_uid=detective,
                        target_uid=citizen,
                        generation=1,
                    )
                ),
                "ok",
            )
        self.assertTrue(game.russian_mafia_detective_confirmed)
        self.assertEqual(game.russian_mafia_detective_alignment, "negative")
        text = _slot_completion_text(game, "detective", citizen)
        self.assertEqual(
            text,
            f"✅ انتخاب شما: {game.players[citizen].full_name}\n"
            "🔎 نتیجهٔ استعلام: منفی (شهروند)",
        )
        # existing separate result DM mechanism preserved
        self.assertIn(detective, [uid for uid, _text in dm])
        self.assertTrue(
            any("نتیجهٔ استعلام: منفی" in text_ for _uid, text_ in dm)
        )

    def test_close_edit_uses_completion_text_vs_generic(self) -> None:
        from bot.russian_mafia_flow import _close_slot

        game = self._night(8)
        self._mirror_entries(game)
        seen: list[tuple[int, int, str]] = []

        async def fake_edit(bot, chat_id, message_id, text, markup):
            seen.append((chat_id, message_id, text))
            return True

        async def run():
            with patch(
                "bot.russian_mafia_flow._try_edit_mirror_message", new=fake_edit
            ):
                await _close_slot(
                    bot=AsyncMock(),
                    game=game,
                    slot="mafia",
                    completion_text="✅ شلیک شما به X ثبت شد.",
                )
                await _close_slot(bot=AsyncMock(), game=game, slot="detective")

        _run(run())
        texts = [t for _c, _m, t in seen]
        self.assertIn("✅ شلیک شما به X ثبت شد.", texts)
        self.assertIn("این اقدام بسته شد.", texts)
        self.assertEqual(
            game.mirror_prompt_messages[
                f"russian:{game.room_code}:night:1:mafia"
            ]["text"],
            "✅ شلیک شما به X ثبت شد.",
        )


if __name__ == "__main__":
    unittest.main()
