"""
دستیار گرداننده — سناریوی تست بازپرس شبکه سلامت (و بعداً بازپرس اصلی).

فقط به گرداننده پیام می‌رود. بازی حضوری است؛ ربات فقط یادآوری، دکمه،
اعتبارسنجی و ثبت وضعیت زنده/مرده (+ بررسی برد) را انجام می‌دهد.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.game import (
    bazpors_counts_as_alive_mafia_for_win,
    bazpors_counts_as_mafia_faction,
    is_mafia_team,
    role_label_fa,
)
from bot.models import Game, NightActions, Player, Role
from bot.bazpors_detective_inquiry import (
    block_detective_inquiry_by_shiad,
    commit_detective_inquiry_pick,
    detective_inquiry_result_label_fa,
    load_detective_inquiry_result,
    mark_detective_no_inquiry,
    void_detective_inquiry_pick,
    commit_shiad_voided_detective_inquiry_note,
)
from bot.roles.registry import (
    find_alive_role_holder,
    require_role_module,
    substep_to_role,
)

_detective_role = require_role_module(Role.DETECTIVE)
_ruintan_role = require_role_module(Role.RUINTAN)
_shiad_role = require_role_module(Role.SHIAD)
_citizen_role = require_role_module(Role.CITIZEN)
from bot.observer_delivery import queue_player_elimination_notify
from bot.roles.night_state import yaku_night_state
from bot.tg_send import safe_send_message, safe_send_message_return

if TYPE_CHECKING:
    from bot.game import GameManager


class BazporsNarrCb(CallbackData, prefix="bzn"):
    code: str
    act: str
    tid: int = 0
    rid: str = ""


# --- وضعیت کلان (game.bazpors_narrator_step) ---
ROLE_ASSIGNED = "role_assigned"
INTRO_DAY = "intro_day"
INTRO_NIGHT = "intro_night"
DAY_DISCUSS = "day_discuss"
CHAOS_DAY_HANDSHAKE = "chaos_day_handshake"
DAY_INTERROG_GATE = "day_interrog_gate"
DAY_VOTE_PICK_DEFENDERS = "day_vote_pick_defenders"
DAY_VOTE_ELIM_ASK = "day_vote_elim_ask"
PICK_DAY_ELIM = "pick_day_elim"
PICK_DAY_ELIM_TIE_PART = "pick_day_elim_tie_part"
CONFIRM_DAY_ELIM = "confirm_day_elim"
PICK_INTERROG_VOTE_ELIM = "pick_interrog_vote_elim"
CONFIRM_INTERROG_VOTE_ELIM = "confirm_interrog_vote_elim"
NIGHT_START = "night_start"
NIGHT_ACTIONS = "night_actions"
ASK_NIGHT_EXTRA = "ask_night_extra"
PICK_NIGHT_EXTRA = "pick_night_extra"
CONFIRM_NIGHT_EXTRA = "confirm_night_extra"
PICK_DISCIPLINE_KICK = "pick_discipline_kick"
CONFIRM_DISCIPLINE_KICK = "confirm_discipline_kick"
CONFIRM_DISCIPLINE_NO = "confirm_discipline_no"
HOST_DISCIPLINE_FLOW_ACTS = frozenset(
    {
        "disc_yes",
        "disc_no",
        "disc_pick",
        "disc_back",
        "disc_no_ok",
        "disc_no_back",
        "disc_ok",
    }
)
MAFIA_TIE_GATE = "mafia_tie_gate"
CITIZEN_WIN_GATE = "citizen_win_gate"

# --- زیرمرحلهٔ شب (game.bazpors_night_substep) ---
NS_HUNTER = "ns_hunter"
NS_MAFIA_MENU = "ns_mafia_menu"
NS_MAFIA_SHOT = "ns_mafia_shot"
NS_NATO_ROLE = "ns_nato_role"
NS_NATO_CONFIRM = "ns_nato_confirm"
NS_NATO_MULTI_ASK = "ns_nato_multi_ask"
NS_NATO_MULTI_PICK = "ns_nato_multi_pick"
NS_YAKU_SAC = "ns_yaku_sac"
NS_YAKU_CIV = "ns_yaku_civ"
NS_YAKU_SUCCESS_ACK = "ns_yaku_success_ack"
NS_YAKU_FAIL_ACK = "ns_yaku_fail_ack"
NS_SHIAD = "ns_shiad"
NS_SHIAD_ACK = "ns_shiad_ack"
NS_DET = "ns_det"
NS_DET_ACK = "ns_det_ack"
NS_DOC = "ns_doc"
NS_DOC_NATO_SKIP = "ns_doc_nato_skip"
NS_DOC_YAKU_SKIP = "ns_doc_yaku_skip"
NS_ROLE_ABSENT = "ns_role_absent"
NS_INT1 = "ns_int1"
NS_INT2 = "ns_int2"
NS_INTERROG_SKIP = "ns_interrog_skip"
NS_SNIPER = "ns_sniper"
NS_DISCIPLINE_ASK = "ns_discipline_ask"
NS_RESOLVE = "ns_resolve"
NIGHT_RESOLVE_BUTTON_LABEL = "⚙️ اعمال پایان شب"

_NIGHT_MILESTONE_ORDER: tuple[str, ...] = (
    NS_HUNTER,
    NS_MAFIA_MENU,
    NS_SHIAD,
    NS_DET,
    NS_DOC,
    NS_INT1,
    NS_SNIPER,
    NS_DISCIPLINE_ASK,
    NS_RESOLVE,
)


def narrator_enabled_for_room(game: Game) -> bool:
    if game.scenario_name == "bazpors_salamat_test":
        return True
    return (
        game.scenario_name in ("bazpors", "mozakere")
        and game.bazpors_host_mode == "semi_auto"
    )


def bazpors_chaos_phase_enabled(game: Game) -> bool:
    """فاز آشوب — semi_auto، no_host، و سناریوی تست."""
    if game.scenario_name == "bazpors_salamat_test":
        return True
    if game.scenario_name != "bazpors":
        return False
    return game.bazpors_host_mode in ("semi_auto", "no_host")


def no_host_assistant_narrator_active(game: Game) -> bool:
    from bot.room_mode import is_no_host_player_room

    return bool(
        is_no_host_player_room(game)
        and game.bot_assistant_user_id is not None
        and game.no_host_assistant_narrator_active
    )


_doctor_role = require_role_module(Role.DOCTOR)
_hunter_role = require_role_module(Role.HUNTER)
_interrogator_role = require_role_module(Role.INTERROGATOR)
_boss_role = require_role_module(Role.MAFIA_BOSS)
_sniper_role = require_role_module(Role.SNIPER)
from bot.semi_auto_role_pick_common import (
    append_narrator_extra_rows,
    build_narrator_action_keyboard,
    build_narrator_action_row,
    build_narrator_confirm_back_rows,
    build_narrator_labeled_grid_rows,
    build_narrator_pick_keyboard,
    build_narrator_pick_rows,
)
_nato_role = require_role_module(Role.NATO)

_hunter_chain_eliminates_link = _hunter_role.chain_eliminates_link
_effective_hunter_link_uid = _hunter_role.effective_link_uid
_hunter_chain_companion_uid = _hunter_role.chain_companion_uid
HUNTER_CHAIN_SECRET_ELIM_SOURCES = _hunter_role.HUNTER_CHAIN_SECRET_ELIM_SOURCES
hunter_chain_public_disclosure = _hunter_role.chain_public_disclosure
_clear_hunter_link_state = _hunter_role.clear_link_state
_yaku_sacrifice_pool = _boss_role.yaku_sacrifice_pool
yakuzai_allowed = _boss_role.yakuzai_allowed

NATO_GUESS_ROLES = _nato_role.GUESS_ROLES
nato_can_register = _nato_role.can_register
nato_denied_message = _nato_role.denied_message

_bazpors_doctor_nato_yaku_rules_active = _doctor_role.nato_yaku_rules_active
_doctor_self_save_pool_excludes_doctor = _doctor_role.self_save_pool_excludes_doctor
_semi_auto_doctor_blocked_this_night = _doctor_role.blocked_this_night
_void_semi_auto_doctor_night_pick = _doctor_role.void_night_pick
_doctor_save_uid_set_raw = _doctor_role.save_uid_set_raw
_doctor_save_uid_set = _doctor_role.save_uid_set
_doctor_save_pool = _doctor_role.save_pool
_semi_auto_doctor_skip_after_yaku_this_night = _doctor_role.skip_after_yaku_this_night
_semi_auto_doctor_night_pick_allowed = _doctor_role.night_pick_allowed
_sniper_mafia_kill_blocked_by_doctor = _doctor_role.mafia_kill_blocked_by_doctor_save


def narrator_panel_receives_updates(game: Game) -> bool:
    return narrator_enabled_for_room(game) or no_host_assistant_narrator_active(
        game
    )


def narrator_operator_user_id(game: Game) -> int:
    if no_host_assistant_narrator_active(game):
        assert game.bot_assistant_user_id is not None
        return game.bot_assistant_user_id
    return game.host_id


def narrator_callback_user_may_act(game: Game, user_id: int) -> bool:
    if user_id == narrator_operator_user_id(game):
        return True
    obs = game.observer_user_id
    if (
        no_host_assistant_narrator_active(game)
        and game.no_host_observer_only_narrator_mirror
        and obs is not None
        and user_id == obs
    ):
        return True
    if no_host_night_role_player_may_act_bazpors_cb(game, user_id):
        return True
    return False


def no_host_night_role_player_may_act_bazpors_cb(game: Game, user_id: int) -> bool:
    """در no_host، بازیکن نقش‌دار می‌تواند دکمه‌های همان مرحلهٔ شب را بزند (مثل نیمه‌خودکار)."""
    if game.scenario_name != "bazpors" or game.bazpors_host_mode != "no_host":
        return False
    if game.bazpors_narrator_step != NIGHT_ACTIONS:
        return False
    ns = game.bazpors_night_substep
    if ns not in (NS_INT1, NS_INT2, NS_INTERROG_SKIP):
        return False
    role = substep_to_role(ns)
    if role is None:
        return False
    pl = find_alive_role_holder(game, role)
    return pl is not None and pl.user_id == user_id


def start_after_deal(game: Game) -> None:
    if not narrator_enabled_for_room(game):
        return
    try:
        from bot.game_audit_log import log_event

        log_event(game, "narrator.assist_started", scenario=game.scenario_name)
    except Exception:
        pass
    game.bazpors_narrator_step = ROLE_ASSIGNED
    game.bazpors_narrator_host_day = 0
    game.bazpors_narrator_night_count = 0
    game.bazpors_narrator_pending_uid = None
    game.bazpors_night_substep = None
    game.bazpors_absent_night_role = None
    yaku_night_state(game).reset_narrator_assist_start()
    game.bazpors_nato_used = False
    game.bazpors_doctor_self_save_count = 0
    game.bazpors_night_pending_doctor_self_save = False
    game.bazpors_night_baseline_doctor_self_saves = 0
    game.bazpors_night_discipline_kick_uid = None
    game.bazpors_interrog_pick_uid = None
    game.bazpors_nato_action_registered = False
    game.bazpors_nato_success = None
    game.bazpors_nato_kill_target_uid = None
    game.bazpors_mafia_shot_registered = False
    game.bazpors_detective_blocked = False
    game.bazpors_hunter_link_uid = None
    game.bazpors_hunter_linked_this_night = False
    game.bazpors_hunter_report_link_uid = None
    game.bazpors_hunter_report_chain_line = None
    game.bazpors_mafia_recruit_ids.clear()
    game.bazpors_sniper_eliminated_uids.clear()
    game.bazpors_nato_guess_role = None
    game.bazpors_nato_multi_uids = None
    game.bazpors_detective_last_answer = None
    game.bazpors_det_ack_positive = False
    game.bazpors_det_no_inquiry = False
    game.bazpors_shiad_target_uid = None
    game.bazpors_nato_guess_target_uid = None
    game.bazpors_night_report_html = None
    game.bazpors_host_flush_note = None
    game.bazpors_interrog_first_uid = None
    game.bazpors_interrog_cancel_next_day = False
    game.bazpors_alive_at_night_start = None
    game.bazpors_alive_at_day_start = None
    game.bazpors_interrog_night_finished = False
    game.bazpors_interrog_second_uid = None
    game.bazpors_interrog_ready_for_day = False
    game.bazpors_interrog_once_done = False
    game.bazpors_ki_as_today = False
    game.bazpors_chaos_handshake_round = 0
    game.bazpors_chaos_choices.clear()
    game.bazpors_night_step_history.clear()
    game.bazpors_night_announce_lines.clear()
    game.bazpors_day_vote_participations.clear()
    game.bazpors_day_vote_pick_uids = None
    game.bazpors_day_vote_defender_uids = None
    game.bazpors_day_vote_elim_reason = None
    game.bazpors_sniper_shot_used = False
    game.bazpors_sniper_night_target_uid = None


def _sorted_players(game: Game) -> list[Player]:
    return sorted(
        game.players.values(),
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    )


def _alive(game: Game) -> list[Player]:
    return [p for p in _sorted_players(game) if p.is_alive]


def _find_alive_role(game: Game, role: Role) -> Player | None:
    return find_alive_role_holder(game, role)


def _find_role_holder(game: Game, role: Role) -> Player | None:
    for p in game.players.values():
        if p.role == role:
            return p
    return None


def _game_has_role(game: Game, role: Role) -> bool:
    return any(p.role == role for p in game.players.values())


def _role_eliminated_from_game(game: Game, role: Role) -> bool:
    return _game_has_role(game, role) and _find_alive_role(game, role) is None


def _player_with_role(game: Game, role: Role) -> Player | None:
    for p in game.players.values():
        if p.role == role:
            return p
    return None


NIGHT_STEP_NEXT_BTN = "برو به مرحله بعد"

_NIGHT_ROLE_STEP_NAMES: dict[Role, str] = {
    Role.HUNTER: "هانتر",
    Role.DETECTIVE: "کارآگاه",
    Role.DOCTOR: "پزشک",
    Role.SHIAD: "شیاد",
    Role.INTERROGATOR: "بازپرس",
    Role.SNIPER: "تک‌تیرانداز",
}


def _night_role_step_name(role: Role) -> str:
    return _NIGHT_ROLE_STEP_NAMES.get(role, role_label_fa(role))


def _night_step_header(nc: int, step_name: str) -> str:
    return f"🌙 <b>شب {_seat_fa(nc)}</b> — ثبت انتخاب {step_name}"


def _night_mafia_shot_header(nc: int) -> str:
    if nc == 1:
        label = "شب اول — هدف شات مافیا"
    elif nc == 2:
        label = "شب دوم — هدف شات مافیا"
    elif nc == 3:
        label = "شب سوم — هدف شات مافیا"
    else:
        label = f"شب {_seat_fa(nc)} — هدف شات مافیا"
    return f"🌙 <b>{label}</b>"


def _night_role_absent_host_text(nc: int, role: Role) -> str:
    label = _night_role_step_name(role)
    return (
        f"{_night_step_header(nc, label)}\n\n"
        f"🎯 {label} در بازی حضور ندارد.\n"
        f"گرداننده فقط به‌صورت نمایشی {label} را بیدار کند، انتخاب بازیکن را "
        f"بپرسد و سپس او را بخواباند.\n\n"
        f"➡️ بعد از انجام این مرحله، دکمه «{NIGHT_STEP_NEXT_BTN}» را بزن."
    )


def _enter_night_role_or_skip_absent(
    game: Game,
    role: Role,
    present_ns: str,
    when_gone: Callable[[Game], None],
) -> None:
    if _find_alive_role(game, role):
        _night_forward(game, present_ns)
    elif _role_eliminated_from_game(game, role):
        _goto_role_absent(game, role)
    else:
        when_gone(game)


def _goto_role_absent(game: Game, role: Role) -> None:
    game.bazpors_night_substep = NS_ROLE_ABSENT
    game.bazpors_absent_night_role = role.value


def _advance_after_role_absent(game: Game) -> None:
    role_val = game.bazpors_absent_night_role
    game.bazpors_absent_night_role = None
    if not role_val:
        return
    try:
        role = Role(role_val)
    except ValueError:
        return
    if role == Role.HUNTER:
        _advance_after_hunter(game)
    elif role == Role.SHIAD:
        _advance_after_shiad(game)
    elif role == Role.DETECTIVE:
        _advance_after_det(game)
    elif role == Role.DOCTOR:
        _advance_after_doc(game)
    elif role == Role.INTERROGATOR:
        _advance_after_interrogator_phase(game)
    elif role == Role.SNIPER:
        _goto_discipline_ask(game)


def _absent_night_role(game: Game) -> Role | None:
    val = game.bazpors_absent_night_role
    if not val:
        return None
    try:
        return Role(val)
    except ValueError:
        return None


def role_absent_popup_text(game: Game, gm: GameManager) -> str | None:
    """پاپ‌آپ تأیید؛ قبل از process_narrator_callback صدا زده شود."""
    del gm
    role = _absent_night_role(game)
    if not role:
        return None
    label = _night_role_step_name(role)
    return (
        f"{label} در بازی حضور ندارد.\n\n"
        f"دکمه «{NIGHT_STEP_NEXT_BTN}» را بزن."
    )


def _seat_fa(seat: int | str) -> str:
    from bot.game import _digits_fa

    return _digits_fa(seat) if isinstance(seat, int) else str(seat)


def _visually_mafia(game: Game, p: Player) -> bool:
    if p.user_id in game.bazpors_sniper_eliminated_uids:
        return False
    if game.scenario_name == "mozakere":
        if p.user_id in game.mozakere_mafia_recruit_ids:
            return True
        if getattr(p, "mozakere_converted_by_negotiation", False):
            return True
    if p.user_id in game.bazpors_mafia_recruit_ids:
        return True
    if getattr(p, "bazpors_converted_by_yakuza", False):
        return True
    if not p.role:
        return False
    return is_mafia_team(p.role)


def _mafia_alive_n(game: Game) -> int:
    return sum(1 for p in _alive(game) if _visually_mafia(game, p))


def _town_alive_n(game: Game) -> int:
    return len(_alive(game)) - _mafia_alive_n(game)


def _mafia_intro_html(game: Game, gm: GameManager) -> str:
    parts = ["🩸 <b>اعضای تیم مافیا:</b>"]
    mafs = [p for p in _alive(game) if p.role and is_mafia_team(p.role)]

    def _mafia_intro_sort_key(p: Player) -> tuple[int, int, int]:
        if p.role == Role.MAFIA_BOSS:
            return (0, p.seat if p.seat is not None else 999, p.user_id)
        return (1, p.seat if p.seat is not None else 999, p.user_id)

    mafs.sort(key=_mafia_intro_sort_key)
    for p in mafs:
        parts.append(
            f"🔴 {html.escape(gm.format_player_tag(p))} — "
            f"<b>{html.escape(role_label_fa(p.role))}</b>"
        )
    if len(parts) == 1:
        parts.append("<i>عضو مافیا در بازی نیست.</i>")
    return "\n".join(parts)


def _win_note(gm: GameManager, game: Game) -> str:
    w = gm.check_winner(game)
    if not w:
        return ""
    return f"\n\n🏁 <b>شرط برد:</b> {html.escape(w)}\n<i>برای پایان رسمی اتاق از /endgame استفاده کنید.</i>"


def _alive_faction_counts(
    game: Game, gm: GameManager
) -> tuple[int, int, int]:
    """(کل زنده، مافیا، شهروند)"""
    alive = gm.alive_players(game)
    mafia_n = sum(1 for p in alive if bazpors_counts_as_alive_mafia_for_win(game, p))
    return len(alive), mafia_n, len(alive) - mafia_n


def _roster_faction_counts(
    game: Game, players: list[Player]
) -> tuple[int, int]:
    mafia_n = sum(1 for p in players if bazpors_counts_as_mafia_faction(game, p))
    return mafia_n, len(players) - mafia_n


def _roster_display_name(p: Player, gm: GameManager) -> str:
    """نام نمایشی کامل بازیکن در وضعیت صندلی."""
    return html.escape(gm.format_player_tag(p))


def _roster_line(
    game: Game, gm: GameManager, p: Player, *, mafia_row: bool
) -> str:
    name = _roster_display_name(p, gm)
    role_txt = html.escape(role_label_fa(p.role)) if p.role else "؟"
    mark = "🔴" if mafia_row else "🟢"
    return f"{mark} {name} - {role_txt}"


def _roster_sort_mafia(players: list[Player]) -> list[Player]:
    """رئیس و نقش‌دار مافیا (ناتو، شیاد، …) قبل از مافیا ساده."""

    def tier(role: Role | None) -> int:
        if role == Role.MAFIA_BOSS:
            return 0
        if role == Role.MAFIA_BASIC:
            return 2
        return 1

    def key(p: Player) -> tuple[int, inlt, int]:
        return (
            tier(p.role),
            p.seat if p.seat is not None else 999,
            p.user_id,
        )

    return sorted(players, key=key)


def _roster_sort_citizens(players: list[Player]) -> list[Player]:
    """شهروند نقش‌دار قبل از شهروند ساده."""

    def key(p: Player) -> tuple[int, int, int]:
        has_special = _citizen_role.is_special_town_role(p.role)
        return (0 if has_special else 1, p.seat if p.seat is not None else 999, p.user_id)

    return sorted(players, key=key)


def _roster_grouped_lines(
    game: Game, gm: GameManager, players: list[Player]
) -> list[str]:
    mafia: list[Player] = []
    citizens: list[Player] = []
    for p in players:
        if bazpors_counts_as_mafia_faction(game, p):
            mafia.append(p)
        else:
            citizens.append(p)
    lines: list[str] = []
    for p in _roster_sort_mafia(mafia):
        lines.append(_roster_line(game, gm, p, mafia_row=True))
    for p in _roster_sort_citizens(citizens):
        lines.append(_roster_line(game, gm, p, mafia_row=False))
    return lines


def _players_roster_html(game: Game, gm: GameManager) -> str:
    """خلاصهٔ وضعیت صندلی — فقط تعداد خارج‌شده‌ها (بدون فهرست نام)."""
    dead = [p for p in _sorted_players(game) if not p.is_alive]
    dead_m, dead_c = _roster_faction_counts(game, dead)
    return (
        f"👥 <b>وضعیت صندلی:</b> {_seat_fa(len(dead))} نفر خارج: "
        f"🔴 {_seat_fa(dead_m)} مافیا + 🟢 {_seat_fa(dead_c)} شهروند"
    )


CHAOS_PHASE_LABEL = "فاز آشوب (Chaos)"


def semi_auto_chaos_host_picks_winner(game: Game) -> bool:
    """نیمه‌خودکار: فاز آشوب — فقط گرداننده برنده را ثبت می‌کند (نه دست‌دادن بازیکن)."""
    return (
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "semi_auto"
        and bazpors_chaos_phase_enabled(game)
    )


def _ki_as_chaos_win_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏆 مافیا برنده شد",
                    callback_data=BazporsNarrCb(
                        code=code, act="ki_as_mafia_win", tid=0
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 شهروند برنده شد",
                    callback_data=BazporsNarrCb(
                        code=code, act="ki_as_citizen_win", tid=0
                    ).pack(),
                )
            ],
        ]
    )


def _ki_as_counts_met(game: Game, gm: GameManager) -> bool:
    """۳ نفر زنده: دقیقاً ۱ مافیا و ۲ شهروند."""
    total, mafia_n, citizen_n = _alive_faction_counts(game, gm)
    return total == 3 and mafia_n == 1 and citizen_n == 2


def _sync_ki_as_today(game: Game, gm: GameManager) -> None:
    """روز فاز آشوب: سه‌نفره با ۱ مافیا و ۲ شهروند (semi_auto و no_host)."""
    if not bazpors_chaos_phase_enabled(game) or gm.check_winner(game):
        game.bazpors_ki_as_today = False
        return
    game.bazpors_ki_as_today = _ki_as_counts_met(game, gm)


def _evaluate_post_night_host_state(game: Game, gm: GameManager) -> None:
    """بعد از مشخص شدن نتایج شب (سناریوی بازپرس)."""
    _sync_ki_as_today(game, gm)


def _ki_as_host_block_html() -> str:
    return (
        f"🔔 <b>امروز {CHAOS_PHASE_LABEL} است.</b>\n"
        "بازیکنان را بیدار کن و به مدت <b>۲ دقیقه</b> اجازه بده حرف بزنند.\n"
        "در پایان ۲ دقیقه، <b>همه بازیکنان</b> باید <b>شهروند خودشان</b> را معرفی کنند."
    )


def _ki_as_split_night_end_panel(game: Game, gm: GameManager) -> bool:
    """پایان شب با فاز آشوب — گزارش و دستور Chaos در دو پیام جدا."""
    if game.bazpors_narrator_step != ASK_NIGHT_EXTRA:
        return False
    if gm.check_winner(game):
        return False
    if not game.bazpors_ki_as_today:
        return False
    if game.bazpors_interrog_ready_for_day:
        return False
    return True


def _interrog_ready_split_night_end_panel(game: Game, gm: GameManager) -> bool:
    """پایان شب با بازپرسی فردا — گزارش و دستور بازپرسی در دو پیام جدا (semi_auto)."""
    if game.bazpors_narrator_step != ASK_NIGHT_EXTRA:
        return False
    if gm.check_winner(game):
        return False
    if not narrator_enabled_for_room(game) or no_host_assistant_narrator_active(game):
        return False
    if not game.bazpors_interrog_ready_for_day:
        return False
    if game.bazpors_interrog_cancel_next_day:
        return False
    if _ki_as_split_night_end_panel(game, gm):
        return False
    return True


def _build_interrog_day_host_panel_html(game: Game, gm: GameManager, win: str) -> str:
    """پیام دوم پایان شب — راهنمای بازپرسی روز بعد + دکمه‌ها."""
    u1, u2 = game.bazpors_interrog_first_uid, game.bazpors_interrog_second_uid
    nominees = ""
    if (
        u1 is not None
        and u2 is not None
        and u1 in game.players
        and u2 in game.players
    ):
        n1 = html.escape(gm.format_player_tag(game.players[u1]))
        n2 = html.escape(gm.format_player_tag(game.players[u2]))
        nominees = f"\n\n<b>نامزدهای بازپرسی:</b> {n1} و {n2}"
    return (
        "🔎 <b>بازپرسی باید انجام شود</b>\n\n"
        "هر یک از بازیکنان ۲ نوبت دفاع خواهند داشت؛\n"
        "⏱ هر نوبت دفاع ۳۰ ثانیه است.\n\n"
        "پس از پایان دفاع‌ها، خواب نیم‌روزی را اعلام کنید و از بازپرس "
        "بخواهید نظر خود را درباره ادامه یا انحلال جلسه بازپرسی اعلام کند:\n\n"
        "👍 لایک = ادامه بازپرسی و شروع رأی‌گیری\n"
        "👎 دیسلایک = انحلال جلسه بازپرسی\n\n"
        "در پایان، نتیجه را از کلیدهای زیر انتخاب کنید."
        f"{nominees}{win}"
    )


def _interrog_ready_night_end_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶️ بازپرسی ادامه پیدا کند",
                    callback_data=BazporsNarrCb(
                        code=code, act="intr_continue", tid=0
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭕ بازپرسی منحل شد",
                    callback_data=BazporsNarrCb(
                        code=code, act="intr_dissolve", tid=0
                    ).pack(),
                )
            ],
        ]
    )


def _night_end_host_guidance_html(game: Game) -> str:
    """راهنمای گرداننده پس از گزارش شب — همان متن پنل semi_auto."""
    _refresh_interrog_ready_for_day(game)
    if game.bazpors_interrog_ready_for_day:
        return (
            "<b>گرداننده:</b> گزارش بالا را در صندلی بخوان؛ سپس فقط یکی از "
            "<b>دو دکمهٔ زیر</b> را بزن.\n\n"
        )
    if game.bazpors_interrog_cancel_next_day and game.bazpors_interrog_night_finished:
        return (
            "<b>گرداننده:</b> گزارش بالا را در صندلی بخوان "
            "(بازپرسی به‌دلیل خروج نامزد در شب منتفی است). "
            "بعد دکمهٔ ادامه را بزن و روز را شروع کن.\n\n"
        )
    return (
        "<i>اگر کسی جدا از شات/ناتو در شب مرده و در ربات ثبت نشده، "
        "از دکمهٔ «ثبت خروج شبانهٔ اضافی» استفاده کن.</i>\n\n"
    )


def build_night_end_report_bundle_html(game: Game, gm: GameManager) -> str:
    """گزارش پایان شب + وضعیت صندلی + راهنمای گرداننده (بدون دکمه)."""
    report = game.bazpors_night_report_html or ""
    if not report.strip():
        return ""
    parts: list[str] = [report, "", _players_roster_html(game, gm), ""]
    parts.append(_night_end_host_guidance_html(game))
    _sync_ki_as_today(game, gm)
    if _ki_as_split_night_end_panel(game, gm):
        parts.extend(["", _ki_as_host_block_html()])
    return "\n".join(parts).rstrip()


async def deliver_observer_night_end_report(
    bot: Bot, game: Game, gm: GameManager
) -> None:
    """گزارش پایان شب (همان متن گرداننده) — یک بار در هر شب برای ناظر."""
    obs_id = game.observer_user_id
    if obs_id is None or game.observer_prompt_status == "skipped":
        return
    if not (game.bazpors_night_report_html or "").strip():
        return
    night = max(1, game.bazpors_narrator_night_count)
    if game.bazpors_observer_night_report_sent_night == night:
        return
    text = build_night_end_report_bundle_html(game, gm)
    if not text.strip():
        return
    if obs_id == narrator_operator_user_id(game):
        return
    body = "👁 <b>گزارش پایان شب</b> (همان گزارش گرداننده)\n\n" + text
    await safe_send_message(
        bot,
        obs_id,
        body,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    game.bazpors_observer_night_report_sent_night = night
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.observer_night_report_sent",
            night_count=night,
            observer_uid=obs_id,
        )
    except Exception:
        pass


def _build_night_end_report_panel_html(
    game: Game, gm: GameManager, win: str
) -> str:
    """گزارش شب + وضعیت صندلی — بدون دکمه (پیام اول فاز آشوب)."""
    return f"{build_night_end_report_bundle_html(game, gm)}{win}"


def _night_end_report_split_active(game: Game, gm: GameManager) -> bool:
    """گزارش پایان شب و دکمه‌های بعدی در دو پیام جدا — گزارش همیشه بماند."""
    if game.bazpors_narrator_step != ASK_NIGHT_EXTRA:
        return False
    if gm.check_winner(game):
        return False
    return bool((game.bazpors_night_report_html or "").strip())


async def deliver_assistant_pinned_night_end_report_if_needed(
    bot: Bot, game: Game, gm: GameManager
) -> bool:
    """گزارش کامل شب — فقط ناظر؛ کمک‌کننده همان خلاصهٔ همگانی را دارد."""
    if not narrator_panel_receives_updates(game):
        return False
    if not (game.bazpors_night_report_html or "").strip():
        return False
    night = max(1, game.bazpors_narrator_night_count)
    await deliver_observer_night_end_report(bot, game, gm)
    if no_host_assistant_narrator_active(game):
        game.bazpors_assistant_night_report_sent_night = night
        return True
    if game.bazpors_assistant_night_report_sent_night == night:
        return True
    text = build_night_end_report_bundle_html(game, gm)
    if not text.strip():
        return False
    sent = await safe_send_message_return(
        bot,
        narrator_operator_user_id(game),
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    if sent is None:
        return False
    game.bazpors_assistant_night_report_sent_night = night
    return True


def ki_as_hand_resolve_day_active(game: Game, gm: GameManager) -> bool:
    """سه نفر زنده — روز فاز آشوب؛ دست دادن از پنل بازیکن (نه دکمهٔ دستی قدیمی)."""
    if not bazpors_chaos_phase_enabled(game):
        return False
    if game.bazpors_narrator_step not in (DAY_DISCUSS, CHAOS_DAY_HANDSHAKE):
        return False
    if gm.check_winner(game):
        return False
    if not _ki_as_counts_met(game, gm):
        return False
    game.bazpors_ki_as_today = True
    return True


def _ki_as_hand_resolve_host_block_html() -> str:
    return (
        f"\n\n🤝 <b>نتیجهٔ {CHAOS_PHASE_LABEL} (سه نفر در صندلی)</b>\n"
        "امروز <b>رأی‌گیری معمول انجام نمی‌شود</b>.\n"
        "بعد از دست دادن، مشخص کن بازیکن شهروند به چه کسی باخت:\n\n"
        "• اگر <b>شهروند به مافیا</b> دست داد → مافیا برنده است.\n"
        "• اگر <b>شهروند به شهروند</b> دست داد → شهروند برنده است.\n"
    )


def mafia_tie_popup_text(game: Game, gm: GameManager) -> str | None:
    """پاپ‌آپ وقتی مافیا برابر یا بیشتر از شهروند است — برد مافیا."""
    if not mafia_faction_wins(game, gm):
        return None
    _, mafia_n, citizen_n = _alive_faction_counts(game, gm)
    if mafia_n == citizen_n:
        balance = (
            f"تعداد مافیا و شهروند برابر شد ({_seat_fa(mafia_n)} به {_seat_fa(citizen_n)})."
        )
    else:
        balance = (
            f"تعداد مافیا ({_seat_fa(mafia_n)}) بیشتر از شهروند ({_seat_fa(citizen_n)}) است."
        )
    return (
        f"بازی تمام شد.\n\n"
        f"{balance}\n"
        "طبق قانون این سناریو، <b>مافیا برنده است</b> — در صندلی اعلام کن."
    )


def _mafia_tie_notice_html(
    game: Game, gm: GameManager, *, after_night_report: bool = True
) -> str:
    """اعلام تساوی مافیا/شهروند و برد مافیا."""
    _, mafia_n, citizen_n = _alive_faction_counts(game, gm)
    if after_night_report:
        lead = (
            "<b>گرداننده:</b> ابتدا <b>گزارش بالا</b> را در صندلی بخوان "
            "(خلاصهٔ اتفاقات این شب).\n\n"
        )
    else:
        lead = "<b>گرداننده:</b> وضعیت فعلی صندلی را در نظر بگیر.\n\n"
    return (
        "🏁 <b>تساوی مافیا و شهروند</b>\n\n"
        f"{lead}"
        + (
            f"تعداد مافیا ({_seat_fa(mafia_n)}) "
            f"<b>برابر یا بیشتر از</b> شهروند ({_seat_fa(citizen_n)}) است.\n"
        )
        + (
            "تعداد برابر است.\n"
            if mafia_n == citizen_n
            else "مافیا اکثریت دارد.\n"
        )
        + "طبق قانون این سناریو، <b>تیم مافیا برنده است</b> — در صندلی اعلام کن.\n\n"
        + "آیا تأیید می‌کنی؟"
    )


def _mafia_tie_gate_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید می‌کنم — مافیا برنده شد",
                    callback_data=BazporsNarrCb(
                        code=code, act="tie_mafia_yes", tid=0
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭕ تأیید نمی‌کنم — خودم برنده را مشخص می‌کنم",
                    callback_data=BazporsNarrCb(
                        code=code, act="tie_mafia_no", tid=0
                    ).pack(),
                )
            ],
        ]
    )


def post_night_host_popup_text(
    game: Game, gm: GameManager, act: str, step_before: str | None
) -> str | None:
    """پاپ‌آپ گرداننده هنگام شروع روز بعد از اعلام نتایج شب."""
    if step_before != ASK_NIGHT_EXTRA:
        return None
    if act not in ("nx_no", "intr_dissolve"):
        return None
    citizen = citizen_win_popup_text(game, gm)
    if citizen:
        return citizen
    tie = mafia_tie_popup_text(game, gm)
    if tie:
        return tie
    if game.bazpors_ki_as_today and not mafia_citizen_equal(game, gm):
        return (
            f"امروز {CHAOS_PHASE_LABEL} است.\n\n"
            "بازیکنان را بیدار کن؛ ۲ دقیقه بحث؛ "
            "در پایان هر بازیکن باید شهروند خودش را معرفی کند."
        )
    return None


def mafia_citizen_equal(game: Game, gm: GameManager) -> bool:
    if not narrator_panel_receives_updates(game):
        return False
    _, mafia_n, citizen_n = _alive_faction_counts(game, gm)
    return mafia_n > 0 and mafia_n == citizen_n


def mafia_faction_wins(game: Game, gm: GameManager) -> bool:
    """مافیا برابر یا بیشتر از شهروند — برد مافیا."""
    if not narrator_panel_receives_updates(game):
        return False
    _, mafia_n, citizen_n = _alive_faction_counts(game, gm)
    return mafia_n > 0 and mafia_n >= citizen_n


def no_mafia_alive(game: Game, gm: GameManager) -> bool:
    """هیچ مافیا (و یاکوزا‌شده) زنده نیست — شرط برد شهروند."""
    if not narrator_panel_receives_updates(game):
        return False
    alive = gm.alive_players(game)
    if not alive:
        return False
    mafia_n = sum(1 for p in alive if bazpors_counts_as_alive_mafia_for_win(game, p))
    return mafia_n == 0


def _citizen_win_lead_html(game: Game, gm: GameManager) -> str:
    src = game.bazpors_citizen_win_elim_source
    uid = game.bazpors_citizen_win_elim_uid
    if uid is not None and uid in game.players:
        tag = html.escape(gm.format_player_tag(game.players[uid]))
        if src == "day_vote":
            return (
                f"<b>{tag}</b> آخرین فرد <b>مافیا</b> بود و با "
                f"<b>رأی‌گیری روز</b> از بازی خارج شد.\n\n"
            )
        if src == "interrog_vote":
            return (
                f"<b>{tag}</b> آخرین فرد <b>مافیا</b> بود و با "
                f"<b>رأی بازپرسی</b> از بازی خارج شد.\n\n"
            )
    if src == "night_resolve":
        return (
            "<b>گرداننده:</b> ابتدا <b>گزارش بالا</b> را در صندلی بخوان "
            "(خلاصهٔ اتفاقات این شب).\n\n"
        )
    return "<b>گرداننده:</b> وضعیت فعلی صندلی را در نظر بگیر.\n\n"


def _citizen_win_notice_html(game: Game, gm: GameManager) -> str:
    _, _mafia_n, citizen_n = _alive_faction_counts(game, gm)
    lead = _citizen_win_lead_html(game, gm)
    return (
        "🏁 <b>پایان بازی — برد شهروند</b>\n\n"
        f"{lead}"
        "مافیا (و اعضای تیم مافیا) دیگر در بازی <b>نیستند</b>.\n"
        f"({_seat_fa(citizen_n)} شهروند زنده در صندلی است.)\n"
        "طبق قانون این سناریو، <b>تیم شهروند برنده است</b> — در صندلی اعلام کن.\n\n"
        "آیا تأیید می‌کنی؟"
    )


def _citizen_win_gate_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید می‌کنم — شهروند برنده شد",
                    callback_data=BazporsNarrCb(
                        code=code, act="tie_citizen_yes", tid=0
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭕ تأیید نمی‌کنم — خودم برنده را مشخص می‌کنم",
                    callback_data=BazporsNarrCb(
                        code=code, act="tie_citizen_no", tid=0
                    ).pack(),
                )
            ],
        ]
    )


def citizen_win_popup_text(game: Game, gm: GameManager) -> str | None:
    if not no_mafia_alive(game, gm):
        return None
    _, _mafia_n, citizen_n = _alive_faction_counts(game, gm)
    src = game.bazpors_citizen_win_elim_source
    if src == "day_vote":
        lead = "آخرین مافیا با رأی‌گیری روز خارج شد.\n\n"
    elif src == "interrog_vote":
        lead = "آخرین مافیا با رأی بازپرسی خارج شد.\n\n"
    else:
        lead = "مافیا دیگر در بازی نیست.\n\n"
    return (
        "بازی تمام شد.\n\n"
        f"{lead}"
        f"طبق قانون این سناریو، شهروند برنده است "
        f"({_seat_fa(citizen_n)} نفر زنده) — در صندلی اعلام کن."
    )


def trigger_citizen_win_gate_if_needed(
    game: Game,
    gm: GameManager,
    *,
    elim_source: str | None = None,
    elim_uid: int | None = None,
) -> bool:
    """اگر هیچ مافیا زنده نماند، گرداننده باید برد شهروند را تأیید کند."""
    if not narrator_enabled_for_room(game):
        return False
    if game.bazpors_narrator_step == CITIZEN_WIN_GATE:
        return True
    if not no_mafia_alive(game, gm):
        return False
    game.bazpors_citizen_win_elim_source = elim_source
    game.bazpors_citizen_win_elim_uid = elim_uid
    game.bazpors_narrator_step = CITIZEN_WIN_GATE
    game.bazpors_night_substep = None
    return True


def trigger_mafia_tie_gate_if_needed(
    game: Game,
    gm: GameManager,
    *,
    after_night_report: bool = False,
) -> bool:
    """اگر تعداد مافیا و شهروند برابر شد، گرداننده باید برد مافیا را تأیید کند."""
    if not narrator_enabled_for_room(game):
        return False
    if game.bazpors_narrator_step == MAFIA_TIE_GATE:
        return True
    if not mafia_faction_wins(game, gm):
        return False
    game.bazpors_mafia_tie_after_night_report = after_night_report
    game.bazpors_narrator_step = MAFIA_TIE_GATE
    game.bazpors_night_substep = None
    return True


def trigger_win_gate_if_needed(
    game: Game,
    gm: GameManager,
    *,
    elim_source: str | None = None,
    elim_uid: int | None = None,
) -> bool:
    """بعد از حذف: اول برد شهروند (بدون مافیا)، بعد تساوی مافیا/شهروند."""
    if trigger_citizen_win_gate_if_needed(
        game, gm, elim_source=elim_source, elim_uid=elim_uid
    ):
        return True
    return trigger_mafia_tie_gate_if_needed(
        game,
        gm,
        after_night_report=(elim_source == "night_resolve"),
    )


def _milestone_index(milestone: str) -> int:
    if milestone == NS_INTERROG_SKIP:
        milestone = NS_INT1
    return _NIGHT_MILESTONE_ORDER.index(milestone)


def _night_forward(game: Game, milestone: str) -> None:
    h = game.bazpors_night_step_history
    if not h:
        h.append(milestone)
    elif h[-1] != milestone:
        h.append(milestone)
    game.bazpors_night_substep = milestone


def _clear_night_state_after_index(game: Game, after_idx: int) -> None:
    if after_idx <= 0:
        game.bazpors_hunter_link_uid = None
        game.bazpors_hunter_linked_this_night = False
    if after_idx <= 1:
        game.actions.mafia_target = None
        game.bazpors_mafia_shot_registered = False
        game.bazpors_nato_action_registered = False
        game.bazpors_nato_success = None
        game.bazpors_nato_kill_target_uid = None
        game.bazpors_nato_guess_target_uid = None
        game.bazpors_nato_guess_role = None
        game.bazpors_nato_multi_uids = None
        yaku_night_state(game).clear_pick_state()
    if after_idx <= 2:
        game.bazpors_shiad_target_uid = None
        game.bazpors_detective_blocked = False
    if after_idx <= 3:
        game.actions.detective_check = None
        game.bazpors_det_no_inquiry = False
        game.bazpors_det_ack_positive = False
        game.bazpors_detective_last_answer = None
    if after_idx <= 4:
        game.actions.doctor_save = None
        game.bazpors_doctor_save_uids = []
        game.bazpors_night_pending_doctor_self_save = False
        game.bazpors_doctor_self_save_count = (
            game.bazpors_night_baseline_doctor_self_saves
        )
    if after_idx <= 5:
        game.bazpors_interrog_pick_uid = None
        game.bazpors_interrog_first_uid = None
        game.bazpors_interrog_second_uid = None
        game.bazpors_interrog_night_finished = False
    if after_idx <= 7:
        game.bazpors_night_discipline_kick_uid = None


def _undo_to_milestone(game: Game, milestone: str) -> None:
    _clear_night_state_after_index(game, _milestone_index(milestone))


def _night_back_button_row(code: str, game: Game) -> list[InlineKeyboardButton]:
    ns = game.bazpors_night_substep
    can = len(game.bazpors_night_step_history) > 1 or ns in (
        NS_MAFIA_SHOT,
        NS_DET_ACK,
        NS_SHIAD_ACK,
        NS_NATO_ROLE,
        NS_NATO_CONFIRM,
        NS_NATO_MULTI_ASK,
        NS_NATO_MULTI_PICK,
        NS_YAKU_SAC,
        NS_YAKU_CIV,
    )
    if not can:
        return []
    return [
        InlineKeyboardButton(
            text="⬅️ بازگشت به مرحلهٔ قبل",
            callback_data=BazporsNarrCb(code=code, act="night_back", tid=0).pack(),
        )
    ]


def _append_night_back_row(
    code: str, game: Game, rows: list[list[InlineKeyboardButton]]
) -> list[list[InlineKeyboardButton]]:
    back = _night_back_button_row(code, game)
    if back:
        rows = list(rows) + [back]
    return rows


def _night_back_one(game: Game) -> str | None:
    ns = game.bazpors_night_substep
    if ns == NS_MAFIA_SHOT:
        game.bazpors_night_substep = NS_MAFIA_MENU
        game.bazpors_mafia_shot_registered = False
        game.actions.mafia_target = None
        return None
    if ns == NS_DET_ACK:
        game.bazpors_night_substep = NS_DET
        return None
    if ns == NS_SHIAD_ACK:
        game.bazpors_night_substep = NS_SHIAD
        return None
    if ns in (
        NS_NATO_ROLE,
        NS_NATO_CONFIRM,
        NS_NATO_MULTI_ASK,
        NS_NATO_MULTI_PICK,
        NS_YAKU_SAC,
        NS_YAKU_CIV,
    ):
        return "برای این زیرمرحله از دکمهٔ «بازگشت» همان بخش استفاده کن."
    h = game.bazpors_night_step_history
    if len(h) < 2:
        return "مرحلهٔ قبلی وجود ندارد."
    h.pop()
    prev = h[-1]
    _undo_to_milestone(game, prev)
    game.bazpors_night_substep = prev
    return None


def _goto_discipline_ask(game: Game) -> None:
    _night_forward(game, NS_DISCIPLINE_ASK)


def _goto_resolve_step(game: Game) -> None:
    _night_forward(game, NS_RESOLVE)



def _hunter_chain_warning_html(
    game: Game, gm: GameManager, eliminated_uid: int, *, public: bool = True
) -> str:
    """هشدار قبل از تأیید خروج — وقتی هانتر به مافیا (غیر رئیس) وصل است."""
    if not public:
        return ""
    link = _hunter_chain_companion_uid(game, eliminated_uid)
    if link is None:
        return ""
    tag = html.escape(gm.format_player_tag(game.players[link]))
    return (
        "\n\n⚠️ <b>زنجیرهٔ هانتر:</b> هانتر به مافیا (غیر از رئیس) وصل است — "
        f"با تأیید، <b>{tag}</b> هم از بازی خارج می‌شود."
    )


def hunter_chain_confirm_alert_text(
    game: Game, gm: GameManager, eliminated_uid: int, *, public: bool = True
) -> str | None:
    """پاپ‌آپ پس از تأیید خروج هانتر با زنجیرهٔ مافیا."""
    if not public:
        return None
    victim = game.players.get(eliminated_uid)
    if not victim or victim.role != Role.HUNTER:
        return None
    link = _effective_hunter_link_uid(game)
    if link is None or link not in game.players:
        return None
    lp = game.players[link]
    if not _hunter_chain_eliminates_link(game, lp):
        return None
    tag = gm.format_player_tag(lp)
    return f"زنجیرهٔ هانتر: {tag} هم از بازی خارج شد."


def _eliminate_player(
    game: Game,
    gm: GameManager,
    uid: int,
    *,
    hunter_chain: bool = True,
    elim_source: str | None = None,
    hunter_chain_public: bool | None = None,
) -> str:
    """حذف یک بازیکن؛ در صورت مرگ هانتر وصل به مافیا، همراه را هم حذف می‌کند."""
    if uid not in game.players:
        return ""
    victim = game.players[uid]
    game.players[uid].is_alive = False
    queue_player_elimination_notify(game, uid)
    chain_public = (
        hunter_chain_public
        if hunter_chain_public is not None
        else hunter_chain_public_disclosure(elim_source)
    )
    note = (
        _hunter_companion_if_eliminated(
            game, gm, uid, public=chain_public
        )
        if hunter_chain
        else ""
    )
    if hunter_chain and victim.role == Role.HUNTER:
        _clear_hunter_link_state(game)
    _sync_interrog_day_state(game)
    try:
        from bot.game_audit_log import log_player_eliminated

        log_player_eliminated(
            game,
            uid,
            source="eliminate_player",
            hunter_chain=hunter_chain,
            companion_note=note,
        )
    except Exception:
        pass
    return note


def _eliminate_and_maybe_win_gate(
    game: Game,
    gm: GameManager,
    uid: int,
    *,
    hunter_chain: bool = True,
    elim_source: str | None = None,
) -> bool:
    """بازیکن را حذف می‌کند؛ اگر شرط پایان بازی باشد True."""
    if elim_source == "day_vote":
        from bot.roles.mozakere_armored import try_survive_mozakere_day_vote_elimination

        armor_note = try_survive_mozakere_day_vote_elimination(game, gm, uid)
        if armor_note is not None:
            _append_host_flush_note(game, armor_note)
            return False
    note = _eliminate_player(
        game,
        gm,
        uid,
        hunter_chain=hunter_chain,
        elim_source=elim_source,
    )
    if note and hunter_chain_public_disclosure(elim_source):
        _append_host_flush_note(game, note)
    gm.check_winner(game)
    return trigger_win_gate_if_needed(
        game, gm, elim_source=elim_source, elim_uid=uid
    )


def _yaku_success_host_panel(
    game: Game, gm: GameManager
) -> tuple[str, InlineKeyboardMarkup]:
    yaku = yaku_night_state(game)
    tid = yaku.night_civilian_uid
    su = yaku.sac_uid
    if tid is None or tid not in game.players:
        return "خطا: هدف یاکوزایی مشخص نیست.", InlineKeyboardMarkup(inline_keyboard=[])
    tgt = game.players[tid]
    sac = game.players.get(su) if su is not None else None
    sac_label = (
        html.escape(role_label_fa(sac.role))
        if sac and sac.role
        else html.escape(gm.format_player_tag(sac))
        if sac
        else "؟"
    )
    tgt_role = (
        html.escape(role_label_fa(tgt.role))
        if tgt.role
        else html.escape(gm.format_player_tag(tgt))
    )
    tgt_name = html.escape(gm.format_player_tag(tgt))
    btn_label = f"{gm.format_player_tag(tgt)} را بیدار کردم. برو به مرحله بعد"
    if len(btn_label) > 64:
        btn_label = btn_label[:62] + "…"
    body = (
        "✅ <b>یاکوزایی موفق بود</b>\n\n"
        f"💀 مافیای فداشده (<b>{sac_label}</b>) از بازی خارج شد.\n\n"
        f"🩸 <b>{tgt_role}</b> به تیم مافیا اضافه شد و از این لحظه به بعد "
        "به‌عنوان عضو مافیا شناخته می‌شود.\n\n"
        f"🤝 گرداننده از تمام بازیکنان بخواهد دست‌های خود را جلو بیاورند، "
        f"سپس دست (<b>{tgt_name}</b>) را لمس کند تا متوجه شود به تیم مافیا پیوسته است.\n\n"
        "👁️ در این مرحله، سایر اعضای تیم مافیا می‌توانند بیدار بمانند تا "
        "عضو جدید، هم‌تیمی‌های مافیای خود را بشناسد."
    )
    return (
        body,
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=btn_label,
                        callback_data=BazporsNarrCb(
                            code=game.room_code, act="yaku_next", tid=0
                        ).pack(),
                    )
                ]
            ]
        ),
    )


def _yaku_fail_host_panel(
    game: Game, gm: GameManager
) -> tuple[str, InlineKeyboardMarkup]:
    yaku = yaku_night_state(game)
    tid = yaku.night_civilian_uid
    su = yaku.sac_uid
    if tid is None or tid not in game.players:
        return "خطا: هدف یاکوزایی مشخص نیست.", InlineKeyboardMarkup(inline_keyboard=[])
    tgt = game.players[tid]
    sac = game.players.get(su) if su is not None else None
    sac_label = (
        html.escape(role_label_fa(sac.role))
        if sac and sac.role
        else html.escape(gm.format_player_tag(sac))
        if sac
        else "؟"
    )
    tgt_name = html.escape(gm.format_player_tag(tgt))
    body = (
        "⭕ <b>یاکوزایی موفق نبود</b>\n\n"
        f"💀 مافیای فداشده (<b>{sac_label}</b>) از بازی خارج شد.\n\n"
        f"🛡️ <b>{tgt_name}</b> به تیم مافیا اضافه نخواهد شد و همچنان "
        "عضو تیم شهروندی باقی می‌ماند.\n\n"
        "🤝 گرداننده از تمام بازیکنان بخواهد به‌صورت نمادین دست‌های خود را "
        "جلو بیاورند، اما دست هیچ‌کس را لمس نکند تا مشخص شود یاکوزایی موفق نبوده است.\n\n"
        "👁️ در این مرحله، سایر اعضای تیم مافیا می‌توانند بیدار بمانند."
    )
    btn_label = "➡️ انجام شد — برو به مرحله بعد"
    return (
        body,
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=btn_label,
                        callback_data=BazporsNarrCb(
                            code=game.room_code, act="yaku_next", tid=0
                        ).pack(),
                    )
                ]
            ]
        ),
    )


def _append_host_flush_note(game: Game, note: str) -> None:
    if not note.strip():
        return
    if game.bazpors_host_flush_note:
        game.bazpors_host_flush_note = game.bazpors_host_flush_note + "\n\n" + note
    else:
        game.bazpors_host_flush_note = note



def hunter_vote_elim_names_html_block(
    game: Game, gm: GameManager, eliminated_uid: int
) -> str:
    """نام بازیکن(ان) خارج‌شده در رأی/اجماع — فقط اسم نمایشی (هانتر + همراه زنجیره)."""
    companion = _hunter_chain_companion_uid(
        game, eliminated_uid, companion_must_be_alive=False
    )
    uids = [eliminated_uid]
    if companion is not None:
        uids.append(companion)
    lines: list[str] = []
    for uid in uids:
        pl = game.players.get(uid)
        if pl is None:
            continue
        lines.append(f"💀 <b>{html.escape(gm.format_player_tag(pl))}</b>")
    return "\n".join(lines)


def hunter_chain_broadcast_suffix_html(
    game: Game, gm: GameManager, eliminated_uid: int, *, public: bool = True
) -> str:
    """سازگاری — فقط نام همراه زنجیره (پس از حذف). ترجیحاً ``hunter_vote_elim_names_html_block``."""
    if not public:
        return ""
    companion = _hunter_chain_companion_uid(
        game, eliminated_uid, companion_must_be_alive=False
    )
    if companion is None:
        return ""
    tag = html.escape(gm.format_player_tag(game.players[companion]))
    return f"\n\n💀 <b>{tag}</b>"


def _hunter_companion_if_eliminated(
    game: Game, gm: GameManager, eliminated_uid: int, *, public: bool = True
) -> str:
    """بعد از مرگ هانتر؛ شهروند وصل‌شده و رئیس مافیا می‌مانند؛ مافیا همراه می‌میرد."""
    victim = game.players.get(eliminated_uid)
    if not victim or victim.role != Role.HUNTER:
        return ""
    link = _effective_hunter_link_uid(game)
    if not link or link not in game.players:
        return ""
    lp = game.players[link]
    if not lp.is_alive:
        return ""
    if not _hunter_chain_eliminates_link(game, lp):
        return ""
    lp.is_alive = False
    queue_player_elimination_notify(game, link)
    chain_tag = html.escape(gm.format_player_tag(lp))
    if not public:
        game.bazpors_elim_private_extra_html[eliminated_uid] = (
            f"⚠️ <b>زنجیرهٔ هانتر:</b> چون به مافیا (غیر از رئیس) وصل بودید، "
            f"<b>{chain_tag}</b> هم از بازی خارج شد."
        )
        return ""
    game.bazpors_hunter_report_chain_line = (
        f"⚠️ <b>زنجیرهٔ هانتر:</b> {chain_tag} "
        "هم خارج شد (وصل به مافیا غیر از رئیس)."
    )
    return (
        f"⚠️ <b>زنجیرهٔ هانتر:</b> {chain_tag} "
        f"هم خارج شد (وصل به مافیا غیر از رئیس).{_win_note(gm, game)}"
    )


def _enter_night_from_day_end(game: Game) -> None:
    """از پایان روز به شب عادی بعدی (شمارندهٔ شب یکی زیاد می‌شود)."""
    game.bazpors_ki_as_today = False
    _apply_day_vote_participations_for_today(game)
    _clear_day_vote_session(game)
    game.bazpors_narrator_night_count += 1
    from bot.room_mode import is_no_host_player_room

    if is_no_host_player_room(game):
        from bot.no_host_phase import reset_no_host_per_night_role_state

        _reset_night_flags(game)
        reset_no_host_per_night_role_state(game)
        game.no_host_night_parallel_collect_active = True
        # جمع‌آوری موازی شب از _begin_night_actions عبور نمی‌کند؛ اسنپ‌شات
        # شروع شب برای تفکیک خداحافظی روز/شب در گزارش پایان شب لازم است.
        _arm_night_actions_baseline(game)
    elif game.scenario_name == "bazpors" and game.bazpors_host_mode == "semi_auto":
        _reset_night_flags(game)
    game.bazpors_narrator_step = NIGHT_START


def _parse_uid_csv(raw: str | None) -> set[int]:
    out: set[int] = set()
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


def _uid_csv(uids: set[int]) -> str | None:
    if not uids:
        return None
    return ",".join(str(u) for u in sorted(uids))


def _day_vote_pick_uids(game: Game) -> set[int]:
    return _parse_uid_csv(game.bazpors_day_vote_pick_uids)


def _day_vote_defender_uids(game: Game) -> set[int]:
    return _parse_uid_csv(game.bazpors_day_vote_defender_uids)


def _set_day_vote_pick_uids(game: Game, uids: set[int]) -> None:
    game.bazpors_day_vote_pick_uids = _uid_csv(uids)


def _clear_day_vote_session(game: Game) -> None:
    game.bazpors_day_vote_pick_uids = None
    game.bazpors_day_vote_defender_uids = None
    game.bazpors_day_vote_elim_reason = None


def _record_day_vote_participants(game: Game, uids: set[int]) -> None:
    for uid in uids:
        game.bazpors_day_vote_participations[uid] = (
            game.bazpors_day_vote_participations.get(uid, 0) + 1
        )


def _apply_day_vote_participations_for_today(game: Game) -> None:
    """شمارندهٔ سابقه را بعد از تمام شدن رأی‌گیری امروز (+۱) به‌روز می‌کند."""
    defenders = _day_vote_defender_uids(game)
    if defenders:
        _record_day_vote_participants(game, defenders)


def _day_vote_participation_label(n: int) -> str:
    if n <= 1:
        return "اولین بار در رأی"
    if n == 2:
        return "دومین بار در رأی"
    if n == 3:
        return "سومین بار در رأی"
    return f"{_seat_fa(n)} بار در رأی"


def _day_vote_defender_pool(game: Game) -> list[Player]:
    pool: list[Player] = []
    for uid in sorted(_day_vote_defender_uids(game)):
        if uid in game.players and game.players[uid].is_alive:
            pool.append(game.players[uid])
    return pool


def _day_vote_participation_count(game: Game, uid: int) -> int:
    return game.bazpors_day_vote_participations.get(uid, 0)


def day_vote_pick_uids(game: Game) -> set[int]:
    return _day_vote_pick_uids(game)


def day_vote_defender_uids(game: Game) -> set[int]:
    return _day_vote_defender_uids(game)


def set_day_vote_pick_uids(game: Game, uids: set[int]) -> None:
    _set_day_vote_pick_uids(game, uids)


def set_day_vote_defender_uids(game: Game, uids: set[int]) -> None:
    game.bazpors_day_vote_defender_uids = _uid_csv(uids) if uids else None


def record_day_vote_participants(game: Game, uids: set[int]) -> None:
    _record_day_vote_participants(game, uids)


def day_vote_participation_count(game: Game, uid: int) -> int:
    return _day_vote_participation_count(game, uid)


def _day_vote_participation_history_html(game: Game, gm: GameManager) -> str:
    uids = _day_vote_defender_uids(game)
    if not uids:
        return ""
    lines: list[str] = []
    for uid in sorted(uids):
        if uid not in game.players:
            continue
        p = game.players[uid]
        n = _day_vote_participation_count(game, uid)
        tag = html.escape(gm.format_player_tag(p))
        lines.append(f"• {tag}: <b>{_seat_fa(n)}</b>")
    if not lines:
        return ""
    return "📌 <b>سابقه حضور در رأی‌گیری:</b>\n" + "\n".join(lines) + "\n\n"


def _day_vote_elim_rules_html() -> str:
    return (
        "⚖️ <b>قانون تعیین خروج:</b>\n"
        "• اگر رأی‌ها مساوی بود → بازیکنی که سابقه حضور بیشتری در رأی‌گیری دارد "
        "خارج می‌شود.\n"
        "• اگر رأی‌ها مساوی نبود → بازیکنی که بیشترین رأی را آورده خارج می‌شود.\n"
        "• اگر هیچ بازیکنی حذف نشد → «<b>کسی خارج نشد</b>».\n"
    )


def _day_vote_tie_break_elim_uids(game: Game) -> list[int]:
    """بیشترین سابقهٔ حضور در رأی — بین نامزدهای امروز."""
    defenders = _day_vote_defender_uids(game)
    if not defenders:
        return []
    best = max(_day_vote_participation_count(game, uid) for uid in defenders)
    return sorted(uid for uid in defenders if _day_vote_participation_count(game, uid) == best)


def _day_vote_defenders_summary_html(game: Game, gm: GameManager) -> str:
    return _day_vote_participation_history_html(game, gm)


def _day_vote_multi_defender_elim_keyboard(
    code: str, game: Game, gm: GameManager
) -> InlineKeyboardMarkup:
    """چند نامزد — دکمهٔ جدا برای خروج هر بازیکن (بدون مساوی/بیشترین رأی)."""
    rows: list[list[InlineKeyboardButton]] = []
    for p in sorted(
        _day_vote_defender_pool(game),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        tag = gm.format_player_tag(p)[:40]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"بازیکن {tag} از بازی خارج شد",
                    callback_data=BazporsNarrCb(
                        code=code, act="dv_defender_out", tid=p.user_id
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⭕ کسی خارج نشد",
                callback_data=BazporsNarrCb(
                    code=code, act="dv_no_elim", tid=0
                ).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ ویرایش انتخاب‌ها",
                callback_data=BazporsNarrCb(
                    code=code, act="dv_pick_back", tid=0
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _day_vote_toggle_rows(
    code: str, game: Game, gm: GameManager
) -> list[list[InlineKeyboardButton]]:
    selected = _day_vote_pick_uids(game)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in _alive(game):
        tick = "✅" if p.user_id in selected else "☐"
        prev = game.bazpors_day_vote_participations.get(p.user_id, 0)
        prev_hint = f"·{_seat_fa(prev)}" if prev else ""
        lab = f"{tick} {gm.format_player_tag(p)[:12]}{prev_hint}"
        row.append(
            InlineKeyboardButton(
                text=lab,
                callback_data=BazporsNarrCb(
                    code=code, act="dv_toggle", tid=p.user_id
                ).pack(),
            )
        )
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="⭕ هیچکسی وارد دفاعیه نشد",
                callback_data=BazporsNarrCb(
                    code=code, act="dv_none_defended", tid=0
                ).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ تأیید انتخاب‌ها",
                callback_data=BazporsNarrCb(code=code, act="dv_confirm", tid=0).pack(),
            )
        ]
    )
    return rows


def _bazpors_player_count(game: Game) -> int:
    return len(game.players)


def _bazpors_sniper_nights_enabled(game: Game) -> bool:
    return _sniper_role.nights_enabled(game)


def _sniper_can_shoot(game: Game) -> bool:
    return _sniper_role.can_shoot(game)


def _sniper_night_host_text(nc: int, *, can_shoot: bool) -> str:
    rules = (
        "📜 <b>قوانین:</b>\n"
        "• تک‌تیرانداز هر شب بیدار می‌شود؛ فقط <b>یک‌بار</b> در کل بازی می‌تواند شلیک کند.\n"
        "• هدف باید عضو تیم مافیا باشد؛ در صورت اشتباه (شهروند)، تک‌تیرانداز خارج می‌شود.\n"
        "• اگر هدف <b>رئیس مافیا</b> باشد، هیچ‌کس خارج نمی‌شود.\n"
        "• شلیک کردن <b>اختیاری</b> است.\n"
    )
    if can_shoot:
        body = (
            "🎯 تک‌تیرانداز را بیدار کن. از لیست زیر هدف شلیک را مشخص کن، "
            "یا «شلیک نکرد» را بزن.\n\n"
        )
    else:
        body = (
            "🎯 تک‌تیرانداز بیدار می‌شود؛ تیر قبلاً استفاده شده — "
            "فقط «ادامه» را بزن.\n\n"
        )
    return f"{_night_step_header(nc, 'تک‌تیرانداز')}\n\n{body}{rules}\n"


def _apply_sniper_night_resolution(game: Game, gm: GameManager) -> None:
    _sniper_role.apply_night_resolution(game, gm)


def _yaku_negotiation_succeeds(game: Game, target: Player) -> bool:
    """بعد از انتخاب هدف؛ شهروند ساده همیشه؛ رویین‌تن فقط در ۱۲ نفره."""
    if not target.role:
        return False
    if _citizen_role.yaku_negotiation_succeeds(
        target.role, player_count=_bazpors_player_count(game)
    ):
        return True
    if _ruintan_role.yaku_negotiation_succeeds(
        target.role, player_count=_bazpors_player_count(game)
    ):
        return True
    return False


def _yaku_civilian_pool(game: Game) -> list[Player]:
    """اهداف یاکوزایی — همهٔ غیرمافیاهای زنده (رویین‌تن هم در ۱۳ نفره در لیست است)."""
    return [p for p in _alive(game) if not _visually_mafia(game, p)]


def _yaku_target_allowed(game: Game, target: Player) -> bool:
    return not _visually_mafia(game, target)


def mafia_shot_allowed(game: Game) -> bool:
    from bot.room_mode import is_mozakere_scenario
    from bot.roles.mozakere_negotiator import mafia_used_negotiation_tonight

    if is_mozakere_scenario(game) and mafia_used_negotiation_tonight(game):
        return False
    if game.bazpors_mafia_shot_registered:
        return False
    if _mafia_alive_n(game) < 1:
        return False
    return _ruintan_role.mafia_shot_allowed(game)


def _doctor_night_nato_skip_host_text(night_count: int) -> str:
    return (
        f"{_night_step_header(night_count, 'پزشک')}\n\n"
        "🚨 چون <b>ناتویی</b> انجام شده، دیگر نیازی به گرفتن انتخاب پزشک "
        "وجود ندارد.\n"
    )


def _doctor_night_yaku_skip_host_text(night_count: int) -> str:
    return (
        f"{_night_step_header(night_count, 'پزشک')}\n\n"
        "🤝 چون <b>یاکوزایی</b> انجام شده (موفق یا ناموفق)، دیگر نیازی به "
        "گرفتن انتخاب پزشک وجود ندارد.\n"
    )


def _doctor_night_host_text(game: Game, night_count: int) -> str:
    n = game.bazpors_doctor_self_save_count
    return (
        f"{_night_step_header(night_count, 'پزشک')}\n\n"
        "🩺 پزشک را بیدار کن و از لیست زیر، بازیکنی را که برای نجات انتخاب کرده "
        "مشخص کن.\n\n"
        "📜 قانون:\n"
        "🛡️ پزشک در طول بازی فقط دو بار می‌تواند خودش را نجات دهد.\n"
        "👥 نجات سایر بازیکنان محدودیتی ندارد.\n\n"
        f"📊 پزشک تاکنون {_seat_fa(n)} بار خودش را نجات داده است.\n"
    )


def _detective_night_host_text(night_count: int) -> str:
    return (
        f"{_night_step_header(night_count, 'کارآگاه')}\n\n"
        "🕵️ کارآگاه را بیدار کن و از لیست زیر، بازیکنی را که برای استعلام انتخاب "
        "کرده مشخص کن.\n\n"
        "🤖 پس از انتخاب، ربات به‌صورت خودکار نتیجه استعلام را به شما اعلام می‌کند "
        "(مثبت یا منفی).\n\n"
        "📢 سپس نتیجه استعلام را به کارآگاه اعلام کن و او را بخوابان.\n"
    )


def _commit_night_pending_state(game: Game) -> None:
    """ثبت قطعی تغییرات موقت شب (فقط پس از «اعمال پایان شب»)."""
    from bot.roles.doctor import commit_pending_self_save

    commit_pending_self_save(game)


def _night_title_fa(night_count: int) -> str:
    if night_count == 1:
        return "شب اول"
    if night_count == 2:
        return "شب دوم"
    if night_count == 3:
        return "شب سوم"
    return f"شب {_seat_fa(night_count)}"


def _night_end_title_fa(night_count: int) -> str:
    if night_count == 1:
        return "پایان شب اول"
    if night_count == 2:
        return "پایان شب دوم"
    if night_count == 3:
        return "پایان شب سوم"
    return f"پایان شب {_seat_fa(night_count)}"


def _day_start_title_fa(day: int, *, ki_as: bool = False) -> str:
    if day == 1:
        title = "روز اول آغاز شد"
    elif day == 2:
        title = "روز دوم آغاز شد"
    elif day == 3:
        title = "روز سوم آغاز شد"
    else:
        title = f"روز {_seat_fa(day)} آغاز شد"
    if ki_as:
        title += f" — {CHAOS_PHASE_LABEL}"
    return f"☀️ <b>{title}</b>"


def _day_discuss_body_fa(*, ki_as: bool, host_picks_winner: bool = False) -> str:
    base = (
        "🕰️ مدیریت زمان صحبت‌ها را انجام بده تا همه بازیکنان صحبت کنند.\n"
        "🗳️ سپس رأی‌گیری را برگزار کن.\n\n"
        "➡️ پس از پایان رأی‌گیری، دکمه زیر را بزن تا بازیکنانی که به دفاع "
        "رفته‌اند انتخاب شوند.\n"
    )
    if ki_as:
        if host_picks_winner:
            return (
                "🕰️ بازیکنان را بیدار کن؛ به آن‌ها <b>۲ دقیقه</b> فرصت بحث بده.\n"
                "در پایان، هر بازیکن باید <b>شهروند خودش</b> را معرفی کند.\n\n"
                f"امروز <b>{CHAOS_PHASE_LABEL}</b> است — <b>رأی‌گیری عادی انجام نمی‌شود</b>.\n"
                "پس از پایان بحث، <b>نتیجهٔ بازی</b> را با یکی از دکمه‌های زیر ثبت کن:\n\n"
                "• اگر <b>شهروند به مافیا</b> دست داد → مافیا برنده است.\n"
                "• اگر <b>شهروند به شهروند</b> دست داد → شهروند برنده است.\n"
            )
        return (
            "🕰️ مدیریت زمان صحبت‌ها را انجام بده تا همه بازیکنان صحبت کنند.\n"
            "بازیکنان را بیدار کن؛ <b>۲ دقیقه</b> فرصت بحث دارند.\n"
            "در پایان ۲ دقیقه، هر بازیکن باید <b>شهروند خودش</b> را معرفی کند.\n\n"
            f"سپس به هر سه نفر در چت ربات پیام «دست دادن» می‌رود؛ امروز <b>رأی‌گیری عادی نیست</b>.\n"
            f"نتیجهٔ <b>{CHAOS_PHASE_LABEL}</b> فقط از انتخاب دوطرفهٔ بازیکنان محاسبه می‌شود.\n"
        )
    return base


def _reset_night_flags(game: Game) -> None:
    game.actions = NightActions()
    game.bazpors_nato_action_registered = False
    game.bazpors_nato_success = None
    game.bazpors_nato_kill_target_uid = None
    game.bazpors_mafia_shot_registered = False
    game.bazpors_detective_blocked = False
    game.bazpors_detective_last_answer = None
    game.bazpors_det_ack_positive = False
    game.bazpors_det_no_inquiry = False
    game.bazpors_shiad_target_uid = None
    game.bazpors_nato_guess_target_uid = None
    yaku_night_state(game).clear_civilian_pick_state()
    game.bazpors_night_report_html = None
    game.bazpors_observer_night_report_sent_night = None
    game.bazpors_assistant_night_report_sent_night = None
    game.bazpors_nato_guess_role = None
    game.bazpors_nato_multi_uids = None
    game.bazpors_interrog_first_uid = None
    game.bazpors_interrog_night_finished = False
    game.bazpors_interrog_second_uid = None
    game.bazpors_interrog_ready_for_day = False
    game.bazpors_interrog_cancel_next_day = False
    game.bazpors_night_announce_lines.clear()
    game.bazpors_absent_night_role = None
    game.bazpors_night_step_history.clear()
    game.bazpors_night_pending_doctor_self_save = False
    game.bazpors_night_discipline_kick_uid = None
    game.bazpors_hunter_linked_this_night = False
    game.bazpors_hunter_report_link_uid = None
    game.bazpors_hunter_report_chain_line = None
    game.bazpors_sniper_night_target_uid = None
    from bot.room_mode import is_mozakere_scenario
    from bot.roles.night_state import mozakere_negotiation_night_state

    if is_mozakere_scenario(game):
        mozakere_negotiation_night_state(game).clear_tonight()
    game.bazpors_sniper_hero_mafia_kill = False
    game.no_host_detective_dm_signature = None
    game.no_host_detective_flow_active = False
    game.no_host_detective_pick_confirmed = False
    game.no_host_detective_pending_tid = None
    game.no_host_detective_result_pending = False
    game.no_host_doctor_dm_signature = None
    game.no_host_doctor_flow_active = False
    game.no_host_doctor_pick_confirmed = False
    game.no_host_doctor_nato_blocked_panel = False
    game.no_host_doctor_pending_save_uids = []
    game.bazpors_doctor_save_uids = []
    game.no_host_sniper_dm_signature = None
    game.no_host_sniper_flow_active = False
    game.no_host_sniper_pick_confirmed = False
    game.no_host_sniper_pending_target_uid = None
    game.no_host_sniper_result_pending = False
    game.no_host_journalist_dm_signature = None
    game.no_host_journalist_flow_active = False
    game.no_host_journalist_pick_confirmed = False
    game.no_host_journalist_pending_tid = None
    game.no_host_journalist_idle_confirmed = False
    game.no_host_journalist_result_pending = False
    from bot.roles.night_state import mozakere_journalist_night_state

    if is_mozakere_scenario(game):
        mozakere_journalist_night_state(game).clear_night()
    game.no_host_ruintan_dm_signature = None
    game.no_host_ruintan_night_confirmed = False
    game.no_host_citizen_night_batch_signature = None
    game.no_host_citizen_night_confirmed_uids = []
    game.no_host_shiad_dm_signature = None
    game.no_host_shiad_flow_active = False
    game.no_host_shiad_pick_confirmed = False
    game.no_host_shiad_pending_tid = None
    game.no_host_shiad_result_pending = False
    game.no_host_night_entry_dispatched_night = None
    game.no_host_night_sage_dispatched_night = None
    game.no_host_sage_needs_observer_resync = False
    game.no_host_interrog_wait_dm_signature = None
    game.no_host_interrog_dm_signature = None
    game.no_host_interrog_flow_active = False
    game.no_host_interrog_pick_confirmed = False
    game.no_host_interrog_ui_phase = None
    from bot.no_host_interrog_day import reset_no_host_interrog_day_state
    from bot.no_host_table_inquiry import reset_no_host_table_inquiry_state

    reset_no_host_interrog_day_state(game)
    reset_no_host_table_inquiry_state(game)
    game.no_host_night_parallel_collect_active = False



def _pick_rows(
    code: str, act: str, players: list[Player], gm: GameManager, emoji: str
) -> list[list[InlineKeyboardButton]]:
    from bot.semi_auto_role_pick_common import build_narrator_pick_rows

    return build_narrator_pick_rows(code, act, players, gm, emoji)


def _nato_back_button_row(code: str) -> list[InlineKeyboardButton]:
    return build_narrator_action_row(code, "nato_back", "↩️ بازگشت")


def _yaku_back_button_row(code: str) -> list[InlineKeyboardButton]:
    return build_narrator_action_row(code, "yaku_back", "↩️ بازگشت")


def _nato_role_buttons(code: str) -> list[list[InlineKeyboardButton]]:
    items = [(role_label_fa(r), r.value) for r in NATO_GUESS_ROLES]
    rows = build_narrator_labeled_grid_rows(code, "nrole", items)
    return append_narrator_extra_rows(rows, _nato_back_button_row(code))


def _apply_night_resolution(game: Game, gm: GameManager) -> None:
    su = yaku_night_state(game).sacrifice_elimination_uid()
    if su is not None:
        sac = game.players[su]
        if sac.is_alive:
            note = _eliminate_player(game, gm, su, elim_source="night_resolve")
            if note:
                _append_host_flush_note(game, note)
    if game.bazpors_nato_success and game.bazpors_nato_kill_target_uid is not None:
        u = game.bazpors_nato_kill_target_uid
        if u in game.players and game.players[u].is_alive:
            note = _eliminate_player(game, gm, u, elim_source="night_resolve")
            if note:
                _append_host_flush_note(game, note)
    t = game.actions.mafia_target
    saves = _doctor_save_uid_set(game)
    if game.bazpors_mafia_shot_registered and t is not None and t in game.players:
        pl = game.players[t]
        if pl.is_alive and t not in saves:
            from bot.room_mode import is_mozakere_scenario

            survived_shot = False
            if is_mozakere_scenario(game):
                from bot.roles.mozakere_armored import (
                    mafia_shot_armor_survival_announce_line,
                    mafia_shot_armor_survival_note,
                    mafia_shot_blocked_by_armor,
                )

                if mafia_shot_blocked_by_armor(game, pl):
                    _append_host_flush_note(
                        game, mafia_shot_armor_survival_note(game, gm, t)
                    )
                    game.bazpors_night_announce_lines.append(
                        mafia_shot_armor_survival_announce_line(game, gm, t)
                    )
                    survived_shot = True
            if not survived_shot and _ruintan_role.mafia_shot_survives(pl):
                _append_host_flush_note(
                    game,
                    "<b>شات روی رویین‌تن بود.</b> در این سناریو شات شب مافیا روی رویین‌تن "
                    "<b>نمی‌نشیند</b>؛ این بازیکن از این شات از بازی خارج نمی‌شود.",
                )
                game.bazpors_night_announce_lines.append(
                    "شات روی رویین‌تن؛ طبق قانون، شات شب مافیا روی رویین‌تن نمی‌نشیند و او خارج نشد."
                )
            elif not survived_shot:
                note = _eliminate_player(game, gm, t, elim_source="night_resolve")
                if note:
                    _append_host_flush_note(game, note)
    _apply_sniper_night_resolution(game, gm)


def _tag_esc(game: Game, gm: GameManager, uid: int | None) -> str:
    if uid is None or uid not in game.players:
        return "؟"
    return html.escape(gm.format_player_tag(game.players[uid]))


_NIGHT_REPORT_HDR = "🌙 ═══ <b>گزارش کامل شب گذشته</b> ═══"
_NIGHT_REPORT_FTR = "🌙 ════════════════════════"


def _nr_player_ref(game: Game, gm: GameManager, uid: int) -> str:
    """نام بازیکن (نقش) برای گزارش کامل شب."""
    p = game.players[uid]
    name = gm.format_player_tag(p)
    role = role_label_fa(p.role) if p.role else "؟"
    if name.strip() == role.strip():
        return f"<b>{html.escape(name)}</b>"
    return f"<b>{html.escape(name)}</b> ({html.escape(role)})"


def _nr_report_name(game: Game, gm: GameManager, uid: int) -> str:
    """نام نمایشی کامل بازیکن در گزارش شب."""
    return html.escape(gm.format_player_tag(game.players[uid]))


def _nr_player_name_only(game: Game, uid: int) -> str:
    """فقط نام بازیکن — بدون نقش (گزارش مذاکره)."""
    p = game.players.get(uid)
    if p is None:
        return html.escape(str(uid))
    return html.escape(p.full_name or str(uid))


def _nr_uid_for_role(game: Game, role: Role) -> int | None:
    for uid, p in game.players.items():
        if p.role == role:
            return uid
    return None


def _nr_append_section(parts: list[str], lines: list[str]) -> None:
    if not lines:
        return
    parts.extend(lines)


def _night_report_hunter_chain_eliminated(
    game: Game,
    hunter_uid: int,
    report_link: int,
    alive_before: dict[int, bool],
) -> bool:
    """هانتر شب گذشته با زنجیرهٔ وصل مافیا (غیر رئیس) خارج شده."""
    if not alive_before.get(hunter_uid, False):
        return False
    if game.players[hunter_uid].is_alive:
        return False
    lp = game.players[report_link]
    if lp.is_alive:
        return False
    return _hunter_chain_eliminates_link(game, lp)


def _night_report_hunter_section(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> list[str]:
    if not _game_has_role(game, Role.HUNTER):
        return []
    hunter_uid = _nr_uid_for_role(game, Role.HUNTER)
    if hunter_uid is None or not alive_before.get(hunter_uid, False):
        return []
    report_link = game.bazpors_hunter_report_link_uid
    if report_link is None or report_link not in game.players:
        return []
    link_name = _nr_report_name(game, gm, report_link)
    if _night_report_hunter_chain_eliminated(
        game, hunter_uid, report_link, alive_before
    ):
        return [f"🏹 هانتر - {link_name} (به همراه هانتر کشته شد)"]
    return [f"🏹 هانتر: {link_name}"]


def _night_report_nato_line(game: Game, gm: GameManager) -> str | None:
    """یک خط ناتویی در گزارش کامل شب — موفق یا ناموفق."""
    if not game.bazpors_nato_action_registered:
        return None
    if game.bazpors_nato_success:
        kill_uid = game.bazpors_nato_kill_target_uid
        if kill_uid is not None and kill_uid in game.players:
            return f"🔴 ناتو: {_nr_report_name(game, gm, kill_uid)} خارج شد"
        return None
    if game.bazpors_nato_success is not False:
        return None

    role_txt: str | None = None
    if game.bazpors_nato_guess_role:
        try:
            role_txt = role_label_fa(Role(game.bazpors_nato_guess_role))
        except ValueError:
            pass
    tgt_uid = game.bazpors_nato_guess_target_uid
    if tgt_uid is None:
        tgt_uid = game.bazpors_narrator_pending_uid
    tgt_name = (
        _nr_report_name(game, gm, tgt_uid)
        if tgt_uid is not None and tgt_uid in game.players
        else None
    )
    if role_txt and tgt_name:
        return f"⚪ ناتویی ناموفق — حدس نقش {role_txt} — هدف {tgt_name}"
    if role_txt:
        return f"⚪ ناتویی ناموفق — حدس نقش {role_txt}"
    if tgt_name:
        return f"⚪ ناتویی ناموفق — هدف {tgt_name}"
    return "⚪ ناتویی ناموفق"


def _night_report_mozakere_negotiation_line(
    game: Game, gm: GameManager
) -> str | None:
    from bot.room_mode import is_mozakere_scenario
    from bot.roles.night_state import mozakere_negotiation_night_state

    del gm
    if not is_mozakere_scenario(game):
        return None
    state = mozakere_negotiation_night_state(game)
    if not state.tonight and not game.mozakere_negotiation_used:
        return None
    target_uid = state.target_uid or game.mozakere_negotiation_target_uid
    if target_uid is None or target_uid not in game.players:
        return None
    target_name = _nr_player_name_only(game, target_uid)
    success = state.night_success
    if success is None:
        success = game.mozakere_negotiation_success
    if success is True:
        return f"🤝 مذاکره موفق با ({target_name})"
    if success is False:
        return f"🤝 مذاکره ناموفق با ({target_name})"
    return f"🤝 مذاکره با ({target_name})"


def _night_report_mozakere_journalist_line(
    game: Game, gm: GameManager
) -> str | None:
    from bot.room_mode import is_mozakere_scenario
    from bot.roles.mozakere_journalist import load_result

    del gm
    if not is_mozakere_scenario(game):
        return None
    if not game.no_host_journalist_pick_confirmed:
        return None
    result = load_result(game)
    if result is None:
        return None
    target_name = _nr_player_name_only(game, result.target_uid)
    label = "مثبت" if result.is_positive else "منفی"
    return f"📰 استعلام خبرنگار: {target_name} — {label}"


def _night_report_mafia_section(game: Game, gm: GameManager) -> list[str]:
    lines: list[str] = []
    shot_t = game.actions.mafia_target
    if (
        game.bazpors_mafia_shot_registered
        and shot_t is not None
        and shot_t in game.players
    ):
        lines.append(f"🔴 شات مافیا: {_nr_report_name(game, gm, shot_t)}")

    neg_line = _night_report_mozakere_negotiation_line(game, gm)
    if neg_line:
        lines.append(neg_line)

    nato_line = _night_report_nato_line(game, gm)
    if nato_line:
        lines.append(nato_line)

    yaku_line = _night_report_yaku_line(game, gm)
    if yaku_line:
        lines.append(yaku_line)

    return lines


def _night_report_yaku_line(game: Game, gm: GameManager) -> str | None:
    """یک خط یاکوزایی در گزارش کامل شب — موفق یا ناموفق."""
    yaku = yaku_night_state(game)
    if not yaku.used:
        return None
    civ_uid = yaku.night_civilian_uid
    sac_uid = yaku.report_sac_uid
    if civ_uid is None or civ_uid not in game.players:
        return None
    if sac_uid is None or sac_uid not in game.players:
        return None
    target_name = _nr_report_name(game, gm, civ_uid)
    sac_name = _nr_report_name(game, gm, sac_uid)
    if yaku.night_success:
        label = "یاکوزایی موفق"
    elif yaku.night_success is False:
        label = "یاکوزایی ناموفق"
    elif game.bazpors_mafia_recruit_ids and civ_uid in game.bazpors_mafia_recruit_ids:
        label = "یاکوزایی موفق"
    elif yaku.night_civilian_uid is not None:
        label = "یاکوزایی ناموفق"
    else:
        return None
    return (
        f"🤝 {label} با ({target_name} - مافیای فدا شده: {sac_name})"
    )


def _night_report_shiad_section(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> list[str]:
    if not _game_has_role(game, Role.SHIAD):
        return []
    shiad_uid = _nr_uid_for_role(game, Role.SHIAD)
    if shiad_uid is None or not alive_before.get(shiad_uid, False):
        return []
    tgt_uid = game.bazpors_shiad_target_uid
    if tgt_uid is None or tgt_uid not in game.players:
        return []
    return [f"🎭 شیاد: {_nr_report_name(game, gm, tgt_uid)}"]


def _night_report_detective_section(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> list[str]:
    if not _game_has_role(game, Role.DETECTIVE):
        return []
    det_uid = _nr_uid_for_role(game, Role.DETECTIVE)
    if det_uid is None or not alive_before.get(det_uid, False):
        return []
    if game.bazpors_det_no_inquiry:
        return []
    check_uid = game.actions.detective_check
    if check_uid is None or check_uid not in game.players:
        return []
    res = detective_inquiry_result_label_fa(game)
    if res is None:
        return []
    return [
        f"🕵️ استعلام کارآگاه: {_nr_report_name(game, gm, check_uid)} — {res}"
    ]


def _night_report_doctor_section(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> list[str]:
    if not _game_has_role(game, Role.DOCTOR):
        return []
    doc_uid = _nr_uid_for_role(game, Role.DOCTOR)
    if doc_uid is None or not alive_before.get(doc_uid, False):
        return []
    if game.bazpors_nato_action_registered:
        return []
    if _semi_auto_doctor_skip_after_yaku_this_night(game):
        return []
    from bot.room_mode import is_mozakere_scenario
    from bot.roles.night_state import doctor_night_state

    if is_mozakere_scenario(game):
        save_uids = [
            uid
            for uid in doctor_night_state(game).get_save_uids()
            if uid in _doctor_save_uid_set(game)
        ]
        if not save_uids:
            return []
        names = [_nr_player_name_only(game, uid) for uid in save_uids]
        if len(names) == 1:
            return [f"💉 نجات پزشک: {names[0]}"]
        bullet_lines = "\n".join(f"- {name}" for name in names)
        return [f"💉 نجات پزشک:\n{bullet_lines}"]
    save_uids = list(_doctor_save_uid_set(game))
    if not save_uids:
        return []
    return [f"💉 نجات پزشک: {_nr_report_name(game, gm, save_uids[0])}"]


def _night_report_interrog_section(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> list[str]:
    if not _game_has_role(game, Role.INTERROGATOR):
        return []
    u1, u2 = game.bazpors_interrog_first_uid, game.bazpors_interrog_second_uid
    if not (
        game.bazpors_interrog_night_finished
        and u1 is not None
        and u2 is not None
        and u1 in game.players
        and u2 in game.players
    ):
        return []
    return [
        "⚖️ بازپرس: "
        f"{_nr_report_name(game, gm, u1)} و {_nr_report_name(game, gm, u2)}"
    ]


def _night_report_sniper_section(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> list[str]:
    if not _bazpors_sniper_nights_enabled(game) or not _game_has_role(game, Role.SNIPER):
        return []
    sn_uid = _nr_uid_for_role(game, Role.SNIPER)
    if sn_uid is None or not alive_before.get(sn_uid, False):
        return []
    tgt_uid = game.bazpors_sniper_night_target_uid
    if tgt_uid is None or tgt_uid not in game.players:
        return []
    tgt = game.players[tgt_uid]
    name = _nr_report_name(game, gm, tgt_uid)
    from bot.room_mode import is_mozakere_scenario

    if is_mozakere_scenario(game):
        if (
            not game.players[sn_uid].is_alive
            and tgt.is_alive
            and not _boss_role.sniper_boss_immune(tgt)
            and not bazpors_counts_as_mafia_faction(game, tgt)
        ):
            role_lbl = role_label_fa(tgt.role) if tgt.role else "شهروند"
            return [f"🎯 تک‌تیرانداز: {name} — شلیک اشتباه ({role_lbl})"]
        return [f"🎯 تک‌تیرانداز: {name}"]
    if (
        game.bazpors_sniper_shot_used
        and not _boss_role.sniper_boss_immune(tgt)
        and not bazpors_counts_as_mafia_faction(game, tgt)
    ):
        role_lbl = role_label_fa(tgt.role) if tgt.role else "شهروند"
        dead_note = "" if tgt.is_alive else " — هدف از قبل مرده بود"
        return [
            f"🎯 تک‌تیرانداز: {name} — شلیک اشتباه ({role_lbl}){dead_note}"
        ]
    return [f"🎯 تک‌تیرانداز: {name}"]


def _discipline_kick_uids(game: Game) -> list[int]:
    uid = game.bazpors_night_discipline_kick_uid
    if uid is not None and uid in game.players:
        return [uid]
    return []


def _nr_discipline_outcome_line(game: Game, gm: GameManager, uid: int) -> str:
    p = game.players[uid]
    tag = html.escape(gm.format_player_tag(p))
    role_txt = html.escape(role_label_fa(p.role)) if p.role else "؟"
    return f"اخراج انضباطی: <b>{tag}</b> — {role_txt}"


def _mark_day_start_alive_snapshot(game: Game) -> None:
    game.bazpors_alive_at_day_start = {
        uid: p.is_alive for uid, p in game.players.items()
    }


def _nr_farewell_names_fa(game: Game, gm: GameManager, uids: list[int]) -> str:
    parts = [
        html.escape(gm.format_player_tag(game.players[u]))
        for u in uids
        if u in game.players
    ]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} و {parts[1]}"
    return "، ".join(parts[:-1]) + f" و {parts[-1]}"


def _night_report_day_farewell_uids(
    game: Game, alive_before: dict[int, bool]
) -> list[int]:
    """بازیکنانی که بین شروع روز و شروع شب از بازی خارج شده‌اند."""
    day_start = game.bazpors_alive_at_day_start
    if day_start is not None:
        return [
            uid
            for uid in game.players
            if day_start.get(uid, True) and not alive_before.get(uid, True)
        ]
    # no_host روز اول: اسنپ‌شات روز ممکن است ثبت نشده باشد — هر کس که
    # قبل از شروع شب مرده، در «خداحافظی روز قبل» می‌آید.
    return [
        uid for uid in game.players if not alive_before.get(uid, True)
    ]


def _night_report_outcome_section(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> list[str]:
    """خداحافظی روز قبل، شب گذشته، و اعلام بازپرسی امروز."""
    lines = ["🕯️ <b>نتیجه نهایی شب و روز گذشته:</b>"]

    day_died = _night_report_day_farewell_uids(game, alive_before)
    day_names = _nr_farewell_names_fa(game, gm, day_died)
    if day_names:
        lines.append(f"در روز قبل که با {day_names} خداحافظی کردیم.")
    else:
        lines.append("در روز قبل که با کسی خداحافظی نکردیم.")

    discipline_uids = set(_discipline_kick_uids(game))
    night_died = [
        uid
        for uid, p in game.players.items()
        if alive_before.get(uid, True) and not p.is_alive
    ]
    night_other = [uid for uid in night_died if uid not in discipline_uids]
    night_names = _nr_farewell_names_fa(game, gm, night_other)
    if night_names:
        lines.append(f"در شبی که گذشت، با {night_names} خداحافظی کردیم.")
    elif not discipline_uids:
        lines.append("در شبی که گذشت با کسی خداحافظی نکردیم.")

    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.mason_night_report import mason_night_report_natasha_silence_outcome_line

        natasha_silence = mason_night_report_natasha_silence_outcome_line(
            game, gm, alive_before
        )
        if natasha_silence:
            lines.append(natasha_silence)

    for uid in discipline_uids:
        lines.append(_nr_discipline_outcome_line(game, gm, uid))

    if is_mason_scenario(game) and game.mason_last_night_had_collapse:
        lines.append("دیشب مرگ ماسونی داشتیم.")

    if (
        game.bazpors_sniper_hero_mafia_kill
        and game.bazpors_host_mode in ("no_host", "semi_auto")
    ):
        lines.append(
            "تبریک به این شهر برای داشتن چنین تک‌تیرانداز قهرمان و بی‌رقیبی! 🎯🔥"
        )

    if (
        game.bazpors_interrog_ready_for_day
        and not game.bazpors_interrog_cancel_next_day
        and _interrog_nominees_both_alive(game)
    ):
        u1, u2 = game.bazpors_interrog_first_uid, game.bazpors_interrog_second_uid
        if u1 is not None and u2 is not None:
            lines.append(
                "امروز بازپرسی داریم که بین "
                f"<b>{_tag_esc(game, gm, u1)}</b> و <b>{_tag_esc(game, gm, u2)}</b> "
                "برگزار می‌شود."
            )

    return lines


def _compose_full_night_report(
    game: Game, gm: GameManager, alive_before: dict[int, bool]
) -> str:
    """گزارش کامل شب — فقط گرداننده می‌بیند؛ برای اعلام شفاهی به صندلی."""
    game.bazpors_night_announce_lines.clear()
    nc = max(1, game.bazpors_narrator_night_count)
    parts: list[str] = [
        f"<b>{_night_end_title_fa(nc)}</b>",
        "-----------",
    ]
    outcome_lines = _night_report_outcome_section(game, gm, alive_before)
    if outcome_lines:
        parts.extend(outcome_lines)
    parts.append("")
    parts.append(_NIGHT_REPORT_HDR)
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.mason_night_report import (
            _mason_night_report_nato_line,
            mason_night_report_section_builders,
        )

        _nr_append_section(parts, _night_report_mafia_section(game, gm))
        for section in mason_night_report_section_builders():
            _nr_append_section(parts, section(game, gm, alive_before))
        _nr_append_section(
            parts, _night_report_detective_section(game, gm, alive_before)
        )
        nato_line = _mason_night_report_nato_line(game, gm)
        if nato_line:
            _nr_append_section(parts, [nato_line])
    else:
        _nr_append_section(parts, _night_report_hunter_section(game, gm, alive_before))
        _nr_append_section(parts, _night_report_mafia_section(game, gm))
        _nr_append_section(parts, _night_report_shiad_section(game, gm, alive_before))
        _nr_append_section(
            parts, _night_report_detective_section(game, gm, alive_before)
        )
        _nr_append_section(parts, _night_report_doctor_section(game, gm, alive_before))
        _nr_append_section(parts, _night_report_interrog_section(game, gm, alive_before))
        journalist_line = _night_report_mozakere_journalist_line(game, gm)
        if journalist_line:
            _nr_append_section(parts, [journalist_line])
        _nr_append_section(parts, _night_report_sniper_section(game, gm, alive_before))
    return "\n".join(parts)


def build_bazpors_night_timeline_lines(game: Game, gm: GameManager) -> list[str]:
    """خطوط خلاصهٔ اقدامات یک شب — برای تایم‌لاین پایان بازی (همان بلوک گزارش کامل)."""
    alive_before = game.bazpors_alive_at_night_start
    if not alive_before:
        alive_before = {uid: p.is_alive for uid, p in game.players.items()}
    lines: list[str] = []
    for section in (
        _night_report_hunter_section,
        lambda g, m, a: _night_report_mafia_section(g, m),
        _night_report_shiad_section,
        _night_report_detective_section,
        _night_report_doctor_section,
        _night_report_interrog_section,
        lambda g, m, a: (
            [line]
            if (line := _night_report_mozakere_journalist_line(g, m)) is not None
            else []
        ),
        _night_report_sniper_section,
    ):
        lines.extend(section(game, gm, alive_before))
    return lines


def _farewell_night_fa(game: Game, gm: GameManager) -> str:
    """یک جملهٔ آمادهٔ اعلام خداحافظی‌شدگان شب به صندلی."""
    snap = game.bazpors_alive_at_night_start
    if not snap:
        return (
            "در شبی که گذشت، اگر کسی از صندلی رفت، جزییات را از بلوک "
            "«خلاصهٔ شب» در پیام قبلی برای بازیکن‌ها بخوان."
        )
    died = [
        uid
        for uid, p in game.players.items()
        if snap.get(uid, True) and not p.is_alive
    ]
    if not died:
        return "در شبی که گذشت با کسی خداحافظی نکردیم."
    parts = [
        html.escape(gm.format_player_tag(game.players[u]))
        for u in died
        if u in game.players
    ]
    if not parts:
        return "در شبی که گذشت با کسی خداحافظی نکردیم."
    if len(parts) == 1:
        return f"در شبی که گذشت با {parts[0]} خداحافظی کردیم."
    if len(parts) == 2:
        return f"در شبی که گذشت با {parts[0]} و {parts[1]} خداحافظی کردیم."
    return (
        "در شبی که گذشت با "
        + "، ".join(parts[:-1])
        + f" و {parts[-1]} خداحافظی کردیم."
    )


def _interrog_nominees_both_alive(game: Game) -> bool:
    return _interrogator_role.nominees_both_alive(game)


def _interrog_nominees_died_uids(
    game: Game, alive_before: dict[int, bool] | None = None
) -> list[int]:
    return _interrogator_role.nominees_died_uids(game, alive_before)


def _sync_interrog_day_state(game: Game) -> None:
    _interrogator_role.sync_day_state(game)


def _refresh_interrog_ready_for_day(game: Game) -> None:
    _interrogator_role.refresh_ready_for_day(game)


def _apply_interrog_cancel_if_nominee_died(
    game: Game, alive_before: dict[int, bool] | None = None
) -> None:
    _interrogator_role.apply_cancel_if_nominee_died(game, alive_before)


def _interrog_day_vote_pool(game: Game) -> list[Player]:
    return _interrogator_role.day_vote_pool(game)


def _clear_interrog_day_targets(game: Game) -> None:
    _interrogator_role.clear_day_targets(game)


def _mark_interrog_session_done(game: Game) -> None:
    _interrogator_role.mark_ability_used(game)


def _interrog_cancel_report_note_fa(
    game: Game, gm: GameManager, alive_before: dict[int, bool] | None = None
) -> str:
    died = _interrog_nominees_died_uids(game, alive_before)
    if len(died) == 1:
        who = _nr_player_ref(game, gm, died[0])
    elif len(died) > 1:
        who = " و ".join(_nr_player_ref(game, gm, u) for u in died)
    else:
        who = "یکی از نامزدهای بازپرسی"
    return (
        f"📌 توجه ⮜➤ بازپرسی روز منتفی شد — {who} "
        "که بازپرس برای بازپرسی انتخاب کرده بود در پایان شب از بازی خارج شد."
    )


def _interrog_cancel_reason_body_fa(
    game: Game, gm: GameManager, alive_before: dict[int, bool] | None = None
) -> str:
    died = _interrog_nominees_died_uids(game, alive_before)
    if not died:
        return (
            "یکی از بازیکنانی که بازپرس برای بازپرسی انتخاب کرده بود "
            "در پایان همان شب از بازی خارج شد."
        )
    tags = [_tag_esc(game, gm, u) for u in died]
    if len(tags) == 1:
        who = tags[0]
    else:
        who = " و ".join(tags)
    return (
        f"<b>{who}</b> که بازپرس برای بازپرسی انتخاب کرده بود "
        "در پایان همان شب از بازی خارج شد."
    )


def _interrog_cancel_notice_fa(
    game: Game, gm: GameManager, alive_before: dict[int, bool] | None = None
) -> str:
    return (
        "⚖️ <b>بازپرسی امروز نداریم.</b>\n"
        "چون "
        + _interrog_cancel_reason_body_fa(game, gm, alive_before)
        + "، بازپرسی نداریم."
    )


def _interrog_morning_block_fa(game: Game, gm: GameManager) -> str:
    _refresh_interrog_ready_for_day(game)
    if game.bazpors_interrog_cancel_next_day:
        return "\n\n" + _interrog_cancel_notice_fa(
            game, gm, game.bazpors_alive_at_night_start
        )
    if game.bazpors_interrog_ready_for_day:
        return (
            "\n\n✅ <b>امروز بازپرسی برنامه‌ریزی است</b> "
            "(دو نفر شب قبل نامزد شده‌اند)."
        )
    return ""


def _arm_night_actions_baseline(game: Game) -> None:
    from bot.roles.night_state import doctor_night_state
    from bot.room_mode import is_mozakere_scenario

    doctor_night_state(game).snapshot_night_baseline()
    if is_mozakere_scenario(game):
        game.mozakere_sniper_shots_used_at_night_start = game.mozakere_sniper_shots_used
    game.bazpors_night_discipline_kick_uid = None
    game.bazpors_alive_at_night_start = {
        uid: p.is_alive for uid, p in game.players.items()
    }


def _begin_night_actions(game: Game) -> None:
    if not (
        game.bazpors_host_mode == "no_host"
        and no_host_assistant_narrator_active(game)
    ):
        _reset_night_flags(game)
    _arm_night_actions_baseline(game)
    game.bazpors_narrator_step = NIGHT_ACTIONS
    game.bazpors_night_step_history = [NS_HUNTER]
    _enter_night_role_or_skip_absent(
        game, Role.HUNTER, NS_HUNTER, _advance_after_hunter
    )


def _advance_after_hunter(game: Game) -> None:
    _night_forward(game, NS_MAFIA_MENU)


def _advance_after_mafia_menu_done(game: Game) -> None:
    _enter_night_role_or_skip_absent(
        game, Role.SHIAD, NS_SHIAD, _advance_after_shiad
    )


def _advance_after_shiad(game: Game) -> None:
    if _find_alive_role(game, Role.DETECTIVE):
        if game.bazpors_detective_blocked:
            game.actions.detective_check = None
            _advance_after_det(game)
        else:
            _night_forward(game, NS_DET)
        return
    _enter_night_role_or_skip_absent(
        game, Role.DETECTIVE, NS_DET, _advance_after_det
    )


def detective_inquiry_alert_text(game: Game) -> str | None:
    """متن پاپ‌آپ بعد از ثبت استعلام؛ فقط وقتی در NS_DET_ACK هستیم."""
    if no_host_assistant_narrator_active(game):
        return None
    if game.bazpors_night_substep != NS_DET_ACK:
        return None
    result = load_detective_inquiry_result(game)
    if result is None:
        return None
    if result.is_positive:
        return "نتیجه استعلام مثبت\n\nبه کاراگاه استعلام مثبت نشون بده"
    return "نتیجه استعلام منفی\n\nبه کاراگاه استعلام منفی نشون بده"


def shiad_detective_alert_text(game: Game, act: str = "") -> str | None:
    """پاپ‌آپ پس از تأیید انتخاب کارآگاه (شیاد روی کارآگاه) — نیمه‌خودکار."""
    if act != "sdp_ok" or not game.bazpors_detective_blocked:
        return None
    if no_host_assistant_narrator_active(game):
        return None
    return detective_inquiry_alert_text(game)


def _goto_interrogator_night_step(game: Game) -> None:
    if not _find_alive_role(game, Role.INTERROGATOR):
        if _role_eliminated_from_game(game, Role.INTERROGATOR):
            _goto_role_absent(game, Role.INTERROGATOR)
        else:
            _advance_after_interrogator_phase(game)
        return
    if _interrogator_role.ability_used(game):
        _night_forward(game, NS_INTERROG_SKIP)
        return
    _night_forward(game, NS_INT1)


def _advance_after_det(game: Game) -> None:
    _void_semi_auto_doctor_night_pick(game)
    if (
        game.bazpors_nato_action_registered
        and narrator_enabled_for_room(game)
        and not no_host_assistant_narrator_active(game)
        and _find_alive_role(game, Role.DOCTOR)
    ):
        _night_forward(game, NS_DOC_NATO_SKIP)
        return
    if game.bazpors_nato_action_registered:
        _goto_interrogator_night_step(game)
        return
    if _semi_auto_doctor_skip_after_yaku_this_night(game):
        if _find_alive_role(game, Role.DOCTOR):
            _night_forward(game, NS_DOC_YAKU_SKIP)
            return
        _advance_after_doc(game)
        return
    _enter_night_role_or_skip_absent(
        game, Role.DOCTOR, NS_DOC, _advance_after_doc
    )


def _advance_after_doc(game: Game) -> None:
    _goto_interrogator_night_step(game)


def _advance_after_int1(game: Game) -> None:
    game.bazpors_night_substep = NS_INT2


def _advance_after_int2(game: Game) -> None:
    _advance_after_interrogator_phase(game)


def _advance_after_interrogator_phase(game: Game) -> None:
    if not _bazpors_sniper_nights_enabled(game):
        _goto_discipline_ask(game)
        return
    if _find_alive_role(game, Role.SNIPER):
        _night_forward(game, NS_SNIPER)
    elif _role_eliminated_from_game(game, Role.SNIPER):
        _goto_role_absent(game, Role.SNIPER)
    else:
        _goto_discipline_ask(game)


def _finish_resolve_to_extra(game: Game, gm: GameManager) -> None:
    snap = game.bazpors_alive_at_night_start or {
        uid: p.is_alive for uid, p in game.players.items()
    }
    _commit_night_pending_state(game)
    _apply_night_resolution(game, gm)
    _apply_interrog_cancel_if_nominee_died(game, snap)
    _refresh_interrog_ready_for_day(game)
    game.bazpors_night_report_html = _compose_full_night_report(game, gm, snap)
    game.bazpors_host_flush_note = None
    game.bazpors_night_substep = None
    if no_host_assistant_narrator_active(game):
        game.no_host_detective_result_pending = True
        if game.no_host_sniper_pick_confirmed:
            game.no_host_sniper_result_pending = True
        if game.no_host_shiad_pick_confirmed:
            game.no_host_shiad_result_pending = True
        if game.no_host_journalist_pick_confirmed:
            game.no_host_journalist_result_pending = True
    gm.check_winner(game)
    if trigger_win_gate_if_needed(game, gm, elim_source="night_resolve"):
        _evaluate_post_night_host_state(game, gm)
    else:
        game.bazpors_narrator_step = ASK_NIGHT_EXTRA
        _evaluate_post_night_host_state(game, gm)
    try:
        from bot.game_audit_log import log_night_resolved

        log_night_resolved(game, gm)
    except Exception:
        pass


def build_host_message_and_keyboard(
    game: Game, gm: GameManager
) -> tuple[str, InlineKeyboardMarkup | None]:
    if (
        game.bazpors_narrator_step == ASK_NIGHT_EXTRA
        and no_mafia_alive(game, gm)
    ):
        game.bazpors_citizen_win_elim_source = (
            game.bazpors_citizen_win_elim_source or "night_resolve"
        )
        game.bazpors_narrator_step = CITIZEN_WIN_GATE
    elif (
        game.bazpors_narrator_step == ASK_NIGHT_EXTRA
        and mafia_citizen_equal(game, gm)
    ):
        game.bazpors_mafia_tie_after_night_report = True
        game.bazpors_narrator_step = MAFIA_TIE_GATE

    step = game.bazpors_narrator_step
    code = game.room_code
    ns = game.bazpors_night_substep
    win = _win_note(gm, game)

    from bot.no_host_interrog_day import (
        NO_HOST_INTERROG_DAY,
        build_no_host_interrog_day_assistant_panel,
    )
    from bot.no_host_handoff import (
        NO_HOST_HANDOFF_OFFER,
        build_handoff_offer_panel,
    )
    from bot.no_host_table_inquiry import (
        NO_HOST_TABLE_INQUIRY,
        build_no_host_table_inquiry_assistant_panel,
    )

    if step == NO_HOST_HANDOFF_OFFER:
        return build_handoff_offer_panel(game, gm)

    if step == NO_HOST_INTERROG_DAY:
        return build_no_host_interrog_day_assistant_panel(game, gm)

    if step == NO_HOST_TABLE_INQUIRY:
        return build_no_host_table_inquiry_assistant_panel(game, gm)

    if step == CITIZEN_WIN_GATE:
        roster = _players_roster_html(game, gm)
        src = game.bazpors_citizen_win_elim_source
        report = game.bazpors_night_report_html or ""
        show_night_report = src == "night_resolve" and bool(report)
        if show_night_report:
            body = (
                f"{report}\n\n"
                f"{roster}\n\n"
                f"{_citizen_win_notice_html(game, gm)}\n"
                f"{win}"
            )
        else:
            body = (
                f"{_citizen_win_notice_html(game, gm)}\n\n"
                f"{roster}\n"
                f"{win}"
            )
        return body, _citizen_win_gate_keyboard(code)

    if step == MAFIA_TIE_GATE:
        roster = _players_roster_html(game, gm)
        report = game.bazpors_night_report_html or ""
        show_report = game.bazpors_mafia_tie_after_night_report and bool(report)
        if show_report:
            body = (
                f"{report}\n\n"
                f"{roster}\n\n"
                f"{_mafia_tie_notice_html(game, gm, after_night_report=True)}\n"
                f"{win}"
            )
        else:
            body = (
                f"{_mafia_tie_notice_html(game, gm, after_night_report=False)}\n\n"
                f"{roster}\n"
                f"{win}"
            )
        return body, _mafia_tie_gate_keyboard(code)

    if step == PICK_DISCIPLINE_KICK:
        rows = _pick_rows(code, "disc_pick", _alive(game), gm, "🚪")
        return (
            f"🚪 <b>اخراج انضباطی</b>\n\n"
            f"بازیکنی را که قصد اخراج انضباطی داری انتخاب کن.\n{win}",
            InlineKeyboardMarkup(
                inline_keyboard=_append_night_back_row(code, game, rows)
            ),
        )

    if step == CONFIRM_DISCIPLINE_KICK:
        uid = game.bazpors_narrator_pending_uid
        if uid is None or uid not in game.players:
            return "خطا.", None
        v = game.players[uid]
        return (
            f"تأیید اخراج انضباطی؟\n<b>{html.escape(gm.format_player_tag(v))}</b>{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ تأیید اخراج",
                            callback_data=BazporsNarrCb(
                                code=code, act="disc_ok", tid=0
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="↩️ برگشت",
                            callback_data=BazporsNarrCb(
                                code=code, act="disc_back", tid=0
                            ).pack(),
                        ),
                    ]
                ]
            ),
        )

    if step == CONFIRM_DISCIPLINE_NO:
        return (
            "⭕ <b>بدون اخراج انضباطی</b>\n\n"
            "آیا تأیید می‌کنید که در این شب اخراج انضباطی انجام نمی‌شود؟"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ تأیید",
                            callback_data=BazporsNarrCb(
                                code=code, act="disc_no_ok", tid=0
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="↩️ برگشت",
                            callback_data=BazporsNarrCb(
                                code=code, act="disc_no_back", tid=0
                            ).pack(),
                        ),
                    ]
                ]
            ),
        )

    if step == ROLE_ASSIGNED:
        return (
            "🎭 <b>نقش‌ها پخش شد</b>\n\n"
            "📜 لیست کامل نقش‌ها در پیام قبلی قرار دارد.\n"
            "📩 هر بازیکن نقش خود را به‌صورت خصوصی دریافت کرده است.\n\n"
            "☀️ اکنون <b>روز معارفه</b> را آغاز کنید؛\n"
            "🗣️ بدون رأی‌گیری و بدون خروج بازیکن.\n"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="☀️ شروع روز معارفه",
                            callback_data=BazporsNarrCb(
                                code=code, act="start_intro_day"
                            ).pack(),
                        )
                    ]
                ]
            ),
        )

    if step == INTRO_DAY:
        return (
            "☀️ <b>روز معارفه آغاز شد</b>\n\n"
            "🎙️ بازیکنان فقط به معرفی خود می‌پردازند.\n"
            "🚫 در این مرحله هیچ چالشی برگزار نمی‌شود.\n\n"
            "🌙 پس از پایان معارفه، دکمه «<b>شروع شب معارفه</b>» را بزنید.\n"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🌙 شروع شب معارفه",
                            callback_data=BazporsNarrCb(
                                code=code, act="start_intro_night"
                            ).pack(),
                        )
                    ]
                ]
            ),
        )

    if step == INTRO_NIGHT:
        return (
            "🌙 <b>شب معارفه آغاز شد</b>\n\n"
            "😴 همه بازیکنان را بخوابان.\n"
            "🔴 سپس تیم مافیا را بیدار کن تا اعضا یکدیگر را بشناسند.\n\n"
            "🚫 در این شب هیچ شلیک، استعلام، نجات، بازپرسی، هانتر، شیاد یا اسنایپری "
            "انجام نمی‌شود.\n\n"
            + _mafia_intro_html(game, gm)
            + "\n\n😴 پس از آشنایی، تیم مافیا را بخوابان.\n\n"
            "☀️ سپس دکمه «<b>اعلام روز اول</b>» را بزن.\n"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="☀️ اعلام روز اول",
                            callback_data=BazporsNarrCb(
                                code=code, act="announce_day1"
                            ).pack(),
                        )
                    ]
                ]
            ),
        )

    if step == CHAOS_DAY_HANDSHAKE:
        from bot.chaos_handshake import build_chaos_assistant_panel_html

        return (
            build_chaos_assistant_panel_html(game, gm) + win,
            None,
        )

    if step == DAY_DISCUSS:
        _sync_ki_as_today(game, gm)
        d = max(1, game.bazpors_narrator_host_day)
        ki_as = game.bazpors_ki_as_today and not gm.check_winner(game)
        ki_resolve = ki_as_hand_resolve_day_active(game, gm)
        host_picks = semi_auto_chaos_host_picks_winner(game) and ki_resolve
        day_head = (
            f"{_day_start_title_fa(d, ki_as=ki_as)}\n\n"
            f"{_day_discuss_body_fa(ki_as=ki_as, host_picks_winner=host_picks)}"
        )
        extra = ""
        if ki_resolve and no_host_assistant_narrator_active(game):
            extra = (
                f"\n\n🤝 <b>{CHAOS_PHASE_LABEL}</b>\n"
                "پس از بحث، به هر سه بازیکن زنده در چت ربات پیام "
                "«دست دادن» ارسال می‌شود.\n"
                "نتیجه فقط از انتخاب دوطرفهٔ بازیکنان محاسبه می‌شود."
            )
        if no_host_assistant_narrator_active(game):
            # رأی پایان روز فقط در پیام اختصاصی mirror (send_no_host_day_vote_prompt)
            kb = None
        elif host_picks:
            kb = _ki_as_chaos_win_keyboard(code)
        else:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗳 رأی‌گیری انجام شد",
                            callback_data=BazporsNarrCb(
                                code=code, act="vote_done"
                            ).pack(),
                        )
                    ]
                ]
            )
        return (
            day_head + extra + win,
            kb,
        )

    if step == DAY_VOTE_PICK_DEFENDERS:
        d = max(1, game.bazpors_narrator_host_day)
        if d == 1:
            day_label = "روز اول"
        elif d == 2:
            day_label = "روز دوم"
        elif d == 3:
            day_label = "روز سوم"
        else:
            day_label = f"روز {_seat_fa(d)}"
        n_sel = len(_day_vote_pick_uids(game))
        sel_note = (
            f"\n<i>انتخاب‌شده: {_seat_fa(n_sel)} نفر</i>\n\n" if n_sel else "\n"
        )
        return (
            f"🛡️ <b>{day_label} — ثبت بازیکنان داخل دفاعیه</b>\n\n"
            "📋 لیست کامل بازیکنان بازی در زیر آمده است.\n\n"
            "✅ بازیکنانی که در رأی‌گیری وارد دفاعیه شدند (از خود دفاع کردند) را "
            "با لمس نامشان انتخاب کن.\n"
            "👥 می‌توانی یک یا چند نفر را انتخاب کنی.\n"
            f"{sel_note}"
            "🚫 اگر هیچ‌کس وارد دفاعیه نشد، گزینه «<b>هیچکسی وارد دفاعیه نشد</b>» را بزن.\n\n"
            "➡️ پس از اتمام، دکمه «<b>تأیید انتخاب‌ها</b>» را بزن.\n"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=_day_vote_toggle_rows(code, game, gm)
            ),
        )

    if step == DAY_VOTE_ELIM_ASK:
        history = _day_vote_participation_history_html(game, gm)
        n_def = len(_day_vote_defender_uids(game))
        if n_def == 0:
            return (
                "🗳️ <b>نتیجهٔ رأی‌گیری پایان روز</b>\n\n"
                "هیچ‌کس وارد دفاعیه نشد؛ کسی با رأی روز خارج نمی‌شود.\n"
                "با «ورود به فاز شب» به شب بعد می‌روی.\n\n"
                f"{win}",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🌙 ورود به فاز شب",
                                callback_data=BazporsNarrCb(
                                    code=code, act="dv_no_elim", tid=0
                                ).pack(),
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="↩️ ویرایش انتخاب‌ها",
                                callback_data=BazporsNarrCb(
                                    code=code, act="dv_pick_back", tid=0
                                ).pack(),
                            )
                        ],
                    ]
                ),
            )
        if n_def == 1:
            sole_pool = _day_vote_defender_pool(game)
            if len(sole_pool) == 1:
                sole = sole_pool[0]
                sole_tag = gm.format_player_tag(sole)[:48]
                return (
                    "🗳️ <b>نتیجهٔ رأی‌گیری پایان روز</b>\n\n"
                    f"{history}"
                    "فقط یک نفر در رأی‌گیری بود. نتیجه را مشخص کن:\n\n"
                    f"{win}",
                    InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=f"بازیکن {sole_tag} خارج شد",
                                    callback_data=BazporsNarrCb(
                                        code=code,
                                        act="dv_single_elim",
                                        tid=sole.user_id,
                                    ).pack(),
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    text="⭕ کسی خارج نشد",
                                    callback_data=BazporsNarrCb(
                                        code=code, act="dv_no_elim", tid=0
                                    ).pack(),
                                )
                            ],
                        ]
                    ),
                )
        return (
            "🗳️ <b>نتیجهٔ رأی‌گیری پایان روز</b>\n\n"
            f"{history}"
            "بازیکنی که با رأی امروز از بازی خارج می‌شود را انتخاب کن:\n\n"
            f"{win}",
            _day_vote_multi_defender_elim_keyboard(code, game, gm),
        )

    if step == PICK_DAY_ELIM_TIE_PART:
        tied_uids = _day_vote_tie_break_elim_uids(game)
        pool = [
            game.players[u]
            for u in tied_uids
            if u in game.players and game.players[u].is_alive
        ]
        if not pool:
            return (
                "خطا در لیست نامزدها. با دکمهٔ زیر برگرد.",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="↩️ برگشت",
                                callback_data=BazporsNarrCb(
                                    code=code, act="dv_elim_back", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )
        rows = _pick_rows(code, "pick_day", pool, gm, "🔴")
        rows.append(
            [
                InlineKeyboardButton(
                    text="↩️ برگشت",
                    callback_data=BazporsNarrCb(
                        code=code, act="dv_elim_back", tid=0
                    ).pack(),
                )
            ]
        )
        return (
            "⚖️ <b>رأی‌ها مساوی بود</b>، اما <b>سابقهٔ حضور در رأی</b> هم یکسان است.\n\n"
            f"{_day_vote_participation_history_html(game, gm)}"
            "کدام بازیکن باید خارج شود؟\n\n"
            f"{win}",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    if step == PICK_DAY_ELIM:
        pool = _day_vote_defender_pool(game)
        if not pool:
            return (
                "هیچ‌یک از بازیکنان انتخاب‌شده در رأی زنده نیستند. "
                "با دکمهٔ زیر به پرسش قبل برگرد.",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="↩️ برگشت",
                                callback_data=BazporsNarrCb(
                                    code=code, act="dv_elim_back", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )
        rows = _pick_rows(code, "pick_day", pool, gm, "🔴")
        rows.append(
            [
                InlineKeyboardButton(
                    text="↩️ برگشت",
                    callback_data=BazporsNarrCb(
                        code=code, act="dv_elim_back", tid=0
                    ).pack(),
                )
            ]
        )
        return (
            "🗳️ <b>بیشترین رأی — نتیجه خروج روز</b>\n\n"
            "🎯 از میان بازیکنان حاضر در رأی، مشخص کن کدام بازیکن با رأی امروز "
            "از بازی خارج شد.\n\n"
            f"{_day_vote_participation_history_html(game, gm)}"
            f"{win}",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    if step == CONFIRM_DAY_ELIM:
        uid = game.bazpors_narrator_pending_uid
        if uid is None or uid not in game.players:
            return "خطای داخلی.", None
        v = game.players[uid]
        n_hist = _day_vote_participation_count(game, uid)
        reason = game.bazpors_day_vote_elim_reason or ""
        tag = html.escape(gm.format_player_tag(v))
        hist_line = f"📌 سابقه حضور در رأی‌گیری: <b>{_seat_fa(n_hist)}</b>\n"
        role_line = f"نقش: <b>{html.escape(role_label_fa(v.role))}</b>\n"
        if reason == "tie_break":
            body = (
                "🗳️ <b>نتیجه رأی‌گیری روز</b>\n\n"
                "⚖️ <b>رأی‌ها مساوی بود.</b>\n"
                f"❌ <b>{tag}</b> با بیشترین سابقه حضور در رأی‌گیری از بازی خارج می‌شود.\n\n"
                f"{hist_line}"
                f"{role_line}"
            )
        elif reason == "tie_particip_pick":
            body = (
                "🗳️ <b>نتیجه رأی‌گیری روز</b>\n\n"
                "⚖️ <b>رأی‌ها مساوی بود</b> و سابقهٔ حضور هم برابر بود.\n"
                f"❌ <b>{tag}</b> برای خروج انتخاب شد.\n\n"
                f"{hist_line}"
                f"{role_line}"
            )
        else:
            body = (
                "🗳️ <b>نتیجه رأی‌گیری روز</b>\n\n"
                f"❌ <b>{tag}</b> با بیشترین رأی از بازی خارج شد.\n\n"
                f"{hist_line}"
            )
        return (
            body + win,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ تأیید",
                            callback_data=BazporsNarrCb(
                                code=code, act="confirm_day_yes"
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="↩️ برگشت",
                            callback_data=BazporsNarrCb(
                                code=code, act="confirm_day_no"
                            ).pack(),
                        ),
                    ],
                ]
            ),
        )

    if step == DAY_INTERROG_GATE:
        d = max(1, game.bazpors_narrator_host_day)
        if game.bazpors_interrog_once_done:
            return (
                f"☀️ <b>روز {_seat_fa(d)} — بازپرس</b>\n\n"
                "نیازی به بیدار کردن بازپرس نیست؛\n"
                "بازپرس قبلاً تصمیم خود را اعلام کرده و کار او انجام شده است.\n\n"
                f"{win}",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ تأیید",
                                callback_data=BazporsNarrCb(
                                    code=code, act="intr_day_gate_ok", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )
        u1, u2 = game.bazpors_interrog_first_uid, game.bazpors_interrog_second_uid
        n1 = (
            html.escape(gm.format_player_tag(game.players[u1]))
            if u1 in game.players
            else "؟"
        )
        n2 = (
            html.escape(gm.format_player_tag(game.players[u2]))
            if u2 in game.players
            else "؟"
        )
        return (
            f"☀️ <b>روز {_seat_fa(d)} — تصمیم بازپرسی</b> — "
            "<code>DAY_INTERROG_DECISION</code>\n\n"
            "طبق اجماع صندلی، یکی از دو حالت زیر را بزن.\n\n"
            f"<b>نامزدهای بازپرسی شب قبل:</b> {n1} و {n2}\n\n"
            "• اگر <b>بازپرسی منحل شد</b>: بحث عادی روز را ادامه بده؛ در پایان رأی روز، "
            "دکمهٔ <b>«رأی‌گیری انجام شد»</b> را بزن.\n\n"
            "• اگر <b>بازپرسی ادامه پیدا کند</b>: بعد از جلسهٔ بازپرسی و رأی روی همان دو نفر، "
            "بگو کدام‌یک با رأی از صندلی خارج شد — ربات فقط همان دو نفر را برای انتخاب نشان می‌دهد.\n"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="▶️ بازپرسی ادامه پیدا کند",
                            callback_data=BazporsNarrCb(
                                code=code, act="intr_continue", tid=0
                            ).pack(),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⭕ بازپرسی منحل شد",
                            callback_data=BazporsNarrCb(
                                code=code, act="intr_dissolve", tid=0
                            ).pack(),
                        )
                    ],
                ]
            ),
        )

    if step == PICK_INTERROG_VOTE_ELIM:
        pool = _interrog_day_vote_pool(game)
        if not pool:
            return (
                "هیچ‌کدام از نامزدهای بازپرسی زنده نیستند. "
                "اگر رأی بازپرسی کسی را حذف نکرده، با دکمه زیر به بحث روز برگرد.",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="☀️ ادامه — بحث روز",
                                callback_data=BazporsNarrCb(
                                    code=code, act="intr_pick_abort", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )
        rows = _pick_rows(code, "intr_day_pick", pool, gm, "🔴")
        rows.append(
            [
                InlineKeyboardButton(
                    text="⭕ کسی خارج نشد",
                    callback_data=BazporsNarrCb(
                        code=code, act="intr_vote_no_elim", tid=0
                    ).pack(),
                )
            ]
        )
        return (
            "رأی‌گیری را برگزار کن و پس از شمارش آرا، بازیکنی که با <b>بیشترین رأی</b> "
            "از بازی خارج شد را از لیست زیر انتخاب کن.\n\n"
            "اگر نتایج رأی‌گیری <b>مساوی</b> شد، گزینهٔ «<b>کسی خارج نشد</b>» را "
            "انتخاب کن.\n"
            f"{win}",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    if step == CONFIRM_INTERROG_VOTE_ELIM:
        uid = game.bazpors_narrator_pending_uid
        if uid is None or uid not in game.players:
            return "خطای داخلی.", None
        v = game.players[uid]
        if uid not in {
            game.bazpors_interrog_first_uid,
            game.bazpors_interrog_second_uid,
        }:
            return "خطای داخلی.", None
        return (
            f"تأیید خروج پس از بازپرسی؟\n<b>{html.escape(gm.format_player_tag(v))}</b>\n"
            f"نقش: <b>{html.escape(role_label_fa(v.role))}</b>"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ تأیید",
                            callback_data=BazporsNarrCb(
                                code=code, act="confirm_intr_vote_yes"
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="↩️ برگشت",
                            callback_data=BazporsNarrCb(
                                code=code, act="confirm_intr_vote_no"
                            ).pack(),
                        ),
                    ],
                ]
            ),
        )

    if step == NIGHT_START:
        from bot.room_mode import is_mason_scenario, mozakere_no_host_uses_parallel_night_ui

        n = game.bazpors_narrator_night_count
        if n == 1:
            night_title = "شب اول آغاز شد"
        elif n == 2:
            night_title = "شب دوم آغاز شد"
        elif n == 3:
            night_title = "شب سوم آغاز شد"
        else:
            night_title = f"شب {_seat_fa(n)} آغاز شد"
        if mozakere_no_host_uses_parallel_night_ui(game) or (
            no_host_assistant_narrator_active(game)
            and game.no_host_night_parallel_collect_active
        ):
            from bot.no_host_night_ready import pending_no_host_night_actor_labels

            pending = pending_no_host_night_actor_labels(game)
            if pending:
                wait_lines = "\n".join(f"• {html.escape(x)}" for x in pending)
                body = (
                    f"🌙 <b>{night_title}</b>\n\n"
                    "⏳ در انتظار ثبت انتخاب/تأیید همهٔ بازیکنان:\n"
                    f"{wait_lines}\n\n"
                    "پس از تکمیل همه، محاسبات شب به‌صورت خودکار آغاز می‌شود.\n"
                )
            else:
                body = (
                    f"🌙 <b>{night_title}</b>\n\n"
                    "✅ همه انتخاب‌ها ثبت شده؛ در حال ورود به محاسبات شب…\n"
                )
            return body + f"{win}", None
        if (
            no_host_assistant_narrator_active(game)
            and not mozakere_no_host_uses_parallel_night_ui(game)
            and not is_mason_scenario(game)
            and n == 1
            and (
                not game.no_host_night1_hunter_done
                or not game.no_host_mafia_night1_done
            )
        ):
            return (
                f"🌙 <b>{night_title}</b>\n\n"
                "🏹 در انتظار ثبت انتخاب‌های هانتر و تیم مافیا…\n\n"
                "پس از تأیید هر دو، اجرای نقش‌های شب ادامه می‌یابد.\n"
                f"{win}",
                None,
            )
        return (
            f"🌙 <b>{night_title}</b>\n\n"
            "😴 همه بازیکنان را بخوابان.\n\n"
            "➡️ سپس دکمه «<b>شروع اجرای نقش‌های شب</b>» را بزن تا ربات مرحله‌به‌مرحله "
            "انتخاب بازیکنان نقش‌دار را دریافت و ثبت کند.\n"
            f"{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🌟 شروع اجرای نقش‌های شب",
                            callback_data=BazporsNarrCb(
                                code=code, act="begin_night_actions"
                            ).pack(),
                        )
                    ]
                ]
            ),
        )

    if step != NIGHT_ACTIONS:
        pass
    else:
        from bot.room_mode import is_mason_scenario

        nc = game.bazpors_narrator_night_count

        if (
            no_host_assistant_narrator_active(game)
            and not is_mason_scenario(game)
            and nc == 1
            and (
                not game.no_host_night1_hunter_done
                or not game.no_host_mafia_night1_done
            )
        ):
            return (
                f"🌙 <b>شب {_seat_fa(nc)} — اجرای نقش‌ها</b>\n\n"
                "🏹 در انتظار ثبت انتخاب‌های هانتر و تیم مافیا…\n\n"
                "پس از تأیید هر دو، اجرای نقش‌های شب ادامه می‌یابد.\n"
                f"{win}",
                None,
            )

        if ns == NS_ROLE_ABSENT:
            role = _absent_night_role(game)
            if not role:
                return "خطا: نقش حذف‌شده مشخص نیست.", None
            return (
                _night_role_absent_host_text(nc, role),
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=f"➡️ {NIGHT_STEP_NEXT_BTN}",
                                callback_data=BazporsNarrCb(
                                    code=code, act="role_absent_ok", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )

        if ns == NS_HUNTER:
            h = _find_alive_role(game, Role.HUNTER)
            if not h:
                return "خطا: هانتر در بازی نیست.", None
            pool = [p for p in _alive(game) if p.user_id != h.user_id]
            rows = build_narrator_pick_rows(code, "hp", pool, gm, "🔗")
            rows = append_narrator_extra_rows(
                rows, build_narrator_action_row(code, "hs", "⭕ هانتر وصل نشد")
            )
            return (
                f"{_night_step_header(nc, 'هانتر')}\n\n"
                "🎯 هانتر را بیدار کن و از لیست زیر، نام بازیکنی را که انتخاب کرده "
                "مشخص کن.\n\n",
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(code, game, rows)
                ),
            )

        if ns == NS_MAFIA_MENU:
            rows_m: list[list[InlineKeyboardButton]] = []
            if mafia_shot_allowed(game):
                rows_m.append(
                    [
                        InlineKeyboardButton(
                            text="🎯 ثبت شات شب",
                            callback_data=BazporsNarrCb(
                                code=code, act="mshot", tid=0
                            ).pack(),
                        )
                    ]
                )
            if nato_can_register(game) and not game.bazpors_nato_action_registered:
                rows_m.append(
                    [
                        InlineKeyboardButton(
                            text="🎲 ثبت ناتویی",
                            callback_data=BazporsNarrCb(
                                code=code, act="mnato", tid=0
                            ).pack(),
                        )
                    ]
                )
            if yakuzai_allowed(game, gm):
                rows_m.append(
                    [
                        InlineKeyboardButton(
                            text="🤝 ثبت یاکوزایی / سوداگری",
                            callback_data=BazporsNarrCb(
                                code=code, act="myaku", tid=0
                            ).pack(),
                        )
                    ]
                )
            rows_m.append(
                [
                    InlineKeyboardButton(
                        text="✅ پایان مرحلهٔ مافیا",
                        callback_data=BazporsNarrCb(
                            code=code, act="mafia_done", tid=0
                        ).pack(),
                    )
                ]
            )
            return (
                f"{_night_step_header(nc, 'تیم مافیا')}\n\n"
                "🎯 تیم مافیا را بیدار کن. از رئیس مافیا بپرس چه تصمیمی دارد و "
                "از منوی زیر انتخاب کن.\n\n",
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(code, game, rows_m)
                ),
            )

        if ns == NS_MAFIA_SHOT:
            if (
                no_host_assistant_narrator_active(game)
                and nc == 1
                and not game.no_host_mafia_shot_done
            ):
                return (
                    f"{_night_mafia_shot_header(nc)}\n\n"
                    "🔫 در انتظار ثبت هدف شات توسط تیم مافیا…\n\n"
                    "پس از تأیید انتخاب، اجرای نقش‌های شب ادامه می‌یابد.\n"
                    f"{win}",
                    None,
                )
            shot_pool = sorted(
                _alive(game),
                key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
            )
            mkt_rows = build_narrator_pick_rows(code, "mkt", shot_pool, gm, "🔴")
            return (
                f"{_night_mafia_shot_header(nc)}\n\n"
                "🎯 لیست زیر شامل تمام بازیکنانی است که در حال حاضر در بازی "
                "حضور دارند.\n\n"
                "🔴 نام بازیکنی را که تیم مافیا به او شلیک کرده از لیست انتخاب کن.\n\n",
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(code, game, mkt_rows)
                ),
            )

        if ns == NS_NATO_ROLE:
            if (
                no_host_assistant_narrator_active(game)
                and nc == 1
                and not game.no_host_mafia_nato_done
            ):
                return (
                    f"🌙 <b>شب {_seat_fa(nc)} — ناتویی</b>\n\n"
                    "🎭 در انتظار ثبت ناتویی توسط بازیکن ناتو…\n\n"
                    f"{win}",
                    None,
                )
            return (
                f"🌙 <b>شب {_seat_fa(nc)} — ناتو: ثبت نقش حدس‌زده</b>\n\n"
                "🎯 ناتو را بیدار کن و فقط <b>نقشی را که حدس زده</b> انتخاب کن.\n\n"
                "➡️ در مرحله بعد، بازیکنی که ناتو انتخاب کرده مشخص می‌شود.\n"
                "📌 در این مرحله فقط نقش حدس‌زده را ثبت کن.\n",
                InlineKeyboardMarkup(inline_keyboard=_nato_role_buttons(code)),
            )

        if ns == NS_NATO_CONFIRM:
            role_val = game.bazpors_nato_guess_role
            if not role_val:
                return "خطا.", None
            try:
                gr = Role(role_val)
            except ValueError:
                return "خطا.", None
            role_txt = html.escape(role_label_fa(gr))
            pool = [p for p in _alive(game) if not _visually_mafia(game, p)]
            if not pool:
                return (
                    "هیچ بازیکن غیرمافیای زنده‌ای برای انتخاب نیست.",
                    InlineKeyboardMarkup(
                        inline_keyboard=[_nato_back_button_row(code)]
                    ),
                )
            rows = _pick_rows(code, "npick", pool, gm, "👤")
            rows.append(_nato_back_button_row(code))
            return (
                f"🎯 <b>نقش انتخاب‌شده برای ناتویی: {role_txt}</b>\n\n"
                "به نظر ناتو <b>کدام بازیکن</b> نقش گفته‌شده در بالا را دارد؟\n",
                InlineKeyboardMarkup(inline_keyboard=rows),
            )

        if ns == NS_NATO_MULTI_ASK:
            role_val = game.bazpors_nato_guess_role or ""
            try:
                gr = Role(role_val)
            except ValueError:
                return "خطا.", None
            cands = [p for p in _alive(game) if p.role == gr]
            lines = [f"نقش: <b>{html.escape(role_label_fa(gr))}</b>", "بازیکنان این نقش:"]
            for p in cands:
                lines.append(f"• {html.escape(gm.format_player_tag(p))}")
            lines.append("\nآیا ناتو یکی از این‌ها را درست حدس زده؟")
            return (
                "\n".join(lines) + "\n",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ بله",
                                callback_data=BazporsNarrCb(
                                    code=code, act="nm_yes", tid=0
                                ).pack(),
                            ),
                            InlineKeyboardButton(
                                text="⭕ خیر",
                                callback_data=BazporsNarrCb(
                                    code=code, act="nm_no", tid=0
                                ).pack(),
                            ),
                        ],
                        _nato_back_button_row(code),
                    ]
                ),
            )

        if ns == NS_NATO_MULTI_PICK:
            raw = game.bazpors_nato_multi_uids or ""
            uids = [int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]
            pool = [game.players[u] for u in uids if u in game.players and game.players[u].is_alive]
            rows = _pick_rows(code, "nm_pick", pool, gm, "☠️")
            rows.append(_nato_back_button_row(code))
            return (
                "کدام بازیکن با ناتویی <b>خارج می‌شود</b>؟\n\n",
                InlineKeyboardMarkup(inline_keyboard=rows),
            )

        if ns == NS_YAKU_SAC:
            if (
                no_host_assistant_narrator_active(game)
                and nc == 1
                and not yaku_night_state(game).no_host_done
            ):
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — یاکوزایی\n\n"
                    "🩸 در انتظار ثبت فدا و هدف یاکوزایی توسط تیم مافیا…\n\n"
                    f"{win}",
                    None,
                )
            sac_pool = _yaku_sacrifice_pool(game)
            rows = _pick_rows(code, "ys", sac_pool, gm, "☠️")
            rows.append(_yaku_back_button_row(code))
            return (
                f"🌙 <b>شب {_seat_fa(nc)}</b> — یاکوزایی — انتخاب عضو یاکوزایی شده\n\n"
                "🎯 ابتدا مشخص کن کدام عضو مافیا برای فدا شدن انتخاب می‌شود.\n",
                InlineKeyboardMarkup(inline_keyboard=rows),
            )

        if ns == NS_YAKU_CIV:
            if (
                no_host_assistant_narrator_active(game)
                and nc == 1
                and not yaku_night_state(game).no_host_done
            ):
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — یاکوزایی\n\n"
                    "🩸 در انتظار ثبت هدف یاکوزایی توسط تیم مافیا…\n\n"
                    f"{win}",
                    None,
                )
            yaku_pool = _yaku_civilian_pool(game)
            ruintan_note = ""
            if _bazpors_player_count(game) == 13 and _find_alive_role(game, Role.RUINTAN):
                ruintan_note = (
                    "\n\n⚠️ در بازی <b>۱۳ نفره</b>، انتخاب <b>رویین‌تن</b> "
                    "منجر به یاکوزای <b>ناموفق</b> می‌شود (فدا خارج می‌شود؛ هدف مافیا نمی‌شود)."
                )
            rows = _pick_rows(code, "yc", yaku_pool, gm, "💬")
            rows.append(_yaku_back_button_row(code))
            return (
                f"🌙 <b>شب {_seat_fa(nc)}</b> — یاکوزایی — هدف مذاکره\n\n"
                "🎯 مافیا باید مشخص کند چه کسی برای یاکوزایی انتخاب شده است.\n\n"
                "📋 لیست زیر شامل بازیکنان فعلی صندلی (به‌جز اعضای مافیا) است.\n\n"
                "➡️ پس از انتخاب، ربات به شما اعلام می‌کند که یاکوزا می‌نشیند یا نه.\n"
                f"{ruintan_note}",
                InlineKeyboardMarkup(inline_keyboard=rows),
            )

        if ns == NS_YAKU_SUCCESS_ACK:
            body, kb = _yaku_success_host_panel(game, gm)
            return body, kb

        if ns == NS_YAKU_FAIL_ACK:
            body, kb = _yaku_fail_host_panel(game, gm)
            return body, kb

        if ns == NS_SHIAD:
            if (
                no_host_assistant_narrator_active(game)
                and _find_alive_role(game, Role.SHIAD)
            ):
                sh = _find_alive_role(game, Role.SHIAD)
                sh_tag = html.escape(
                    gm.format_player_tag(sh) if sh else "شیاد"
                )
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — شیاد\n\n"
                    f"🎭 در انتظار ثبت انتخاب توسط <b>{sh_tag}</b>…\n\n"
                    f"{win}",
                    None,
                )
            sh = _find_alive_role(game, Role.SHIAD)
            pool = _shiad_role.guess_pool(game)
            if not pool:
                return (
                    f"{_night_step_header(nc, 'شیاد')}\n\n"
                    "هیچ بازیکن <b>غیرمافیا</b> زنده‌ای برای حدس شیاد باقی نمانده؛ "
                    "این مرحله را رد کن.\n",
                    InlineKeyboardMarkup(
                        inline_keyboard=[
                            build_narrator_action_row(
                                code, "shiad_skip", "⏭ رد کردن شیاد / ادامه"
                            )
                        ]
                    ),
                )
            return (
                f"{_night_step_header(nc, 'شیاد')}\n\n"
                "🎭 شیاد را بیدار کن و از لیست زیر، بازیکنی را که برای حدس نقش کارآگاه "
                "انتخاب کرده مشخص کن.\n\n"
                "📜 <b>قوانین:</b>\n"
                "🎯 اگر شیاد نقش کارآگاه را درست حدس بزند، استعلام کارآگاه در این شب "
                "بدون توجه به انتخاب خودش <b>منفی</b> خواهد شد.\n"
                "👑 استعلام <b>رییس مافیا</b> برای کارآگاه همیشه <b>منفی</b> است.\n\n",
                InlineKeyboardMarkup(
                    inline_keyboard=build_narrator_pick_rows(code, "sg", pool, gm, "🎭")
                ),
            )

        if ns == NS_SHIAD_ACK:
            det = _find_alive_role(game, Role.DETECTIVE)
            if not det:
                return "خطا: کارآگاه در بازی نیست.", None
            pool = [p for p in _alive(game) if p.user_id != det.user_id]
            if game.bazpors_narrator_pending_uid is not None:
                tid = game.bazpors_narrator_pending_uid
                if tid in game.players and game.players[tid].is_alive:
                    tag = html.escape(gm.format_player_tag(game.players[tid]))
                    return (
                        f"{_night_step_header(nc, 'کارآگاه')}\n\n"
                        f"بازیکن انتخاب‌شده: <b>{tag}</b>\n\n"
                        "فارغ از انتخاب، استعلام کارآگاه در این شب "
                        "<b>منفی</b> است. تأیید کنید.\n",
                        InlineKeyboardMarkup(
                            inline_keyboard=build_narrator_confirm_back_rows(
                                code,
                                confirm_act="sdp_ok",
                                confirm_text="✅ تأیید",
                                back_act="sdp_back",
                                back_text="↩️ بازگشت",
                            )
                        ),
                    )
            rows = _pick_rows(code, "sdp", pool, gm, "🔍")
            return (
                f"{_night_step_header(nc, 'کارآگاه')}\n\n"
                "از لیست زیر یک بازیکن را انتخاب کن "
                "(نام کارآگاه در لیست نیست).\n\n"
                "فارغ از انتخاب، نتیجهٔ استعلام این شب "
                "<b>منفی</b> خواهد بود.\n",
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(code, game, rows)
                ),
            )

        if ns == NS_DET:
            if (
                no_host_assistant_narrator_active(game)
                and _find_alive_role(game, Role.DETECTIVE)
                and not game.bazpors_detective_blocked
            ):
                det = _find_alive_role(game, Role.DETECTIVE)
                det_tag = html.escape(
                    gm.format_player_tag(det) if det else "کارآگاه"
                )
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — کارآگاه\n\n"
                    f"🕵️ در انتظار ثبت استعلام توسط <b>{det_tag}</b>…\n\n"
                    f"{win}",
                    None,
                )
            return (
                _detective_night_host_text(nc),
                build_narrator_pick_keyboard(
                    code,
                    "dp",
                    _alive(game),
                    gm,
                    "🔍",
                    build_narrator_action_row(code, "dx", "⭕ استعلام نگرفت"),
                ),
            )

        if ns == NS_DET_ACK:
            if no_host_assistant_narrator_active(game):
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — کارآگاه\n\n"
                    "🕵️ استعلام توسط کارآگاه ثبت شد.\n\n"
                    f"{win}",
                    None,
                )
            pos = load_detective_inquiry_result(game)
            hint = (
                "به کارآگاه <b>استعلام مثبت</b> نشان بده."
                if pos is not None and pos.is_positive
                else "به کارآگاه <b>استعلام منفی</b> نشان بده."
            )
            return (
                f"🌙 شب {_seat_fa(nc)} — <b>کارآگاه — تأیید نتیجه</b>\n\n"
                f"{hint}\n",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ اوکی",
                                callback_data=BazporsNarrCb(
                                    code=code, act="det_ack", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )

        if ns == NS_DOC_NATO_SKIP:
            return (
                _doctor_night_nato_skip_host_text(nc),
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ تأیید",
                                callback_data=BazporsNarrCb(
                                    code=code, act="doc_nato_skip_ok", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )

        if ns == NS_DOC_YAKU_SKIP:
            return (
                _doctor_night_yaku_skip_host_text(nc),
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ تأیید",
                                callback_data=BazporsNarrCb(
                                    code=code, act="doc_yaku_skip_ok", tid=0
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )

        if ns == NS_DOC:
            if (
                no_host_assistant_narrator_active(game)
                and _find_alive_role(game, Role.DOCTOR)
                and not game.bazpors_nato_action_registered
            ):
                doc = _find_alive_role(game, Role.DOCTOR)
                doc_tag = html.escape(
                    gm.format_player_tag(doc) if doc else "پزشک"
                )
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — پزشک\n\n"
                    f"💉 در انتظار ثبت نجات توسط <b>{doc_tag}</b>…\n\n"
                    f"{win}",
                    None,
                )
            return (
                _doctor_night_host_text(game, nc),
                build_narrator_pick_keyboard(
                    code,
                    "dr",
                    _doctor_save_pool(game),
                    gm,
                    "💉",
                    build_narrator_action_row(code, "dxd", "⭕ نجات نداد"),
                ),
            )

        if ns == NS_INTERROG_SKIP:
            if no_host_assistant_narrator_active(game):
                intr = _find_alive_role(game, Role.INTERROGATOR)
                intr_tag = html.escape(
                    gm.format_player_tag(intr) if intr else "بازپرس"
                )
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — بازپرس\n\n"
                    f"⚖️ در انتظار تأیید <b>{intr_tag}</b> (بازپرسی قبلاً انجام شده)…\n\n"
                    f"{win}",
                    None,
                )
            return (
                f"{_night_step_header(nc, 'بازپرس')}\n\n"
                "نیازی به بیدار کردن بازپرس نیست؛\n"
                "بازپرس قبلاً تصمیم خود را اعلام کرده و کار او انجام شده است.\n\n"
                f"{win}",
                build_narrator_action_keyboard(code, "int_skip_ok", "✅ تأیید"),
            )

        if ns == NS_INT1:
            if no_host_assistant_narrator_active(game):
                intr = _find_alive_role(game, Role.INTERROGATOR)
                intr_tag = html.escape(
                    gm.format_player_tag(intr) if intr else "بازپرس"
                )
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — بازپرس\n\n"
                    f"⚖️ در انتظار ثبت بازپرسی توسط <b>{intr_tag}</b>…\n\n"
                    f"{win}",
                    None,
                )
            rows_i1 = build_narrator_pick_rows(code, "i1", _alive(game), gm, "🪪")
            rows_i1 = append_narrator_extra_rows(
                rows_i1,
                build_narrator_action_row(code, "i1_skip", "⭕ کسی رو انتخاب نکرد"),
            )
            return (
                f"{_night_step_header(nc, 'بازپرس')}\n\n"
                "⚖️ بازپرس را بیدار کن و نفر اول بازپرسی را از لیست زیر انتخاب کن.\n\n"
                "➡️ پس از انتخاب نفر اول، مرحله انتخاب نفر دوم باز می‌شود.\n"
                "🚫 اگر این شب بازپرسی انجام نمی‌شود، گزینه «کسی رو انتخاب نکرد» را بزن.\n\n"
                "📜 قوانین:\n"
                "🎯 بازپرس فقط یک‌بار در کل بازی می‌تواند از قابلیت خود استفاده کند.\n"
                "🛡️ اگر بازپرس پس از انتخاب از بازی خارج شود، بازپرسی همچنان "
                "برگزار خواهد شد.\n"
                "❌ اما اگر یکی یا هر دو بازیکن انتخاب‌شده برای بازپرسی تا پایان شب "
                "از بازی خارج شوند، بازپرسی برگزار نمی‌شود.\n"
                "🌙 در این صورت، اگر بازپرس هنوز در بازی باشد، می‌تواند در شب دوم "
                "بازیکنان جدیدی را انتخاب کند.\n\n",
                InlineKeyboardMarkup(inline_keyboard=rows_i1),
            )

        if ns == NS_INT2:
            if no_host_assistant_narrator_active(game):
                intr = _find_alive_role(game, Role.INTERROGATOR)
                intr_tag = html.escape(
                    gm.format_player_tag(intr) if intr else "بازپرس"
                )
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — بازپرس (نفر دوم)\n\n"
                    f"⚖️ در انتظار ثبت نفر دوم توسط <b>{intr_tag}</b>…\n\n"
                    f"{win}",
                    None,
                )
            fu = game.bazpors_interrog_pick_uid
            pool = [p for p in _alive(game) if p.user_id != fu]
            rows_i2 = build_narrator_pick_rows(code, "i2", pool, gm, "🪪")
            rows_i2 = append_narrator_extra_rows(
                rows_i2,
                build_narrator_action_row(
                    code, "i2_abort", "⭕ بازپرس از بازپرسی منصرف شد"
                ),
                build_narrator_action_row(
                    code, "i2_redo1", "↩️ انتخاب مجدد نفر اول بازپرسی"
                ),
            )
            return (
                f"{_night_step_header(nc, 'بازپرس — نفر دوم')}\n\n"
                "🎯 نفر دوم بازپرسی را از لیست زیر انتخاب کن.\n\n",
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(code, game, rows_i2)
                ),
            )

        if ns == NS_SNIPER:
            if (
                no_host_assistant_narrator_active(game)
                and _find_alive_role(game, Role.SNIPER)
                and _sniper_can_shoot(game)
            ):
                sn = _find_alive_role(game, Role.SNIPER)
                sn_tag = html.escape(
                    gm.format_player_tag(sn) if sn else "اسنایپر"
                )
                return (
                    f"🌙 <b>شب {_seat_fa(nc)}</b> — اسنایپر\n\n"
                    f"🎯 در انتظار ثبت شلیک توسط <b>{sn_tag}</b>…\n\n"
                    f"{win}",
                    None,
                )
            can_shoot = _sniper_can_shoot(game)
            if can_shoot:
                pool = _sniper_role.shot_pool(game)
                sn_rows = build_narrator_pick_rows(code, "sn_pick", pool, gm, "🎯")
                sn_rows = append_narrator_extra_rows(
                    sn_rows,
                    build_narrator_action_row(
                        code, "sn_skip", "⭕ تک‌تیرانداز شلیک نکرد"
                    ),
                )
            else:
                sn_rows = [
                    build_narrator_action_row(
                        code, "sn_skip", "➡️ ادامه — تیر قبلاً استفاده شده"
                    )
                ]
            return (
                _sniper_night_host_text(nc, can_shoot=can_shoot),
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(code, game, sn_rows)
                ),
            )

        if ns == NS_DISCIPLINE_ASK:
            disc_rows = [
                [
                    InlineKeyboardButton(
                        text="✅ بله — اخراج انضباطی",
                        callback_data=BazporsNarrCb(
                            code=code, act="disc_yes", tid=0
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⭕ خیر",
                        callback_data=BazporsNarrCb(
                            code=code, act="disc_no", tid=0
                        ).pack(),
                    )
                ],
            ]
            return (
                f"🌙 شب {_seat_fa(nc)} — <b>اخراج انضباطی</b>\n\n"
                "نقش‌های شب تمام شد.\n"
                "آیا در این شب می‌خواهی <b>اخراج انضباطی</b> انجام بدهی؟\n",
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(code, game, disc_rows)
                ),
            )

        if ns == NS_RESOLVE:
            if no_host_assistant_narrator_active(game):
                return (
                    f"🌙 {_night_title_fa(nc)} — جمع‌بندی شب\n\n"
                    "⏳ در حال اعمال محاسبات شب و اعلان نتایج به بازیکنان…\n"
                    f"{win}",
                    None,
                )
            return (
                f"🌙 {_night_title_fa(nc)} — جمع‌بندی شب\n\n"
                "⚙️ ربات آماده بررسی و اعمال اتفاقات این شب است.\n\n"
                f"➡️ برای ادامه، دکمه «{NIGHT_RESOLVE_BUTTON_LABEL}» را بزن.\n"
                + win,
                InlineKeyboardMarkup(
                    inline_keyboard=_append_night_back_row(
                        code,
                        game,
                        [
                            [
                                InlineKeyboardButton(
                                    text=NIGHT_RESOLVE_BUTTON_LABEL,
                                    callback_data=BazporsNarrCb(
                                        code=code, act="apply_resolve", tid=0
                                    ).pack(),
                                )
                            ]
                        ],
                    )
                ),
            )

    if step == ASK_NIGHT_EXTRA:
        _sync_ki_as_today(game, gm)
        _refresh_interrog_ready_for_day(game)
        next_day = max(1, game.bazpors_narrator_host_day + 1)
        roster = _players_roster_html(game, gm)
        intr_ready = game.bazpors_interrog_ready_for_day
        intr_cancel = game.bazpors_interrog_cancel_next_day
        if intr_ready and _interrog_ready_split_night_end_panel(game, gm):
            body = _build_interrog_day_host_panel_html(game, gm, win)
            return (body, _interrog_ready_night_end_keyboard(code))
        host_tail = _night_end_host_guidance_html(game)
        extra_note = ""
        if not intr_ready and not (
            intr_cancel and game.bazpors_interrog_night_finished
        ):
            pass  # guidance already includes extra-night hint
        if _ki_as_split_night_end_panel(game, gm):
            body = _ki_as_host_block_html() + win
            kb_rows = [
                [
                    InlineKeyboardButton(
                        text="فاز آشوب شروع شد",
                        callback_data=BazporsNarrCb(
                            code=code, act="nx_no", tid=0
                        ).pack(),
                    )
                ],
            ]
            return (body, InlineKeyboardMarkup(inline_keyboard=kb_rows))

        body = (
            f"{roster}\n\n"
            + host_tail
            + extra_note
            + win
        )
        if intr_ready:
            kb_rows = [
                [
                    InlineKeyboardButton(
                        text="▶️ بازپرسی ادامه پیدا کند",
                        callback_data=BazporsNarrCb(
                            code=code, act="intr_continue", tid=0
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⭕ بازپرسی منحل شد",
                        callback_data=BazporsNarrCb(
                            code=code, act="intr_dissolve", tid=0
                        ).pack(),
                    )
                ],
            ]
        else:
            kb_rows = [
                [
                    InlineKeyboardButton(
                        text=f"☀️ ادامه — شروع روز {_seat_fa(next_day)}",
                        callback_data=BazporsNarrCb(
                            code=code, act="nx_no", tid=0
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="➕ ثبت خروج شبانهٔ اضافی (حالت خاص)",
                        callback_data=BazporsNarrCb(
                            code=code, act="nx_yes", tid=0
                        ).pack(),
                    )
                ],
            ]
        return (body, InlineKeyboardMarkup(inline_keyboard=kb_rows))

    if step == PICK_NIGHT_EXTRA:
        rows = _pick_rows(code, "nx_pick", _alive(game), gm, "⚫")
        return ("کدام بازیکن خارج شده؟\n" + win, InlineKeyboardMarkup(inline_keyboard=rows))

    if step == CONFIRM_NIGHT_EXTRA:
        uid = game.bazpors_narrator_pending_uid
        if uid is None or uid not in game.players:
            return "خطا.", None
        v = game.players[uid]
        return (
            f"تأیید خروج شبانه؟\n<b>{html.escape(gm.format_player_tag(v))}</b>{win}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ تأیید",
                            callback_data=BazporsNarrCb(
                                code=code, act="nx_ok", tid=0
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="↩️ برگشت",
                            callback_data=BazporsNarrCb(
                                code=code, act="nx_back", tid=0
                            ).pack(),
                        ),
                    ]
                ]
            ),
        )

    return "وضعیت نامشخص.", None


def process_narrator_callback(
    game: Game, gm: GameManager, act: str, tid: int, rid: str = ""
) -> str | None:
    if not narrator_panel_receives_updates(game) or not game.bazpors_narrator_step:
        return "این پنل برای این اتاق فعال نیست."
    step = game.bazpors_narrator_step
    ns = game.bazpors_night_substep

    from bot.no_host_interrog_day import (
        NO_HOST_INTERROG_DAY,
        process_no_host_interrog_day_narrator_cb,
    )
    from bot.no_host_handoff import (
        NO_HOST_HANDOFF_OFFER,
        process_handoff_narrator_cb,
    )
    from bot.no_host_table_inquiry import (
        NO_HOST_TABLE_INQUIRY,
        process_no_host_table_inquiry_narrator_cb,
    )

    if step == NO_HOST_HANDOFF_OFFER:
        return process_handoff_narrator_cb(game, gm, act, tid)

    if step == NO_HOST_INTERROG_DAY:
        return process_no_host_interrog_day_narrator_cb(game, gm, act, tid)

    if step == NO_HOST_TABLE_INQUIRY:
        return process_no_host_table_inquiry_narrator_cb(game, gm, act, tid)

    def go_day_after_night_extra() -> None:
        game.bazpors_narrator_host_day += 1
        _mark_day_start_alive_snapshot(game)
        game.bazpors_narrator_step = DAY_DISCUSS
        _sync_ki_as_today(game, gm)

    if act == "start_intro_day":
        if step != ROLE_ASSIGNED:
            return "دکمه نامعتبر."
        game.bazpors_narrator_step = INTRO_DAY
        return None
    if act == "start_intro_night":
        if step != INTRO_DAY:
            return "ابتدا روز معارفه را شروع کنید."
        game.bazpors_narrator_step = INTRO_NIGHT
        return None
    if act == "announce_day1":
        if step != INTRO_NIGHT:
            return "ابتدا شب معارفه را شروع کنید."
        game.bazpors_narrator_host_day = 1
        _mark_day_start_alive_snapshot(game)
        game.bazpors_narrator_step = DAY_DISCUSS
        return None
    if act == "intr_day_gate_ok":
        if step != DAY_INTERROG_GATE:
            return "نامعتبر."
        game.bazpors_narrator_step = DAY_DISCUSS
        return None
    if act == "intr_dissolve":
        if step == ASK_NIGHT_EXTRA:
            _refresh_interrog_ready_for_day(game)
            if game.bazpors_interrog_cancel_next_day:
                return (
                    "بازپرسی امروز نیست — یکی از نامزدهای بازپرسی در شب از بازی خارج شده. "
                    "دکمهٔ «ادامه — شروع روز» را بزن."
                )
            if not game.bazpors_interrog_ready_for_day:
                return "نامعتبر."
            _mark_interrog_session_done(game)
            game.bazpors_interrog_cancel_next_day = False
            game.bazpors_interrog_ready_for_day = False
            game.bazpors_narrator_host_day += 1
            _mark_day_start_alive_snapshot(game)
            _clear_interrog_day_targets(game)
            game.bazpors_narrator_step = DAY_DISCUSS
            return None
        if step != DAY_INTERROG_GATE:
            return "نامعتبر."
        _mark_interrog_session_done(game)
        _clear_interrog_day_targets(game)
        game.bazpors_narrator_step = DAY_DISCUSS
        return None
    if act == "intr_continue":
        if step == ASK_NIGHT_EXTRA:
            _refresh_interrog_ready_for_day(game)
            if game.bazpors_interrog_cancel_next_day:
                return (
                    "بازپرسی امروز نیست — یکی از نامزدهای بازپرسی در شب از بازی خارج شده. "
                    "دکمهٔ «ادامه — شروع روز» را بزن."
                )
            if not game.bazpors_interrog_ready_for_day:
                return "نامعتبر."
            _mark_interrog_session_done(game)
            game.bazpors_interrog_cancel_next_day = False
            game.bazpors_interrog_ready_for_day = False
            game.bazpors_narrator_host_day += 1
            _mark_day_start_alive_snapshot(game)
            pool = _interrog_day_vote_pool(game)
            if not pool:
                return "هیچ‌کدام از نامزدهای بازپرسی زنده نیستند."
            game.bazpors_narrator_step = PICK_INTERROG_VOTE_ELIM
            return None
        if step != DAY_INTERROG_GATE:
            return "نامعتبر."
        _mark_interrog_session_done(game)
        pool = _interrog_day_vote_pool(game)
        if not pool:
            return "هیچ‌کدام از نامزدهای بازپرسی زنده نیستند."
        game.bazpors_narrator_step = PICK_INTERROG_VOTE_ELIM
        return None
    if act == "intr_day_pick":
        if step != PICK_INTERROG_VOTE_ELIM:
            return "نامعتبر."
        allowed = {p.user_id for p in _interrog_day_vote_pool(game)}
        if tid not in allowed or tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = tid
        game.bazpors_narrator_step = CONFIRM_INTERROG_VOTE_ELIM
        return None
    if act == "confirm_intr_vote_no":
        if step != CONFIRM_INTERROG_VOTE_ELIM:
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = None
        game.bazpors_narrator_step = PICK_INTERROG_VOTE_ELIM
        return None
    if act == "confirm_intr_vote_yes":
        if step != CONFIRM_INTERROG_VOTE_ELIM:
            return "نامعتبر."
        uid = game.bazpors_narrator_pending_uid
        if uid is None or uid not in game.players:
            return "خطا."
        if uid not in {
            game.bazpors_interrog_first_uid,
            game.bazpors_interrog_second_uid,
        }:
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = None
        _mark_interrog_session_done(game)
        _clear_interrog_day_targets(game)
        if _eliminate_and_maybe_win_gate(game, gm, uid, elim_source="interrog_vote"):
            return None
        game.bazpors_narrator_step = DAY_DISCUSS
        return None
    if act == "intr_vote_no_elim":
        if step != PICK_INTERROG_VOTE_ELIM:
            return "نامعتبر."
        _clear_interrog_day_targets(game)
        game.bazpors_narrator_step = DAY_DISCUSS
        return None
    if act == "intr_pick_abort":
        if step != PICK_INTERROG_VOTE_ELIM:
            return "نامعتبر."
        _clear_interrog_day_targets(game)
        game.bazpors_narrator_step = DAY_DISCUSS
        return None
    if act == "vote_done":
        if step != DAY_DISCUSS:
            return "الان فاز روز نیست."
        if no_host_assistant_narrator_active(game):
            return (
                "در مسیر بدون گرداننده از دو دکمهٔ پایین استفاده کنید:\n"
                "«کسی برای دفاعیه انتخاب نشد → شب» یا "
                "«رأی‌گیری لازم است → پنل دفاعیه»."
            )
        if ki_as_hand_resolve_day_active(game, gm):
            if semi_auto_chaos_host_picks_winner(game):
                return (
                    f"امروز {CHAOS_PHASE_LABEL} است (۳ نفر زنده). رأی‌گیری معمول این روز انجام نمی‌شود؛ "
                    "نتیجهٔ بازی را با یکی از دو دکمهٔ پایین ثبت کن."
                )
            return (
                f"امروز {CHAOS_PHASE_LABEL} است (۳ نفر زنده). رأی‌گیری معمول این روز انجام نمی‌شود؛ "
                "نتیجهٔ دست را با یکی از دو دکمهٔ پایین ثبت کن."
            )
        _set_day_vote_pick_uids(game, set())
        game.bazpors_day_vote_defender_uids = None
        game.bazpors_narrator_step = DAY_VOTE_PICK_DEFENDERS
        return None
    if act == "dv_toggle":
        if step != DAY_VOTE_PICK_DEFENDERS:
            return "نامعتبر."
        if tid not in game.players or not game.players[tid].is_alive:
            return "بازیکن زنده نیست."
        picked = _day_vote_pick_uids(game)
        if tid in picked:
            picked.discard(tid)
        else:
            picked.add(tid)
        _set_day_vote_pick_uids(game, picked)
        return None
    if act == "dv_none_defended":
        if step != DAY_VOTE_PICK_DEFENDERS:
            return "نامعتبر."
        _set_day_vote_pick_uids(game, set())
        game.bazpors_day_vote_defender_uids = None
        game.bazpors_narrator_step = DAY_VOTE_ELIM_ASK
        return None
    if act == "dv_confirm":
        if step != DAY_VOTE_PICK_DEFENDERS:
            return "نامعتبر."
        picked = _day_vote_pick_uids(game)
        if not picked:
            return (
                "حداقل یک بازیکن را انتخاب کنید، "
                "یا «هیچکسی وارد دفاعیه نشد» را بزنید."
            )
        alive_picked = {
            u for u in picked if u in game.players and game.players[u].is_alive
        }
        if not alive_picked:
            return "هیچ بازیکن زنده‌ای انتخاب نشده."
        game.bazpors_day_vote_defender_uids = _uid_csv(alive_picked)
        _set_day_vote_pick_uids(game, set())
        game.bazpors_narrator_step = DAY_VOTE_ELIM_ASK
        return None
    if act == "dv_pick_back":
        if step != DAY_VOTE_ELIM_ASK:
            return "نامعتبر."
        defenders = _day_vote_defender_uids(game)
        _set_day_vote_pick_uids(game, set(defenders))
        game.bazpors_day_vote_defender_uids = None
        game.bazpors_narrator_step = DAY_VOTE_PICK_DEFENDERS
        return None
    if act in ("dv_no_elim", "elim_no"):
        if step != DAY_VOTE_ELIM_ASK:
            return "نامعتبر."
        _enter_night_from_day_end(game)
        return None
    if act == "dv_single_elim":
        if step != DAY_VOTE_ELIM_ASK:
            return "نامعتبر."
        pool = _day_vote_defender_pool(game)
        if len(pool) != 1:
            return "نامعتبر."
        if tid != pool[0].user_id:
            return "نامعتبر."
        if tid not in game.players or not game.players[tid].is_alive:
            return "بازیکن زنده نیست."
        game.bazpors_narrator_pending_uid = tid
        game.bazpors_day_vote_elim_reason = "majority"
        game.bazpors_narrator_step = CONFIRM_DAY_ELIM
        return None
    if act == "dv_defender_out":
        if step != DAY_VOTE_ELIM_ASK:
            return "نامعتبر."
        pool_ids = {p.user_id for p in _day_vote_defender_pool(game)}
        if tid not in pool_ids:
            return "نامعتبر."
        if tid not in game.players or not game.players[tid].is_alive:
            return "بازیکن زنده نیست."
        game.bazpors_narrator_pending_uid = tid
        game.bazpors_day_vote_elim_reason = "majority"
        game.bazpors_narrator_step = CONFIRM_DAY_ELIM
        return None
    if act in ("dv_votes_winner", "elim_yes"):
        if step != DAY_VOTE_ELIM_ASK:
            return "نامعتبر."
        if not _day_vote_defender_pool(game):
            return "لیست رأی خالی است؛ ابتدا بازیکنان رأی را انتخاب کنید."
        game.bazpors_day_vote_elim_reason = "majority"
        game.bazpors_narrator_step = PICK_DAY_ELIM
        return None
    if act == "dv_votes_tied":
        if step != DAY_VOTE_ELIM_ASK:
            return "نامعتبر."
        defenders = _day_vote_defender_uids(game)
        if len(defenders) < 2:
            return "برای تساوی رأی حداقل دو نامزد لازم است."
        tied = _day_vote_tie_break_elim_uids(game)
        if not tied:
            return "خطا در محاسبهٔ سابقه."
        if len(tied) == 1:
            game.bazpors_narrator_pending_uid = tied[0]
            game.bazpors_day_vote_elim_reason = "tie_break"
            game.bazpors_narrator_step = CONFIRM_DAY_ELIM
            return None
        game.bazpors_day_vote_elim_reason = "tie_particip_pick"
        game.bazpors_narrator_step = PICK_DAY_ELIM_TIE_PART
        return None
    if act == "dv_elim_back":
        if step not in (PICK_DAY_ELIM, PICK_DAY_ELIM_TIE_PART):
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = None
        game.bazpors_day_vote_elim_reason = None
        game.bazpors_narrator_step = DAY_VOTE_ELIM_ASK
        return None
    if act == "pick_day":
        if step == PICK_DAY_ELIM:
            allowed = {p.user_id for p in _day_vote_defender_pool(game)}
            game.bazpors_day_vote_elim_reason = "majority"
        elif step == PICK_DAY_ELIM_TIE_PART:
            allowed = set(_day_vote_tie_break_elim_uids(game))
            game.bazpors_day_vote_elim_reason = "tie_particip_pick"
        else:
            return "نامعتبر."
        if tid not in allowed:
            return "این بازیکن برای این مرحله مجاز نیست."
        if tid not in game.players or not game.players[tid].is_alive:
            return "بازیکن زنده نیست."
        game.bazpors_narrator_pending_uid = tid
        game.bazpors_narrator_step = CONFIRM_DAY_ELIM
        return None
    if act == "confirm_day_no":
        if step != CONFIRM_DAY_ELIM:
            return "نامعتبر."
        reason = game.bazpors_day_vote_elim_reason
        game.bazpors_narrator_pending_uid = None
        if reason == "tie_break":
            game.bazpors_day_vote_elim_reason = None
            game.bazpors_narrator_step = DAY_VOTE_ELIM_ASK
        elif reason == "tie_particip_pick":
            game.bazpors_day_vote_elim_reason = "tie_particip_pick"
            game.bazpors_narrator_step = PICK_DAY_ELIM_TIE_PART
        else:
            game.bazpors_day_vote_elim_reason = "majority"
            game.bazpors_narrator_step = PICK_DAY_ELIM
        return None
    if act == "confirm_day_yes":
        if step != CONFIRM_DAY_ELIM:
            return "نامعتبر."
        uid = game.bazpors_narrator_pending_uid
        if uid is None or uid not in game.players:
            return "خطا."
        if uid not in _day_vote_defender_uids(game):
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = None
        if _eliminate_and_maybe_win_gate(game, gm, uid, elim_source="day_vote"):
            _apply_day_vote_participations_for_today(game)
            _clear_day_vote_session(game)
            return None
        _enter_night_from_day_end(game)
        return None
    if act == "begin_night_actions":
        if step != NIGHT_START:
            return "ابتدا شب را آغاز کن."
        from bot.room_mode import mozakere_no_host_uses_parallel_night_ui

        if (
            no_host_assistant_narrator_active(game)
            and mozakere_no_host_uses_parallel_night_ui(game)
        ):
            return (
                "در سناریوی مذاکره انتخاب‌های شبانه به‌صورت خودکار جمع‌آوری می‌شود."
            )
        if (
            no_host_assistant_narrator_active(game)
            and game.no_host_night_parallel_collect_active
        ):
            return "بازیکنان در حال ثبت انتخاب‌های شبانه‌اند؛ پس از تکمیل همه، محاسبات خودکار آغاز می‌شود."
        if no_host_assistant_narrator_active(game) and (
            not game.no_host_night1_hunter_done
            or not game.no_host_mafia_night1_done
        ):
            return "ابتدا هانتر و تیم مافیا باید انتخاب خود را ثبت و تأیید کنند."
        _begin_night_actions(game)
        return None
    if act == "skip_hunter":
        if step != NIGHT_ACTIONS or ns != NS_HUNTER:
            return "نامعتبر."
        if _find_alive_role(game, Role.HUNTER):
            return "هانتر هنوز زنده است؛ از دکمه‌های بالا استفاده کن."
        if _role_eliminated_from_game(game, Role.HUNTER):
            _goto_role_absent(game, Role.HUNTER)
        else:
            _advance_after_hunter(game)
        return None
    if act == "role_absent_ok":
        if step != NIGHT_ACTIONS or ns != NS_ROLE_ABSENT:
            return "نامعتبر."
        _advance_after_role_absent(game)
        return None
    if act == "hp":
        if step != NIGHT_ACTIONS or ns != NS_HUNTER:
            return "نامعتبر."
        if not _hunter_role.target_valid(game, tid):
            return "نامعتبر."
        if not _hunter_role.find_alive_hunter(game):
            return "هانتر در بازی نیست."
        _hunter_role.commit_pick(game, tid)
        _advance_after_hunter(game)
        return None
    if act == "hs":
        if step != NIGHT_ACTIONS or ns != NS_HUNTER:
            return "نامعتبر."
        _hunter_role.commit_no_link(game)
        _advance_after_hunter(game)
        return None
    if act == "mshot":
        if step != NIGHT_ACTIONS or ns != NS_MAFIA_MENU:
            return "نامعتبر."
        if not mafia_shot_allowed(game):
            return "شات مجاز نیست."
        game.bazpors_night_substep = NS_MAFIA_SHOT
        return None
    if act == "mkt":
        if step != NIGHT_ACTIONS or ns != NS_MAFIA_SHOT:
            return "نامعتبر."
        if (
            no_host_assistant_narrator_active(game)
            and game.bazpors_narrator_night_count == 1
        ):
            return "هدف شات را تیم مافیا از پنل خود ثبت می‌کند."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        game.actions.mafia_target = tid
        game.bazpors_mafia_shot_registered = True
        _advance_after_mafia_menu_done(game)
        return None
    if act == "mnato":
        if step != NIGHT_ACTIONS or ns != NS_MAFIA_MENU:
            return "نامعتبر."
        if (
            no_host_assistant_narrator_active(game)
            and game.bazpors_narrator_night_count == 1
        ):
            return "ناتویی را بازیکن ناتو از پنل خود ثبت می‌کند."
        if not nato_can_register(game):
            return nato_denied_message(game)
        game.bazpors_night_substep = NS_NATO_ROLE
        return None
    if act == "nrole" and rid:
        if step != NIGHT_ACTIONS or ns != NS_NATO_ROLE:
            return "نامعتبر."
        if (
            no_host_assistant_narrator_active(game)
            and game.bazpors_narrator_night_count == 1
        ):
            return "ناتویی را بازیکن ناتو از پنل خود ثبت می‌کند."
        try:
            Role(rid)
        except ValueError:
            return "نقش نامعتبر."
        game.bazpors_nato_guess_role = rid
        game.bazpors_narrator_pending_uid = None
        game.bazpors_nato_multi_uids = None
        game.bazpors_night_substep = NS_NATO_CONFIRM
        return None
    if act == "npick":
        if step != NIGHT_ACTIONS or ns != NS_NATO_CONFIRM:
            return "نامعتبر."
        if (
            no_host_assistant_narrator_active(game)
            and game.bazpors_narrator_night_count == 1
        ):
            return "ناتویی را بازیکن ناتو از پنل خود ثبت می‌کند."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        if _visually_mafia(game, game.players[tid]):
            return "فقط بازیکنان غیرمافیا را می‌توان انتخاب کرد."
        role_val = game.bazpors_nato_guess_role
        if not role_val:
            return "ابتدا نقش را انتخاب کن."
        try:
            gr = Role(role_val)
        except ValueError:
            return "نقش نامعتبر."
        if not _nato_role.target_valid(game, tid):
            return "نامعتبر."
        _nato_role.commit_guess(game, gr, tid)
        _advance_after_mafia_menu_done(game)
        return None
    if act == "nato_back":
        if step != NIGHT_ACTIONS or ns not in (
            NS_NATO_ROLE,
            NS_NATO_CONFIRM,
            NS_NATO_MULTI_ASK,
            NS_NATO_MULTI_PICK,
        ):
            return "نامعتبر."
        if ns == NS_NATO_CONFIRM:
            game.bazpors_night_substep = NS_NATO_ROLE
            game.bazpors_nato_guess_role = None
            game.bazpors_narrator_pending_uid = None
        elif ns == NS_NATO_MULTI_PICK:
            game.bazpors_night_substep = NS_NATO_MULTI_ASK
            game.bazpors_narrator_pending_uid = None
        elif ns == NS_NATO_MULTI_ASK:
            game.bazpors_night_substep = NS_NATO_ROLE
            game.bazpors_nato_guess_role = None
            game.bazpors_nato_multi_uids = None
            game.bazpors_narrator_pending_uid = None
        elif ns == NS_NATO_ROLE:
            game.bazpors_night_substep = NS_MAFIA_MENU
            game.bazpors_nato_guess_role = None
        else:
            game.bazpors_nato_guess_role = None
            game.bazpors_nato_multi_uids = None
            game.bazpors_night_substep = NS_MAFIA_MENU
        return None
    if act == "nok":
        if step != NIGHT_ACTIONS or ns != NS_NATO_CONFIRM:
            return "نامعتبر."
        pending = game.bazpors_narrator_pending_uid
        if pending is None:
            return "ابتدا یک بازیکن را انتخاب کن."
        _nato_role.commit_confirm_result(game, pending, success=True)
        _advance_after_mafia_menu_done(game)
        return None
    if act == "nwr":
        if step != NIGHT_ACTIONS or ns != NS_NATO_CONFIRM:
            return "نامعتبر."
        pending = game.bazpors_narrator_pending_uid
        if pending is None:
            return "ابتدا یک بازیکن را انتخاب کن."
        _nato_role.commit_confirm_result(game, pending, success=False)
        _advance_after_mafia_menu_done(game)
        return None
    if act == "nm_yes":
        if step != NIGHT_ACTIONS or ns != NS_NATO_MULTI_ASK:
            return "نامعتبر."
        game.bazpors_night_substep = NS_NATO_MULTI_PICK
        return None
    if act == "nm_no":
        if step != NIGHT_ACTIONS or ns != NS_NATO_MULTI_ASK:
            return "نامعتبر."
        _nato_role.commit_multi_pick_fail(game)
        _advance_after_mafia_menu_done(game)
        return None
    if act == "nm_pick":
        if step != NIGHT_ACTIONS or ns != NS_NATO_MULTI_PICK:
            return "نامعتبر."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        _nato_role.commit_multi_pick_success(game, tid)
        _advance_after_mafia_menu_done(game)
        return None
    if act == "myaku":
        if step != NIGHT_ACTIONS or ns != NS_MAFIA_MENU:
            return "نامعتبر."
        if (
            no_host_assistant_narrator_active(game)
            and game.bazpors_narrator_night_count == 1
        ):
            return "یاکوزایی را تیم مافیا از پنل خود ثبت می‌کند."
        if not yakuzai_allowed(game, gm):
            return "یاکوزایی مجاز نیست."
        game.bazpors_night_substep = NS_YAKU_SAC
        return None
    if act == "yaku_back":
        if step != NIGHT_ACTIONS or ns not in (NS_YAKU_SAC, NS_YAKU_CIV):
            return "نامعتبر."
        yaku = yaku_night_state(game)
        if ns == NS_YAKU_CIV:
            game.bazpors_night_substep = NS_YAKU_SAC
            yaku.back_from_civilian_to_sac()
        else:
            game.bazpors_night_substep = NS_MAFIA_MENU
            yaku.back_from_sac_to_menu()
        return None
    if act == "ys":
        if step != NIGHT_ACTIONS or ns != NS_YAKU_SAC:
            return "نامعتبر."
        if (
            no_host_assistant_narrator_active(game)
            and game.bazpors_narrator_night_count == 1
        ):
            return "فدای یاکوزا را تیم مافیا از پنل خود ثبت می‌کند."
        pool = _yaku_sacrifice_pool(game)
        allowed = {p.user_id for p in pool}
        if tid not in allowed:
            return "این بازیکن طبق قوانین نمی‌تواند فدا شود."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        yaku_night_state(game).commit_sac_pick(tid)
        game.bazpors_night_substep = NS_YAKU_CIV
        return None
    if act == "yc":
        if step != NIGHT_ACTIONS or ns != NS_YAKU_CIV:
            return "نامعتبر."
        if (
            no_host_assistant_narrator_active(game)
            and game.bazpors_narrator_night_count == 1
        ):
            return "هدف یاکوزایی را تیم مافیا از پنل خود ثبت می‌کند."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        tgt = game.players[tid]
        if not _yaku_target_allowed(game, tgt):
            return "هدف باید غیرمافیا باشد."
        yaku = yaku_night_state(game)
        su = yaku.sac_uid
        if su is None or su not in game.players or not game.players[su].is_alive:
            return "ابتدا فدا را انتخاب کن."
        sac = game.players[su]
        ok = _yaku_negotiation_succeeds(game, tgt)
        yaku.commit_outcome(civ_uid=tid, sac_uid=su, success=ok)
        sac_role = html.escape(role_label_fa(sac.role)) if sac.role else html.escape(gm.format_player_tag(sac))
        tgt_role = html.escape(role_label_fa(tgt.role)) if tgt.role else html.escape(gm.format_player_tag(tgt))
        if ok:
            from bot.game import apply_bazpors_yakuzai_recruit

            apply_bazpors_yakuzai_recruit(game, tgt)
            game.bazpors_night_announce_lines.append(
                f"یاکوزای موفق: {sac_role} فدا شد؛ {tgt_role} به مافیا پیوست."
            )
        else:
            game.bazpors_night_announce_lines.append(
                f"یاکوزای ناموفق: {sac_role} فدا شد؛ {tgt_role} مافیا نشد."
            )
        gm.check_winner(game)
        yaku.mark_used()
        game.bazpors_narrator_pending_uid = None
        _void_semi_auto_doctor_night_pick(game)
        if trigger_win_gate_if_needed(game, gm, elim_source="night_resolve"):
            return None
        if ok:
            game.bazpors_night_substep = NS_YAKU_SUCCESS_ACK
            return None
        game.bazpors_night_substep = NS_YAKU_FAIL_ACK
        return None
    if act == "yaku_next":
        if step != NIGHT_ACTIONS or ns not in (NS_YAKU_SUCCESS_ACK, NS_YAKU_FAIL_ACK):
            return "نامعتبر."
        yaku = yaku_night_state(game)
        if ns == NS_YAKU_SUCCESS_ACK and not yaku.night_success:
            return "نامعتبر."
        if ns == NS_YAKU_FAIL_ACK and yaku.night_success:
            return "نامعتبر."
        yaku.clear_sac_uid_after_ack()
        _advance_after_mafia_menu_done(game)
        return None
    if act == "mafia_done":
        if step != NIGHT_ACTIONS or ns != NS_MAFIA_MENU:
            return "نامعتبر."
        _advance_after_mafia_menu_done(game)
        return None
    if act == "sg":
        if step != NIGHT_ACTIONS or ns != NS_SHIAD:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "انتخاب شیاد را خودش از پنل خصوصی ثبت می‌کند."
        if not _shiad_role.target_valid(game, tid):
            if tid in game.players and game.players[tid].is_alive:
                sh = _find_alive_role(game, Role.SHIAD)
                if sh and tid == sh.user_id:
                    return "شیاد نمی‌تواند خودش را به‌عنوان هدف حدس انتخاب کند."
                return "شیاد نمی‌تواند عضو تیم مافیا را هدف حدس قرار دهد."
            return "نامعتبر."
        hit_det = _shiad_role.commit_pick(game, tid, gm=gm, semi_auto=True)
        if hit_det:
            game.bazpors_night_substep = NS_SHIAD_ACK
            return None
        _advance_after_shiad(game)
        return None
    if act == "sdp":
        if step != NIGHT_ACTIONS or ns != NS_SHIAD_ACK:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "شیاد از پنل خصوصی خود انتخاب را ثبت می‌کند."
        det = _find_alive_role(game, Role.DETECTIVE)
        if not det:
            return "کارآگاه در بازی نیست."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        if tid == det.user_id:
            return "کارآگاه را نمی‌توان در این لیست انتخاب کرد."
        game.bazpors_narrator_pending_uid = tid
        game.actions.detective_check = tid
        return None
    if act == "sdp_back":
        if step != NIGHT_ACTIONS or ns != NS_SHIAD_ACK:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "شیاد از پنل خصوصی خود انتخاب را ثبت می‌کند."
        game.bazpors_narrator_pending_uid = None
        game.actions.detective_check = None
        return None
    if act == "sdp_ok":
        if step != NIGHT_ACTIONS or ns != NS_SHIAD_ACK:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "شیاد از پنل خصوصی خود انتخاب را ثبت می‌کند."
        if not game.bazpors_detective_blocked:
            return "نامعتبر."
        if game.bazpors_narrator_pending_uid is None:
            return "ابتدا یک بازیکن را انتخاب کن."
        commit_shiad_voided_detective_inquiry_note(game)
        game.bazpors_narrator_pending_uid = None
        game.bazpors_night_substep = NS_DET_ACK
        return None
    if act == "shiad_ack":
        if step != NIGHT_ACTIONS or ns != NS_SHIAD_ACK:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "شیاد از پنل خصوصی خود انتخاب را ثبت می‌کند."
        if not game.bazpors_detective_blocked:
            return "نامعتبر."
        _advance_after_shiad(game)
        return None
    if act == "shiad_skip":
        if step != NIGHT_ACTIONS or ns != NS_SHIAD:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "انتخاب شیاد را خودش از پنل خصوصی ثبت می‌کند."
        _advance_after_shiad(game)
        return None
    if act == "dp":
        if step != NIGHT_ACTIONS or ns != NS_DET:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "استعلام کارآگاه را خودش از پنل خصوصی ثبت می‌کند."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        result = _detective_role.commit_pick(game, tid)
        tag = gm.format_player_tag(game.players[tid])
        game.bazpors_detective_last_answer = f"استعلام روی {tag}: {result.host_answer_fa()}"
        game.bazpors_night_substep = NS_DET_ACK
        return None
    if act == "det_ack":
        if step != NIGHT_ACTIONS or ns != NS_DET_ACK:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "تأیید استعلام کارآگاه خودکار است."
        _advance_after_det(game)
        return None
    if act == "dx":
        if step != NIGHT_ACTIONS or ns != NS_DET:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "کارآگاه از پنل خودش استعلام را ثبت می‌کند."
        _detective_role.mark_no_inquiry(game)
        _advance_after_det(game)
        return None
    if act == "doc_nato_skip_ok":
        if step != NIGHT_ACTIONS or ns != NS_DOC_NATO_SKIP:
            return "نامعتبر."
        _goto_interrogator_night_step(game)
        return None
    if act == "doc_yaku_skip_ok":
        if step != NIGHT_ACTIONS or ns != NS_DOC_YAKU_SKIP:
            return "نامعتبر."
        _advance_after_doc(game)
        return None
    if act == "dr":
        if step != NIGHT_ACTIONS or ns != NS_DOC:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "نجات را پزشک از پنل خصوصی خود ثبت می‌کند."
        if not _semi_auto_doctor_night_pick_allowed(game):
            return (
                "پس از ناتویی یا یاکوزایی در این شب، انتخاب پزشک دیگر اعمال نمی‌شود."
            )
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        doc = _find_alive_role(game, Role.DOCTOR)
        if doc and tid == doc.user_id:
            if _doctor_role.self_save_limit_reached(game):
                return "پزشک قبلاً دو بار خودش را نجات داده و دیگر نمی‌تواند خودش را انتخاب کند."
            if not _doctor_role.can_register_self_save_this_night(game):
                return "نجات خودی پزشک در این شب قبلاً ثبت شده؛ با «بازگشت» می‌توانی اصلاح کنی."
        _doctor_role.commit_pick(game, tid)
        _advance_after_doc(game)
        return None
    if act == "dxd":
        if step != NIGHT_ACTIONS or ns != NS_DOC:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "نجات را پزشک از پنل خصوصی خود ثبت می‌کند."
        if not _semi_auto_doctor_night_pick_allowed(game):
            return (
                "پس از ناتویی یا یاکوزایی در این شب، انتخاب پزشک دیگر اعمال نمی‌شود."
            )
        _doctor_role.clear_pick(game)
        _advance_after_doc(game)
        return None
    if act == "i1":
        if no_host_assistant_narrator_active(game):
            return "بازپرسی را بازپرس از پنل خصوصی خود ثبت می‌کند."
        if step != NIGHT_ACTIONS or ns != NS_INT1:
            return "نامعتبر."
        if not _interrogator_role.first_target_valid(game, tid):
            return "نامعتبر."
        _interrogator_role.commit_first_nominee(game, tid)
        _advance_after_int1(game)
        return None
    if act == "int_skip_ok":
        if no_host_assistant_narrator_active(game):
            return "بازپرس را بازپرس از پنل خصوصی خود ثبت می‌کند."
        if step != NIGHT_ACTIONS or ns != NS_INTERROG_SKIP:
            return "نامعتبر."
        _interrogator_role.clear_night_pick(game)
        _advance_after_int2(game)
        return None
    if act == "i1_skip":
        if no_host_assistant_narrator_active(game):
            return "بازپرسی را بازپرس از پنل خصوصی خود ثبت می‌کند."
        if step != NIGHT_ACTIONS or ns != NS_INT1:
            return "نامعتبر."
        _interrogator_role.clear_night_pick(game)
        _advance_after_int2(game)
        return None
    if act == "i2":
        if no_host_assistant_narrator_active(game):
            return "بازپرس را بازپرس از پنل خصوصی خود ثبت می‌کند."
        if step != NIGHT_ACTIONS or ns != NS_INT2:
            return "نامعتبر."
        if not _interrogator_role.second_target_valid(game, tid):
            return "باید غیر از نفر اول باشد."
        _interrogator_role.commit_second_nominee(game, tid)
        _advance_after_int2(game)
        return None
    if act == "i2_abort":
        if no_host_assistant_narrator_active(game):
            return "بازپرس را بازپرس از پنل خصوصی خود ثبت می‌کند."
        if step != NIGHT_ACTIONS or ns != NS_INT2:
            return "نامعتبر."
        _interrogator_role.clear_night_pick(game)
        _advance_after_int2(game)
        return None
    if act == "i2_redo1":
        if no_host_assistant_narrator_active(game):
            return "بازپرس را بازپرس از پنل خصوصی خود ثبت می‌کند."
        if step != NIGHT_ACTIONS or ns != NS_INT2:
            return "نامعتبر."
        _interrogator_role.clear_night_pick(game)
        game.bazpors_night_substep = NS_INT1
        return None
    if act == "night_back":
        if step == PICK_DISCIPLINE_KICK:
            game.bazpors_narrator_pending_uid = None
            game.bazpors_narrator_step = NIGHT_ACTIONS
            game.bazpors_night_substep = NS_DISCIPLINE_ASK
            return None
        if step == CONFIRM_DISCIPLINE_KICK:
            game.bazpors_narrator_pending_uid = None
            game.bazpors_narrator_step = PICK_DISCIPLINE_KICK
            return None
        if step == CONFIRM_DISCIPLINE_NO:
            game.bazpors_narrator_step = NIGHT_ACTIONS
            game.bazpors_night_substep = NS_DISCIPLINE_ASK
            return None
        if step != NIGHT_ACTIONS:
            return "نامعتبر."
        return _night_back_one(game)
    if act == "disc_yes":
        if step != NIGHT_ACTIONS or ns != NS_DISCIPLINE_ASK:
            return "نامعتبر."
        game.bazpors_narrator_step = PICK_DISCIPLINE_KICK
        return None
    if act == "disc_no":
        if step != NIGHT_ACTIONS or ns != NS_DISCIPLINE_ASK:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            game.bazpors_narrator_step = CONFIRM_DISCIPLINE_NO
            return None
        _goto_resolve_step(game)
        return None
    if act == "disc_no_ok":
        if step != CONFIRM_DISCIPLINE_NO:
            return "نامعتبر."
        if not no_host_assistant_narrator_active(game):
            return "نامعتبر."
        game.bazpors_night_discipline_kick_uid = None
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DISCIPLINE_ASK
        return None
    if act == "disc_no_back":
        if step != CONFIRM_DISCIPLINE_NO:
            return "نامعتبر."
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DISCIPLINE_ASK
        return None
    if act == "disc_pick":
        if step != PICK_DISCIPLINE_KICK:
            return "نامعتبر."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = tid
        game.bazpors_narrator_step = CONFIRM_DISCIPLINE_KICK
        return None
    if act == "disc_back":
        if step != CONFIRM_DISCIPLINE_KICK:
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = None
        game.bazpors_narrator_step = PICK_DISCIPLINE_KICK
        return None
    if act == "disc_ok":
        if step != CONFIRM_DISCIPLINE_KICK:
            return "نامعتبر."
        u = game.bazpors_narrator_pending_uid
        if u is None or u not in game.players:
            return "خطا."
        game.bazpors_night_discipline_kick_uid = u
        game.bazpors_narrator_pending_uid = None
        game.bazpors_narrator_step = NIGHT_ACTIONS
        if _eliminate_and_maybe_win_gate(
            game, gm, u, hunter_chain=False, elim_source="discipline"
        ):
            return None
        if not no_host_assistant_narrator_active(game):
            _goto_resolve_step(game)
        return None
    if act == "sn_skip":
        if step != NIGHT_ACTIONS or ns != NS_SNIPER:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "شلیک را اسنایپر از پنل خصوصی خود ثبت می‌کند."
        _sniper_role.clear_pick(game)
        _goto_discipline_ask(game)
        return None
    if act == "sn_pick":
        if step != NIGHT_ACTIONS or ns != NS_SNIPER:
            return "نامعتبر."
        if no_host_assistant_narrator_active(game):
            return "شلیک را اسنایپر از پنل خصوصی خود ثبت می‌کند."
        if not _sniper_role.can_shoot(game):
            return "تیر تک‌تیرانداز قبلاً استفاده شده."
        if not _sniper_role.target_valid(game, tid):
            return "نامعتبر."
        _sniper_role.commit_pick(game, tid)
        _goto_discipline_ask(game)
        return None
    if act == "apply_resolve":
        if step != NIGHT_ACTIONS or ns != NS_RESOLVE:
            return "نامعتبر."
        _finish_resolve_to_extra(game, gm)
        return None
    if act == "nx_no":
        if step != ASK_NIGHT_EXTRA:
            return "نامعتبر."
        if game.bazpors_interrog_ready_for_day:
            return (
                "ابتدا با دکمهٔ «بازپرسی ادامه پیدا کند» یا «بازپرسی منحل شد» وضعیت را مشخص کن."
            )
        game.bazpors_interrog_cancel_next_day = False
        game.bazpors_interrog_ready_for_day = False
        if trigger_win_gate_if_needed(game, gm):
            return None
        go_day_after_night_extra()
        return None
    if act == "nx_yes":
        if step != ASK_NIGHT_EXTRA:
            return "نامعتبر."
        if game.bazpors_interrog_ready_for_day:
            return "در این وضعیت فقط دو دکمهٔ بازپرسی را بزن."
        game.bazpors_narrator_step = PICK_NIGHT_EXTRA
        return None
    if act == "nx_pick":
        if step != PICK_NIGHT_EXTRA:
            return "نامعتبر."
        if tid not in game.players or not game.players[tid].is_alive:
            return "نامعتبر."
        game.bazpors_narrator_pending_uid = tid
        game.bazpors_narrator_step = CONFIRM_NIGHT_EXTRA
        return None
    if act == "nx_back":
        if step != CONFIRM_NIGHT_EXTRA:
            return "نامعتبر."
        game.bazpors_narrator_step = PICK_NIGHT_EXTRA
        game.bazpors_narrator_pending_uid = None
        return None
    if act == "nx_ok":
        if step != CONFIRM_NIGHT_EXTRA:
            return "نامعتبر."
        u = game.bazpors_narrator_pending_uid
        if u is None or u not in game.players:
            return "خطا."
        game.bazpors_narrator_pending_uid = None
        if _eliminate_and_maybe_win_gate(game, gm, u, elim_source="night_extra"):
            snap = game.bazpors_alive_at_night_start
            if snap:
                game.bazpors_night_report_html = _compose_full_night_report(
                    game, gm, snap
                )
            return None
        snap = game.bazpors_alive_at_night_start
        if snap:
            game.bazpors_night_report_html = _compose_full_night_report(
                game, gm, snap
            )
        game.bazpors_narrator_step = ASK_NIGHT_EXTRA
        _evaluate_post_night_host_state(game, gm)
        return None

    return "دکمه نامعتبر است."


def _tag_esc_host(game: Game, gm: GameManager, uid: int | None) -> str:
    if uid is None or uid not in game.players:
        return "؟"
    return html.escape(gm.format_player_tag(game.players[uid]))


def narrator_compact_ack_html(
    game: Game,
    gm: GameManager,
    act: str,
    tid: int,
    rid: str,
    *,
    pending_uid_before: int | None,
) -> str:
    """یک خط کوتاه پس از حذف پیام پنل گرداننده (parse_mode=HTML)."""
    if act == "start_intro_day":
        return "☀️ روز معارفه شروع شد."
    if act == "start_intro_night":
        return "🌙 شب معارفه شروع شد."
    if act == "announce_day1":
        return "☀️ روز اول اعلام شد."
    if act == "intr_dissolve":
        return "⭕ بازپرسی منحل شد."
    if act == "intr_continue":
        return "▶️ بازپرسی ادامه پیدا کرد."
    if act == "intr_day_pick":
        return f"بازپرسی — رأی خروج ← {_tag_esc_host(game, gm, tid)}"
    if act == "confirm_intr_vote_no":
        return "↩️ بازگشت از تأیید خروج بازپرسی."
    if act == "confirm_intr_vote_yes":
        return f"بازپرسی — تأیید خروج ← {_tag_esc_host(game, gm, pending_uid_before)}"
    if act == "intr_vote_no_elim":
        return "بازپرسی — رأی مساوی؛ کسی خارج نشد."
    if act == "intr_pick_abort":
        return "☀️ بازپرسی — ادامه بدون حذف."
    if act == "vote_done":
        return "🗳 رأی‌گیری روز ثبت شد — انتخاب کسانی که در رأی بودند."
    if act == "ki_as_mafia_win":
        return f"{CHAOS_PHASE_LABEL} — مافیا برنده شد."
    if act == "ki_as_citizen_win":
        return f"{CHAOS_PHASE_LABEL} — شهروند برنده شد."
    if act == "dv_toggle":
        return f"رأی روز — {'انتخاب' if tid in _day_vote_pick_uids(game) else 'حذف'} ← {_tag_esc_host(game, gm, tid)}"
    if act == "dv_none_defended":
        return "رأی روز — هیچکسی وارد دفاعیه نشد."
    if act == "dv_confirm":
        return "رأی روز — لیست حاضران در رأی ثبت شد."
    if act == "dv_pick_back":
        return "↩️ ویرایش لیست حاضران در رأی."
    if act == "dv_elim_back":
        return "↩️ بازگشت از انتخاب خروج."
    if act in ("dv_no_elim", "elim_no"):
        return "روز — با رأی اتاق کسی خارج نشد."
    if act == "dv_single_elim":
        return f"روز — خروج ← {_tag_esc_host(game, gm, tid)}"
    if act == "dv_defender_out":
        return f"روز — خروج ← {_tag_esc_host(game, gm, tid)}"
    if act in ("dv_votes_winner", "elim_yes"):
        return "روز — بیشترین رأی؛ انتخاب بازیکن خروج."
    if act == "dv_votes_tied":
        return "روز — رأی مساوی؛ تعیین خروج با سابقهٔ حضور در رأی."
    if act == "pick_day":
        return f"روز — خروج با رأی ← {_tag_esc_host(game, gm, tid)}"
    if act == "confirm_day_no":
        return "↩️ بازگشت از تأیید خروج روز."
    if act == "confirm_day_yes":
        return f"روز — تأیید خروج ← {_tag_esc_host(game, gm, pending_uid_before)}"
    if act == "begin_night_actions":
        nc = game.bazpors_narrator_night_count
        return f"🌙 اجرای نقش‌های شب {_seat_fa(nc)} آغاز شد."
    if act == "skip_hunter":
        return "هانتر — مرحله رد شد."
    if act == "hp":
        return f"هانتر — وصل به {_tag_esc_host(game, gm, tid)}"
    if act == "hs":
        return "هانتر — این شب وصل جدید نداشت (وصل قبلی حفظ می‌شود)."
    if act == "mshot":
        return "مافیا — ثبت شات شب (انتخاب هدف)."
    if act == "mkt":
        tag = _tag_esc_host(game, gm, tid)
        if tid in game.players and _ruintan_role.mafia_shot_survives(game.players[tid]):
            return f"شات مافیا → {tag} (رویین‌تن؛ در پایان شب خارج نمی‌شود)."
        return f"شات مافیا → {tag}"
    if act == "mnato":
        return "مافیا — ثبت ناتویی."
    if act == "nrole" and rid:
        try:
            rlab = html.escape(role_label_fa(Role(rid)))
        except ValueError:
            rlab = html.escape(rid)
        return f"ناتو — نقش حدس‌زده ثبت شد: {rlab}"
    if act == "nato_back":
        return "ناتو — بازگشت."
    if act == "nok":
        return f"ناتو — حدس درست؛ هدف ← {_tag_esc_host(game, gm, pending_uid_before)}"
    if act == "nwr":
        return "ناتو — حدس نادرست."
    if act == "nm_yes":
        return "ناتو — حدس درست (انتخاب خروج)."
    if act == "nm_no":
        return "ناتو — حدس نادرست (چندنفره)."
    if act == "nm_pick":
        return f"ناتو — خروج با ناتویی ← {_tag_esc_host(game, gm, tid)}"
    if act == "myaku":
        return "مافیا — یاکوزایی آغاز شد."
    if act == "yaku_back":
        return "یاکوزا — بازگشت."
    if act == "ys":
        return f"یاکوزا — فدا: {_tag_esc_host(game, gm, tid)}"
    if act == "yc":
        if tid in game.players and tid in game.bazpors_mafia_recruit_ids:
            return f"یاکوزایی موفق — هدف: {_tag_esc_host(game, gm, tid)}"
        return f"یاکوزایی ناموفق — هدف: {_tag_esc_host(game, gm, tid)}"
    if act == "yaku_next":
        if yaku_night_state(game).night_success:
            return "یاکوزا — عضو جدید بیدار شد؛ ادامه به شیاد"
        return "یاکوزا — ناموفق؛ ادامه به شیاد"
    if act == "mafia_done":
        return "مافیا — پایان مرحلهٔ مافیا."
    if act == "sg":
        return f"شیاد — هدف حدس ← {_tag_esc_host(game, gm, tid)}"
    if act == "sdp":
        return f"کارآگاه — انتخاب استعلام ← {_tag_esc_host(game, gm, tid)}"
    if act == "sdp_ok":
        return "کارآگاه — تأیید استعلام منفی (اوکی)"
    if act == "sdp_back":
        return "کارآگاه — بازگشت به لیست"
    if act == "npick":
        return f"ناتو — حدس بازیکن ← {_tag_esc_host(game, gm, tid)}"
    if act == "shiad_ack":
        return "شیاد — کارآگاه خوابید؛ ادامه به پزشک"
    if act == "shiad_skip":
        return "شیاد — مرحله رد شد."
    if act == "dp":
        return f"کارآگاه — استعلام ← {_tag_esc_host(game, gm, tid)}"
    if act == "det_ack":
        return "کارآگاه — تأیید نتیجه استعلام (اوکی)"
    if act == "dx":
        return "کارآگاه — استعلام نگرفت."
    if act == "dr":
        return f"پزشک — نجات ← {_tag_esc_host(game, gm, tid)}"
    if act == "dxd":
        return "پزشک — نجات نداد."
    if act == "doc_nato_skip_ok":
        return "پزشک — ناتویی؛ بدون انتخاب. ادامه به بازپرس."
    if act == "doc_yaku_skip_ok":
        return "پزشک — یاکوزایی؛ بدون انتخاب. ادامه به بازپرس."
    if act == "role_absent_ok":
        role = _absent_night_role(game)
        if role:
            return f"{_night_role_step_name(role)} — {NIGHT_STEP_NEXT_BTN}."
        return f"{NIGHT_STEP_NEXT_BTN}."
    if act == "i1":
        return f"بازپرسی — نفر اول ← {_tag_esc_host(game, gm, tid)}"
    if act == "int_skip_ok":
        return "بازپرس — نیازی به گرفتن نقش نیست (تأیید)."
    if act == "i1_skip":
        return "بازپرسی — کسی انتخاب نشد (بدون بازپرسی این شب)."
    if act == "i2":
        return f"بازپرسی — نفر دوم ← {_tag_esc_host(game, gm, tid)}"
    if act == "i2_abort":
        return "بازپرس از بازپرسی منصرف شد."
    if act == "i2_redo1":
        return "انتخاب مجدد نفر اول بازپرسی."
    if act == "sn_skip":
        if game.bazpors_sniper_shot_used:
            return "تک‌تیرانداز — ادامه (تیر قبلاً استفاده شده)."
        return "تک‌تیرانداز — این شب شلیک نکرد."
    if act == "sn_pick":
        return f"تک‌تیرانداز — هدف شلیک ← {_tag_esc_host(game, gm, tid)}"
    if act == "night_back":
        return "⬅️ بازگشت به مرحلهٔ قبل (شب)."
    if act == "disc_yes":
        return "اخراج انضباطی — بله."
    if act == "disc_no":
        return "اخراج انضباطی — خیر."
    if act == "disc_pick":
        return f"اخراج انضباطی — انتخاب ← {_tag_esc_host(game, gm, tid)}"
    if act == "disc_ok":
        return f"اخراج انضباطی — تأیید حذف ← {_tag_esc_host(game, gm, pending_uid_before)}"
    if act == "disc_back":
        return "اخراج انضباطی — بازگشت."
    if act == "apply_resolve":
        return "پایان شب — اعمال شد."
    if act == "nx_no":
        return "روز بعد — ادامه به بحث روز."
    if act == "nx_yes":
        return "خروج شبانهٔ اضافی — انتخاب بازیکن."
    if act == "nx_pick":
        return f"خروج شبانهٔ اضافی ← {_tag_esc_host(game, gm, tid)}"
    if act == "nx_back":
        return "↩️ بازگشت از تأیید خروج شبانه."
    if act == "nx_ok":
        return f"خروج شبانهٔ اضافی — تأیید ← {_tag_esc_host(game, gm, pending_uid_before)}"
    return "ثبت شد."


def _remember_assistant_panel_ref(
    game: Game, chat_id: int, message_id: int
) -> None:
    game.bazpors_assistant_panel_chat_id = chat_id
    game.bazpors_assistant_panel_message_id = message_id


def clear_narrator_panel_ref(game: Game) -> None:
    """پس از انتقال گردانندگی — ویرایش پیام قدیمی کمک‌کننده/گردانندهٔ قبلی را قطع کن."""
    game.bazpors_assistant_panel_chat_id = None
    game.bazpors_assistant_panel_message_id = None


async def dismiss_assistant_panel_message(
    bot: Bot,
    game: Game,
    *,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> None:
    """پنل ذخیره‌شدهٔ کمک‌کننده را از چت حذف کن (قبل از ارسال پنل جدید)."""
    cid = (
        chat_id
        if chat_id is not None
        else game.bazpors_assistant_panel_chat_id
    )
    mid = (
        message_id
        if message_id is not None
        else game.bazpors_assistant_panel_message_id
    )
    if cid is not None and mid is not None:
        try:
            await bot.delete_message(chat_id=cid, message_id=mid)
        except TelegramBadRequest:
            pass
    clear_narrator_panel_ref(game)


def clear_observer_narrator_mirror_ref(game: Game) -> None:
    game.bazpors_observer_narrator_mirror_chat_id = None
    game.bazpors_observer_narrator_mirror_message_id = None


async def dismiss_observer_narrator_mirror_message(
    bot: Bot,
    game: Game,
    *,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> None:
    """آینهٔ پنل نریتور برای ناظر را از چت حذف کن."""
    cid = (
        chat_id
        if chat_id is not None
        else game.bazpors_observer_narrator_mirror_chat_id
    )
    mid = (
        message_id
        if message_id is not None
        else game.bazpors_observer_narrator_mirror_message_id
    )
    if cid is not None and mid is not None:
        try:
            await bot.delete_message(chat_id=cid, message_id=mid)
        except TelegramBadRequest:
            pass
    clear_observer_narrator_mirror_ref(game)


async def dismiss_no_host_narrator_operator_panels(
    bot: Bot,
    game: Game,
    *,
    clicked: Message | None = None,
) -> None:
    """پنل کمک‌کننده و آینهٔ ناظر — مثلاً پس از تأیید استعلام میز."""
    if clicked is not None:
        try:
            await bot.delete_message(
                chat_id=clicked.chat.id,
                message_id=clicked.message_id,
            )
        except TelegramBadRequest:
            pass
    await dismiss_assistant_panel_message(bot, game)
    await dismiss_observer_narrator_mirror_message(bot, game)


def _remember_observer_narrator_mirror_ref(
    game: Game, chat_id: int, message_id: int
) -> None:
    game.bazpors_observer_narrator_mirror_chat_id = chat_id
    game.bazpors_observer_narrator_mirror_message_id = message_id


async def finalize_assistant_panel_message(
    bot: Bot,
    game: Game,
    message: Message,
    text: str,
) -> None:
    """پس از تأیید — همان پیام دستیار بدون دکمه (بدون پیام جدید)."""
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=None,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        _remember_assistant_panel_ref(game, message.chat.id, message.message_id)
    except TelegramBadRequest:
        pass


async def _try_edit_assistant_panel(
    bot: Bot,
    game: Game,
    text: str,
    kb: InlineKeyboardMarkup | None,
    *,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> bool:
    cid = chat_id if chat_id is not None else game.bazpors_assistant_panel_chat_id
    mid = (
        message_id
        if message_id is not None
        else game.bazpors_assistant_panel_message_id
    )
    if cid is None or mid is None:
        return False
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=cid,
            message_id=mid,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        _remember_assistant_panel_ref(game, cid, mid)
        return True
    except TelegramBadRequest:
        return False


async def _try_edit_observer_narrator_mirror(
    bot: Bot,
    game: Game,
    body: str,
    kb: InlineKeyboardMarkup | None,
) -> bool:
    cid = game.bazpors_observer_narrator_mirror_chat_id
    mid = game.bazpors_observer_narrator_mirror_message_id
    if cid is None or mid is None:
        return False
    try:
        await bot.edit_message_text(
            text=body,
            chat_id=cid,
            message_id=mid,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        _remember_observer_narrator_mirror_ref(game, cid, mid)
        return True
    except TelegramBadRequest:
        return False


async def _mirror_narrator_panel_to_observer(
    bot: Bot, game: Game, text: str, kb: InlineKeyboardMarkup | None
) -> None:
    if not game.no_host_observer_only_narrator_mirror:
        return
    obs_id = game.observer_user_id
    op_id = narrator_operator_user_id(game)
    if obs_id is None or obs_id == op_id:
        return
    body = (
        "👁 <i>ناظر — ادامهٔ روند (فقط برای شما؛ بازیکنان پیام نمی‌گیرند)</i>\n\n"
        + text
    )
    if await _try_edit_observer_narrator_mirror(bot, game, body, kb):
        return
    sent = await safe_send_message_return(
        bot,
        obs_id,
        body,
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )
    if sent is not None:
        _remember_observer_narrator_mirror_ref(
            game, sent.chat.id, sent.message_id
        )


async def _deliver_host_narrator_panel(
    bot: Bot,
    game: Game,
    gm: GameManager,
    text: str,
    kb: InlineKeyboardMarkup | None,
    *,
    edit_in_place: Message | None = None,
    force_new_message: bool = False,
    remember_panel: bool = True,
) -> bool:
    """پنل به کمک‌کننده/گرداننده؛ آینهٔ ناظر فقط اگر همان پنل به اپراتور رسید."""
    operator_id = narrator_operator_user_id(game)
    assistant_ok = False

    # کمک‌کنندهٔ no_host: همیشه پنل قبلی حذف و پیام تازه (انتهای چت)، بدون edit.
    if no_host_assistant_narrator_active(game):
        if edit_in_place is not None and edit_in_place.chat.id == operator_id:
            try:
                await bot.delete_message(
                    chat_id=edit_in_place.chat.id,
                    message_id=edit_in_place.message_id,
                )
            except TelegramBadRequest:
                pass
        await dismiss_assistant_panel_message(bot, game)
        await dismiss_observer_narrator_mirror_message(bot, game)
        sent = await safe_send_message_return(
            bot,
            operator_id,
            text,
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True,
        )
        if sent is not None:
            if remember_panel:
                _remember_assistant_panel_ref(game, sent.chat.id, sent.message_id)
            assistant_ok = True
        if remember_panel:
            await _mirror_narrator_panel_to_observer(bot, game, text, kb)
        return assistant_ok

    if force_new_message:
        await dismiss_assistant_panel_message(bot, game)
        edit_in_place = None
    elif edit_in_place is not None and edit_in_place.chat.id != operator_id:
        # ناظر دکمه زده — پیام او را به‌جای پنل کمک‌کننده ویرایش نکن.
        edit_in_place = None
        force_new_message = True
    if edit_in_place is not None:
        if await _try_edit_assistant_panel(
            bot,
            game,
            text,
            kb,
            chat_id=edit_in_place.chat.id,
            message_id=edit_in_place.message_id,
        ):
            assistant_ok = True
    elif not force_new_message and await _try_edit_assistant_panel(bot, game, text, kb):
        assistant_ok = True
    else:
        sent = await safe_send_message_return(
            bot,
            operator_id,
            text,
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True,
        )
        if sent is not None:
            if remember_panel:
                _remember_assistant_panel_ref(game, sent.chat.id, sent.message_id)
            assistant_ok = True
    if assistant_ok and remember_panel:
        await _mirror_narrator_panel_to_observer(bot, game, text, kb)
    return assistant_ok


async def _deliver_current_host_panel(
    bot: Bot,
    game: Game,
    gm: GameManager,
    *,
    edit_in_place: Message | None = None,
    force_new_message: bool = False,
) -> bool:
    """پنل فعلی — در فاز آشوب دو پیام: گزارش شب (بدون دکمه) + دستور Chaos."""
    _sync_ki_as_today(game, gm)
    win = _win_note(gm, game)
    if (
        _ki_as_split_night_end_panel(game, gm)
        or _interrog_ready_split_night_end_panel(game, gm)
        or _night_end_report_split_active(game, gm)
    ):
        await deliver_assistant_pinned_night_end_report_if_needed(bot, game, gm)
        out = build_host_message_and_keyboard(game, gm)
        if isinstance(out, tuple) and out[0] and out[0].startswith("خطا"):
            return False
        text, kb = out
        if not text:
            return False
        text = _host_message_with_optional_flush(game, text)
        await _deliver_host_narrator_panel(
            bot,
            game,
            gm,
            text,
            kb,
            edit_in_place=edit_in_place,
            force_new_message=True,
        )
        return True
    out = build_host_message_and_keyboard(game, gm)
    if isinstance(out, tuple) and out[0] and out[0].startswith("خطا"):
        return False
    text, kb = out
    if not text:
        return False
    if isinstance(text, str) and text.startswith("وضعیت"):
        return False
    text = _host_message_with_optional_flush(game, text)
    assistant_new_only = no_host_assistant_narrator_active(game)
    return await _deliver_host_narrator_panel(
        bot,
        game,
        gm,
        text,
        kb,
        edit_in_place=None if assistant_new_only else edit_in_place,
        force_new_message=force_new_message or assistant_new_only,
    )


async def push_host_step(
    bot: Bot,
    game: Game,
    gm: GameManager,
    *,
    force_new_host_message: bool = False,
) -> None:
    if not narrator_panel_receives_updates(game) or not game.bazpors_narrator_step:
        return
    from bot.no_host_interrog_day import interrog_day_session_wait_locked

    if interrog_day_session_wait_locked(game):
        return
    from bot.no_host_handoff import (
        NO_HOST_HANDOFF_OFFER,
        deliver_no_host_handoff_offer_panels,
    )

    if game.bazpors_narrator_step == NO_HOST_HANDOFF_OFFER:
        await deliver_no_host_handoff_offer_panels(bot, game, gm)
        await _run_post_host_panel_side_effects(bot, game, gm)
        return
    force_new = force_new_host_message or no_host_assistant_narrator_active(game)
    if not await _deliver_current_host_panel(
        bot, game, gm, force_new_message=force_new
    ):
        await _run_post_host_panel_side_effects(bot, game, gm)
        return
    await _run_post_host_panel_side_effects(bot, game, gm)


async def _run_post_host_panel_side_effects(
    bot: Bot, game: Game, gm: GameManager
) -> None:
    from bot.no_host_interrog_day import NO_HOST_INTERROG_DAY

    if game.bazpors_narrator_step == NO_HOST_INTERROG_DAY:
        return
    from bot.no_host_night_common import no_host_night_wait_phase_active

    try:
        from bot.no_host_night_entry import (
            complete_no_host_role_night_if_already_picked,
            dispatch_all_no_host_night_entry_panels,
        )
        from bot.no_host_night_ready import no_host_parallel_night_collect_active

        if game.bazpors_narrator_step == NIGHT_START:
            await dispatch_all_no_host_night_entry_panels(bot, game, gm)
        else:
            await complete_no_host_role_night_if_already_picked(bot, game, gm)
        if no_host_parallel_night_collect_active(game):
            return
    except Exception:
        pass
    if not no_host_night_wait_phase_active(game):
        return
    try:
        from bot.no_host_night_role_dms import dispatch_no_host_role_night_panels

        await dispatch_no_host_role_night_panels(bot, game, gm)
    except Exception:
        pass
    try:
        from bot.no_host_detective_night import (
            dispatch_no_host_detective_night_panel,
            flush_no_host_detective_result_pending,
        )

        await dispatch_no_host_detective_night_panel(bot, game, gm)
        await flush_no_host_detective_result_pending(bot, game, gm)
    except Exception:
        pass
    try:
        from bot.no_host_doctor_night import dispatch_no_host_doctor_night_panel

        await dispatch_no_host_doctor_night_panel(bot, game, gm)
    except Exception:
        pass
    try:
        from bot.no_host_sniper_night import (
            dispatch_no_host_sniper_night_panel,
            flush_no_host_sniper_result_pending,
        )

        await dispatch_no_host_sniper_night_panel(bot, game, gm)
        await flush_no_host_sniper_result_pending(bot, game, gm)
    except Exception:
        pass
    try:
        from bot.no_host_shiad_night import (
            dispatch_no_host_shiad_night_panel,
            flush_no_host_shiad_result_pending,
        )

        await dispatch_no_host_shiad_night_panel(bot, game, gm)
        await flush_no_host_shiad_result_pending(bot, game, gm)
    except Exception:
        pass
    try:
        from bot.no_host_journalist_night import (
            dispatch_no_host_journalist_night_panel,
            flush_no_host_journalist_result_pending,
        )

        await dispatch_no_host_journalist_night_panel(bot, game, gm)
        await flush_no_host_journalist_result_pending(bot, game, gm)
    except Exception:
        pass


def _host_message_with_optional_flush(game: Game, text: str) -> str:
    """یادداشت یک‌بارمصرف گرداننده — در مرحلهٔ پزشک به متن اضافه نمی‌شود."""
    note = game.bazpors_host_flush_note
    if not note or not note.strip():
        return text
    if game.bazpors_narrator_step in (
        ASK_NIGHT_EXTRA,
        CITIZEN_WIN_GATE,
        MAFIA_TIE_GATE,
    ):
        game.bazpors_host_flush_note = None
        return text
    if (
        game.bazpors_narrator_step == NIGHT_ACTIONS
        and game.bazpors_night_substep == NS_DOC
    ):
        return text
    game.bazpors_host_flush_note = None
    return note + "\n\n" + text


async def begin_narrator_assist_after_roles_dealt(
    bot: Bot, game: Game, gm: GameManager
) -> None:
    start_after_deal(game)
    await push_host_step(bot, game, gm)


def preserve_night_end_host_message(step_before: str | None, act: str) -> bool:
    """پیام گزارش شب (بدون دکمه) بعد از انتخاب گزینهٔ بعدی حذف نشود."""
    if step_before != ASK_NIGHT_EXTRA:
        return False
    return bool(act)


async def refresh_host_message_after_callback(
    bot: Bot,
    game: Game,
    gm: GameManager,
    *,
    edit_in_place: Message | None = None,
) -> None:
    """پنل دستیار — به گرداننده یا کمک‌کنندهٔ no_host (نه broadcast به بازیکنان)."""
    from bot.no_host_interrog_day import interrog_day_session_wait_locked

    if interrog_day_session_wait_locked(game):
        return
    if not narrator_panel_receives_updates(game) or not game.bazpors_narrator_step:
        return
    if game.bazpors_night_report_html:
        await deliver_observer_night_end_report(bot, game, gm)
    assistant_new_only = no_host_assistant_narrator_active(game)
    from bot.no_host_handoff import (
        NO_HOST_HANDOFF_OFFER,
        deliver_no_host_handoff_offer_panels,
    )

    if game.bazpors_narrator_step == NO_HOST_HANDOFF_OFFER:
        await deliver_no_host_handoff_offer_panels(bot, game, gm)
        await _run_post_host_panel_side_effects(bot, game, gm)
        return
    if not await _deliver_current_host_panel(
        bot,
        game,
        gm,
        edit_in_place=None if assistant_new_only else edit_in_place,
        force_new_message=assistant_new_only,
    ):
        return
    await _run_post_host_panel_side_effects(bot, game, gm)


def begin_no_host_day1_defense_pick(game: Game) -> None:
    """آماده‌سازی پنل چندگزینه‌ای دفاعیهٔ پایان روز (no_host، بدون پنل گرداننده)."""
    game.no_host_day1_defense_active = True
    game.no_host_day1_defense_phase = "pick"
    set_day_vote_pick_uids(game, set())
    set_day_vote_defender_uids(game, set())
    game.bazpors_day_vote_elim_reason = None


def begin_no_host_day1_vote_panel(game: Game) -> None:
    """سازگاری با نام قدیمی — همان پنل اختصاصی no_host."""
    begin_no_host_day1_defense_pick(game)


def no_host_skip_day1_vote_enter_night(game: Game) -> None:
    """ورود به شب ۱ — همان پرچم‌های نریتور کمک‌کننده که در پایان دفاعیهٔ روز اول ست می‌شوند."""
    game.no_host_assistant_narrator_active = True
    game.no_host_observer_only_narrator_mirror = True
    _enter_night_from_day_end(game)


def no_host_day1_defense_no_votes_enter_night(game: Game) -> None:
    """پایان روز اول بدون دفاعیه — ورود به شب یک برای کمک‌کننده."""
    game.no_host_day1_defense_active = False
    game.no_host_day1_defense_phase = None
    game.no_host_day1_pending_elim_uid = None
    game.no_host_assistant_narrator_active = True
    game.no_host_observer_only_narrator_mirror = True
    _enter_night_from_day_end(game)


def eliminate_player_from_game(
    game: Game,
    gm: "GameManager",
    uid: int,
    *,
    hunter_chain: bool = True,
    elim_source: str | None = "day_vote",
) -> str:
    """حذف بازیکن (برای کمک‌کننده no_host و گرداننده)."""
    if elim_source == "day_vote":
        from bot.roles.mozakere_armored import try_survive_mozakere_day_vote_elimination

        armor_note = try_survive_mozakere_day_vote_elimination(game, gm, uid)
        if armor_note is not None:
            return armor_note
    return _eliminate_player(
        game, gm, uid, hunter_chain=hunter_chain, elim_source=elim_source
    )


def no_host_day1_after_elim_enter_night(game: Game) -> None:
    """پس از حذف رأی روز اول — ورود به شب یک."""
    no_host_day1_defense_no_votes_enter_night(game)


def no_host_day1_no_exit_enter_night(game: Game) -> None:
    """پس از دفاعیه بدون خروج — ورود به شب یک."""
    no_host_day1_defense_no_votes_enter_night(game)
