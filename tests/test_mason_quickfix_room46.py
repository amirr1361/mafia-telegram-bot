"""تست‌های سریع اتاق ۴۶ — پزشک (رنگ اولین انتخاب) و پیام عضویت (تأخیر تا READY).

فقط سناریوی ماسون؛ دادهٔ آزمون ایزوله.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_ACTIONS
from bot.game import GameManager
from bot.mason_night_entry import dispatch_mason_night_wait_ok
from bot.mason_night_ready import mason_recipient_ready_for_pending_delivery
from bot.mason_night_role import (
    MSD_CONFIRM,
    MSD_DONE,
    MSD_PICK,
    MSM_CONFIRM,
    MSM_PICK,
    dispatch_mason_doctor_panel,
    dispatch_mason_night_role,
)
from bot.mason_recruit_delivery import (
    flush_pending_mason_recruit_deliveries,
)
from bot.models import Game, Player, Role
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_msn


class _FakeMsg:
    def __init__(self, mid: int, chat_id: int) -> None:
        self.message_id = mid
        self.chat = type("C", (), {"id": chat_id})()


class _FakeBot:
    def __init__(self) -> None:
        self._mid = 100
        self.calls: list[tuple] = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None, **kw):
        self._mid += 1
        self.calls.append(("send", chat_id, self._mid, text, reply_markup))
        return _FakeMsg(self._mid, chat_id)

    async def edit_message_text(
        self, chat_id=None, message_id=None, text=None, reply_markup=None, **kw
    ):
        self.calls.append(("edit", chat_id, message_id, text, reply_markup))
        return True


def _p(uid: int, name: str, role: Role, seat: int | None = None) -> Player:
    return Player(
        user_id=uid, full_name=name, username=None, role=role, is_alive=True, seat=seat
    )


def _final_doctor_panel(bot: _FakeBot):
    """آخرین نسخهٔ پنل پزشکِ بازیکن (chat=40)."""
    state: dict[tuple, tuple] = {}
    for kind, chat, mid, text, kb in bot.calls:
        state[(chat, mid)] = (text, kb)
    for (chat, _mid), (text, kb) in state.items():
        if chat == 40 and kb is not None and kb.inline_keyboard:
            return text, kb
    return None, None


def _doctor_buttons(kb) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in kb.inline_keyboard:
        for btn in row:
            parts = (btn.callback_data or "").split(":")
            if len(parts) >= 5 and parts[2] == "msdp" and parts[4].isdigit():
                out[int(parts[4])] = btn.style
    return out


class MasonDoctorFirstTapTests(unittest.IsolatedAsyncioTestCase):
    """اولین انتخاب (مخصوصاً نجات خود) باید فوراً قرمز و نمایان بماند."""

    async def _game_with_doctor(self, n: int = 15):
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=n,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 900
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR, seat=1))
        for i, uid in enumerate(range(21, 21 + n - 1), start=2):
            gm.add_player(game, _p(uid, f"P{i}", Role.TOWN_SIMPLE, seat=i))
        bot = _FakeBot()
        await dispatch_mason_doctor_panel(bot, game, gm)
        return game, bot

    async def _tap(self, game, bot: _FakeBot, tid: int, uid: int = 40) -> None:
        from unittest.mock import patch as _patch

        cb = MagicMock()
        cb.answer = AsyncMock()
        with _patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, bot, game, GameManager(),
                as_uid=uid, actor_uid=uid, act=MSD_PICK, tid=tid,
            )

    async def test_capacity_is_three_for_fifteen_alive(self) -> None:
        game, _ = await self._game_with_doctor(15)
        self.assertEqual(ms_doc.mason_doctor_save_capacity(game), 3)

    async def test_first_tap_other_player_is_red_immediately(self) -> None:
        game, bot = await self._game_with_doctor(15)
        await self._tap(game, bot, 21)
        _, kb = _final_doctor_panel(bot)
        btns = _doctor_buttons(kb)
        self.assertEqual(len(btns), 15)  # همهٔ دکمه‌ها نمایان
        self.assertEqual(btns[21], "danger")
        self.assertEqual(btns[22], "primary")

    async def test_first_tap_self_stays_visible_and_red(self) -> None:
        game, bot = await self._game_with_doctor(15)
        await self._tap(game, bot, 40)  # نجات خود
        _, kb = _final_doctor_panel(bot)
        btns = _doctor_buttons(kb)
        self.assertEqual(len(btns), 15)
        self.assertEqual(btns[40], "danger")
        self.assertEqual(btns[21], "primary")
        self.assertEqual(game.mason_doctor_night_save_uids, [40])
        self.assertTrue(game.mason_night_pending_doctor_self_save)

    async def test_deselect_after_self_tap_restores_blue(self) -> None:
        game, bot = await self._game_with_doctor(15)
        await self._tap(game, bot, 40)
        await self._tap(game, bot, 40)
        _, kb = _final_doctor_panel(bot)
        btns = _doctor_buttons(kb)
        self.assertEqual(btns[40], "primary")
        self.assertEqual(game.mason_doctor_night_save_uids, [])
        self.assertFalse(game.mason_night_pending_doctor_self_save)

    async def test_partial_confirm_one_of_three(self) -> None:
        game, bot = await self._game_with_doctor(15)
        await self._tap(game, bot, 21)
        cb = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, _FakeBot(), game, GameManager(),
                as_uid=40, actor_uid=40, act=MSD_CONFIRM, tid=0,
            )
        self.assertTrue(game.mason_night_doctor_confirmed)
        self.assertEqual(game.mason_doctor_night_save_uids, [21])

    async def test_partial_confirm_two_of_three(self) -> None:
        game, _ = await self._game_with_doctor(15)
        await self._tap(game, _FakeBot(), 21)
        await self._tap(game, _FakeBot(), 22)
        cb = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, _FakeBot(), game, GameManager(),
                as_uid=40, actor_uid=40, act=MSD_CONFIRM, tid=0,
            )
        self.assertTrue(game.mason_night_doctor_confirmed)
        self.assertEqual(game.mason_doctor_night_save_uids, [21, 22])

    async def test_never_exceeds_capacity(self) -> None:
        game, bot = await self._game_with_doctor(15)
        for uid in (21, 22, 23):
            await self._tap(game, bot, uid)
        self.assertEqual(game.mason_doctor_night_save_uids, [21, 22, 23])
        await self._tap(game, bot, 24)  # ظرفیت پر — نباید اضافه شود
        self.assertEqual(game.mason_doctor_night_save_uids, [21, 22, 23])
        _, kb = _final_doctor_panel(bot)
        btns = _doctor_buttons(kb)
        self.assertEqual(btns[23], "danger")
        self.assertEqual(btns[24], "primary")


def _night_state(game: Game) -> None:
    """فاز واقعی جمع‌آوری شب موازی ماسون."""
    game.bot_assistant_user_id = 900
    game.no_host_assistant_narrator_active = True
    game.no_host_night_parallel_collect_active = True
    game.bazpors_narrator_step = NIGHT_ACTIONS
    game.bazpors_narrator_night_count = 1


class MasonRecruitDeliveryGateTests(unittest.IsolatedAsyncioTestCase):
    """پیام عضویت: ارسال فقط وقتی گیرنده READY است — دقیقاً یک‌بار."""

    async def _game(self, n: int = 12):
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=n,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 900
        gm.add_player(game, _p(10, "Ms", Role.MASON, seat=1))
        gm.add_player(game, _p(20, "Rec", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(30, "Tl", Role.TAILOR, seat=3))
        _night_state(game)
        return game

    async def _confirm_recruit(self, game, target_uid: int):
        """انتخاب + تأیید جذب با مسیر واقعی (کلاه‌برداری‌های ایزوله)."""
        delivered: list[tuple[int, str]] = []

        async def _cap(bot_, game_, uid, text, **kw):
            delivered.append((uid, text))

        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            side_effect=_cap,
        ), patch(
            "bot.mason_night_role.register_mirror_prompt_pair", new=AsyncMock()
        ), patch(
            "bot.mason_night_role.sync_role_mirror_panel", new=AsyncMock()
        ), patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, bot, game, GameManager(),
                as_uid=10, actor_uid=10, act=MSM_PICK, tid=target_uid,
            )
            await dispatch_mason_night_role(
                cb, bot, game, GameManager(),
                as_uid=10, actor_uid=10, act=MSM_CONFIRM, tid=0,
            )
        return delivered

    async def test_recipient_not_ready_message_held(self) -> None:
        game = await self._game()
        self.assertFalse(
            mason_recipient_ready_for_pending_delivery(game, 20)
        )
        delivered = await self._confirm_recruit(game, 20)
        self.assertEqual(delivered, [])
        self.assertEqual(len(game.mason_recruit_pending_deliveries), 1)
        self.assertEqual(game.mason_recruit_pending_deliveries[0][0], 20)

    async def test_recipient_becomes_ready_auto_delivery(self) -> None:
        game = await self._game()
        delivered = await self._confirm_recruit(game, 20)
        self.assertEqual(delivered, [])
        self.assertEqual(len(game.mason_recruit_pending_deliveries), 1)

        sent: list[int] = []

        async def _cap(bot_, game_, uid, text, **kw):
            sent.append(uid)

        async def _noop(*a, **kw):
            return None

        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            side_effect=_cap,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_reminder.refresh_mason_night_helper_reminder",
            new=AsyncMock(),
        ):
            # گیرنده اوکیِ «بدون اقدام» خودش را ثبت می‌کند → ارسال خودکار
            await dispatch_mason_night_wait_ok(
                cb, bot, game, GameManager(), as_uid=20, actor_uid=20
            )
        self.assertEqual(sent, [20])
        self.assertEqual(game.mason_recruit_pending_deliveries, [])
        self.assertIn(20, game.mason_night_wait_ok_uids)

    async def test_recipient_already_ready_immediate_delivery(self) -> None:
        game = await self._game()
        game.mason_night_wait_ok_uids.append(20)
        delivered = await self._confirm_recruit(game, 20)
        self.assertEqual([uid for uid, _ in delivered], [20])
        self.assertEqual(game.mason_recruit_pending_deliveries, [])

    async def test_no_duplicate_delivery_on_repeated_flush(self) -> None:
        game = await self._game()
        await self._confirm_recruit(game, 20)
        self.assertEqual(len(game.mason_recruit_pending_deliveries), 1)
        game.mason_night_wait_ok_uids.append(20)  # گیرنده READY

        sent: list[int] = []

        async def _cap(bot_, game_, uid, text, **kw):
            sent.append(uid)

        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            side_effect=_cap,
        ):
            await flush_pending_mason_recruit_deliveries(
                MagicMock(), game, GameManager()
            )
            await flush_pending_mason_recruit_deliveries(
                MagicMock(), game, GameManager()
            )
        self.assertEqual(sent, [20])
        self.assertEqual(game.mason_recruit_pending_deliveries, [])

    async def test_pending_survives_snapshot_restart(self) -> None:
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict
        import json

        game = await self._game()
        await self._confirm_recruit(game, 20)
        self.assertEqual(len(game.mason_recruit_pending_deliveries), 1)

        raw = json.dumps(game_to_snapshot_dict(game), ensure_ascii=False)
        restored = game_from_snapshot_dict(json.loads(raw))
        self.assertEqual(
            restored.mason_recruit_pending_deliveries,
            game.mason_recruit_pending_deliveries,
        )
        self.assertFalse(
            mason_recipient_ready_for_pending_delivery(restored, 20)
        )

        sent: list[int] = []

        async def _cap(bot_, game_, uid, text, **kw):
            sent.append(uid)

        restored.mason_night_wait_ok_uids.append(20)
        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            side_effect=_cap,
        ):
            await flush_pending_mason_recruit_deliveries(
                MagicMock(), restored, GameManager()
            )
        self.assertEqual(sent, [20])
        self.assertEqual(restored.mason_recruit_pending_deliveries, [])

    async def test_phase_moved_on_pending_not_lost(self) -> None:
        game = await self._game()
        await self._confirm_recruit(game, 20)
        self.assertEqual(len(game.mason_recruit_pending_deliveries), 1)
        # فاز عوض شد (شب تمام شد) — پیام نباید گم شود
        game.no_host_night_parallel_collect_active = False
        self.assertTrue(mason_recipient_ready_for_pending_delivery(game, 20))

        sent: list[int] = []

        async def _cap(bot_, game_, uid, text, **kw):
            sent.append(uid)

        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            side_effect=_cap,
        ):
            await flush_pending_mason_recruit_deliveries(
                MagicMock(), game, GameManager()
            )
        self.assertEqual(sent, [20])
        self.assertEqual(game.mason_recruit_pending_deliveries, [])

    async def test_recipient_holder_pending_until_confirmed(self) -> None:
        game = await self._game()
        gm = GameManager()
        # گیرنده = کارآگاه (دارندهٔ اقدام شبانه، هنوز تأیید نکرده)
        game.players[20].role = Role.DETECTIVE
        delivered = await self._confirm_recruit(game, 20)
        self.assertEqual(delivered, [])
        self.assertEqual(len(game.mason_recruit_pending_deliveries), 1)

        sent: list[int] = []

        async def _cap(bot_, game_, uid, text, **kw):
            sent.append(uid)

        # اقدام خودِ گیرنده تمام شد → ارسال خودکار در next flush
        game.mason_night_detective_confirmed = True
        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            side_effect=_cap,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_reminder.refresh_mason_night_helper_reminder",
            new=AsyncMock(),
        ):
            from bot.mason_night_ready import maybe_finish_mason_parallel_night

            await maybe_finish_mason_parallel_night(
                MagicMock(), game, GameManager()
            )
        self.assertEqual(sent, [20])
        self.assertEqual(game.mason_recruit_pending_deliveries, [])

    async def test_existing_membership_text_unchanged(self) -> None:
        game = await self._game()
        game.mason_night_wait_ok_uids.append(20)
        delivered = await self._confirm_recruit(game, 20)
        self.assertEqual(len(delivered), 1)
        self.assertIn("شما عضو تیم ماسون شدید", delivered[0][1])


if __name__ == "__main__":
    unittest.main()
