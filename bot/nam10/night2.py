"""Namayande-10 fork — redesigned independent night panels (night v2).

Owns the whole fork night-panel workflow for Namayande-10 no-host rooms,
independent of the Bazpors-derived semi-auto narrator machinery:

- Mafia Boss capability menu (shot plain / shot neutralized / NATO
  once-per-game), with a safe placeholder waiting state for the future
  shooting-target rules.
- Two-step NATO guessing (role then player) with a public start
  announcement and once-per-game usage enforcement.
- Immediate Doctor cancellation (with transactional self-save rollback)
  the moment NATO mode is activated.
- Redesigned per-role selection panels with blue ``primary`` picks, green
  ``success`` toggles and explicit confirm buttons.
- Waiting-only panels (Rebel, Simple Citizen, spent Mine Layer / Lawyer).
- Collection extension: as soon as the Guide and Hacker choices are both
  confirmed the Guide's aftermath is granted — either a separate extra
  investigation panel for the selected town recipient, a private Guide
  identity notice to the selected Mafia recipient, or nothing when the
  Hacker pair intercepts the grant. The extra investigation confirmation
  is an additional readiness requirement.
- A deterministic, idempotent resolution engine: once collection is
  finished it evaluates the NATO guess (correct guess eliminates the
  target regardless of protection), computes the validity of the Doctor
  save, Miner/Guardian/Lawyer grants (skipped when the Hacker pair
  intercepts them), records the Boss shooting intent, applies an already
  validated shot intent (Doctor precedence, mine triggering /
  permanent neutralization, pending mine-casualty consequence) and
  exposes predicates for next-day Guardian armor, Lawyer defense
  immunity, extra investigation results and Rebel assassination.
  No public publication/day-transition rules run — the night stops at an
  explicit ``resolved`` boundary with ``publication_pending``.

State lives only in dedicated ``nmnd_night2_*`` Game fields, so snapshot
round-trips and old fork/Bazpors state stay untouched.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.app_state import manager
from bot.models import Game, Phase, Player, Role

from bot.observer_delivery import (
    PlayerMirrorCb,
    broadcast_to_alive_players,
    game_observer_mirror_active,
    mirror_ui_claim_key,
    no_host_observer_registered as nam10_observer_registered,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)

from bot.nam10.engine import is_synthetic_player_uid
from bot.nam10.no_host_role_pick_common import (
    build_target_button_rows,
    player_button_name,
)
from bot.nam10.role_registry import find_alive_role_holder

logger = logging.getLogger(__name__)

# -- Callback acts (PlayerMirrorCb) -----------------------------------------
ACT_BOSS_MODE = "bmode"   # Boss capability select (tid 1|2|3)
ACT_SHOT_TGT = "sht"      # Boss shot target pick (tid = player uid)
ACT_SHOT_TGT_OK = "shtok" # Boss shot target confirm
ACT_NATO_ROLE = "nrole"   # NATO stage 1 toggle (tid = guess-role index 1..5)
ACT_NATO_ROLE_OK = "nrok"
ACT_NATO_PLAYER = "npl"   # NATO stage 2 toggle (tid = player uid)
ACT_NATO_PLAYER_OK = "npok"
ACT_DOC_PICK = "docp"
ACT_DOC_OK = "docok"
ACT_SHIAD_PICK = "hacp"   # Hacker pick (stage 1 source, stage 2 destination)
ACT_SHIAD_NEXT = "hacn"   # Hacker proceed stage 1 -> stage 2 (not a confirm)
ACT_SHIAD_OK = "hacok"    # Hacker final confirm (stage 2)
ACT_GUIDE_PICK = "gdsp"
ACT_GUIDE_OK = "gdsok"
ACT_MINE_PICK = "minp"    # tid = uid, tid = 0 -> انتخابی ندارم
ACT_MINE_OK = "minok"
ACT_LAW_PICK = "lawp"     # tid = uid, tid = 0 -> انتخابی ندارم
ACT_LAW_OK = "lawok"
ACT_GUARD_PICK = "gdnp"
ACT_GUARD_OK = "gdnok"
ACT_WAIT_OK = "waitok"    # Rebel / Citizen / spent Mine / spent Lawyer acks
ACT_EXTRA_PICK = "exin"   # Guide-granted extra investigation pick
ACT_EXTRA_OK = "exok"     # Guide-granted extra investigation confirm
ACT_SOLDIER_PICK = "sldp"  # Soldier candidate toggle (tid = player uid)
ACT_SOLDIER_OK = "sldok"   # Soldier confirm
ACT_SNIPER_PICK = "tsnp"   # Temporary-Sniper target toggle
ACT_SNIPER_OK = "tsnok"    # Temporary-Sniper shot confirm
ACT_SNIPER_SKIP = "tsns"   # Temporary-Sniper voluntary skip (no charge return)

# کمک‌کنندهٔ ربات — اتمام اجباری شب (فقط کمک‌کننده؛ نام بازیکن ندارد)
ACT_FORCE_BTN = "n2fft"    # دکمهٔ «اتمام شب» → پنل تأیید
ACT_FORCE_YES = "n2ffy"    # ✅ بله، اتمام شب
ACT_FORCE_NO = "n2ffn"     # ❌ انصراف

from bot.nam10.rebel_day import NAM10_REBEL_ACTS

NIGHT2_ACTS = frozenset(
    {
        ACT_BOSS_MODE,
        ACT_SHOT_TGT,
        ACT_SHOT_TGT_OK,
        ACT_NATO_ROLE,
        ACT_NATO_ROLE_OK,
        ACT_NATO_PLAYER,
        ACT_NATO_PLAYER_OK,
        ACT_DOC_PICK,
        ACT_DOC_OK,
        ACT_SHIAD_PICK,
        ACT_SHIAD_NEXT,
        ACT_SHIAD_OK,
        ACT_GUIDE_PICK,
        ACT_GUIDE_OK,
        ACT_MINE_PICK,
        ACT_MINE_OK,
        ACT_LAW_PICK,
        ACT_LAW_OK,
        ACT_GUARD_PICK,
        ACT_GUARD_OK,
        ACT_WAIT_OK,
        ACT_EXTRA_PICK,
        ACT_EXTRA_OK,
        ACT_SOLDIER_PICK,
        ACT_SOLDIER_OK,
        ACT_SNIPER_PICK,
        ACT_SNIPER_OK,
        ACT_SNIPER_SKIP,
        ACT_FORCE_BTN,
        ACT_FORCE_YES,
        ACT_FORCE_NO,
    }
    | NAM10_REBEL_ACTS
)

# Legacy fork-night act tokens that v2 rooms must never process (stale).
NIGHT2_LEGACY_ACTS = frozenset(
    {
        "nwok", "cic", "ruc",
        "sgt", "sgc", "sgb",
        "ndp", "ndc", "ndb",
        "dkt", "dkn", "dkc", "dkb", "dko", "dkng",
        "skt", "skn", "skc", "skb",
        "jic", "jrp", "jrc", "jrb",
        "nii1", "nii1s", "nii2", "nii2a", "nii2r", "niisk",
        "hnp", "hns", "hnc", "hnb",
        "nms", "nmy", "nmn", "nmc", "nmb", "nmg",
        "msk", "msc", "msb",
        "ysp", "ysc", "ysb", "ycp", "ycc", "ycb",
        "n1c", "n1b", "n2p", "n2c", "n2b",
    }
)

# NATO guess roles: exactly five citizen-side role types, internal values.
N2_NATO_GUESS_ROLES: tuple[Role, ...] = (
    Role.DOCTOR,
    Role.INTERROGATOR,
    Role.HUNTER,
    Role.DETECTIVE,
    Role.RUINTAN,
)

N2_STEP_WAIT = "night2_wait"
N2_MAX_SELF_SAVES = 2

ALERT_STALE = "این مرحله دیگر فعال نیست."
ALERT_FORBIDDEN = "شما مجاز به این عمل نیستید."
ALERT_INVALID = "نامعتبر."
ALERT_ALREADY = "قبلاً ثبت شده است."
ALERT_GUIDE_NATO_REMOVED = "این نقش دیگر برای حدس ناتو در دسترس نیست."

PENDING_COLLECTING = "collecting"
PENDING_COLLECTED = "collected"
PENDING_RESOLVED = "resolved"

HACKER_STAGE_SRC = "src"
HACKER_STAGE_DST = "dst"
HACKER_STAGE_DONE = "done"

EXTRA_KIND_SENT = "extra_sent"
EXTRA_KIND_INTERCEPTED = "intercepted"
EXTRA_KIND_MAFIA_ID = "mafia_id"
EXTRA_KIND_DEAD = "recipient_dead"

INVEST_POSITIVE = "positive"
INVEST_NEGATIVE = "negative"

ELIM_CAUSE_NATO = "nato_correct_guess"
ELIM_CAUSE_MAFIA_SHOT = "mafia_shot"
ELIM_CAUSE_REBEL_ASSASSIN = "rebel_assassination"
ELIM_CAUSE_REBEL_ASSASSIN_SELF = "rebel_assassination_self"
ELIM_CAUSE_MINE_MAFIA = "mine_mafia"

BOSS_MODE_SHOT_PLAIN = "shot_plain"
BOSS_MODE_SHOT_NEUTRALIZED = "shot_neutralized"
BOSS_MODE_NATO = "nato"

# Shot-mode labels (no emoji) used by shot panels/confirmations.
N2_BOSS_MODE_LABELS = {
    BOSS_MODE_SHOT_PLAIN: "شات بدون خنثی‌سازی",
    BOSS_MODE_SHOT_NEUTRALIZED: "شات به همراه خنثی‌سازی",
    BOSS_MODE_NATO: "ناتویی",
}

BOSS_PHASE_MENU = "menu"
BOSS_PHASE_SHOT_TARGET = "shot_target"  # shooting targets being picked
BOSS_PHASE_SHOT_PENDING = "shot_pending"
BOSS_PHASE_NATO_ROLE = "nato_role"
BOSS_PHASE_NATO_PLAYER = "nato_player"
BOSS_PHASE_DONE = "done"


def _audit(game: Game, event: str, **data) -> None:
    try:
        from bot.game_audit_log import log_event

        log_event(game, event, **data)
    except Exception:
        pass


def _fa(n: int) -> str:
    from bot.text_fa import fa_digits

    return fa_digits(n)


def _seat_fa(n: int | None) -> str:
    if n is None:
        return "—"
    return _fa(int(n))


def nam10_night2_mode(game: Game) -> bool:
    return bool(getattr(game, "nmnd_night2_mode", False))


def night2_act_active(game: Game, act: str) -> bool:
    return nam10_night2_mode(game) and act in NIGHT2_ACTS


def night2_legacy_act_blocked(game: Game, act: str) -> bool:
    if not nam10_night2_mode(game):
        return False
    if act in NIGHT2_ACTS:
        return False
    return act in NIGHT2_LEGACY_ACTS


# ---------------------------------------------------------------------------
# UI keys
# ---------------------------------------------------------------------------


def _ui_key(game: Game, prefix: str, uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, prefix, uid)


def _boss_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2boss", uid)


def _doc_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2doc", uid)


def _shiad_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2shiad", uid)


def _guide_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2guide", uid)


def _guard_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2guard", uid)


def _mine_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2mine", uid)


def _law_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2law", uid)


def _rebel_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2rebel", uid)


def _citizen_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2citizen", uid)


def _extra_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2extra", uid)


def _soldier_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2soldier", uid)


def _sniper_key(game: Game, uid: int) -> str:
    return _ui_key(game, "n2sniper", uid)


def _night2_panel_available(game: Game, key: str) -> bool:
    """True وقتی پنل با موفقیت به بازیکن یا آینهٔ ناظر تحویل شده است.

    مرجع‌های delivery فقط پس از ارسال موفق تلگرام ثبت می‌شوند؛ خرابی
    ارسال یعنی پنل در دسترس نبوده و مسیر امن (بدون جریمه) اجرا می‌شود.
    """
    entry = game.mirror_prompt_messages.get(key) or {}
    return bool(entry.get("player") or entry.get("observer"))


# ---------------------------------------------------------------------------
# Shared panel helpers
# ---------------------------------------------------------------------------


def _custom_display_name(uid: int) -> str | None:
    """Custom /myname name for uid (production singleton manager).

    The bot runs a single GameManager (bot.app_state.manager); night-2
    panel helpers are spread across sync/async subroutines without a
    uniform gm parameter, so the display-name dict is read from the
    singleton lazily.
    """
    from bot.app_state import custom_display_name

    return custom_display_name(uid)


def _button_label(game: Game, p: Player | None, uid: int) -> str:
    """Seat + display name for every nam10 night2 target panel.

    ``player_button_name`` keeps /myname custom-name priority. Synthetic
    players keep their role suffix (``رضا-هکر``) — it is part of full_name
    and must survive selection/confirmation/multi-stage panels. The suffix
    is never appended here, so it can never be duplicated. Real players'
    names stay role-free.
    """
    if p is None:
        return html.escape(str(uid))
    name = player_button_name(p, uid, _custom_display_name(uid))
    seat = f"{_seat_fa(p.seat)} — " if p.seat is not None else ""
    return html.escape(f"{seat}{name}"[:40])


def _may_act(game: Game, actor_uid: int, owner_uid: int) -> bool:
    if actor_uid == owner_uid:
        return True
    return bool(
        is_synthetic_player_uid(owner_uid)
        and game_observer_mirror_active(game)
        and game.observer_user_id == actor_uid
    )


async def _publish_panel(
    bot: Bot,
    game: Game,
    owner_uid: int,
    key: str,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    """Player panel + Observer mirror; synthetic seats are observer-only.

    First call per key registers fresh messages; later calls update the
    existing live panel pair (button re-render / finalization).
    """
    if key in game.mirror_prompt_messages:
        await _update_panel(bot, game, owner_uid, key, text, kb)
        return
    await register_mirror_prompt_pair(
        bot,
        game,
        owner_uid,
        key,
        text,
        kb,
        send_player=True,
        send_observer=nam10_observer_registered(game)
        or is_synthetic_player_uid(owner_uid),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def _update_panel(
    bot: Bot,
    game: Game,
    owner_uid: int,
    key: str,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    """Update an already-registered v2 panel pair (never creates)."""
    await update_mirror_prompt_pair(
        bot,
        game,
        key,
        text,
        kb,
        assistant_uid=owner_uid,
        parse_mode="HTML",
    )


def _confirm_kb(game: Game, act: str, owner_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=act, as_uid=owner_uid
                    ).pack(),
                    style="success",
                )
            ]
        ]
    )


def _player_rows(
    game: Game,
    owner_uid: int,
    pick_act: str,
    pool: list[Player],
    selected: list[int] | int,
) -> list[list[InlineKeyboardButton]]:
    sel = [selected] if isinstance(selected, int) else list(selected)
    return build_target_button_rows(
        game,
        as_uid=owner_uid,
        pick_act=pick_act,
        players=pool,
        selected_uids=sel,
    )


# ---------------------------------------------------------------------------
# Eligibility pools
# ---------------------------------------------------------------------------


def _alive_players(game: Game) -> list[Player]:
    out = [p for p in game.players.values() if p.is_alive]
    out.sort(key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id))
    return out


def _holder(game: Game, role: Role) -> Player | None:
    for p in _alive_players(game):
        if p.role == role and not getattr(p, "nmnd_converted_by_yakuza", False):
            return p
    return None


def _is_mafia_member(game: Game, p: Player) -> bool:
    from bot.game import is_mafia_team

    if is_mafia_team(p.role):
        return True
    if getattr(p, "nmnd_converted_by_yakuza", False):
        return True
    return p.user_id in (game.nmnd_mafia_recruit_ids or [])


def _is_simple_citizen(game: Game, p: Player) -> bool:
    return p.role == Role.CITIZEN and not _is_mafia_member(game, p)


def _is_simple_rebel(game: Game, p: Player) -> bool:
    return p.role == Role.NATO


def night2_active_shooter(game: Game) -> Player | None:
    """Authorized Mafia night shooter for Night v2.

    Priority over living players: Mafia Boss → Rebel (Yaghi) → Hacker —
    the same order the legacy chooser uses. Only the first eligible
    living player is the authorised shooter. NATO is a shared
    Mafia-team lifetime allowance: the current shooter may use it until
    it is used once in the game, and the allowance never resets on
    shooter succession. The same holds for the neutralized-shot
    allowance. Returns None when nobody may shoot this night.
    """
    boss = _holder(game, Role.MAFIA_BOSS)
    if boss is not None:
        return boss
    rebel = _holder(game, Role.NATO)
    if rebel is not None:
        return rebel
    shiad = _holder(game, Role.SHIAD)
    if shiad is not None:
        return shiad
    # Legacy fallback ("وگرنه اولین مافیا"): when the whole named chain
    # is dead, the first living Mafia-team member in seat order inherits
    # the shot — e.g. the independent NATO agent (Room 48, Night 3).
    # Yakuza-converted players and mafia recruits count as Mafia-team
    # members; None is returned only when nobody on the Mafia team is
    # alive (then the variant's legitimate no-shooter resolution applies).
    for p in _alive_players(game):
        if _is_mafia_member(game, p):
            return p
    return None


def _shooter_is_rebel(game: Game) -> bool:
    shooter = night2_active_shooter(game)
    return shooter is not None and shooter.role == Role.NATO


def _town_members(game: Game) -> list[Player]:
    return [p for p in _alive_players(game) if not _is_mafia_member(game, p)]


# ---------------------------------------------------------------------------
# Readiness: authoritative pending set, order independent
# ---------------------------------------------------------------------------


def _acked_uids(game: Game, key: str) -> list[int]:
    return list(game.nmnd_night2_waiting_acked.get(key, []))


def night2_required_keys(game: Game) -> list[str]:
    """Authoritative set of role keys that still owe an action/ack."""
    keys: list[str] = []
    nc = int(game.nmnd_narrator_night_count or 0)

    nato_independent_pending = _nato_independent_mode_pending(game)
    shooter = night2_active_shooter(game)
    if shooter is not None and shooter.role != Role.SHIAD:
        # Shooter succession (Boss → Rebel): the shooter's role key means
        # the shooting obligation (phase-driven); for the Rebel it
        # replaces the waiting acknowledgement. During the independent
        # NATO stages (12/13) the shooter is only waiting for the NATO
        # agent, who owes the readiness key instead.
        if (
            game.nmnd_night2_boss_phase != BOSS_PHASE_DONE
            and not nato_independent_pending
        ):
            keys.append(shooter.role.value)
    elif (
        shooter is None
        and _holder(game, Role.MAFIA_BOSS) is not None
        and game.nmnd_night2_boss_phase != BOSS_PHASE_DONE
        and not nato_independent_pending
    ):
        keys.append(Role.MAFIA_BOSS.value)

    doc = _holder(game, Role.DOCTOR)
    if (
        doc is not None
        and not game.nmnd_night2_doctor_cancelled
        and game.nmnd_night2_doctor_uid is None
    ):
        keys.append(Role.DOCTOR.value)

    shiad = _holder(game, Role.SHIAD)
    if shiad is not None:
        owes_intercept = not game.nmnd_night2_hacker_uids and not (
            game.nmnd_night2_dispositions.get("hacker_none")
        )
        owes_inherited_shot = (
            night2_active_shooter(game) is shiad
            and game.nmnd_night2_boss_phase != BOSS_PHASE_DONE
            and not _nato_independent_mode_pending(game)
        )
        # A Hacker shooter owes BOTH its separate intercept action and
        # the inherited Mafia shot; one key clears only when both do.
        if owes_intercept or owes_inherited_shot:
            keys.append(Role.SHIAD.value)

    if _holder(game, Role.INTERROGATOR) is not None and (
        game.nmnd_night2_guide_uids.get(nc) is None
        and not game.nmnd_night2_dispositions.get("guide_none")
    ):
        keys.append(Role.INTERROGATOR.value)

    guard_holder = _holder(game, Role.DETECTIVE)
    if guard_holder is not None:
        if night2_guardian_exempt_after_assassin(game):
            # Exemption state: the OK acknowledgement is the Guardian's
            # night obligation, not a target selection.
            if guard_holder.user_id not in _acked_uids(
                game, Role.DETECTIVE.value
            ):
                keys.append(Role.DETECTIVE.value)
        elif (
            game.nmnd_night2_guardian_uid is None
            and not game.nmnd_night2_dispositions.get("guardian_none")
        ):
            keys.append(Role.DETECTIVE.value)

    mine = _holder(game, Role.RUINTAN)
    if mine is not None:
        if game.nmnd_night2_mine_used:
            if mine.user_id not in _acked_uids(game, Role.RUINTAN.value):
                keys.append(Role.RUINTAN.value)
        elif (
            game.nmnd_night2_mine_uid is None
            and not game.nmnd_night2_dispositions.get("mine_none")
        ):
            keys.append(Role.RUINTAN.value)

    law = _holder(game, Role.HUNTER)
    if law is not None:
        if game.nmnd_night2_lawyer_used:
            if law.user_id not in _acked_uids(game, Role.HUNTER.value):
                keys.append(Role.HUNTER.value)
        elif (
            game.nmnd_night2_lawyer_uid is None
            and not game.nmnd_night2_dispositions.get("lawyer_none")
        ):
            keys.append(Role.HUNTER.value)

    rebel = _holder(game, Role.NATO)
    if (
        rebel is not None
        and not _shooter_is_rebel(game)
        and rebel.user_id not in _acked_uids(game, Role.NATO.value)
    ):
        keys.append(Role.NATO.value)

    for p in _alive_players(game):
        if (
            _is_simple_citizen(game, p)
            and p.user_id not in _acked_uids(game, Role.CITIZEN.value)
        ):
            if Role.CITIZEN.value not in keys:
                keys.append(Role.CITIZEN.value)

    soldier = _holder(game, Role.SOLDIER)
    if soldier is not None:
        if game.nmnd_night2_soldier_used:
            # Lifetime allowance consumed: the waiting ack is a
            # later-night obligation only; in the night the charge was
            # consumed the Soldier's confirmed selection already
            # settled his obligation.
            if (
                game.nmnd_night2_soldier_used_night != nc
                and soldier.user_id
                not in _acked_uids(game, Role.SOLDIER.value)
            ):
                keys.append(Role.SOLDIER.value)
        elif game.nmnd_night2_soldier_uid is None:
            # The Soldier MUST select a recipient (no skip button).
            keys.append(Role.SOLDIER.value)

    agent = _holder(game, Role.NATO_AGENT)
    if agent is not None:
        if nato_independent_pending:
            # Independent NATO stages active (12/13): the shooter's
            # handoff transferred the pending obligation to the agent,
            # who stays NOT ready until both NATO selection stages and
            # their confirmations are completed (Room 32 readiness fix).
            keys.append(Role.NATO_AGENT.value)
        elif night2_active_shooter(game) is agent:
            # Shooter succession: the inherited Mafia shot replaces the
            # waiting acknowledgement (same rule as the Rebel shooter);
            # the shooting key above already covers readiness.
            pass
        elif agent.user_id not in _acked_uids(game, Role.NATO_AGENT.value):
            keys.append(Role.NATO_AGENT.value)

    if (
        game.nmnd_night2_extra_kind == EXTRA_KIND_SENT
        and game.nmnd_night2_extra_uid is not None
        and game.nmnd_night2_extra_target_uid is None
        and not game.nmnd_night2_dispositions.get("extra_none")
    ):
        # Guide-granted additional investigation is an extra readiness
        # requirement for its recipient.
        keys.append("n2extra")

    # A pending, unsettled Soldier grant must resolve (delivered,
    # intercepted or voided) before the night may finish.
    if game.nmnd_night2_soldier_grant_status == GRANT_STATUS_PENDING:
        keys.append("n2grant")
    if (
        game.nmnd_night2_soldier_grant_status == GRANT_STATUS_DELIVERED
        and game.nmnd_night2_sniper_night == nc
        and not game.nmnd_night2_sniper_resolved
    ):
        keys.append("n2sniper")
    return keys


def night2_maybe_finish(game: Game, gm=None, *, force: bool = False) -> bool:
    """Collection boundary: persist, then run the deterministic resolution.

    ``force=True`` is exclusively the helper's force-finish path: the
    caller has already settled every outstanding readiness key.
    """
    if game.nmnd_night2_phase != PENDING_COLLECTING:
        return False
    if not force and night2_required_keys(game):
        return False
    game.nmnd_night2_phase = PENDING_COLLECTED
    _audit(
        game,
        "night2.collection_finished",
        night_count=game.nmnd_night2_night_count,
        dispositions=dict(game.nmnd_night2_dispositions),
    )
    try:
        manager.persist_snapshot(game, reason="night2_collection_finished")
    except Exception:
        pass
    # Deterministic resolution: computes outcomes, applies internal
    # eliminations (no publication) and stops at the explicit resolved
    # boundary with publication pending.
    night2_run_resolution(game)
    return True


# ---------------------------------------------------------------------------
# Entry dispatch
# ---------------------------------------------------------------------------


async def nam10_night2_entry_dispatch(bot: Bot, game: Game, gm) -> bool:
    """Take over the fork night; returns True when v2 handled the entry."""
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return False
    # First activation happens when the fork Day-1 stage machine hands the
    # room to Night 1 (``day1_night_entered``). Any later night keeps v2
    # through the persistent ``nmnd_night2_mode`` flag. Rooms that reach a
    # night by exotic legacy paths keep the old machinery untouched.
    if not game.nmnd_night2_mode and (
        game.nam10_day1_stage != "day1_night_entered"
    ):
        return False
    if game.phase == Phase.ENDED:
        return False
    nc = int(game.nmnd_narrator_night_count or 0)
    if game.nmnd_night2_mode:
        if (
            game.nmnd_night2_night_count == nc
            and game.nmnd_night2_entry_dispatched
        ):
            return True
    # Per-night surface reset (lifetime counters untouched) on every entry.
    _reset_per_night_state(game, nc)
    game.nmnd_night2_mode = True
    game.nmnd_night2_night_count = nc
    game.nmnd_night2_entry_dispatched = True
    game.nmnd_night2_phase = PENDING_COLLECTING
    game.nmnd_narrator_step = N2_STEP_WAIT

    try:
        from bot.nam10.no_host_night_sage_quote import (
            dispatch_no_host_night_sage_quotes_at_entry,
        )

        await dispatch_no_host_night_sage_quotes_at_entry(bot, game)
    except Exception as exc:  # flavour only
        logger.warning("night2: sage quotes skipped: %r", exc)

    results = await _dispatch_entry_panels(bot, game, gm)
    for err in results:
        if isinstance(err, BaseException):
            _audit(game, "night2.entry_panel_error", error=repr(err))
    try:
        manager.persist_snapshot(game, reason="night2_entry_dispatched")
    except Exception:
        pass
    _audit(
        game,
        "night2.entry_panels_dispatched",
        night_count=nc,
        pending=night2_required_keys(game),
    )

    # یادآور عمومی شب کمک‌کننده (از شب اول واقعی به بعد — هرگز در فازهای روز ۱).
    try:
        from bot.night_helper_reminder import schedule_night_helper_reminder

        schedule_night_helper_reminder(bot, game)
    except Exception as exc:
        _audit(game, "night_helper_reminder.schedule_error", error=repr(exc))
    return True


def _reset_per_night_state(game: Game, nc: int) -> None:
    """Per-night surface reset; lifetime counters untouched."""
    game.nmnd_night2_phase = PENDING_COLLECTING
    game.nmnd_night2_boss_phase = BOSS_PHASE_MENU
    game.nmnd_night2_boss_mode = None
    game.nmnd_night2_boss_shot_marked = False
    game.nmnd_night2_shot_pending_uid = None
    game.nmnd_night2_nato_announced = False
    game.nmnd_night2_nato_pending_role_idx = None
    game.nmnd_night2_nato_role = None
    game.nmnd_night2_nato_pending_uid = None
    game.nmnd_night2_nato_target_uid = None
    game.nmnd_night2_doctor_cancelled = False
    game.nmnd_night2_doctor_cancel_reason = None
    game.nmnd_night2_doctor_pending_uid = None
    game.nmnd_night2_doctor_uid = None
    game.nmnd_night2_doctor_confirmed_self = False
    game.nmnd_night2_doctor_self_before = None
    game.nmnd_night2_hacker_pending_uids = []
    game.nmnd_night2_hacker_uids = []
    game.nmnd_night2_hacker_stage = None
    game.nmnd_night2_hacker_src_pending = None
    game.nmnd_night2_hacker_dst_pending = None
    game.nmnd_night2_guide_pending_uid = None
    game.nmnd_night2_grant_decided = False
    game.nmnd_night2_extra_kind = None
    game.nmnd_night2_extra_uid = None
    game.nmnd_night2_extra_target_pending = None
    game.nmnd_night2_extra_target_uid = None
    game.nmnd_night2_extra_result = None
    game.nmnd_night2_extra_materialized = False
    game.nmnd_night2_mine_pending_uid = None
    game.nmnd_night2_mine_pending_none = False
    game.nmnd_night2_mine_uid = None
    game.nmnd_night2_mine_used_night = None
    game.nmnd_night2_lawyer_pending_uid = None
    game.nmnd_night2_lawyer_pending_none = False
    game.nmnd_night2_lawyer_uid = None
    game.nmnd_night2_lawyer_used_night = None
    game.nmnd_night2_guardian_pending_uid = None
    game.nmnd_night2_guardian_uid = None
    game.nmnd_night2_waiting_acked = {}
    game.nmnd_night2_dispositions = {}
    game.nmnd_night2_entry_dispatched = False
    # Resolution surface resets per night; durable consequences (active
    # mine, mine events, armor, lawyer immunity, rebel flags, elimination
    # records, pending mine-casualty) are never reset here.
    game.nmnd_night2_outcome = {}
    game.nmnd_night2_outcome_committed = False
    game.nmnd_night2_resolved = False
    game.nmnd_night2_resolved_night = None
    game.nmnd_night2_publication_pending = False
    game.nmnd_night2_shot_target_uid = None
    game.nmnd_night2_shot_resolved = False
    game.nmnd_night2_publication_active = False
    game.nmnd_night2_publication_stage = None
    game.nmnd_night2_mine_announced = False
    game.nmnd_night2_mine_nap_confirmed = False
    game.nmnd_night2_mine_chooser_uid = None
    game.nmnd_night2_mine_chooser_pending_uid = None
    game.nmnd_night2_mine_casualty_uid = None
    game.nmnd_night2_mine_wait_acked = []
    # Soldier / temporary-Sniper surface resets per night; the Soldier's
    # lifetime allowance (nmnd_night2_soldier_used + used-night stamp) is
    # never reset here.
    game.nmnd_night2_soldier_pending_uid = None
    game.nmnd_night2_soldier_uid = None
    game.nmnd_night2_soldier_grant_status = None
    # اتمام اجباری شب — هر شب از نو
    game.nmnd_night2_force_finished = False
    game.nmnd_night2_soldier_forfeited = False
    game.nmnd_night2_sniper_pending_uid = None
    game.nmnd_night2_sniper_target_uid = None
    game.nmnd_night2_sniper_skipped = False
    game.nmnd_night2_sniper_resolved = False
    game.nmnd_night2_sniper_result = {}
    game.nmnd_night2_sniper_night = None
    game.nmnd_night2_sniper_delivered_refs = []
    # Legacy night baseline for the established summary/report
    # machinery (farewell lines need the at-night-start aliveness).
    game.nmnd_night_discipline_kick_uid = None
    game.nmnd_alive_at_night_start = {
        uid: p.is_alive for uid, p in game.players.items()
    }


async def _dispatch_entry_panels(bot: Bot, game: Game, gm) -> list:
    """Send every role panel exactly once per night (entry)."""
    import asyncio

    coros = []
    boss = _holder(game, Role.MAFIA_BOSS)
    if boss is not None:
        if game.nmnd_night2_boss_phase == BOSS_PHASE_SHOT_TARGET:
            coros.append(_send_boss_shot_panel(bot, game, boss.user_id))
        else:
            coros.append(_send_boss_menu(bot, game, boss.user_id))
    doc = _holder(game, Role.DOCTOR)
    if doc is not None:
        if game.nmnd_night2_doctor_cancelled:
            coros.append(_send_doctor_cancelled(bot, game, doc.user_id))
        else:
            coros.append(_send_doctor_pick_panel(bot, game, doc.user_id))
    shiad = _holder(game, Role.SHIAD)
    if shiad is not None:
        coros.append(_send_shiad_panel(bot, game, shiad.user_id))
        if night2_active_shooter(game) is shiad:
            # Hacker inherited the Mafia shot: the shooting menu is a
            # second, independent obligation with its own panel/key.
            if game.nmnd_night2_boss_phase == BOSS_PHASE_SHOT_TARGET:
                coros.append(_send_boss_shot_panel(bot, game, shiad.user_id))
            else:
                coros.append(_send_boss_menu(bot, game, shiad.user_id))
    guide = _holder(game, Role.INTERROGATOR)
    if guide is not None:
        coros.append(_send_guide_panel(bot, game, guide.user_id))
    guard = _holder(game, Role.DETECTIVE)
    if guard is not None:
        if night2_guardian_exempt_after_assassin(game):
            coros.append(_send_guard_exempt_panel(bot, game, guard.user_id))
        else:
            coros.append(_send_guard_panel(bot, game, guard.user_id))
    mine = _holder(game, Role.RUINTAN)
    if mine is not None:
        if game.nmnd_night2_mine_used:
            coros.append(_send_mine_spent_panel(bot, game, mine.user_id))
        else:
            coros.append(_send_mine_panel(bot, game, mine.user_id))
    law = _holder(game, Role.HUNTER)
    if law is not None:
        if game.nmnd_night2_lawyer_used:
            coros.append(_send_law_spent_panel(bot, game, law.user_id))
        else:
            coros.append(_send_law_panel(bot, game, law.user_id))
    rebel = _holder(game, Role.NATO)
    if rebel is not None:
        if night2_active_shooter(game) is rebel:
            # Shooter succession: the inherited Mafia-shot panel replaces
            # the waiting-only panel for this night.
            if game.nmnd_night2_boss_phase == BOSS_PHASE_SHOT_TARGET:
                coros.append(_send_boss_shot_panel(bot, game, rebel.user_id))
            else:
                coros.append(_send_boss_menu(bot, game, rebel.user_id))
        else:
            coros.append(_send_rebel_wait_panel(bot, game, rebel.user_id))
    for p in _alive_players(game):
        if _is_simple_citizen(game, p):
            coros.append(_send_citizen_wait_panel(bot, game, p.user_id))
    # Recovery/re-entry: re-render an owed extra investigation panel,
    # but only when the obligation was already materialized before the
    # interruption (an undecided/unmaterialized grant must not appear).
    if (
        game.nmnd_night2_extra_kind == EXTRA_KIND_SENT
        and game.nmnd_night2_extra_materialized
        and game.nmnd_night2_extra_uid is not None
        and game.nmnd_night2_extra_target_uid is None
    ):
        coros.append(
            _send_extra_investigation_panel(
                bot, game, game.nmnd_night2_extra_uid
            )
        )
    soldier = _holder(game, Role.SOLDIER)
    if soldier is not None:
        if game.nmnd_night2_soldier_used:
            coros.append(_send_soldier_spent_panel(bot, game, soldier.user_id))
        else:
            coros.append(_send_soldier_panel(bot, game, soldier.user_id))
    agent = _holder(game, Role.NATO_AGENT)
    if agent is not None:
        if _nato_independent_mode_pending(game):
            # Independent NATO stages are owned by the NATO agent.
            if game.nmnd_night2_boss_phase == BOSS_PHASE_NATO_ROLE:
                coros.append(_send_nato_role_panel(bot, game, agent.user_id))
            else:
                coros.append(_send_nato_player_panel(bot, game, agent.user_id))
        elif night2_active_shooter(game) is agent:
            # Shooter succession: the inherited Mafia-shot panel replaces
            # the waiting-only panel for this night (Room 48, Night 3).
            if game.nmnd_night2_boss_phase == BOSS_PHASE_SHOT_TARGET:
                coros.append(_send_boss_shot_panel(bot, game, agent.user_id))
            else:
                coros.append(_send_boss_menu(bot, game, agent.user_id))
        else:
            coros.append(_send_nato_agent_wait_panel(bot, game, agent.user_id))
    # Recovery/re-entry: re-render the temporary-Sniper panel when the
    # grant was already delivered and the shot/skip is still owed.
    if (
        game.nmnd_night2_soldier_grant_status == GRANT_STATUS_DELIVERED
        and game.nmnd_night2_sniper_night
        == int(game.nmnd_narrator_night_count or 0)
        and not game.nmnd_night2_sniper_resolved
        and game.nmnd_night2_soldier_uid is not None
    ):
        coros.append(_send_sniper_panel(bot, game, game.nmnd_night2_soldier_uid))
    return list(await asyncio.gather(*coros, return_exceptions=True)) if coros else []


# ---------------------------------------------------------------------------
# Panel senders
# ---------------------------------------------------------------------------


async def _send_boss_menu(bot: Bot, game: Game, uid: int) -> None:
    key = _boss_key(game, uid)
    shooter = night2_active_shooter(game)
    is_boss_shooter = shooter is not None and shooter.role == Role.MAFIA_BOSS
    # NATO is a shared Mafia-team lifetime allowance: the current shooter
    # (Boss, Rebel or Hacker) may pick it until it is used once in the
    # game; the allowance never resets on shooter succession.
    spent_nato = game.nmnd_night2_nato_used
    # The neutralized shot is a lifetime once-per-game Mafia-team
    # allowance: once its allowance is consumed the option must not be
    # offered again, regardless of who the current shooter is.
    spent_neutral = bool(game.nmnd_night2_boss_neutral_shot_used)
    modes = [
        (1, "🎯 شات بدون خنثی‌سازی", BOSS_MODE_SHOT_PLAIN),
        (2, "🎯 شات به همراه خنثی‌سازی", BOSS_MODE_SHOT_NEUTRALIZED),
        (3, "🎭 ناتویی", BOSS_MODE_NATO),
    ]
    rows = [
        InlineKeyboardButton(
            text=label,
            callback_data=PlayerMirrorCb(
                code=game.room_code, act=ACT_BOSS_MODE, as_uid=uid, tid=tid
            ).pack(),
            style="primary",
        )
        for tid, label, _mode in modes
        if not (
            (spent_nato and _mode == BOSS_MODE_NATO)
            or (spent_neutral and _mode == BOSS_MODE_SHOT_NEUTRALIZED)
            or (
                _mode == BOSS_MODE_NATO
                and _nato_agent_dealt(game)
                and _holder(game, Role.NATO_AGENT) is None
            )
        )
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[[b] for b in rows])
    if is_boss_shooter:
        body = (
            "<b>🔴 انتخاب قابلیت رئیس مافیا</b>\n\n"
            "لطفاً قابلیت موردنظر خود را برای این شب از گزینه‌های زیر انتخاب کنید."
        )
    else:
        body = (
            "<b>🔴 انتخاب شات مافیا — جانشین رئیس مافیا</b>\n\n"
            "قابلیت شات تیم مافیا پس از خارج شدن رئیس مافیا در اختیار شماست.\n"
            "لطفاً نوع شات موردنظر خود را برای این شب انتخاب کنید."
        )
    await _publish_panel(bot, game, uid, key, body, kb)


SHOT_PANEL_MARK = "انتخاب هدف شات"


async def _send_boss_shot_panel(bot: Bot, game: Game, uid: int) -> None:
    """Single-target shooting panel for the selected Boss shot mode."""
    key = _boss_key(game, uid)
    mode = game.nmnd_night2_boss_mode
    mode_label = N2_BOSS_MODE_LABELS.get(mode) or "؟"
    pending = game.nmnd_night2_shot_pending_uid
    rows: list[list[InlineKeyboardButton]] = []
    for p in _alive_players(game):
        selected = p.user_id == pending
        # Colour normalisation: no faction-based distinction — every
        # eligible target starts blue; only the selected one is red.
        style = "danger" if selected else "primary"
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_label(game, p, p.user_id),
                    style=style,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act=ACT_SHOT_TGT,
                        as_uid=uid,
                        tid=p.user_id,
                    ).pack(),
                )
            ]
        )
    rows.append(_confirm_row(game, uid, ACT_SHOT_TGT_OK))
    body = (
        f"<b>{SHOT_PANEL_MARK}</b>\n\n"
        f"نوع شات: <b>{html.escape(mode_label)}</b>\n\n"
        "بازیکنی را که می‌خواهید هدف شات قرار دهید انتخاب کنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def _act_shot_target(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    shooter = night2_active_shooter(game)
    if shooter is None or shooter.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if game.nmnd_night2_boss_phase != BOSS_PHASE_SHOT_TARGET:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if game.nmnd_night2_boss_mode not in (
        BOSS_MODE_SHOT_PLAIN,
        BOSS_MODE_SHOT_NEUTRALIZED,
    ):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if tid not in {p.user_id for p in _alive_players(game)}:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_shot_pending_uid == tid:
        game.nmnd_night2_shot_pending_uid = None
    else:
        game.nmnd_night2_shot_pending_uid = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_boss_shot_panel(bot, game, uid)


async def _act_shot_target_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    shooter = night2_active_shooter(game)
    if shooter is None or shooter.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if game.nmnd_night2_boss_phase != BOSS_PHASE_SHOT_TARGET:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    target = game.nmnd_night2_shot_pending_uid
    if not target:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    # Re-validate eligibility on confirmation, not only when rendering.
    tpl = game.players.get(target)
    if (
        tpl is None
        or not tpl.is_alive
        or game.nmnd_night2_boss_mode
        not in (BOSS_MODE_SHOT_PLAIN, BOSS_MODE_SHOT_NEUTRALIZED)
    ):
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    game.nmnd_night2_shot_target_uid = target
    game.nmnd_night2_shot_pending_uid = None
    game.nmnd_night2_boss_shot_marked = True
    # Confirmed neutralized shot consumes its lifetime allowance exactly
    # once — regardless of the eventual resolution (Doctor protection,
    # mine, armor). Never reset by the per-night reset; a later night's
    # menu no longer offers it and replayed mode callbacks are rejected.
    if (
        game.nmnd_night2_boss_mode == BOSS_MODE_SHOT_NEUTRALIZED
        and not game.nmnd_night2_boss_neutral_shot_used
    ):
        game.nmnd_night2_boss_neutral_shot_used = True
        game.nmnd_night2_boss_neutral_shot_used_night = (
            game.nmnd_night2_night_count
        )
        _audit(
            game,
            "night2.boss_neutral_shot_consumed",
            boss_uid=uid,
            target_uid=target,
            night=game.nmnd_night2_night_count,
        )
    game.nmnd_night2_boss_phase = BOSS_PHASE_DONE
    game.nmnd_night2_dispositions[f"boss_mode:{uid}"] = (
        game.nmnd_night2_boss_mode
    )
    _audit(
        game,
        "night2.shot_target_confirmed",
        mode=game.nmnd_night2_boss_mode,
        target_uid=target,
        boss_uid=uid,
    )
    mode_label = N2_BOSS_MODE_LABELS.get(game.nmnd_night2_boss_mode) or "؟"
    await callback.answer("ثبت شد.")
    await _update_panel(
        bot,
        game,
        uid,
        _boss_key(game, uid),
        "<b>✅ انتخاب شات شما ثبت شد.</b>\n\n"
        f"نوع شات: <b>{html.escape(mode_label)}</b>\n"
        "بازیکن انتخاب‌شده: "
        f"{_button_label(game, tpl, target)}",
        None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_shot_target_confirmed")
    except Exception:
        pass
    # ONE private notification to the other authorised Mafia teammates
    # (committed shot only; no outcome disclosure, no buttons).
    from bot.nam10.mafia_team_notify import (
        build_shot_notification_text,
        notify_mafia_teammates,
        plain_player_name,
    )

    shot_mode_text = (
        "با خنثی‌سازی"
        if game.nmnd_night2_boss_mode == BOSS_MODE_SHOT_NEUTRALIZED
        else "بدون خنثی‌سازی"
    )
    try:
        await notify_mafia_teammates(
            bot,
            game,
            build_shot_notification_text(
                shot_mode_text,
                plain_player_name(game.players.get(target), target),
            ),
            exclude_uid=uid,
            event="night2.shot_teammates_notified",
        )
    except Exception:
        logger.exception(
            "shot teammate notification failed room=%s", game.room_code
        )
    night2_maybe_finish(game, gm)
    # Mafia main actions settled: the delayed Guide-identity notice may
    # now deliver (idempotent; no-op while any obligation remains).
    await night2_maybe_grant_guide_extra(bot, game)


async def _send_nato_role_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _nato_stage_key(game, uid)
    pending = game.nmnd_night2_nato_pending_role_idx
    rows: list[list[InlineKeyboardButton]] = []
    from bot.nam10.role_labels import nam10_role_label_fa

    for idx, role in enumerate(N2_NATO_GUESS_ROLES, start=1):
        # Guide-identity restriction: once the Guide's identity was
        # successfully disclosed to a Mafia member, راهنما is no longer
        # offered (the original tid indices stay stable so forged or
        # stale callbacks remain individually rejectable).
        if (
            role is Role.INTERROGATOR
            and game.namayande_guide_identity_revealed_to_mafia
        ):
            continue
        cb = PlayerMirrorCb(
            code=game.room_code, act=ACT_NATO_ROLE, as_uid=uid, tid=idx
        ).pack()
        rows.append(
            [
                InlineKeyboardButton(
                    text=nam10_role_label_fa(role),
                    callback_data=cb,
                    style="danger" if pending == idx else "primary",
                )
            ]
        )
    rows.append(_confirm_row(game, uid, ACT_NATO_ROLE_OK))
    body = (
        "<b>🎭 ناتویی — انتخاب نقش</b>\n\n"
        "قصد دارید نقش کدام بازیکن را حدس بزنید؟\n\n"
        "لطفاً یکی از نقش‌های شهروندی زیر را انتخاب و تأیید کنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def _send_nato_player_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _nato_stage_key(game, uid)
    from bot.nam10.role_labels import nam10_role_label_fa

    role_name = ""
    if game.nmnd_night2_nato_role:
        try:
            role_name = nam10_role_label_fa(Role(game.nmnd_night2_nato_role))
        except ValueError:
            role_name = "؟"
    pool = _town_members(game)
    pending = game.nmnd_night2_nato_pending_uid
    rows = _player_rows(
        game, uid, ACT_NATO_PLAYER, pool, [pending] if pending else []
    )
    rows.append(_confirm_row(game, uid, ACT_NATO_PLAYER_OK))
    body = (
        "<b>🎭 ناتویی — انتخاب بازیکن</b>\n\n"
        f"نقش انتخاب‌شده: <b>{html.escape(role_name)}</b>\n\n"
        "اکنون بازیکنی را که تصور می‌کنید دارای نقش "
        f"<b>{html.escape(role_name)}</b> است، از فهرست زیر انتخاب کنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


DOC_CANCEL_BODY = (
    "<b>💉 پزشک — لغو اقدام شب</b>\n\n"
    "به دلیل اجرای ناتویی توسط تیم مافیا، "
    "امشب انتخابی برای شما ثبت نخواهد شد."
)


async def _send_doctor_cancelled(bot: Bot, game: Game, uid: int) -> None:
    await _publish_panel(
        bot, game, uid, _doc_key(game, uid), DOC_CANCEL_BODY, None
    )


async def _send_doctor_pick_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _doc_key(game, uid)
    # Once both lifetime self-save charges are consumed, the «خودم»
    # option must not be rendered at all (forged selections are still
    # rejected server-side; a valid NATO rollback restores the option).
    self_exhausted = (
        int(game.nmnd_night2_doctor_self_saves or 0) >= N2_MAX_SELF_SAVES
    )
    pool = [
        pl
        for pl in _alive_players(game)
        if not (self_exhausted and pl.user_id == uid)
    ]

    def label(pl: Player) -> str:
        if pl.user_id == uid:
            return "خودم"
        return _button_label(game, pl, pl.user_id)

    pend = game.nmnd_night2_doctor_pending_uid
    rows = build_target_button_rows(
        game,
        as_uid=uid,
        pick_act=ACT_DOC_PICK,
        players=pool,
        selected_uids=[pend] if pend else [],
        label_for_player=label,
    )
    rows.append(_confirm_row(game, uid, ACT_DOC_OK))
    body = (
        "<b>💉 انتخاب پزشک</b>\n\n"
        "هر شب می‌توانید یک بازیکن را نجات دهید.\n\n"
        f"<b>نجات خود: {_fa(int(game.nmnd_night2_doctor_self_saves or 0))} "
        "از ۲ بار استفاده‌شده</b>\n\n"
        "یک بازیکن را انتخاب و تأیید کنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


def _confirm_row(game: Game, uid: int, act: str) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text="✅ تأیید",
            callback_data=PlayerMirrorCb(
                code=game.room_code, act=act, as_uid=uid
            ).pack(),
            style="success",
        )
    ]


async def _send_shiad_panel(bot: Bot, game: Game, uid: int) -> None:
    """Hacker two sequential panels: stage 1 ability source (town player
    whose ability may be disrupted), stage 2 destination (town player against
    whom the source's ability becomes ineffective). Same-UID source=dest
    allowed; both stages exclude Mafia members (the Hacker is Mafia)."""
    key = _shiad_key(game, uid)
    stage = game.nmnd_night2_hacker_stage or HACKER_STAGE_SRC
    pool = _town_members(game)
    if stage == HACKER_STAGE_SRC:
        pend = game.nmnd_night2_hacker_src_pending
        rows = _player_rows(
            game, uid, ACT_SHIAD_PICK, pool, [pend] if pend else []
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏭️ مرحله بعد",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act=ACT_SHIAD_NEXT,
                        as_uid=uid,
                    ).pack(),
                    style="success",
                )
            ]
        )
        body = (
            "<b>💻 انتخاب‌های هکر — مرحله ۱ از ۲</b>\n\n"
            "هکر هر شب می‌تواند در عملکرد یک بازیکن شهروندی اختلال ایجاد کند.\n\n"
            "لطفاً بازیکنی از تیم شهروندی را انتخاب کنید که قابلیت او ممکن است "
            "دچار اختلال شود، سپس دکمه «مرحله بعد» را بزنید."
        )
    else:
        pend = game.nmnd_night2_hacker_dst_pending
        rows = _player_rows(
            game, uid, ACT_SHIAD_PICK, pool, [pend] if pend else []
        )
        rows.append(_confirm_row(game, uid, ACT_SHIAD_OK))
        src_label = ""
        src_uid = game.nmnd_night2_hacker_src_pending
        if src_uid:
            src_label = (
                "\n\nمبدأ انتخاب‌شده: "
                f"{_button_label(game, game.players.get(src_uid), src_uid)}"
            )
        body = (
            "<b>💻 انتخاب‌های هکر — مرحله ۲ از ۲</b>\n\n"
            "لطفاً بازیکنی از تیم شهروندی را انتخاب کنید که اثر قابلیت "
            f"بازیکن مرحلهٔ قبل به او نرسد.{src_label}\n\n"
            "سپس انتخاب خود را تأیید کنید."
        )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def _send_guide_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _guide_key(game, uid)
    nc = int(game.nmnd_narrator_night_count or 0)
    prev = game.nmnd_night2_guide_uids.get(nc - 1)
    pool = [
        p
        for p in _alive_players(game)
        if p.user_id != uid and p.user_id != prev
    ]
    pend = game.nmnd_night2_guide_pending_uid
    rows = _player_rows(
        game, uid, ACT_GUIDE_PICK, pool, [pend] if pend else []
    )
    rows.append(_confirm_row(game, uid, ACT_GUIDE_OK))
    body = (
        "<b>🧭 انتخاب راهنما</b>\n\n"
        "راهنما هر شب یک بازیکن را انتخاب می‌کند.\n\n"
        "اگر بازیکن انتخاب‌شده شهروند باشد، راهنما از شهروندبودن او مطلع می‌شود.\n\n"
        "اگر بازیکن انتخاب‌شده عضو مافیا باشد، آن بازیکن متوجه خواهد شد که "
        "راهنما چه کسی است.\n\n"
        "راهنما نمی‌تواند یک بازیکن را در دو شب متوالی انتخاب کند.\n\n"
        "لطفاً یک بازیکن را انتخاب و تأیید کنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def _send_mine_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _mine_key(game, uid)
    # Game rule: the Mine Layer may never place a mine on themselves —
    # their own button is not rendered at all. Stale / already-delivered
    # keyboards and forged callbacks stay covered by the server-side
    # rejections in _act_mine_pick / _act_mine_ok.
    pool = [p for p in _alive_players(game) if p.user_id != uid]
    pend = game.nmnd_night2_mine_pending_uid
    rows = _player_rows(
        game,
        uid,
        ACT_MINE_PICK,
        pool,
        [pend] if pend else [],
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=(
                    "انتخابی ندارم ✓"
                    if game.nmnd_night2_mine_pending_none
                    else "انتخابی ندارم"
                ),
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act=ACT_MINE_PICK, as_uid=uid, tid=0
                ).pack(),
                style="danger"
                if game.nmnd_night2_mine_pending_none
                else "primary",
            )
        ]
    )
    rows.append(_confirm_row(game, uid, ACT_MINE_OK))
    body = (
        "<b>💣 انتخاب مین‌گذار</b>\n\n"
        "مین‌گذار در طول بازی یک بار می‌تواند برای محافظت از یک بازیکن، "
        "مقابل خانه او مین‌گذاری کند.\n\n"
        "اگر مافیا آن بازیکن را هدف قرار دهد، مین فعال می‌شود و نتیجه آن طبق "
        "قوانین مین‌گذار محاسبه خواهد شد.\n\n"
        "لطفاً یک بازیکن را انتخاب کنید یا گزینه «انتخابی ندارم» را بزنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


MINE_SPENT_BODY = (
    "<b>🌙 مین‌گذار</b>\n\n"
    "شما قبلاً از قابلیت مین‌گذاری خود استفاده کرده‌اید.\n\n"
    "لطفاً منتظر بمانید."
)


def _wait_ok_kb(game: Game, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ اوکی",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=ACT_WAIT_OK, as_uid=uid
                    ).pack(),
                    style="primary",
                )
            ]
        ]
    )


async def _send_mine_spent_panel(bot: Bot, game: Game, uid: int) -> None:
    await _publish_panel(
        bot, game, uid, _mine_key(game, uid), MINE_SPENT_BODY, _wait_ok_kb(game, uid)
    )


async def _send_law_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _law_key(game, uid)
    pool = [p for p in _alive_players(game) if p.user_id != uid]
    pend = game.nmnd_night2_lawyer_pending_uid
    rows = _player_rows(
        game,
        uid,
        ACT_LAW_PICK,
        pool,
        [pend] if pend else [],
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=(
                    "انتخابی ندارم ✓"
                    if game.nmnd_night2_lawyer_pending_none
                    else "انتخابی ندارم"
                ),
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act=ACT_LAW_PICK, as_uid=uid, tid=0
                ).pack(),
                style="danger"
                if game.nmnd_night2_lawyer_pending_none
                else "primary",
            )
        ]
    )
    rows.append(_confirm_row(game, uid, ACT_LAW_OK))
    body = (
        "<b>⚖️ انتخاب وکیل</b>\n\n"
        "وکیل در طول بازی یک بار می‌تواند وکالت یک بازیکن را بر عهده بگیرد.\n\n"
        "بازیکنی که تحت حمایت وکیل قرار گیرد، در روز بعد طبق قوانین این نقش "
        "از ورود به دفاعیه مصون خواهد بود.\n\n"
        "لطفاً یک بازیکن را انتخاب کنید یا گزینه «انتخابی ندارم» را بزنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


LAW_SPENT_BODY = (
    "<b>🌙 وکیل</b>\n\n"
    "شما قبلاً از قابلیت وکالت خود استفاده کرده‌اید.\n\n"
    "لطفاً منتظر بمانید."
)


async def _send_law_spent_panel(bot: Bot, game: Game, uid: int) -> None:
    await _publish_panel(
        bot, game, uid, _law_key(game, uid), LAW_SPENT_BODY, _wait_ok_kb(game, uid)
    )


async def _send_guard_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _guard_key(game, uid)
    pool = [p for p in _alive_players(game) if p.user_id != uid]
    pend = game.nmnd_night2_guardian_pending_uid
    rows = _player_rows(
        game, uid, ACT_GUARD_PICK, pool, [pend] if pend else []
    )
    rows.append(_confirm_row(game, uid, ACT_GUARD_OK))
    body = (
        "<b>🛡️ انتخاب محافظ</b>\n\n"
        "محافظ هر شب می‌تواند یک بازیکن را در برابر ترور محافظت کند.\n\n"
        "بازیکن انتخاب‌شده در روز بعد در برابر ترور دارای زره خواهد بود. "
        "خود محافظ نیز در برابر ترور ایمن است.\n\n"
        "لطفاً یک بازیکن را انتخاب و تأیید کنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )


GUARD_EXEMPT_BODY = (
    "<b>🛡️ محافظ</b>\n\n"
    "یاغی از قابلیت ترور خود استفاده کرده و از بازی خارج شده است.\n\n"
    "دیگر نیازی به انتخاب بازیکن برای محافظت نیست."
)


async def _send_guard_exempt_panel(bot: Bot, game: Game, uid: int) -> None:
    """Post-assassination waiting-only Guardian panel: no target
    selection, no armor grant; the OK counts as the Guardian's completed
    night obligation."""
    await _publish_panel(
        bot,
        game,
        uid,
        _guard_key(game, uid),
        GUARD_EXEMPT_BODY,
        _wait_ok_kb(game, uid),
    )


REBEL_WAIT_BODY = (
    "<b>🌙 انتظار برای پایان شب</b>\n\n"
    "تیم مافیا در حال انجام اقدامات شبانه است.\n\n"
    "لطفاً منتظر بمانید و آمادگی خود را تأیید کنید."
)


async def _send_rebel_wait_panel(bot: Bot, game: Game, uid: int) -> None:
    await _publish_panel(
        bot, game, uid, _rebel_key(game, uid), REBEL_WAIT_BODY, _wait_ok_kb(game, uid)
    )


CITIZEN_WAIT_BODY = (
    "<b>🌙 انتظار برای پایان شب</b>\n\n"
    "لطفاً تا پایان اقدامات شبانه منتظر بمانید.\n\n"
    "برای ثبت آمادگی خود، دکمه زیر را بزنید."
)


async def _send_citizen_wait_panel(bot: Bot, game: Game, uid: int) -> None:
    await _publish_panel(
        bot,
        game,
        uid,
        _citizen_key(game, uid),
        CITIZEN_WAIT_BODY,
        _wait_ok_kb(game, uid),
    )


NATO_ANNOUNCE_TEXT = "🎭 تیم مافیا در حال انجام ناتویی است."


# ---------------------------------------------------------------------------
# Act dispatch
# ---------------------------------------------------------------------------


async def nam10_night2_dispatch_act(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm,
    *,
    actor_uid: int,
    act: str,
    as_uid: int,
    tid: int,
) -> None:
    from bot.nam10.night_force_finish import nam10_force_finish_act_active

    if nam10_force_finish_act_active(act):
        from bot.nam10.night_force_finish import dispatch_nam10_force_finish_act

        await dispatch_nam10_force_finish_act(
            callback,
            bot,
            game,
            gm,
            actor_uid=actor_uid,
            act=act,
        )
        return
    pl = game.players.get(as_uid)
    if pl is None:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.phase == Phase.ENDED:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    from bot.nam10.night2_publish import NIGHT2_PUBLISH_ACTS

    if act in NIGHT2_PUBLISH_ACTS:
        from bot.nam10.night2_publish import (
            dispatch_night2_publish_act,
        )

        await dispatch_night2_publish_act(
            callback,
            bot,
            game,
            gm,
            actor_uid=actor_uid,
            act=act,
            as_uid=as_uid,
            tid=tid,
        )
        return
    if act in NAM10_REBEL_ACTS:
        # Daytime Rebel-assassination driver: valid during the eligible
        # day stage, so it must be dispatched before the night-collect
        # phase gate below.
        from bot.nam10.rebel_day import dispatch_nam10_rebel_act

        await dispatch_nam10_rebel_act(
            callback,
            bot,
            game,
            gm,
            actor_uid=actor_uid,
            act=act,
            as_uid=as_uid,
            tid=tid,
        )
        return
    if game.nmnd_night2_phase != PENDING_COLLECTING:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if not _may_act(game, actor_uid, as_uid):
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if not pl.is_alive:
        await callback.answer(ALERT_STALE, show_alert=True)
        return

    if act == ACT_BOSS_MODE:
        await _act_boss_mode(callback, bot, game, gm, as_uid, actor_uid, tid)
    elif act == ACT_SHOT_TGT:
        await _act_shot_target(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_SHOT_TGT_OK:
        await _act_shot_target_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_NATO_ROLE:
        await _act_nato_role(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_NATO_ROLE_OK:
        await _act_nato_role_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_NATO_PLAYER:
        await _act_nato_player(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_NATO_PLAYER_OK:
        await _act_nato_player_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_DOC_PICK:
        await _act_doc_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_DOC_OK:
        await _act_doc_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_SHIAD_PICK:
        await _act_shiad_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_SHIAD_NEXT:
        await _act_shiad_next(callback, bot, game, gm, as_uid)
    elif act == ACT_SHIAD_OK:
        await _act_shiad_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_GUIDE_PICK:
        await _act_guide_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_GUIDE_OK:
        await _act_guide_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_MINE_PICK:
        await _act_mine_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_MINE_OK:
        await _act_mine_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_LAW_PICK:
        await _act_law_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_LAW_OK:
        await _act_law_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_GUARD_PICK:
        await _act_guard_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_GUARD_OK:
        await _act_guard_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_WAIT_OK:
        await _act_wait_ok(callback, bot, game, gm, as_uid, actor_uid)
    elif act == ACT_EXTRA_PICK:
        await _act_extra_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_EXTRA_OK:
        await _act_extra_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_SOLDIER_PICK:
        await _act_soldier_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_SOLDIER_OK:
        await _act_soldier_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_SNIPER_PICK:
        await _act_sniper_pick(callback, bot, game, gm, as_uid, tid)
    elif act == ACT_SNIPER_OK:
        await _act_sniper_ok(callback, bot, game, gm, as_uid)
    elif act == ACT_SNIPER_SKIP:
        await _act_sniper_skip(callback, bot, game, gm, as_uid)
    else:
        await callback.answer(ALERT_INVALID, show_alert=True)

    # Post-resolution publication flow (Branch A / Branch B mine
    # flow). Cheap no-op while the night is still collecting.
    from bot.nam10.night2_publish import nam10_night2_publish_tick

    try:
        await nam10_night2_publish_tick(bot, game, gm)
    except Exception:
        logger.exception(
            "night2 publication tick failed room=%s", game.room_code
        )

    # Live outstanding-counter refresh on the SAME reminder message
    # (never reschedules the timer; deletes the panel at count zero).
    try:
        from bot.night_helper_reminder import refresh_night_helper_reminder

        await refresh_night_helper_reminder(bot, game)
    except Exception:
        logger.exception(
            "night helper reminder refresh failed room=%s", game.room_code
        )


async def _act_boss_mode(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm,
    uid: int,
    actor_uid: int,
    tid: int,
) -> None:
    if game.nmnd_night2_boss_phase != BOSS_PHASE_MENU:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    shooter = night2_active_shooter(game)
    if shooter is None or shooter.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if tid not in (1, 2, 3):
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if tid == 3 and game.nmnd_night2_nato_used:
        # NATO is a shared Mafia-team lifetime allowance: once used by
        # any shooter it is unavailable for every successor.
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if (
        tid == 3
        and _nato_agent_dealt(game)
        and _holder(game, Role.NATO_AGENT) is None
    ):
        # Independent NATO (12/13): the NATO agent is dead — the NATO
        # mode cannot run even while its allowance is unused.
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if tid == 2 and game.nmnd_night2_boss_neutral_shot_used:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if tid == 1:
        mode = BOSS_MODE_SHOT_PLAIN
    elif tid == 2:
        mode = BOSS_MODE_SHOT_NEUTRALIZED
    else:
        mode = BOSS_MODE_NATO

    game.nmnd_night2_boss_mode = mode
    _audit(
        game,
        "night2.boss_mode_selected",
        mode=mode,
        boss_uid=uid,
        actor_uid=actor_uid,
        shooter_role=shooter.role.value,
    )
    if mode == BOSS_MODE_NATO:
        await _activate_nato_mode(callback, bot, game, gm, uid)
        return
    # Shooting mode: single-target selection panel (no fabricated target).
    game.nmnd_night2_boss_phase = BOSS_PHASE_SHOT_TARGET
    game.nmnd_night2_shot_pending_uid = None
    await callback.answer("ثبت شد.")
    await _send_boss_shot_panel(bot, game, uid)
    try:
        manager.persist_snapshot(game, reason="night2_boss_mode")
    except Exception:
        pass
    night2_maybe_finish(game, gm)


async def _activate_nato_mode(
    callback: CallbackQuery, bot: Bot, game: Game, gm, boss_uid: int
) -> None:
    """NATO mode begins: announce once + cancel Doctor immediately."""
    if not game.nmnd_night2_nato_announced:
        game.nmnd_night2_nato_announced = True
        from bot.game import is_synthetic_player_uid as _is_syn

        await broadcast_to_alive_players(
            bot,
            game,
            NATO_ANNOUNCE_TEXT,
            parse_mode="HTML",
            is_synthetic_uid=_is_syn,
        )
        _audit(game, "night2.nato_announced", boss_uid=boss_uid)
    game.nmnd_night2_nato_used = True
    # Night stamp: only the night that actually played NATO may claim it
    # in its committed outcome/report (the flag itself is the menu gate).
    game.nmnd_night2_nato_used_night = game.nmnd_night2_night_count
    await night2_cancel_doctor_for_nato(bot, game, gm)
    game.nmnd_night2_boss_phase = BOSS_PHASE_NATO_ROLE
    game.nmnd_night2_nato_pending_role_idx = None
    await callback.answer("ثبت شد.")
    agent = _holder(game, Role.NATO_AGENT)
    if agent is not None:
        # Independent NATO (12/13): the handoff transferred the pending
        # obligation to the agent — the shooter's own interactive panel
        # is deleted so its stale buttons can never be reused.
        await _delete_panel_pair(bot, game, boss_uid, _boss_key(game, boss_uid))
    await _send_nato_role_panel(
        bot, game, agent.user_id if agent is not None else boss_uid
    )
    try:
        manager.persist_snapshot(game, reason="night2_nato_activated")
    except Exception:
        pass
    night2_maybe_finish(game, gm)


async def night2_cancel_doctor_for_nato(bot: Bot, game: Game, gm) -> bool:
    """Cancel the Doctor's current-night action (idempotent, atomic)."""
    if game.nmnd_night2_doctor_cancelled:
        return True
    had_confirmed = game.nmnd_night2_doctor_uid is not None
    had_self = game.nmnd_night2_doctor_confirmed_self
    game.nmnd_night2_doctor_cancelled = True
    game.nmnd_night2_doctor_cancel_reason = "cancelled_by_nato"
    # Transactional rollback of the confirmed action and its counters.
    if had_self and game.nmnd_night2_doctor_self_before is not None:
        game.nmnd_night2_doctor_self_saves = max(
            0, int(game.nmnd_night2_doctor_self_before)
        )
    game.nmnd_night2_doctor_uid = None
    game.nmnd_night2_doctor_confirmed_self = False
    game.nmnd_night2_doctor_pending_uid = None
    game.nmnd_night2_doctor_self_before = None
    game.nmnd_night2_dispositions[Role.DOCTOR.value] = "cancelled_by_nato"
    _audit(
        game,
        "night2.doctor_cancelled_by_nato",
        had_confirmed=had_confirmed,
        had_self=had_self,
    )
    doc = _holder(game, Role.DOCTOR)
    if doc is not None:
        key = _doc_key(game, doc.user_id)
        if key in game.mirror_prompt_messages:
            await _update_panel(
                bot, game, doc.user_id, key, DOC_CANCEL_BODY, None
            )
        else:
            await _send_doctor_cancelled(bot, game, doc.user_id)
    # A cancelled main action counts as settled for a Guide-granted
    # recipient: the extra panel may now be materialized (idempotent).
    await night2_maybe_grant_guide_extra(bot, game)
    return True


# -- NATO guess: stage 1 (role) ---------------------------------------------


async def _act_nato_role(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if game.nmnd_night2_boss_phase != BOSS_PHASE_NATO_ROLE:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    owner = _nato_stage_owner(game)
    if owner is None or owner.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if tid < 1 or tid > len(N2_NATO_GUESS_ROLES):
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if (
        game.namayande_guide_identity_revealed_to_mafia
        and N2_NATO_GUESS_ROLES[tid - 1] is Role.INTERROGATOR
    ):
        # Guide-identity restriction: forged or stale callbacks selecting
        # راهنما are rejected and consume no NATO opportunity.
        await callback.answer(ALERT_GUIDE_NATO_REMOVED, show_alert=True)
        return
    if game.nmnd_night2_nato_pending_role_idx == tid:
        game.nmnd_night2_nato_pending_role_idx = None
    else:
        game.nmnd_night2_nato_pending_role_idx = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_nato_role_panel(bot, game, uid)


async def _act_nato_role_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if game.nmnd_night2_boss_phase != BOSS_PHASE_NATO_ROLE:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    owner = _nato_stage_owner(game)
    if owner is None or owner.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    idx = game.nmnd_night2_nato_pending_role_idx
    if not idx:
        await callback.answer("ابتدا یک نقش را انتخاب کنید.", show_alert=True)
        return
    if (
        game.namayande_guide_identity_revealed_to_mafia
        and N2_NATO_GUESS_ROLES[idx - 1] is Role.INTERROGATOR
    ):
        # Defence-in-depth: a pending راهنما selection that became
        # invalid must never be confirmed; the NATO opportunity is not
        # consumed and the panel re-renders without راهنما.
        game.nmnd_night2_nato_pending_role_idx = None
        await callback.answer(ALERT_GUIDE_NATO_REMOVED, show_alert=True)
        await _send_nato_role_panel(bot, game, uid)
        return
    role = N2_NATO_GUESS_ROLES[idx - 1]
    game.nmnd_night2_nato_role = role.value
    game.nmnd_night2_nato_pending_role_idx = None
    game.nmnd_night2_boss_phase = BOSS_PHASE_NATO_PLAYER
    game.nmnd_night2_nato_pending_uid = None
    _audit(game, "night2.nato_role_confirmed", role=role.value, boss_uid=uid)
    await callback.answer("ثبت شد.")
    await _send_nato_player_panel(bot, game, uid)


def _nato_player_pool(game: Game) -> list[Player]:
    """Alive town-faction members only (authoritative current faction)."""
    return _town_members(game)


async def _act_nato_player(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if game.nmnd_night2_boss_phase != BOSS_PHASE_NATO_PLAYER:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    owner = _nato_stage_owner(game)
    if owner is None or owner.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    pool = {p.user_id for p in _nato_player_pool(game)}
    if tid not in pool:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_nato_pending_uid == tid:
        game.nmnd_night2_nato_pending_uid = None
    else:
        game.nmnd_night2_nato_pending_uid = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_nato_player_panel(bot, game, uid)


async def _act_nato_player_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    from bot.nam10.role_labels import nam10_role_label_fa
    if game.nmnd_night2_boss_phase != BOSS_PHASE_NATO_PLAYER:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    owner = _nato_stage_owner(game)
    if owner is None or owner.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    if not game.nmnd_night2_nato_pending_uid:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    target = game.nmnd_night2_nato_pending_uid
    game.nmnd_night2_nato_target_uid = target
    game.nmnd_night2_nato_pending_uid = None
    game.nmnd_night2_boss_phase = BOSS_PHASE_DONE
    _audit(
        game,
        "night2.nato_target_confirmed",
        role=game.nmnd_night2_nato_role,
        target_uid=target,
        boss_uid=uid,
    )
    await callback.answer("ثبت شد.")
    await _update_panel(
        bot,
        game,
        uid,
        _nato_stage_key(game, uid),
        "<b>✅ انتخاب ناتویی شما ثبت شد.</b>",
        None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_nato_confirmed")
    except Exception:
        pass
    # ONE private notification to the other authorised Mafia teammates
    # (only now, after role AND target are both validly confirmed —
    # covers the 10/11 shooter-controlled flow and the 12/13 separate
    # NATO-role player flow alike; no buttons, no duplicates).
    from bot.nam10.mafia_team_notify import (
        build_nato_notification_text,
        notify_mafia_teammates,
        plain_player_name,
    )

    try:
        role_label = nam10_role_label_fa(Role(str(game.nmnd_night2_nato_role)))
    except (ValueError, TypeError):
        role_label = "؟"
    try:
        await notify_mafia_teammates(
            bot,
            game,
            build_nato_notification_text(
                role_label,
                plain_player_name(game.players.get(target), target),
            ),
            exclude_uid=uid,
            event="night2.nato_teammates_notified",
        )
    except Exception:
        logger.exception(
            "nato teammate notification failed room=%s", game.room_code
        )
    night2_maybe_finish(game, gm)
    # Independent NATO settled: the delayed Guide-identity notice may
    # now deliver (idempotent; no-op while any obligation remains).
    await night2_maybe_grant_guide_extra(bot, game)


# -- Doctor -----------------------------------------------------------------


async def _act_doc_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if game.nmnd_night2_doctor_cancelled:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    doc = _holder(game, Role.DOCTOR)
    if doc is None or doc.user_id != uid or game.nmnd_night2_doctor_uid is not None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if tid not in {p.user_id for p in _alive_players(game)}:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_doctor_pending_uid == tid:
        game.nmnd_night2_doctor_pending_uid = None
    else:
        game.nmnd_night2_doctor_pending_uid = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_doctor_pick_panel(bot, game, uid)


async def _act_doc_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if game.nmnd_night2_doctor_cancelled:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    doc = _holder(game, Role.DOCTOR)
    if doc is None or doc.user_id != uid or game.nmnd_night2_doctor_uid is not None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    target = game.nmnd_night2_doctor_pending_uid
    if not target:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    self_save = target == uid
    if self_save:
        if game.nmnd_night2_doctor_self_saves >= N2_MAX_SELF_SAVES:
            await callback.answer(
                "سهمیهٔ نجات خود شما تمام شده است.", show_alert=True
            )
            return
        game.nmnd_night2_doctor_self_before = game.nmnd_night2_doctor_self_saves
        game.nmnd_night2_doctor_self_saves += 1
    game.nmnd_night2_doctor_uid = target
    game.nmnd_night2_doctor_confirmed_self = self_save
    game.nmnd_night2_doctor_pending_uid = None
    _audit(
        game,
        "night2.doctor_confirmed",
        target_uid=target,
        self_save=self_save,
    )
    await callback.answer("ثبت شد.")
    if self_save:
        label = "خودم"
    else:
        label = _button_label(game, game.players.get(target), target)
    await _update_panel(
        bot,
        game,
        uid,
        _doc_key(game, uid),
        f"<b>✅ انتخاب شما: {label}</b>\n\n⏳ لطفاً منتظر اتمام فاز شب بمانید.",
        None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_doctor_confirmed")
    except Exception:
        pass
    await night2_maybe_grant_guide_extra(bot, game)
    night2_maybe_finish(game, gm)


# -- Hacker -----------------------------------------------------------------


async def _act_shiad_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if game.nmnd_night2_hacker_uids:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    stage = game.nmnd_night2_hacker_stage or HACKER_STAGE_SRC
    if stage == HACKER_STAGE_DONE:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if _holder(game, Role.SHIAD) is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    # Both stages draw from the authoritative current town faction.
    allowed = {p.user_id for p in _town_members(game)}
    if tid not in allowed:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if stage == HACKER_STAGE_SRC:
        if game.nmnd_night2_hacker_src_pending == tid:
            game.nmnd_night2_hacker_src_pending = None
        else:
            game.nmnd_night2_hacker_src_pending = tid
    else:
        if game.nmnd_night2_hacker_dst_pending == tid:
            game.nmnd_night2_hacker_dst_pending = None
        else:
            game.nmnd_night2_hacker_dst_pending = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_shiad_panel(bot, game, uid)


async def _act_shiad_next(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if game.nmnd_night2_hacker_uids:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if (game.nmnd_night2_hacker_stage or HACKER_STAGE_SRC) != HACKER_STAGE_SRC:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if _holder(game, Role.SHIAD) is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if not game.nmnd_night2_hacker_src_pending:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    game.nmnd_night2_hacker_stage = HACKER_STAGE_DST
    game.nmnd_night2_hacker_dst_pending = None
    _audit(
        game,
        "night2.hacker_stage2_entered",
        source_uid=game.nmnd_night2_hacker_src_pending,
    )
    await callback.answer("ثبت شد؛ به مرحله دوم بروید.")
    await _send_shiad_panel(bot, game, uid)


async def _act_shiad_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if game.nmnd_night2_hacker_uids:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if (game.nmnd_night2_hacker_stage or HACKER_STAGE_SRC) != HACKER_STAGE_DST:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    src = game.nmnd_night2_hacker_src_pending
    dst = game.nmnd_night2_hacker_dst_pending
    if not src or not dst:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    game.nmnd_night2_hacker_uids = [src, dst]
    game.nmnd_night2_hacker_stage = HACKER_STAGE_DONE
    game.nmnd_night2_hacker_src_pending = None
    game.nmnd_night2_hacker_dst_pending = None
    body = (
        "<b>✅ انتخاب شما ثبت شد.</b>\n\n"
        f"مبدأ: {_button_label(game, game.players.get(src), src)}\n"
        f"مقصد: {_button_label(game, game.players.get(dst), dst)}\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید."
    )
    await callback.answer("ثبت شد.")
    await _update_panel(bot, game, uid, _shiad_key(game, uid), body, None)
    try:
        manager.persist_snapshot(game, reason="night2_shiad_confirmed")
    except Exception:
        pass
    # With both Hacker and Guide choices known the Guide aftermath may be
    # granted immediately (extra investigation / mafia identification).
    await night2_maybe_grant_guide_extra(bot, game)
    night2_maybe_finish(game, gm)


# -- Guide ------------------------------------------------------------------


async def _act_guide_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    nc = int(game.nmnd_narrator_night_count or 0)
    if game.nmnd_night2_guide_uids.get(nc) is not None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if _holder(game, Role.INTERROGATOR) is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    prev = game.nmnd_night2_guide_uids.get(nc - 1)
    allowed = {
        p.user_id
        for p in _alive_players(game)
        if p.user_id != uid and p.user_id != prev
    }
    if tid not in allowed:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_guide_pending_uid == tid:
        game.nmnd_night2_guide_pending_uid = None
    else:
        game.nmnd_night2_guide_pending_uid = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_guide_panel(bot, game, uid)


async def _act_guide_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    nc = int(game.nmnd_narrator_night_count or 0)
    tid = game.nmnd_night2_guide_pending_uid
    if not tid:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    game.nmnd_night2_guide_uids[nc] = tid
    game.nmnd_night2_guide_pending_uid = None
    await callback.answer("ثبت شد.")
    await _update_panel(
        bot,
        game,
        uid,
        _guide_key(game, uid),
        f"<b>✅ انتخاب شما: {_button_label(game, game.players.get(tid), tid)}</b>"
        "\n\n⏳ لطفاً منتظر اتمام فاز شب بمانید.",
        None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_guide_confirmed")
    except Exception:
        pass
    # Both Guide and Hacker choices may now be complete: grant the Guide
    # aftermath (extra investigation panel / Mafia identification notice).
    await night2_maybe_grant_guide_extra(bot, game)
    night2_maybe_finish(game, gm)


# -- Mine Layer ---------------------------------------------------------------


async def _act_mine_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if game.nmnd_night2_mine_uid is not None or game.nmnd_night2_dispositions.get(
        "mine_none"
    ):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if _holder(game, Role.RUINTAN) is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if tid == 0:
        if game.nmnd_night2_mine_pending_none:
            game.nmnd_night2_mine_pending_none = False
        else:
            game.nmnd_night2_mine_pending_none = True
            game.nmnd_night2_mine_pending_uid = None
    else:
        if tid not in {p.user_id for p in _alive_players(game)}:
            await callback.answer(ALERT_INVALID, show_alert=True)
            return
        if tid == uid:
            # Mine Layer may never target themselves (all counts).
            await callback.answer(ALERT_INVALID, show_alert=True)
            return
        if game.nmnd_night2_mine_pending_uid == tid:
            game.nmnd_night2_mine_pending_uid = None
        else:
            game.nmnd_night2_mine_pending_uid = tid
            game.nmnd_night2_mine_pending_none = False
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_mine_panel(bot, game, uid)


async def _act_mine_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    nc = int(game.nmnd_narrator_night_count or 0)
    if game.nmnd_night2_mine_uid is not None or (
        game.nmnd_night2_dispositions.get("mine_none")
    ):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    target = game.nmnd_night2_mine_pending_uid
    none_pick = game.nmnd_night2_mine_pending_none
    if not target and not none_pick:
        await callback.answer(
            "یک بازیکن انتخاب کنید یا «انتخابی ندارم» را بزنید.",
            show_alert=True,
        )
        return
    if target == uid:
        # Confirmation re-validation: a self-placement can never be
        # committed, not even from a stale pending state or a forged
        # callback (unchanged mines from before the rule stay valid).
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if target:
        game.nmnd_night2_mine_uid = target
        game.nmnd_night2_mine_used = True
        game.nmnd_night2_mine_used_night = nc
    else:
        game.nmnd_night2_dispositions["mine_none"] = "no_target"
    game.nmnd_night2_mine_pending_uid = None
    game.nmnd_night2_mine_pending_none = False
    await callback.answer("ثبت شد.")
    if target:
        body = (
            f"<b>✅ انتخاب شما: {_button_label(game, game.players.get(target), target)}</b>"
            "\n\n⏳ لطفاً منتظر اتمام فاز شب بمانید."
        )
    else:
        body = (
            "<b>✅ انتخابی ندارم — ثبت شد.</b>\n\n"
            "⏳ لطفاً منتظر اتمام فاز شب بمانید."
        )
    # The spent-Mine same-night ack (see night2_required_keys /
    # _wait_ok_allowed) must be pressable: without the OK button the
    # collection could never complete and the room would stall. With
    # the "select none" disposition the requirement is satisfied
    # immediately, so no further ack is offered.
    await _update_panel(
        bot,
        game,
        uid,
        _mine_key(game, uid),
        body,
        _wait_ok_kb(game, uid) if target else None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_mine_confirmed")
    except Exception:
        pass
    await night2_maybe_grant_guide_extra(bot, game)
    night2_maybe_finish(game, gm)


# -- Lawyer -----------------------------------------------------------------


async def _act_law_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if game.nmnd_night2_lawyer_uid is not None or game.nmnd_night2_dispositions.get(
        "lawyer_none"
    ):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if _holder(game, Role.HUNTER) is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if tid == 0:
        if game.nmnd_night2_lawyer_pending_none:
            game.nmnd_night2_lawyer_pending_none = False
        else:
            game.nmnd_night2_lawyer_pending_none = True
            game.nmnd_night2_lawyer_pending_uid = None
    else:
        allowed = {p.user_id for p in _alive_players(game) if p.user_id != uid}
        if tid not in allowed:
            await callback.answer(ALERT_INVALID, show_alert=True)
            return
        if game.nmnd_night2_lawyer_pending_uid == tid:
            game.nmnd_night2_lawyer_pending_uid = None
        else:
            game.nmnd_night2_lawyer_pending_uid = tid
            game.nmnd_night2_lawyer_pending_none = False
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_law_panel(bot, game, uid)


async def _act_law_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    nc = int(game.nmnd_narrator_night_count or 0)
    if game.nmnd_night2_lawyer_uid is not None or (
        game.nmnd_night2_dispositions.get("lawyer_none")
    ):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    target = game.nmnd_night2_lawyer_pending_uid
    none_pick = game.nmnd_night2_lawyer_pending_none
    if not target and not none_pick:
        await callback.answer(
            "یک بازیکن انتخاب کنید یا «انتخابی ندارم» را بزنید.",
            show_alert=True,
        )
        return
    if target:
        game.nmnd_night2_lawyer_uid = target
        game.nmnd_night2_lawyer_used = True
        game.nmnd_night2_lawyer_used_night = nc
    else:
        game.nmnd_night2_dispositions["lawyer_none"] = "no_target"
    game.nmnd_night2_lawyer_pending_uid = None
    game.nmnd_night2_lawyer_pending_none = False
    await callback.answer("ثبت شد.")
    if target:
        body = (
            f"<b>✅ انتخاب شما: {_button_label(game, game.players.get(target), target)}</b>"
            "\n\n⏳ لطفاً منتظر اتمام فاز شب بمانید."
        )
    else:
        body = (
            "<b>✅ انتخابی ندارم — ثبت شد.</b>\n\n"
            "⏳ لطفاً منتظر اتمام فاز شب بمانید."
        )
    # Same-night spent-Lawyer ack must stay pressable (see
    # night2_required_keys / _wait_ok_allowed); none-pick needs no
    # further acknowledgement.
    await _update_panel(
        bot,
        game,
        uid,
        _law_key(game, uid),
        body,
        _wait_ok_kb(game, uid) if target else None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_lawyer_confirmed")
    except Exception:
        pass
    await night2_maybe_grant_guide_extra(bot, game)
    night2_maybe_finish(game, gm)


# -- Guardian ---------------------------------------------------------------


async def _act_guard_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if night2_guardian_exempt_after_assassin(game):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if game.nmnd_night2_guardian_uid is not None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if _holder(game, Role.DETECTIVE) is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    allowed = {p.user_id for p in _alive_players(game) if p.user_id != uid}
    if tid not in allowed:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_guardian_pending_uid == tid:
        game.nmnd_night2_guardian_pending_uid = None
    else:
        game.nmnd_night2_guardian_pending_uid = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_guard_panel(bot, game, uid)


async def _act_guard_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if night2_guardian_exempt_after_assassin(game):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    nc = int(game.nmnd_narrator_night_count or 0)
    tid = game.nmnd_night2_guardian_pending_uid
    if not tid:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    game.nmnd_night2_guardian_uid = tid
    game.nmnd_night2_guardian_pending_uid = None
    await callback.answer("ثبت شد.")
    await _update_panel(
        bot,
        game,
        uid,
        _guard_key(game, uid),
        f"<b>✅ انتخاب محافظ در شب {_seat_fa(nc)} ثبت شد.</b>\n\n"
        f"بازیکن انتخاب‌شده: {_button_label(game, game.players.get(tid), tid)}",
        None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_guardian_confirmed")
    except Exception:
        pass
    await night2_maybe_grant_guide_extra(bot, game)
    night2_maybe_finish(game, gm)


# -- Waiting acknowledgements -------------------------------------------------


async def _act_wait_ok(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm,
    uid: int,
    actor_uid: int,
) -> None:
    pl = game.players.get(uid)
    if pl is None or pl.role is None:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    key = pl.role.value
    if key not in (
        Role.CITIZEN.value,
        Role.NATO.value,
        Role.RUINTAN.value,
        Role.HUNTER.value,
        Role.DETECTIVE.value,
        Role.SOLDIER.value,
        Role.NATO_AGENT.value,
    ):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if not _wait_ok_allowed(game, key, uid):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    acked = _acked_uids(game, key)
    if uid in acked:
        await callback.answer(ALERT_ALREADY, show_alert=True)
        return
    game.nmnd_night2_waiting_acked.setdefault(key, []).append(uid)
    await callback.answer("ثبت شد.")
    body = "<b>✅ تأیید شما ثبت شد.</b>"
    if key == Role.CITIZEN.value:
        ui_key = _citizen_key(game, uid)
    elif key == Role.NATO.value:
        ui_key = _rebel_key(game, uid)
    elif key == Role.RUINTAN.value:
        ui_key = _mine_key(game, uid)
    elif key == Role.HUNTER.value:
        ui_key = _law_key(game, uid)
    elif key == Role.SOLDIER.value:
        ui_key = _soldier_key(game, uid)
    elif key == Role.NATO_AGENT.value:
        ui_key = _nato_stage_key(game, uid)
    else:
        ui_key = _guard_key(game, uid)
    await _update_panel(bot, game, uid, ui_key, body, None)
    try:
        manager.persist_snapshot(game, reason="night2_wait_acked")
    except Exception:
        pass
    await night2_maybe_grant_guide_extra(bot, game)
    night2_maybe_finish(game, gm)


def _wait_ok_allowed(game: Game, key: str, uid: int) -> bool:
    """Only spent Mine/Lawyer, the exempted Guardian and simple
    Rebel/Citizen may ack waiting."""
    if key == Role.DETECTIVE.value:
        # Exemption-only: valid solely after the Rebel's confirmed
        # assassination; _act_wait_ok has already filtered non-Guardians.
        return night2_guardian_exempt_after_assassin(game)
    if key in (Role.RUINTAN.value, Role.HUNTER.value):
        spent = (
            game.nmnd_night2_mine_used
            if key == Role.RUINTAN.value
            else game.nmnd_night2_lawyer_used
        )
        return bool(spent)
    if key == Role.SOLDIER.value:
        return bool(game.nmnd_night2_soldier_used)
    if key == Role.NATO_AGENT.value:
        pl = game.players.get(uid)
        return pl is not None and pl.role == Role.NATO_AGENT
    pl = game.players.get(uid)
    if pl is None:
        return False
    if key == Role.NATO.value:
        if _shooter_is_rebel(game):
            # The Rebel owes the inherited Mafia shot this night; the old
            # waiting-only panel's OK must never settle the night.
            return False
        return _is_simple_rebel(game, pl)
    return _is_simple_citizen(game, pl)


# ---------------------------------------------------------------------------
# Soldier + temporary Sniper + independent NATO (Namayande 12/13)
# ---------------------------------------------------------------------------

GRANT_STATUS_PENDING = "pending"
GRANT_STATUS_INTERCEPTED = "intercepted"
GRANT_STATUS_DELIVERED = "delivered"
GRANT_STATUS_MAFIA = "mafia_target"
GRANT_STATUS_VOID = "void"

ELIM_CAUSE_SNIPER = "sniper_shot"
ELIM_CAUSE_SOLDIER_MAFIA = "soldier_mafia_target"

# اتمام اجباری کمک‌کننده: سرباز/اسنایپر موقتِ بی‌تأیید حذف می‌شوند
# (فقط نمایندهٔ ۱۲/۱۳ — از طریق پایپ‌لاین موجود و یک‌بار ثبت می‌شوند).
ELIM_CAUSE_FORCE_SOLDIER = "force_finish_soldier_unconfirmed"
ELIM_CAUSE_FORCE_SNIPER = "force_finish_temp_sniper_unconfirmed"

SOLDIER_PANEL_BODY = (
    "<b>🪖 انتخاب اسنایپر</b>\n\n"
    "شما می‌توانید یکی از بازیکنان را برای دریافت قابلیت اسنایپر انتخاب کنید.\n\n"
    "اگر بازیکن انتخاب‌شده عضو تیم شهروند باشد، پس از تکمیل اقدامات لازم، "
    "قابلیت یک شلیک اسنایپری به او داده می‌شود.\n\n"
    "اگر بازیکن انتخاب‌شده عضو تیم مافیا باشد، شما از بازی خارج می‌شوید.\n\n"
    "یک بازیکن را انتخاب کنید و دکمه «✅ تأیید» را بزنید."
)

SOLDIER_SPENT_BODY = (
    "<b>🪖 سرباز</b>\n\n"
    "شما قبلاً از قابلیت انتخاب اسنایپر استفاده کرده‌اید.\n\n"
    "امشب اقدام دیگری ندارید. لطفاً تا پایان مرحله شب منتظر بمانید."
)

SNIPER_PANEL_BODY = (
    "<b>🎯 قابلیت اسنایپر</b>\n\n"
    "سرباز به شما قابلیت یک شلیک اسنایپری داده است.\n\n"
    "می‌بایست دقیقاً یک بازیکن را انتخاب کنید و با «✅ تأیید» شلیک را ثبت کنید.\n\n"
    "اگر به یکی از شهروندان شلیک کنید، خودتان از بازی خارج می‌شوید و هدف زنده می‌ماند.\n\n"
    "اگر به رئیس مافیا شلیک کنید، هر دو زنده می‌مانید.\n\n"
    "اگر به یکی دیگر از اعضای تیم مافیا شلیک کنید، آن بازیکن از بازی خارج می‌شود."
)

NATO_AGENT_WAIT_BODY = (
    "<b>🎭 ناتو</b>\n\n"
    "تیم مافیا در حال انجام اقدامات شبانه است.\n\n"
    "لطفاً منتظر بمانید و آمادگی خود را تأیید کنید."
)


def _nato_agent_holder(game: Game) -> Player | None:
    return _holder(game, Role.NATO_AGENT)


def _nato_agent_dealt(game: Game) -> bool:
    """True when this room's composition includes the independent NATO."""
    return any(p.role == Role.NATO_AGENT for p in game.players.values())


def _nato_independent_mode_pending(game: Game) -> bool:
    """Independent NATO stages are active (12/13 rooms only)."""
    return (
        _holder(game, Role.NATO_AGENT) is not None
        and game.nmnd_night2_boss_phase
        in (BOSS_PHASE_NATO_ROLE, BOSS_PHASE_NATO_PLAYER)
    )


def _nato_stage_owner(game: Game) -> Player | None:
    """Who performs the NATO role/target stages: the independent NATO
    agent (12/13) or the active shooter (10/11 shared mode)."""
    agent = _nato_agent_holder(game)
    if agent is not None:
        return agent
    return night2_active_shooter(game)


def _nato_stage_key(game: Game, uid: int) -> str:
    agent = _nato_agent_holder(game)
    if agent is not None and uid == agent.user_id:
        return _ui_key(game, "n2nato", uid)
    return _boss_key(game, uid)


def _danger_pick_rows(
    game: Game,
    owner_uid: int,
    pick_act: str,
    pool: list[Player],
    pending: int | None,
) -> list[list[InlineKeyboardButton]]:
    """Single-select rows: unselected primary blue, the selected one
    danger red. Seat/name labels only — never roles or factions."""
    rows: list[list[InlineKeyboardButton]] = []
    for p in pool:
        style = "danger" if p.user_id == pending else "primary"
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_label(game, p, p.user_id),
                    style=style,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act=pick_act,
                        as_uid=owner_uid,
                        tid=p.user_id,
                    ).pack(),
                )
            ]
        )
    return rows


async def _delete_panel_pair(bot, game: Game, owner_uid: int, key: str) -> None:
    """Best-effort deletion of one registered v2 panel pair.

    Removes the player message and the Observer mirror copy, then drops
    the registration so the night-resolution purge no longer sees it.
    Uses the established purge fallback: when a message cannot be
    deleted, its reply markup is removed so the buttons die anyway.
    """
    from bot.nam10.nmnd_night_panel_purge import _try_delete_panel_message

    entry = game.mirror_prompt_messages.get(key)
    if not isinstance(entry, dict):
        return
    for role in ("player", "observer"):
        ref = entry.get(role)
        if isinstance(ref, tuple) and len(ref) >= 2:
            try:
                await _try_delete_panel_message(bot, ref[0], ref[1])
            except Exception:
                pass
    game.mirror_prompt_messages.pop(key, None)
    game.mirror_action_claims.pop(key, None)


def _pair_pick_rows(
    rows: list[list[InlineKeyboardButton]],
) -> list[list[InlineKeyboardButton]]:
    """Presentation-only: two pick buttons per row (odd tail keeps
    exactly one button). Styles/callbacks are preserved per button."""
    paired: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(rows), 2):
        chunk = rows[i : i + 2]
        paired.append([button for row in chunk for button in row])
    return paired


def _night_line(game: Game) -> str:
    nc = int(game.nmnd_narrator_night_count or 0)
    return f"🌙 شب: {_seat_fa(nc)}"


async def _send_soldier_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _soldier_key(game, uid)
    pool = [p for p in _alive_players(game) if p.user_id != uid]
    pend = game.nmnd_night2_soldier_pending_uid
    rows = _pair_pick_rows(
        _danger_pick_rows(game, uid, ACT_SOLDIER_PICK, pool, pend)
    )
    rows.append(_confirm_row(game, uid, ACT_SOLDIER_OK))
    await _publish_panel(
        bot,
        game,
        uid,
        key,
        f"{SOLDIER_PANEL_BODY}\n\n{_night_line(game)}",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _send_soldier_spent_panel(bot: Bot, game: Game, uid: int) -> None:
    await _publish_panel(
        bot,
        game,
        uid,
        _soldier_key(game, uid),
        f"{SOLDIER_SPENT_BODY}\n\n{_night_line(game)}",
        _wait_ok_kb(game, uid),
    )


async def _send_sniper_panel(bot: Bot, game: Game, uid: int) -> None:
    key = _sniper_key(game, uid)
    pool = [p for p in _alive_players(game) if p.user_id != uid]
    if not pool:
        # Exceptional end-state: no eligible target exists. Do not
        # invent a target and do not deadlock the night — the mandatory
        # obligation resolves as an unavailable action (no shot, no
        # elimination) using the established unavailable-action path.
        nc = int(game.nmnd_narrator_night_count or 0)
        game.nmnd_night2_sniper_pending_uid = None
        game.nmnd_night2_sniper_resolved = True
        _audit(
            game,
            "night2.sniper_no_eligible_target",
            sniper_uid=uid,
            night=nc,
        )
        try:
            manager.persist_snapshot(
                game, reason="night2_sniper_no_eligible_target"
            )
        except Exception:
            pass
        await _publish_panel(
            bot,
            game,
            uid,
            key,
            "<b>🎯 قابلیت اسنایپر</b>\n\n"
            "در حال حاضر هدفی برای شلیک در دسترس نیست.\n\n"
            f"{_night_line(game)}",
            None,
        )
        return
    pend = game.nmnd_night2_sniper_pending_uid
    rows = _pair_pick_rows(
        _danger_pick_rows(game, uid, ACT_SNIPER_PICK, pool, pend)
    )
    rows.append(_confirm_row(game, uid, ACT_SNIPER_OK))
    # Mandatory-shot rule: the temporary Sniper MUST select exactly one
    # eligible target and confirm it. No voluntary skip/no-shot option
    # is offered and the old skip callback is rejected server-side.
    await _publish_panel(
        bot,
        game,
        uid,
        key,
        f"{SNIPER_PANEL_BODY}\n\n{_night_line(game)}",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _send_nato_agent_wait_panel(bot: Bot, game: Game, uid: int) -> None:
    await _publish_panel(
        bot,
        game,
        uid,
        _nato_stage_key(game, uid),
        NATO_AGENT_WAIT_BODY,
        _wait_ok_kb(game, uid),
    )


def _mirror_delivery_ok(game: Game, ui_key: str, owner_uid: int) -> bool:
    """Actual successful Telegram delivery reference for a panel pair."""
    entry = game.mirror_prompt_messages.get(ui_key) or {}
    if is_synthetic_player_uid(owner_uid):
        return bool(entry.get("observer"))
    return bool(entry.get("player"))


def _sniper_active_uid(game: Game) -> int | None:
    """The recipient currently holding the temporary Sniper panel."""
    if (
        game.nmnd_night2_soldier_grant_status == GRANT_STATUS_DELIVERED
        and game.nmnd_night2_soldier_uid is not None
        and game.nmnd_night2_sniper_night
        == int(game.nmnd_narrator_night_count or 0)
        and not game.nmnd_night2_sniper_resolved
    ):
        return game.nmnd_night2_soldier_uid
    return None


async def night2_reconcile_soldier_grant(bot: Bot, game: Game) -> None:
    """Authoritative single path for the pending Soldier grant.

    Idempotent; callable from any act handler or re-entry. A pending
    grant settles exactly once per night as intercepted (silent), void
    (invalid recipient) or delivered (delivery consumes the Soldier's
    lifetime allowance). Conditions, in order:
      1. the Hacker obligation is resolved (or authoritatively absent);
      2. the recipient's own original night action is settled;
      3. every mandatory Guide-granted extra action is settled;
      4. the recipient is still an eligible living Town player.
    A failed Telegram delivery keeps the grant pending (charge not
    consumed); the next reconcile tick retries it.
    """
    if game.nmnd_night2_phase != PENDING_COLLECTING:
        return
    status = game.nmnd_night2_soldier_grant_status
    if status in (None, GRANT_STATUS_MAFIA):
        return
    if status in (
        GRANT_STATUS_INTERCEPTED,
        GRANT_STATUS_DELIVERED,
        GRANT_STATUS_VOID,
    ):
        return
    recipient = game.nmnd_night2_soldier_uid
    soldier = _holder(game, Role.SOLDIER)
    if soldier is None or recipient is None:
        return
    nc = int(game.nmnd_narrator_night_count or 0)
    # (1) Hacker resolution gate: a living Hacker that has not confirmed
    # its pair keeps the grant waiting.
    if _holder(game, Role.SHIAD) is not None and not (
        game.nmnd_night2_hacker_uids
    ):
        return
    if night2_hack_intercepts(game, soldier.user_id, recipient):
        # Silent cancellation: no panel, no notification, no charge.
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_INTERCEPTED
        _audit(
            game,
            "night2.soldier_grant_intercepted",
            soldier_uid=soldier.user_id,
            recipient_uid=recipient,
            night=nc,
        )
        try:
            manager.persist_snapshot(
                game, reason="night2_soldier_grant_intercepted"
            )
        except Exception:
            pass
        return
    # (4) Recipient eligibility (re-validated at dispatch time).
    rpl = game.players.get(recipient)
    if rpl is None or not rpl.is_alive or _is_mafia_member(game, rpl):
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_VOID
        _audit(
            game,
            "night2.soldier_grant_void",
            recipient_uid=recipient,
            night=nc,
        )
        return
    # (2) Recipient's own original night action settled.
    if not night2_recipient_main_complete(game, recipient):
        return
    # (3) Every mandatory Guide-granted extra action settled.
    if (
        game.nmnd_night2_extra_kind == EXTRA_KIND_SENT
        and game.nmnd_night2_extra_uid == recipient
        and game.nmnd_night2_extra_target_uid is None
    ):
        return
    # All conditions satisfied: dispatch the temporary-Sniper panel.
    key = _sniper_key(game, recipient)
    entry = game.mirror_prompt_messages.get(key) or {}
    if not (entry.get("player") or entry.get("observer")):
        # A previous failed delivery left the key registered without any
        # delivery reference: force a fresh registration so the retry
        # actually sends a live panel instead of editing a dead one.
        game.mirror_prompt_messages.pop(key, None)
    await _send_sniper_panel(bot, game, recipient)
    if not _mirror_delivery_ok(game, key, recipient):
        # Failed delivery: keep pending, charge not consumed, no second
        # selection opportunity; a later reconcile retries delivery.
        _audit(
            game,
            "night2.soldier_grant_delivery_failed",
            recipient_uid=recipient,
            night=nc,
        )
        return
    game.nmnd_night2_soldier_grant_status = GRANT_STATUS_DELIVERED
    game.nmnd_night2_soldier_used = True
    game.nmnd_night2_soldier_used_night = nc
    game.nmnd_night2_sniper_night = nc
    entry = game.mirror_prompt_messages.get(key) or {}
    game.nmnd_night2_sniper_delivered_refs = [
        {"role": role, "chat_id": ref[0], "message_id": ref[1]}
        for role, ref in entry.items()
        if role in ("player", "observer")
        and isinstance(ref, (tuple, list))
        and len(ref) == 2
    ]
    _audit(
        game,
        "night2.sniper_grant_delivered",
        soldier_uid=soldier.user_id,
        recipient_uid=recipient,
        night=nc,
    )
    try:
        manager.persist_snapshot(game, reason="night2_sniper_grant_delivered")
    except Exception:
        pass


async def _act_soldier_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if game.nmnd_night2_soldier_used or game.nmnd_night2_soldier_uid is not None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    soldier = _holder(game, Role.SOLDIER)
    if soldier is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if soldier.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    alive = {p.user_id for p in _alive_players(game)}
    if tid not in alive or tid == uid:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_soldier_pending_uid == tid:
        game.nmnd_night2_soldier_pending_uid = None
    else:
        game.nmnd_night2_soldier_pending_uid = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_soldier_panel(bot, game, uid)


async def _act_soldier_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if game.nmnd_night2_soldier_used or game.nmnd_night2_soldier_uid is not None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    soldier = _holder(game, Role.SOLDIER)
    if soldier is None:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if soldier.user_id != uid:
        await callback.answer(ALERT_FORBIDDEN, show_alert=True)
        return
    target = game.nmnd_night2_soldier_pending_uid
    if not target:
        await callback.answer(
            "ابتدا یک بازیکن را انتخاب کنید.", show_alert=True
        )
        return
    tpl = game.players.get(target)
    if tpl is None or not tpl.is_alive or target == uid:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    game.nmnd_night2_soldier_uid = target
    game.nmnd_night2_soldier_pending_uid = None
    if _is_mafia_member(game, tpl):
        # Mafia recipient: no grant, no announcement; resolution
        # eliminates the Soldier.
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_MAFIA
    else:
        # Town recipient: the grant waits for Hacker resolution, the
        # recipient's own action and all mandatory extra actions.
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_PENDING
    _audit(
        game,
        "night2.soldier_confirmed",
        soldier_uid=uid,
        target_uid=target,
        status=game.nmnd_night2_soldier_grant_status,
    )
    await callback.answer("ثبت شد.")
    await _update_panel(
        bot,
        game,
        uid,
        _soldier_key(game, uid),
        "<b>✅ انتخاب شما ثبت شد.</b>\n\n"
        f"بازیکن انتخاب‌شده: {_button_label(game, tpl, target)}\n\n"
        f"{_night_line(game)}\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید.",
        None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_soldier_confirmed")
    except Exception:
        pass
    await night2_reconcile_soldier_grant(bot, game)
    night2_maybe_finish(game, gm)


async def _act_sniper_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if _sniper_active_uid(game) != uid:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    alive = {p.user_id for p in _alive_players(game)}
    if tid not in alive or tid == uid:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_sniper_pending_uid == tid:
        game.nmnd_night2_sniper_pending_uid = None
    else:
        game.nmnd_night2_sniper_pending_uid = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_sniper_panel(bot, game, uid)


async def _act_sniper_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if _sniper_active_uid(game) != uid:
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    target = game.nmnd_night2_sniper_pending_uid
    if not target:
        await callback.answer(
            "ابتدا یک بازیکن را انتخاب کنید.", show_alert=True
        )
        return
    tpl = game.players.get(target)
    if tpl is None or not tpl.is_alive or target == uid:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    game.nmnd_night2_sniper_target_uid = target
    game.nmnd_night2_sniper_pending_uid = None
    game.nmnd_night2_sniper_resolved = True
    _audit(
        game,
        "night2.sniper_target_confirmed",
        sniper_uid=uid,
        target_uid=target,
        night=game.nmnd_night2_sniper_night,
    )
    await callback.answer("ثبت شد.")
    await _update_panel(
        bot,
        game,
        uid,
        _sniper_key(game, uid),
        "<b>✅ انتخاب شما ثبت شد.</b>\n\n"
        f"هدف شلیک: {_button_label(game, tpl, target)}\n\n"
        "⏳ لطفاً منتظر اتمام فاز شب بمانید.",
        None,
    )
    try:
        manager.persist_snapshot(game, reason="night2_sniper_target_confirmed")
    except Exception:
        pass
    night2_maybe_finish(game, gm)


async def _act_sniper_skip(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    # Mandatory-shot rule: the temporary Sniper cannot voluntarily skip
    # the shot. The old skip pathway is disabled for new actions —
    # stale panels and forged/stale/duplicate callbacks are rejected
    # without resolving the obligation or touching any state.
    await callback.answer(ALERT_STALE, show_alert=True)


# ---------------------------------------------------------------------------
# Hacker intercept + investigation classification helpers
# ---------------------------------------------------------------------------


def night2_hack_intercepts(game: Game, src_uid: int, dst_uid: int) -> bool:
    """True when the confirmed Hacker pair is exactly source -> destination.

    FINAL global rule (every Namayande count): the Mine Layer is immune
    as the Hacker's SOURCE — such a pair produces no gameplay effect at
    all, regardless of the chosen destination, and never counts as an
    interception. The pair itself stays recorded for completion/audit
    only, and the Mine Layer's own action is never cancelled.
    """
    pair = list(game.nmnd_night2_hacker_uids or [])
    if len(pair) != 2 or pair[0] != src_uid or pair[1] != dst_uid:
        return False
    mine_holder = _holder(game, Role.RUINTAN)
    if mine_holder is not None and pair[0] == mine_holder.user_id:
        return False
    return True


def night2_investigation_is_positive(game: Game, target: Player) -> bool:
    """Authoritative extra-investigation classification.

    Positive: current mafia members except the Mafia Boss (Rebel/Yaghi,
    Hacker, yakuza-converted players — conversion sets the current role to
    ``MAFIA_BASIC``). Negative: the Mafia Boss himself and every town
    role/explicit mapping case.
    """
    if target.role == Role.MAFIA_BOSS:
        return False
    if target.role == Role.SHIAD:
        return True
    from bot.game import is_mafia_team

    if getattr(target, "nmnd_converted_by_yakuza", False) or target.user_id in (
        game.nmnd_mafia_recruit_ids or []
    ):
        return True
    return bool(is_mafia_team(target.role))


# ---------------------------------------------------------------------------
# Guide aftermath: extra investigation / Mafia identification
# ---------------------------------------------------------------------------


def _guide_holder_uid(game: Game) -> int | None:
    guide = _holder(game, Role.INTERROGATOR)
    return guide.user_id if guide is not None else None


def _guide_identity_uid(game: Game) -> int | None:
    """UID of the Guide for NAME resolution (display only).

    Alive holder first; when the Guide was eliminated the same night
    they selected a Mafia member (Room 37 case), the role stays on the
    stored player record — resolve the name from the full player table
    instead of rendering '؟'.
    """
    guide = _guide_holder_uid(game)
    if guide is not None:
        return guide
    for pl in game.players.values():
        if (
            pl.role == Role.INTERROGATOR
            and not getattr(pl, "nmnd_converted_by_yakuza", False)
        ):
            return pl.user_id
    return None


def _night2_extra_owed(game: Game) -> bool:
    return (
        game.nmnd_night2_extra_kind == EXTRA_KIND_SENT
        and game.nmnd_night2_extra_uid is not None
        and game.nmnd_night2_extra_target_uid is None
    )


def night2_recipient_main_complete(game: Game, uid: int) -> bool:
    """Is the recipient's own original night obligation settled?

    Dead recipients need no main action. Waiting-style obligations
    (citizen/rebel acknowledgements, spent Mine/Lawyer acks) are settled
    per player via the waiting-ack ledger. Confirm-based single-holder
    actions are settled when the role key is gone from the readiness
    set (confirmed, skipped, or validly auto-cancelled like the NATO
    doctor rollback). The granted extra obligation itself is excluded.
    """
    pl = game.players.get(uid)
    if pl is None or not pl.is_alive or pl.role is None:
        return True
    role = pl.role.value
    if uid in _acked_uids(game, role):
        return True
    if role == Role.CITIZEN.value:
        # the citizen obligation is exactly the waiting acknowledgement
        return False
    keys = [k for k in night2_required_keys(game) if k != "n2extra"]
    return role not in keys


async def night2_maybe_grant_guide_extra(bot: Bot, game: Game) -> None:
    """Guide aftermath after Guide + Hacker choices are both known.

    Decision (once): intercepted by the Hacker pair (Guide source ->
    recipient destination) sends nothing and reveals nothing; a town
    recipient owes a separate additional investigation; a Mafia
    recipient gets the one-time private Guide-identity notice.

    The additional-investigation panel is MATERIALIZED only after the
    recipient's own original night action is settled (completed,
    acknowledged, or validly auto-cancelled). Until then no panel and
    no waiting notification is sent; the ``n2extra`` readiness key
    already keeps the night from finishing in the meantime. Calls are
    idempotent across duplicates, retries and snapshot restores.
    """
    nc = int(game.nmnd_narrator_night_count or 0)
    recipient = game.nmnd_night2_guide_uids.get(nc)
    if recipient not in game.players:
        return
    if not game.nmnd_night2_grant_decided:
        # Decision requires both choices; a missing Hacker holder means no
        # interception is possible at all.
        if _holder(game, Role.SHIAD) is not None and not (
            game.nmnd_night2_hacker_uids
        ):
            return
        game.nmnd_night2_grant_decided = True
        rpl = game.players.get(recipient)
        if rpl is None or not rpl.is_alive:
            game.nmnd_night2_extra_kind = EXTRA_KIND_DEAD
        elif _is_mafia_member(game, rpl):
            game.nmnd_night2_extra_kind = EXTRA_KIND_MAFIA_ID
            game.nmnd_night2_extra_uid = rpl.user_id
        elif _guide_holder_uid(game) is not None and night2_hack_intercepts(
            game, _guide_holder_uid(game), recipient
        ):
            game.nmnd_night2_extra_kind = EXTRA_KIND_INTERCEPTED
        else:
            game.nmnd_night2_extra_kind = EXTRA_KIND_SENT
            game.nmnd_night2_extra_uid = recipient
        _audit(
            game,
            "night2.guide_grant_decided",
            kind=game.nmnd_night2_extra_kind,
            recipient_uid=recipient,
        )
    if game.nmnd_night2_extra_kind == EXTRA_KIND_MAFIA_ID:
        flag = f"mafia_id_notified:{game.nmnd_night2_extra_uid}"
        if not game.nmnd_night2_dispositions.get(flag) and (
            night2_mafia_shot_settled(game)
        ):
            # Delayed disclosure (Room 32 rule): the Guide-identity
            # notice must wait until every mandatory Mafia main action
            # (shot target / independent NATO stages) is settled. The
            # flag keeps delivery exactly-once across retries.
            notice_uid = game.nmnd_night2_extra_uid
            await _send_guide_identity_notice(
                bot,
                game,
                notice_uid,
                _guide_identity_uid(game),
            )
            if _mirror_delivery_ok(game, _extra_key(game, notice_uid), notice_uid):
                # Confirmed successful delivery (player message or the
                # authorised Observer mirror for synthetic recipients):
                # mark the exactly-once ledger and permanently restrict
                # راهنما from the NATO role-guess options.
                game.nmnd_night2_dispositions[flag] = "sent"
                if not game.namayande_guide_identity_revealed_to_mafia:
                    game.namayande_guide_identity_revealed_to_mafia = True
                    _audit(
                        game,
                        "night2.guide_identity_revealed_to_mafia",
                        recipient_uid=notice_uid,
                        guide_uid=_guide_identity_uid(game),
                    )
            else:
                # Failed Telegram delivery: the notice was NOT received.
                # The exactly-once marker stays unset so the established
                # retry path re-attempts on the next call, and the
                # Guide-NATO restriction is NOT activated. Drop the dead
                # registration so the retry sends a fresh live message
                # (same pattern as the Soldier-grant delivery retry).
                _audit(
                    game,
                    "night2.mafia_guide_identity_delivery_failed",
                    recipient_uid=notice_uid,
                )
                game.mirror_prompt_messages.pop(
                    _extra_key(game, notice_uid), None
                )
    elif game.nmnd_night2_extra_kind == EXTRA_KIND_SENT and _night2_extra_owed(
        game
    ):
        # Deliver the panel only once the recipient's own main night
        # action is settled; before that, silently wait.
        if game.nmnd_night2_extra_materialized:
            await _send_extra_investigation_panel(
                bot, game, game.nmnd_night2_extra_uid
            )
        elif night2_recipient_main_complete(
            game, game.nmnd_night2_extra_uid
        ):
            game.nmnd_night2_extra_materialized = True
            _audit(
                game,
                "night2.extra_investigation_materialized",
                recipient_uid=game.nmnd_night2_extra_uid,
            )
            await _send_extra_investigation_panel(
                bot, game, game.nmnd_night2_extra_uid
            )
    try:
        manager.persist_snapshot(game, reason="night2_guide_grant")
    except Exception:
        pass
    # A settled recipient obligation may unblock the pending Soldier
    # grant (idempotent reconcile).
    await night2_reconcile_soldier_grant(bot, game)


async def _send_extra_investigation_panel(
    bot: Bot, game: Game, uid: int
) -> None:
    """Panel for the Guide-granted recipient: pick one other alive player."""
    key = _extra_key(game, uid)
    pool = [p for p in _alive_players(game) if p.user_id != uid]
    pend = game.nmnd_night2_extra_target_pending
    rows = _player_rows(
        game, uid, ACT_EXTRA_PICK, pool, [pend] if pend else []
    )
    rows.append(_confirm_row(game, uid, ACT_EXTRA_OK))
    body = (
        "<b>🔎 استعلام کارآگاهی</b>\n\n"
        "راهنما شما را برای گرفتن استعلام امشب انتخاب کرده است.\n\n"
        "از فهرست بازیکنان زیر، فردی را که می\u200cخواهید استعلام بگیرید "
        "انتخاب کنید و سپس دکمه «✅ تأیید» را بزنید."
    )
    await _publish_panel(
        bot, game, uid, key, body, InlineKeyboardMarkup(inline_keyboard=rows)
    )
    _audit(
        game,
        "night2.extra_investigation_dispatched",
        recipient_uid=uid,
    )


async def _send_guide_identity_notice(
    bot: Bot, game: Game, uid: int, guide_uid: int | None
) -> None:
    """Privately tell the Mafia recipient who the Guide is — sent once."""
    names = (
        _button_label(game, game.players.get(guide_uid), guide_uid)
        if guide_uid in game.players
        else "؟"
    )
    body = (
        "<b>🧭 شناسایی راهنما</b>\n\n"
        "از آنجا که راهنما امشب شما را که عضو تیم مافیا هستید انتخاب "
        "کرده است، طبق قوانین بازی هویت او برای شما آشکار می‌شود.\n\n"
        f"<b>نقش راهنمای بازی متعلق است به: {names}</b>"
    )
    await register_mirror_prompt_pair(
        bot,
        game,
        uid,
        _extra_key(game, uid),
        body,
        None,
        send_player=True,
        send_observer=False,
        observer_same_text=False,
        parse_mode="HTML",
    )
    _audit(
        game,
        "night2.mafia_guide_identity_notified",
        recipient_uid=uid,
        guide_uid=guide_uid,
    )


# -- Extra investigation acts -------------------------------------------------


def _night2_extra_allowed(game: Game, uid: int) -> bool:
    return (
        game.nmnd_night2_extra_kind == EXTRA_KIND_SENT
        and game.nmnd_night2_extra_uid == uid
        and game.nmnd_night2_extra_materialized
        and game.nmnd_night2_extra_target_uid is None
        and _may_act(game, uid, uid)
    )


async def _act_extra_pick(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int, tid: int
) -> None:
    if not _night2_extra_allowed(game, uid):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    if tid not in {p.user_id for p in _alive_players(game)} or tid == uid:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    if game.nmnd_night2_extra_target_pending == tid:
        game.nmnd_night2_extra_target_pending = None
    else:
        game.nmnd_night2_extra_target_pending = tid
    await callback.answer("انتخاب شد؛ تأیید کنید.")
    await _send_extra_investigation_panel(bot, game, uid)


async def _act_extra_ok(
    callback: CallbackQuery, bot: Bot, game: Game, gm, uid: int
) -> None:
    if not _night2_extra_allowed(game, uid):
        await callback.answer(ALERT_STALE, show_alert=True)
        return
    target = game.nmnd_night2_extra_target_pending
    if not target:
        await callback.answer("ابتدا یک بازیکن را انتخاب کنید.", show_alert=True)
        return
    tpl = game.players.get(target)
    if tpl is None or not tpl.is_alive:
        await callback.answer(ALERT_INVALID, show_alert=True)
        return
    positive = night2_investigation_is_positive(game, tpl)
    result = INVEST_POSITIVE if positive else INVEST_NEGATIVE
    game.nmnd_night2_extra_target_uid = target
    game.nmnd_night2_extra_target_pending = None
    game.nmnd_night2_extra_result = result
    verdict = "مثبت" if positive else "منفی"
    body = (
        "<b>🧭 نتیجهٔ تحقیق اضافه</b>\n\n"
        f"نتیجهٔ تحقیق دربارهٔ بازیکن انتخاب‌شده: <b>{verdict}</b> است."
    )
    await callback.answer("ثبت شد.")
    await _update_panel(
        bot, game, uid, _extra_key(game, uid), body, None
    )
    _audit(
        game,
        "night2.extra_investigation_confirmed",
        recipient_uid=uid,
        target_uid=target,
        result=result,
    )
    try:
        manager.persist_snapshot(game, reason="night2_extra_investigation")
    except Exception:
        pass
    # A settled extra investigation may unblock the pending Soldier
    # grant (idempotent reconcile).
    await night2_reconcile_soldier_grant(bot, game)
    night2_maybe_finish(game, gm)


# ---------------------------------------------------------------------------
# Internal elimination applier (no publication)
# ---------------------------------------------------------------------------


def night2_apply_elimination(game: Game, uid: int, cause: str) -> dict | None:
    """Apply an internal night elimination without any publication.

    Sets ``is_alive = False``, records a durable elimination entry and
    unlocks the Rebel assassination when the Mafia Boss or Hacker is
    removed. No messages, no reports and no day-flow run here — those are
    the deferred publication/day-transition concerns.
    """
    pl = game.players.get(uid)
    if pl is None or not pl.is_alive:
        return None
    nc = int(game.nmnd_narrator_night_count or 0)
    pl.is_alive = False
    rec = {"uid": uid, "cause": cause, "night": nc}
    game.nmnd_night2_eliminations.append(rec)
    _audit(game, "night2.elimination", uid=uid, cause=cause, night=nc)
    # Room 38: the independent NATO (ناتو) counts as a Rebel
    # assassination unlock trigger too (12/13 compositions — the role
    # cannot exist elsewhere, so 10/11 rooms are unaffected).
    if pl.role in (Role.MAFIA_BOSS, Role.SHIAD, Role.NATO_AGENT):
        if not game.nmnd_night2_rebel_unlocked:
            game.nmnd_night2_rebel_unlocked = True
            _audit(
                game,
                "night2.rebel_assassination_unlocked",
                trigger_uid=uid,
                cause=cause,
            )
    return rec


def night2_eliminations_append_durable(game: Game, rec: dict) -> None:
    """Keep already-recorded elimination entries stable across retries."""
    if rec and rec not in game.nmnd_night2_eliminations:
        game.nmnd_night2_eliminations.append(rec)


# ---------------------------------------------------------------------------
# Deterministic resolution engine
# ---------------------------------------------------------------------------


def night2_run_resolution(game: Game) -> dict:
    """Idempotent, replay-safe deterministic resolution.

    Order: NATO evaluation (correct guess eliminates regardless of
    Doctor/Guardian protection) -> Doctor save validity (incl. Hacker
    nullification and NATO cancellation) -> mine placement -> Guardian
    armor -> Lawyer immunity -> Boss shooting intent -> Rebel state ->
    commit outcomes. Applies internal eliminations only; publication,
    elimination reports and the day transition are explicitly deferred
    (``publication_pending``). Repeated calls, snapshot restores and
    service restarts do not duplicate effects.
    """
    nc = int(game.nmnd_narrator_night_count or 0)
    if game.nmnd_night2_resolved and game.nmnd_night2_resolved_night == nc:
        return dict(game.nmnd_night2_outcome or {})
    if game.nmnd_night2_phase != PENDING_COLLECTED:
        return dict(game.nmnd_night2_outcome or {})

    outcome: dict = {}

    # 1. NATO evaluation ------------------------------------------------------
    # Night-scoped: the durable nato_used flag is the once-per-game menu
    # gate; only the night that actually played NATO may claim activation
    # in its committed outcome (later nights must not inherit the line).
    nato_used_this_night = bool(
        game.nmnd_night2_nato_used
        and int(getattr(game, "nmnd_night2_nato_used_night", None) or -1)
        == nc
    )
    nato_out: dict = {"activated": nato_used_this_night}
    if nato_used_this_night:
        guess = game.nmnd_night2_nato_role
        tuid = game.nmnd_night2_nato_target_uid
        if guess and tuid:
            tpl = game.players.get(tuid)
            success = tpl is not None and tpl.role.value == guess
            eliminated = False
            if success and tpl.is_alive:
                # Doctor protection and Guardian armor never stop NATO.
                night2_apply_elimination(game, tuid, ELIM_CAUSE_NATO)
                eliminated = True
            nato_out.update(
                {
                    "guessed_role": guess,
                    "target_uid": tuid,
                    "success": success,
                    "eliminated": eliminated,
                    "consumed": True,
                }
            )
            _audit(
                game,
                "night2.nato_evaluated",
                guessed_role=guess,
                target_uid=tuid,
                success=success,
                eliminated=eliminated,
                night=nc,
            )
        else:
            nato_out["incomplete"] = True
    outcome["nato"] = nato_out

    # 2. Doctor save ----------------------------------------------------------
    doc_holder = _holder(game, Role.DOCTOR)
    save_target = None if game.nmnd_night2_doctor_cancelled else (
        game.nmnd_night2_doctor_uid
    )
    valid_save = bool(
        save_target is not None
        and (game.players.get(save_target) is not None)
    )
    nullified = bool(
        valid_save
        and doc_holder is not None
        and night2_hack_intercepts(game, doc_holder.user_id, save_target)
    )
    outcome["doctor"] = {
        "cancelled": bool(game.nmnd_night2_doctor_cancelled),
        "cancelled_reason": game.nmnd_night2_doctor_cancel_reason,
        "save_target_uid": save_target,
        "self_save": bool(game.nmnd_night2_doctor_confirmed_self),
        "self_save_charges_used": game.nmnd_night2_doctor_self_saves,
        "valid_save": valid_save,
        "nullified_by_hacker": nullified,
        "protects_shot": bool(valid_save and not nullified),
        # NATO cancellation is distinct from Hacker nullification and is
        # already performed transactionally at activation; nothing here
        # reapplies or double-charges it.
    }

    # 3. Mine placement ---------------------------------------------------
    mine_section: dict = {"attempt_uid": game.nmnd_night2_mine_uid}
    if mine_section["attempt_uid"] is not None:
        if game.nmnd_night2_active_mine_uid is not None:
            mine_section["placed"] = True
        else:
            mine_holder = _holder(game, Role.RUINTAN)
            if mine_holder is None:
                mine_section["placed"] = False
                mine_section["consumed_anyway"] = True
                mine_section["reason"] = "mine_layer_not_present"
            elif night2_hack_intercepts(
                game, mine_holder.user_id, mine_section["attempt_uid"]
            ):
                mine_section["placed"] = False
                mine_section["nullified_by_hacker"] = True
                mine_section["consumed_anyway"] = True
                _audit(
                    game,
                    "night2.mine_place_intercepted",
                    target_uid=mine_section["attempt_uid"],
                    night=nc,
                )
            else:
                game.nmnd_night2_active_mine_uid = mine_section["attempt_uid"]
                game.nmnd_night2_active_mine_night = nc
                mine_section["placed"] = True
                mine_section["active_mine_uid"] = mine_section["attempt_uid"]
                _audit(
                    game,
                    "night2.mine_placed",
                    target_uid=mine_section["attempt_uid"],
                    night=nc,
                )
    elif game.nmnd_night2_dispositions.get("mine_none"):
        mine_section["skipped"] = True
        mine_section["consumed"] = False
    else:
        mine_section["placed"] = False
        mine_section["consumed"] = False
        mine_section["reason"] = "no_attempt"
    # 3.5 NATO-triggered mine (Room 73): a successful NATO elimination of
    # the effectively mined target detonates that mine exactly once.
    # The target is already eliminated by NATO (never re-eliminated);
    # the trigger reuses the established deferred Mafia-casualty flow.
    nato_elim_target = (
        nato_out.get("target_uid")
        if (
            nato_used_this_night
            and nato_out.get("success")
            and nato_out.get("eliminated")
        )
        else None
    )
    if (
        nato_elim_target is not None
        and game.nmnd_night2_active_mine_uid is not None
        and game.nmnd_night2_active_mine_uid == nato_elim_target
    ):
        game.nmnd_night2_active_mine_uid = None
        mine_section["triggered"] = True
        mine_section["triggered_by_nato"] = True
        mine_section["mafia_casualty_deferred"] = True
        game.nmnd_night2_mine_events.append(
            {
                "target_uid": nato_elim_target,
                "night": nc,
                "mode": "nato",
                "triggered": True,
                "neutralized": False,
            }
        )
        _audit(
            game,
            "night2.mine_triggered_by_nato",
            target_uid=nato_elim_target,
            night=nc,
        )
        game.nmnd_night2_mine_casualty_pending = True
        _audit(
            game,
            "night2.mine_casualty_deferred",
            target_uid=nato_elim_target,
            night=nc,
        )
    outcome["mine"] = mine_section

    # 4. Guardian armor ---------------------------------------------------
    guard_target = game.nmnd_night2_guardian_uid
    # An un-consumed armor record from an earlier night is already
    # expired (armor granted during night N protects only the day after
    # night N); it must never silently swallow this night's grant.
    if (
        game.nmnd_night2_armor_uid is not None
        and int(game.nmnd_night2_armor_day or 0) < nc
    ):
        game.nmnd_night2_armor_uid = None
        game.nmnd_night2_armor_day = None
        _audit(game, "night2.guardian_armor_expired", night=nc)
    guard_section: dict = {"attempt_uid": guard_target}
    if night2_guardian_exempt_after_assassin(game):
        # The Rebel's confirmed assassination voids future Guardian
        # grants: no armor is granted this night; the waiting
        # acknowledgement was the night obligation instead.
        guard_section["exempt"] = True
        guard_section["granted"] = False
        guard_section["reason"] = "rebel_assassination_used"
        _audit(game, "night2.guardian_exempt_no_grant", night=nc)
    elif guard_target is not None:
        guard_holder = _holder(game, Role.DETECTIVE)
        if guard_holder is None:
            guard_section["granted"] = False
            guard_section["reason"] = "guardian_not_present"
        elif game.nmnd_night2_armor_uid is not None:
            if game.nmnd_night2_armor_uid == guard_target:
                # Same-target re-protection inside the current window:
                # keep the armor and refresh it to cover the day after
                # THIS night (Room 12: the re-grant was silently
                # absorbed while the stale day stamp made the armor
                # expire before the daytime assassination).
                game.nmnd_night2_armor_day = nc
                guard_section["granted"] = True
                guard_section["refreshed"] = True
                _audit(
                    game,
                    "night2.guardian_armor_regranted",
                    target_uid=guard_target,
                    night=nc,
                )
            else:
                # A different stale target inside the current window can
                # only come from a snapshot-restore replay; this night's
                # pick is authoritative.
                game.nmnd_night2_armor_uid = guard_target
                game.nmnd_night2_armor_day = nc
                guard_section["granted"] = True
                guard_section["active"] = True
                guard_section["protects_day_after_night"] = nc
                _audit(
                    game,
                    "night2.guardian_armor_granted",
                    target_uid=guard_target,
                    night=nc,
                )
        elif night2_hack_intercepts(game, guard_holder.user_id, guard_target):
            guard_section["granted"] = False
            guard_section["nullified_by_hacker"] = True
            guard_section["consumed_anyway"] = True
            _audit(
                game,
                "night2.guardian_armor_intercepted",
                target_uid=guard_target,
                night=nc,
            )
        else:
            game.nmnd_night2_armor_uid = guard_target
            game.nmnd_night2_armor_day = nc
            guard_section["granted"] = True
            guard_section["active"] = True
            guard_section["protects_day_after_night"] = nc
            _audit(
                game,
                "night2.guardian_armor_granted",
                target_uid=guard_target,
                night=nc,
            )
    outcome["guardian"] = guard_section

    # 5. Lawyer immunity --------------------------------------------------
    law_target = game.nmnd_night2_lawyer_uid
    law_section: dict = {"attempt_uid": law_target}
    if law_target is not None:
        law_holder = _holder(game, Role.HUNTER)
        if law_holder is None:
            law_section["granted"] = False
            law_section["reason"] = "lawyer_not_present"
        elif game.nmnd_night2_lawyer_immune_uid is not None:
            law_section["granted"] = True
        elif night2_hack_intercepts(game, law_holder.user_id, law_target):
            law_section["granted"] = False
            law_section["nullified_by_hacker"] = True
            law_section["consumed_anyway"] = True
            _audit(
                game,
                "night2.lawyer_immunity_intercepted",
                target_uid=law_target,
                night=nc,
            )
        else:
            game.nmnd_night2_lawyer_immune_uid = law_target
            game.nmnd_night2_lawyer_immune_day = nc
            law_section["granted"] = True
            law_section["protects_day_after_night"] = nc
            _audit(
                game,
                "night2.lawyer_immunity_granted",
                target_uid=law_target,
                night=nc,
            )
    elif game.nmnd_night2_dispositions.get("lawyer_none"):
        law_section["skipped"] = True
        law_section["consumed"] = False
    outcome["lawyer"] = law_section

    # 5.5 Soldier disposition + temporary Sniper shot ---------------------
    soldier = _holder(game, Role.SOLDIER)
    grant_status = game.nmnd_night2_soldier_grant_status
    sniper_out: dict = {
        "soldier_uid": soldier.user_id if soldier is not None else None,
        "grant_status": grant_status,
        "recipient_uid": game.nmnd_night2_soldier_uid,
        "soldier_used": bool(game.nmnd_night2_soldier_used),
        "used_night": game.nmnd_night2_soldier_used_night,
        "sniper_night": game.nmnd_night2_sniper_night,
        "skipped": bool(game.nmnd_night2_sniper_skipped),
        "target_uid": None,
        "eliminated_uid": None,
        "sniper_eliminated": False,
        "reason": None,
        "deferred": False,
    }
    if grant_status == GRANT_STATUS_MAFIA and soldier is not None:
        # Mafia recipient: no grant, no announcement — the Soldier is
        # eliminated by the established resolution machinery.
        night2_apply_elimination(
            game, soldier.user_id, ELIM_CAUSE_SOLDIER_MAFIA
        )
        sniper_out["eliminated_uid"] = soldier.user_id
        sniper_out["reason"] = "soldier_mafia_target"
        _audit(
            game,
            "night2.soldier_mafia_target_eliminated",
            soldier_uid=soldier.user_id,
            target_uid=game.nmnd_night2_soldier_uid,
            night=nc,
        )
    if (
        grant_status == GRANT_STATUS_DELIVERED
        and game.nmnd_night2_sniper_night == nc
        and not game.nmnd_night2_sniper_skipped
        and game.nmnd_night2_sniper_target_uid is not None
    ):
        tuid = game.nmnd_night2_sniper_target_uid
        sniper_uid = game.nmnd_night2_soldier_uid
        tpl = game.players.get(tuid)
        sniper_out["target_uid"] = tuid
        if tpl is None or not tpl.is_alive or sniper_uid is None:
            sniper_out["reason"] = "invalid_target"
        elif tpl.role == Role.MAFIA_BOSS:
            # Shooting the Boss: both survive (no elimination).
            sniper_out["reason"] = "boss_immune"
        elif _is_mafia_member(game, tpl):
            # Rebel/Hacker/independent NATO (or a converted town player):
            # the target is eliminated, the Sniper survives. When the
            # committed plain shot is about to detonate an active mine,
            # the elimination itself is DEFERRED so the Mafia-sacrifice
            # roster still lists this living member (Room 32 ordering).
            sniper_out["reason"] = "mafia_member_eliminated"
            game.nmnd_night2_sniper_mafia_kill_night = nc
            if night2_mine_casualty_expected(game):
                sniper_out["deferred"] = True
                game.nmnd_night2_sniper_deferred_elim_uid = tuid
            else:
                night2_apply_elimination(game, tuid, ELIM_CAUSE_SNIPER)
                sniper_out["eliminated_uid"] = tuid
        else:
            # Town target: the target survives, the Sniper is eliminated.
            night2_apply_elimination(game, sniper_uid, ELIM_CAUSE_SNIPER)
            sniper_out["eliminated_uid"] = sniper_uid
            sniper_out["sniper_eliminated"] = True
            sniper_out["reason"] = "town_target"
        _audit(
            game,
            "night2.sniper_shot_resolved",
            sniper_uid=sniper_uid,
            target_uid=tuid,
            eliminated_uid=sniper_out["eliminated_uid"],
            reason=sniper_out["reason"],
            deferred=bool(sniper_out.get("deferred")),
            night=nc,
        )
    game.nmnd_night2_sniper_result = sniper_out
    outcome["soldier_sniper"] = sniper_out

    # 6. Boss shooting intent ---------------------------------------------
    mode = game.nmnd_night2_boss_mode
    if mode in (BOSS_MODE_SHOT_PLAIN, BOSS_MODE_SHOT_NEUTRALIZED):
        outcome["shot"] = {
            "mode": mode,
            "resolved": bool(game.nmnd_night2_shot_resolved),
            "target_uid": game.nmnd_night2_shot_target_uid,
            "pending_target": not game.nmnd_night2_shot_resolved,
        }
    elif mode == BOSS_MODE_NATO:
        outcome["shot"] = {"skipped": True, "reason": "nato_mode"}
    else:
        outcome["shot"] = {"mode": None}

    # 7. Guide aftermath + extra investigation ----------------------------
    outcome["guide"] = {
        "recipient_uid": game.nmnd_night2_guide_uids.get(nc),
        "grant_kind": game.nmnd_night2_extra_kind,
        "extra_uid": game.nmnd_night2_extra_uid,
        "extra_target_uid": game.nmnd_night2_extra_target_uid,
        "extra_result": game.nmnd_night2_extra_result,
    }

    # 8. Hacker + Rebel surface -------------------------------------------
    pair = list(game.nmnd_night2_hacker_uids or [])
    outcome["hacker"] = {
        "confirmed": len(pair) == 2,
        "source_uid": pair[0] if len(pair) == 2 else None,
        "destination_uid": pair[1] if len(pair) == 2 else None,
    }
    rebel = _holder(game, Role.NATO)
    outcome["rebel"] = {
        "unlocked": bool(game.nmnd_night2_rebel_unlocked),
        "assassin_used": bool(game.nmnd_night2_rebel_assassin_used),
        "assassin_available": night2_rebel_assassination_available(game),
        "rebel_uid": rebel.user_id if rebel is not None else None,
    }

    # Explicit safe boundary: publication/day-transition rules are
    # deliberately undecided product rules.
    pending_items = ["night_results_publication"]
    if game.nmnd_night2_mine_casualty_pending:
        pending_items.append("mine_casualty_selection")
    if mode in (BOSS_MODE_SHOT_PLAIN, BOSS_MODE_SHOT_NEUTRALIZED) and not (
        game.nmnd_night2_shot_resolved
    ):
        pending_items.append("shot_target_selection")
    outcome["publication"] = {"pending": True, "pending_items": pending_items}

    game.nmnd_night2_outcome = outcome
    game.nmnd_night2_outcome_committed = True
    game.nmnd_night2_resolved = True
    game.nmnd_night2_resolved_night = nc
    game.nmnd_night2_phase = PENDING_RESOLVED
    game.nmnd_night2_publication_pending = True
    _audit(
        game,
        "night2.resolution_committed",
        night=nc,
        pending_items=list(pending_items),
    )
    # The confirmed Boss shot intent is consumed by the deterministic
    # resolver right after the outcome commit (Doctor/mine precedence
    # requires the committed doctor section). Internal only — no messages.
    if (
        mode in (BOSS_MODE_SHOT_PLAIN, BOSS_MODE_SHOT_NEUTRALIZED)
        and game.nmnd_night2_shot_target_uid is not None
        and not game.nmnd_night2_shot_resolved
        and game.phase != Phase.ENDED
    ):
        night2_resolve_shot_intent(game, game.nmnd_night2_shot_target_uid)
    try:
        manager.persist_snapshot(game, reason="night2_resolution_committed")
    except Exception:
        pass
    return dict(game.nmnd_night2_outcome or {})


# ---------------------------------------------------------------------------
# Boss shooting: deterministic intent resolver (no Telegram output)
# ---------------------------------------------------------------------------


def night2_resolve_shot_intent(game: Game, target_uid: int) -> dict:
    """Deterministic Boss-shot resolution for an already validated intent.

    Validates the shooting mode, target existence/aliveness and
    idempotency, then applies, in order:

    1. a shot WITH neutralization against an active mine neutralizes
       and consumes the mine, while the Doctor save still resolves the
       target's survival normally (no Mafia-casualty selection);
    2. a shot WITHOUT neutralization against an active mine detonates
       and consumes the mine; the mined target is eliminated regardless
       of any Doctor save, and the existing Mafia-casualty selection is
       deferred to its established flow;
    3. otherwise a valid Doctor save protects the target;
    4. otherwise the target is eliminated.

    Guardian armor is irrelevant to the night shot by rule. Pure state
    mutation + audit; no messages, no publication, no day-flow.
    """
    nc = int(game.nmnd_narrator_night_count or 0)
    mode = game.nmnd_night2_boss_mode
    if not nam10_night2_mode(game) or mode not in (
        BOSS_MODE_SHOT_PLAIN,
        BOSS_MODE_SHOT_NEUTRALIZED,
    ):
        return {"accepted": False, "reason": "no_shoot_mode"}
    if not game.nmnd_night2_outcome_committed:
        # Doctor-save validity is only authoritative after the deterministic
        # resolution committed; a pre-resolution call must never guess.
        return {"accepted": False, "reason": "resolution_not_committed"}
    if game.phase == Phase.ENDED:
        return {"accepted": False, "reason": "game_ended"}
    if game.nmnd_night2_shot_resolved:
        return dict(
            game.nmnd_night2_shot_result
            or {"accepted": True, "resolved": True, "repeat": True}
        )
    target = game.players.get(target_uid)
    if target is None or not target.is_alive:
        return {"accepted": False, "reason": "invalid_target"}

    # FINAL matrix: neutralization consumes the mine but keeps the
    # Doctor save meaningful; a plain shot detonates the mine and the
    # mined target dies regardless of the Doctor.
    doc_section = (game.nmnd_night2_outcome or {}).get("doctor") or {}
    protected_by_doctor = bool(
        doc_section.get("protects_shot")
        and doc_section.get("save_target_uid") == target_uid
    )
    has_mine = (
        game.nmnd_night2_active_mine_uid == target_uid
        and game.nmnd_night2_active_mine_uid is not None
        and target.is_alive
    )
    result: dict = {
        "accepted": True,
        "mode": mode,
        "target_uid": target_uid,
        "night": nc,
        "protected_by_doctor": False,
        "had_mine": has_mine,
        "doctor_save_ineffective": False,
        "eliminated": False,
    }
    if has_mine and mode == BOSS_MODE_SHOT_NEUTRALIZED:
        # FINAL matrix — WITH neutralization: the mine is neutralized
        # and consumed exactly once, the Mafia-casualty selection never
        # runs, and the Doctor save still resolves the target's
        # survival normally.
        game.nmnd_night2_active_mine_uid = None
        result["mine_disposition"] = "neutralized"
        game.nmnd_night2_mine_events.append(
            {
                "target_uid": target_uid,
                "night": nc,
                "mode": mode,
                "triggered": False,
                "neutralized": True,
            }
        )
        _audit(
            game,
            "night2.mine_neutralized_by_shot",
            target_uid=target_uid,
            night=nc,
            mode=mode,
        )
        if protected_by_doctor:
            result["protected_by_doctor"] = True
        else:
            night2_apply_elimination(
                game, target_uid, ELIM_CAUSE_MAFIA_SHOT
            )
            result["eliminated"] = True
    elif has_mine:
        # FINAL matrix — WITHOUT neutralization: the mine detonates and
        # is consumed exactly once; the mined target is eliminated
        # regardless of any Doctor save, and the existing Mafia-casualty
        # selection is deferred to its established flow.
        result["doctor_save_ineffective"] = protected_by_doctor
        night2_apply_elimination(game, target_uid, ELIM_CAUSE_MAFIA_SHOT)
        result["eliminated"] = True
        game.nmnd_night2_active_mine_uid = None
        result["mine_disposition"] = "triggered"
        game.nmnd_night2_mine_events.append(
            {
                "target_uid": target_uid,
                "night": nc,
                "mode": mode,
                "triggered": True,
                "neutralized": False,
            }
        )
        _audit(
            game,
            "night2.mine_triggered",
            target_uid=target_uid,
            night=nc,
            mode=mode,
        )
        game.nmnd_night2_mine_casualty_pending = True
        result["mine_casualty_pending"] = True
        # Explicit deferred-consequence marker: the Mafia-casualty
        # side effect is handled by the established mine-casualty
        # flow; it must not block the internal resolution here.
        if isinstance(game.nmnd_night2_outcome, dict):
            mine_out = dict(game.nmnd_night2_outcome.get("mine") or {})
            mine_out["triggered"] = True
            mine_out["mafia_casualty_deferred"] = True
            game.nmnd_night2_outcome["mine"] = mine_out
        _audit(
            game,
            "night2.mine_casualty_deferred",
            target_uid=target_uid,
            night=nc,
        )
    elif protected_by_doctor:
        # Survivor: valid Doctor save without any mine involved.
        result["protected_by_doctor"] = True
        result["mine_disposition"] = "kept_intact"
    else:
        night2_apply_elimination(game, target_uid, ELIM_CAUSE_MAFIA_SHOT)
        result["eliminated"] = True

    game.nmnd_night2_shot_target_uid = target_uid
    game.nmnd_night2_shot_resolved = True
    game.nmnd_night2_shot_result = result
    if isinstance(game.nmnd_night2_outcome, dict):
        shot = dict(game.nmnd_night2_outcome.get("shot") or {})
        shot.update(
            {
                "resolved": True,
                "target_uid": target_uid,
                "pending_target": False,
                "result": result,
            }
        )
        pub = dict(game.nmnd_night2_outcome.get("publication") or {})
        items = [
            x for x in (pub.get("pending_items") or [])
            if x != "shot_target_selection"
        ]
        if game.nmnd_night2_mine_casualty_pending and (
            "mine_casualty_selection" not in items
        ):
            items.append("mine_casualty_selection")
        pub["pending_items"] = items
        game.nmnd_night2_outcome["shot"] = shot
        game.nmnd_night2_outcome["publication"] = pub
    _audit(
        game,
        "night2.shot_intent_resolved",
        target_uid=target_uid,
        mode=mode,
        eliminated=result["eliminated"],
        protected_by_doctor=result["protected_by_doctor"],
        doctor_save_ineffective=result["doctor_save_ineffective"],
        night=nc,
    )
    try:
        manager.persist_snapshot(game, reason="night2_shot_intent_resolved")
    except Exception:
        pass
    return dict(result)


# ---------------------------------------------------------------------------
# Durable effect predicates (day-flow integration deliberately deferred)
# ---------------------------------------------------------------------------


def night2_guardian_armor_active(
    game: Game, uid: int, *, day_after_night: int
) -> bool:
    """Next-day Guardian armor state for ``uid``.

    Granted during night ``N`` protects the day immediately following
    night ``N``. Callers pass the narrator night count of the night whose
    following day is in progress. Expiry is baked into the day comparison;
    the armor never protects against the night shot or a successful NATO.
    """
    return (
        game.nmnd_night2_armor_uid == uid
        and game.nmnd_night2_armor_day == day_after_night
        and game.players.get(uid) is not None
    )


def night2_consume_guardian_armor(
    game: Game, uid: int, *, day_after_night: int
) -> bool:
    """Consume the current armor when it blocks an assassination."""
    if not night2_guardian_armor_active(
        game, uid, day_after_night=day_after_night
    ):
        return False
    game.nmnd_night2_armor_uid = None
    game.nmnd_night2_armor_day = None
    _audit(
        game,
        "night2.guardian_armor_consumed",
        uid=uid,
        night=day_after_night,
    )
    return True


def night2_lawyer_defense_immunity(
    game: Game, uid: int, *, day_after_night: int
) -> bool:
    """Next-day Lawyer effect: the protected player must not enter defense
    at all on the following day. Day-targeting/defense integration stays
    deferred; only the durable predicate is exposed."""
    return (
        game.nmnd_night2_lawyer_immune_uid == uid
        and game.nmnd_night2_lawyer_immune_day == day_after_night
        and game.players.get(uid) is not None
    )


def night2_mine_casualty_pending(game: Game) -> bool:
    return bool(game.nmnd_night2_mine_casualty_pending)


def night2_mine_casualty_expected(game: Game) -> bool:
    """Deterministic preview: will the committed plain Boss shot
    detonate the active mine and require a Mafia-casualty selection?

    Mirrors exactly the trigger condition of
    ``night2_resolve_shot_intent`` (plain mode + active mine on a living
    confirmed target; neutralized mode never detonates). Used before the
    commit to defer the temporary-Sniper elimination.
    """
    if game.nmnd_night2_mine_casualty_pending:
        return True
    if game.nmnd_night2_boss_mode != BOSS_MODE_SHOT_PLAIN:
        return False
    tuid = game.nmnd_night2_shot_target_uid
    if tuid is None:
        return False
    tpl = game.players.get(tuid)
    if tpl is None or not tpl.is_alive:
        return False
    return (
        game.nmnd_night2_active_mine_uid is not None
        and game.nmnd_night2_active_mine_uid == tuid
    )


def night2_apply_deferred_sniper_elimination(game: Game) -> None:
    """Apply the deferred temporary-Sniper elimination (Room 32 order).

    Runs strictly AFTER the mine-casualty selection settled (or after the
    unresolvable fallback). Consumes the pending uid first, so replayed
    publications/restarts can never apply it twice. When the sacrifice
    selected the very same Mafia member, that player is already out:
    one elimination, both contributing causes recorded.
    """
    nc = int(game.nmnd_narrator_night_count or 0)
    d_uid = game.nmnd_night2_sniper_deferred_elim_uid
    game.nmnd_night2_sniper_deferred_elim_uid = None
    if d_uid is None:
        return
    out = dict(game.nmnd_night2_sniper_result or {})
    tpl = game.players.get(d_uid)
    already_dead = tpl is None or not tpl.is_alive
    if not already_dead:
        night2_apply_elimination(game, d_uid, ELIM_CAUSE_SNIPER)
    out["eliminated_uid"] = d_uid
    out["reason"] = "mafia_member_eliminated"
    out["deferred"] = False
    out["shared_with_mine_casualty"] = already_dead
    game.nmnd_night2_sniper_result = out
    outcome = game.nmnd_night2_outcome
    if isinstance(outcome, dict):
        outcome["soldier_sniper"] = dict(out)
    _audit(
        game,
        "night2.sniper_deferred_elim_applied",
        uid=d_uid,
        already_dead=already_dead,
        night=nc,
    )


def night2_mafia_shot_settled(game: Game) -> bool:
    """True when every mandatory Mafia main action is complete.

    Covers the active shooter's shot-target/NATO stages, the independent
    NATO recipient's two-stage selections (12/13) and a Hacker shooter's
    inherited shot. Waiting acknowledgements are deliberately excluded:
    they are not main choices and must never deadlock the delayed
    Guide-identity disclosure.
    """
    if not nam10_night2_mode(game):
        return True
    keys = night2_required_keys(game)
    shooter = night2_active_shooter(game)
    if shooter is not None and shooter.role.value in keys:
        return False
    if _nato_independent_mode_pending(game):
        return False
    if Role.SHIAD.value in keys:
        return False
    return True


def night2_publication_pending(game: Game) -> bool:
    return bool(game.nmnd_night2_publication_pending)


def night2_rebel_assassination_unlocked(game: Game) -> bool:
    return bool(game.nmnd_night2_rebel_unlocked)


def night2_guardian_exempt_after_assassin(game: Game) -> bool:
    """Guardian exemption once the Rebel ACTUALLY used the assassination.

    Durable ``nmnd_night2_rebel_assassin_used`` is only ever set by the
    committed ``night2_rebel_assassination_effect`` (which always removes
    the Rebel as part of the effect). Eliminating the Rebel through day
    voting, a night shot, a mine casualty or any other route never sets
    it, so those keep the Guardian's normal target-selection panel.
    """
    return bool(getattr(game, "nmnd_night2_rebel_assassin_used", False))


def night2_rebel_assassination_available(game: Game) -> bool:
    """Unlocked, not yet used and the Rebel currently alive. The daytime
    gating (only before daily voting starts) belongs to the deferred
    day-flow integration and is intentionally not assumed here."""
    if not night2_rebel_assassination_unlocked(game):
        return False
    if game.nmnd_night2_rebel_assassin_used:
        return False
    rebel = _holder(game, Role.NATO)
    return rebel is not None


def night2_rebel_assassination_effect(game: Game, target_uid: int) -> dict:
    """Apply a confirmed daytime Rebel assassination intent.

    Durable eligibility/once-per-game/effect rules only — the daytime UI
    and announcement wording belong to the deferred day-flow integration,
    so no Telegram messages are produced here. Order: the opportunity is
    consumed first, the Rebel always dies, then the target either dies or
    survives on Guardian immunity / current armor.
    """
    nc = int(game.nmnd_narrator_night_count or 0)
    if not night2_rebel_assassination_available(game):
        return {"accepted": False, "reason": "assassination_unavailable"}
    rebel = _holder(game, Role.NATO)
    if rebel is None:
        return {"accepted": False, "reason": "rebel_not_present"}
    target = game.players.get(target_uid)
    if target is None or not target.is_alive:
        return {"accepted": False, "reason": "invalid_target"}
    if target.user_id == rebel.user_id:
        return {"accepted": False, "reason": "rebel_self_target"}

    game.nmnd_night2_rebel_assassin_used = True
    game.nmnd_night2_rebel_assassin_used_night = nc
    night2_apply_elimination(
        game, rebel.user_id, ELIM_CAUSE_REBEL_ASSASSIN_SELF
    )
    result: dict = {
        "accepted": True,
        "night": nc,
        "rebel_uid": rebel.user_id,
        "target_uid": target_uid,
        "target_eliminated": False,
        "reason": None,
        "armor_consumed": False,
    }
    if target.role == Role.DETECTIVE:
        # Guardian themselves is intrinsically immune.
        result["reason"] = "guardian_immune"
    elif night2_consume_guardian_armor(
        game, target_uid, day_after_night=nc
    ):
        result["reason"] = "armor_absorbed"
        result["armor_consumed"] = True
    else:
        night2_apply_elimination(game, target_uid, ELIM_CAUSE_REBEL_ASSASSIN)
        result["target_eliminated"] = True
        result["reason"] = "eliminated"
    game.nmnd_night2_rebel_assassin_result = result
    if isinstance(game.nmnd_night2_outcome, dict):
        game.nmnd_night2_outcome["rebel_assassination"] = dict(result)
        pub = dict(game.nmnd_night2_outcome.get("publication") or {})
        pub["pending_items"] = sorted(
            set((pub.get("pending_items") or []) + ["rebel_assassination_publication"])
        )
        game.nmnd_night2_outcome["publication"] = pub
    _audit(
        game,
        "night2.rebel_assassination_effect",
        rebel_uid=rebel.user_id,
        target_uid=target_uid,
        target_eliminated=result["target_eliminated"],
        reason=result["reason"],
        night=nc,
    )
    # Day-scoped durable record (Room 93): daytime assassinations were
    # previously only night-stamped, so the end-of-game timeline could
    # not attribute them to the actual day and dropped them entirely.
    _audit(
        game,
        "night2.rebel_assassination_day_elim",
        rebel_uid=rebel.user_id,
        target_uid=target_uid,
        target_eliminated=result["target_eliminated"],
        reason=result["reason"],
        host_day=int(getattr(game, "nmnd_narrator_host_day", 0) or 0),
        night=nc,
    )
    try:
        manager.persist_snapshot(game, reason="night2_rebel_assassination")
    except Exception:
        pass
    return dict(result)
