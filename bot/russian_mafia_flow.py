"""جریان روز/شب مافیای روسی و آینهٔ ناظر. قوانین سناریوهای دیگر را صدا نمی‌زند."""

from __future__ import annotations

import html

import asyncio
import logging

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.game import is_synthetic_player_uid
from bot.models import Game, Phase, Role
from bot.observer_delivery import (
    PlayerMirrorCb,
    _try_edit_mirror_message,
    register_mirror_prompt_pair,
    try_claim_mirror_ui,
    update_mirror_prompt_pair,
)
from bot.russian_mafia import (
    HOST_HELPER_MODE,
    ROLE_GODFATHER,
    ROLE_TERROR,
    STALE_ACTION_FA,
    alive_players,
    apply_night_resolution,
    detective_alignment,
    doctor_self_save_allowed,
    find_alive_role,
    initialize_russian_mafia_state,
    is_russian_host_helper,
    is_russian_mafia_game,
    is_russian_mafia_role,
    mafia_shot_holder,
    explain_russian_mafia_night_readiness,
    night_ready_to_resolve,
    night_slots_complete,
    required_night_slots,
    required_waiting_player_ids,
    waiting_acks_complete,
    reset_russian_day_actions,
    reset_russian_night_actions,
    record_russian_elimination,
    ensure_russian_doctor_night_capacity,
    russian_alive_player_count,
    russian_doctor_heal_capacity,
    russian_doctor_self_save_limit,
    russian_mafia_observer_registered,
    russian_role_label_fa,
    winner_of,
)
from bot.tg_send import safe_callback_answer, safe_send_message

logger = logging.getLogger(__name__)

_ROOM_LOCKS: dict[str, asyncio.Lock] = {}
_ACTS = frozenset({
    "zrm_shot",
    "zrm_doc",
    "zrm_det",
    "zrm_ter",
    "zok_shot",
    "zok_doc",
    "zok_det",
    "zok_ter",
    "zbk_shot",
    "zbk_doc",
    "zbk_det",
    "zbk_ter",
    "zrm_cit",
})
_SELECT_ACTS = {
    "zrm_shot": "mafia",
    "zrm_doc": "doctor",
    "zrm_det": "detective",
    "zrm_ter": "terror",
}
_CONFIRM_ACTS = {
    "zok_shot": "mafia",
    "zok_doc": "doctor",
    "zok_det": "detective",
    "zok_ter": "terror",
}
_BACK_ACTS = {
    "zbk_shot": "mafia",
    "zbk_doc": "doctor",
    "zbk_det": "detective",
    "zbk_ter": "terror",
}
_SLOT_ACT = {"mafia": "zrm_shot", "doctor": "zrm_doc", "detective": "zrm_det", "terror": "zrm_ter"}



def room_lock(room_code: str) -> asyncio.Lock:
    return _ROOM_LOCKS.setdefault(room_code, asyncio.Lock())


def russian_mirror_act(act: str) -> bool:
    return act in _ACTS


class _UseCurrentGeneration:
    """فراخوان داخلی نسل جاری را می‌خواهد. دکمهٔ تلگرام باید نسل را صریح بفرستد."""


_USE_CURRENT = _UseCurrentGeneration()


def _expected_generation(game: Game, slot: str) -> int:
    if slot == "terror":
        return int(game.russian_mafia_day_index)
    return int(game.russian_mafia_night_index)


def _ui_key(game: Game, slot: str) -> str:
    kind = "day" if slot == "terror" else "night"
    return (
        f"russian:{game.room_code}:{kind}:{_expected_generation(game, slot)}:{slot}"
    )


def _legacy_ui_key(room: str, slot: str) -> str:
    return f"russian:{room}:{slot}"


def generation_from_callback_rid(rid: str | None) -> int | None:
    if rid is None or rid == "":
        return None
    try:
        return int(rid)
    except ValueError:
        return None


def _slot_for_act(act: str) -> str:
    mapping = {**_SELECT_ACTS, **_CONFIRM_ACTS, **_BACK_ACTS, "zrm_ter": "terror"}
    return mapping[act]


def _coerce_mirror_ref(ref: object) -> tuple[int, int] | None:
    if isinstance(ref, dict) and "__tuple__" in ref:
        ref = ref["__tuple__"]
    if isinstance(ref, (tuple, list)) and len(ref) >= 2:
        try:
            return int(ref[0]), int(ref[1])
        except (TypeError, ValueError):
            return None
    return None


def _panel_has_ref(game: Game, key: str) -> bool:
    entry = game.mirror_prompt_messages.get(key)
    if not isinstance(entry, dict):
        return False
    return any(
        _coerce_mirror_ref(entry.get(role)) is not None
        for role in ("player", "observer")
    )


def _current_panel_open(game: Game, slot: str) -> bool:
    base = _ui_key(game, slot)
    return _panel_has_ref(game, base) or _panel_has_ref(game, base + ":obs")


def _alive_targets(
    game: Game,
    *,
    exclude: int | None = None,
    exclude_uids: set[int] | frozenset[int] | None = None,
) -> list:
    skipped = set(exclude_uids or ())
    if exclude is not None:
        skipped.add(exclude)
    rows = []
    for player in sorted(
        alive_players(game),
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    ):
        if player.user_id in skipped:
            continue
        rows.append(player)
    return rows


def _button(
    game: Game,
    *,
    act: str,
    as_uid: int,
    target_uid: int,
    label: str,
    mirror: bool,
    generation: int,
):
    if mirror:
        data = PlayerMirrorCb(
            code=game.room_code,
            act=act,
            as_uid=as_uid,
            tid=target_uid,
            rid=str(generation),
        ).pack()
    else:
        data = f"rmf:{game.room_code}:{act}:{as_uid}:{target_uid}:{generation}"
    return InlineKeyboardButton(text=label[:40], callback_data=data)


def action_keyboard(
    game: Game,
    *,
    act: str,
    as_uid: int,
    exclude: int | None,
    mirror: bool,
    exclude_uids: set[int] | frozenset[int] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for player in _alive_targets(game, exclude=exclude, exclude_uids=exclude_uids):
        seat = player.seat if player.seat is not None else player.user_id
        row.append(
            _button(
                game,
                act=act,
                as_uid=as_uid,
                target_uid=player.user_id,
                label=f"{seat}. {player.full_name}",
                mirror=mirror,
                generation=_expected_generation(game, _slot_for_act(act)),
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows or [[
        InlineKeyboardButton(text="هدف زنده‌ای نیست", callback_data="noop")
    ]])


def parse_player_action(data: str) -> tuple[str, str, int, int, int | None] | None:
    """نسلِ غایب (دکمه‌های شب/روز قبل) None است و تأیید نمی‌شود."""
    parts = (data or "").split(":")
    if len(parts) not in (5, 6) or parts[0] != "rmf":
        return None
    room, act, as_raw, tid_raw = parts[1], parts[2], parts[3], parts[4]
    if act not in _ACTS:
        return None
    try:
        generation = int(parts[5]) if len(parts) == 6 else None
        return room, act, int(as_raw), int(tid_raw), generation
    except ValueError:
        return None


def _actor_allowed(game: Game, actor_uid: int, as_uid: int) -> bool:
    if actor_uid == as_uid and as_uid in game.players:
        return not is_synthetic_player_uid(as_uid)
    return (
        russian_mafia_observer_registered(game)
        and actor_uid == game.observer_user_id
        and as_uid in game.players
    )


def _log_completed(slot: str, *, by_observer: bool) -> None:
    who = "observer" if by_observer else "player"
    if slot == "doctor":
        logger.info("Russian Mafia Doctor action completed by %s", who)
    elif slot == "detective":
        logger.info("Russian Mafia Detective action completed by %s", who)
    elif slot == "terror":
        logger.info("Russian Mafia Terror action completed by %s", who)
    elif slot == "mafia":
        logger.info("Russian Mafia Mafia-shot action completed by %s", who)


def try_confirm_action(
    game: Game,
    *,
    slot: str,
    actor_uid: int,
    as_uid: int,
    target_uid: int,
    generation: int | None | _UseCurrentGeneration = _USE_CURRENT,
) -> str:
    """ok / stale / forbidden / rejected. اولین تأیید معتبر برنده است."""
    if not _actor_allowed(game, actor_uid, as_uid):
        return "forbidden"
    if game.phase == Phase.ENDED:
        return "stale"
    target = game.players.get(target_uid)
    if target is None or not target.is_alive:
        return "rejected"

    expected = _expected_generation(game, slot)
    if isinstance(generation, _UseCurrentGeneration):
        generation = expected
    if generation != expected:
        logger.info(
            "Russian Mafia room=%s rejected stale %s callback generation=%s expected=%s",
            game.room_code,
            slot,
            generation,
            expected,
        )
        return "stale"

    if slot == "mafia":
        if game.phase != Phase.NIGHT or game.russian_mafia_mafia_confirmed:
            return "stale"
        holder = mafia_shot_holder(game)
        if holder is None or holder.user_id != as_uid:
            return "forbidden"
    elif slot == "doctor":
        if game.phase != Phase.NIGHT or game.russian_mafia_doctor_confirmed:
            return "stale"
        doctor = find_alive_role(game, Role.DOCTOR)
        if doctor is None or doctor.user_id != as_uid:
            return "forbidden"
        if target_uid in (game.russian_mafia_doctor_targets or []):
            return "rejected"
        if not doctor_self_save_allowed(game, as_uid, target_uid):
            return "rejected"
    elif slot == "detective":
        if game.phase != Phase.NIGHT or game.russian_mafia_detective_confirmed:
            return "stale"
        detective = find_alive_role(game, Role.DETECTIVE)
        if detective is None or detective.user_id != as_uid:
            return "forbidden"
    elif slot == "terror":
        if not game.russian_mafia_terror_day_active or game.russian_mafia_terror_confirmed:
            return "stale"
        if game.phase not in (Phase.DAY_DISCUSSION, Phase.DAY_VOTE):
            return "stale"
        terror = find_alive_role(game, ROLE_TERROR)
        if terror is None or terror.user_id != as_uid:
            return "forbidden"
        if target_uid == as_uid:
            return "rejected"
    else:
        return "forbidden"

    ui_key = _ui_key(game, slot)
    doctor_partial = (
        slot == "doctor"
        and bool(game.russian_mafia_doctor_targets)
        and not game.russian_mafia_doctor_confirmed
    )
    if not doctor_partial:
        claim = try_claim_mirror_ui(game, ui_key, actor_uid, as_uid)
        if claim in ("already_claimed", "dup_self", "forbidden"):
            return "stale" if claim != "forbidden" else "forbidden"

    by_observer = actor_uid == game.observer_user_id and actor_uid != as_uid
    if slot == "mafia":
        game.russian_mafia_mafia_target = target_uid
        game.russian_mafia_mafia_confirmed = True
        holder = mafia_shot_holder(game)
        game.russian_mafia_mafia_action_holder = (
            holder.user_id if holder is not None else as_uid
        )
    elif slot == "doctor":
        capacity = ensure_russian_doctor_night_capacity(game)
        targets = list(game.russian_mafia_doctor_targets or [])
        if target_uid in targets:
            return "rejected"
        if not doctor_self_save_allowed(game, as_uid, target_uid):
            return "rejected"
        targets.append(target_uid)
        game.russian_mafia_doctor_targets = targets
        game.russian_mafia_doctor_target = targets[0]
        if target_uid == as_uid:
            game.russian_mafia_doctor_self_save_count += 1
        game.russian_mafia_doctor_confirmed = len(targets) >= capacity
    elif slot == "detective":
        game.russian_mafia_detective_target = target_uid
        game.russian_mafia_detective_confirmed = True
        investigated = game.players.get(target_uid)
        game.russian_mafia_detective_alignment = detective_alignment(
            investigated.role if investigated else None
        )
    elif slot == "terror":
        game.russian_mafia_terror_target = target_uid
        game.russian_mafia_terror_confirmed = True
        game.russian_mafia_terror_day_active = False
    _log_completed(slot, by_observer=by_observer)
    logger.info(
        "Russian Mafia room=%s target confirmed slot=%s",
        game.room_code,
        slot,
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "russian.action_confirmed",
            slot=slot,
            actor_uid=as_uid,
            target_uid=target_uid,
            alignment=(
                game.russian_mafia_detective_alignment
                if slot == "detective"
                else None
            ),
            russian={
                "day": int(game.russian_mafia_day_index or 1),
                "night": int(game.russian_mafia_night_index or 0),
                "phase": game.phase.value,
            },
        )
    except Exception:
        logger.exception(
            "Russian Mafia action audit failed room=%s slot=%s",
            game.room_code,
            slot,
        )
    return "ok"


def eliminate(game: Game, uid: int, *, source: str = "day_vote") -> None:
    record_russian_elimination(game, uid, source=source)


def finish_if_won(game: Game) -> str | None:
    winner = winner_of(game)
    if winner is None:
        return None
    game.phase = Phase.ENDED
    game.russian_mafia_terror_day_active = False
    logger.info(
        "Russian Mafia ended: room=%s winner=%s", game.room_code, winner
    )
    return winner


def apply_terror_eliminations(game: Game) -> str | None:
    casualty_uids: list[int] = []
    for player in game.players.values():
        if player.role == ROLE_TERROR:
            if player.is_alive:
                casualty_uids.append(player.user_id)
            eliminate(game, player.user_id, source="terror")
            break
    if game.russian_mafia_terror_target is not None:
        target = game.players.get(game.russian_mafia_terror_target)
        if target is not None and target.is_alive:
            casualty_uids.append(target.user_id)
        eliminate(game, game.russian_mafia_terror_target, source="terror")
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "russian.terror_resolved",
            casualty_uids=casualty_uids,
            russian={
                "day": int(game.russian_mafia_day_index or 1),
                "night": int(game.russian_mafia_night_index or 0),
                "phase": game.phase.value,
            },
        )
    except Exception:
        logger.exception("Russian Mafia terror audit failed room=%s", game.room_code)
    return finish_if_won(game)


def resolve_night_state(game: Game) -> str | None:
    winner = apply_night_resolution(game)
    if winner is not None:
        game.phase = Phase.ENDED
        logger.info(
            "Russian Mafia ended: room=%s winner=%s", game.room_code, winner
        )
        return winner
    return None


async def _send_pair(
    bot: Bot,
    game: Game,
    *,
    player_uid: int,
    slot: str,
    text: str,
    act: str,
    exclude: int | None,
    exclude_uids: set[int] | frozenset[int] | None = None,
) -> None:
    player_kb = action_keyboard(
        game,
        act=act,
        as_uid=player_uid,
        exclude=exclude,
        mirror=False,
        exclude_uids=exclude_uids,
    )
    observer_kb = action_keyboard(
        game,
        act=act,
        as_uid=player_uid,
        exclude=exclude,
        mirror=True,
        exclude_uids=exclude_uids,
    )
    send_player = not is_synthetic_player_uid(player_uid)
    ui_key = _ui_key(game, slot)
    markup = observer_kb if not send_player else player_kb
    if not send_player:
        markup = observer_kb
    else:
        markup = player_kb
    await register_mirror_prompt_pair(
        bot,
        game,
        player_uid,
        ui_key,
        text,
        markup,
        send_player=send_player,
        send_observer=russian_mafia_observer_registered(game),
        parse_mode="HTML",
    )
    if russian_mafia_observer_registered(game):
        await register_mirror_prompt_pair(
            bot,
            game,
            player_uid,
            ui_key + ":obs",
            text,
            observer_kb,
            send_player=False,
            send_observer=True,
            parse_mode="HTML",
        )


async def _close_existing_prompt(bot: Bot, game: Game, key: str) -> None:
    """فقط پیامِ موجود را می‌بندد. برای پنلِ هرگز ساخته‌نشده پیام تازه نمی‌فرستد."""
    entry = game.mirror_prompt_messages.get(key)
    if not isinstance(entry, dict):
        return
    text = "این اقدام بسته شد."
    edited = False
    for role in ("player", "observer"):
        pair = _coerce_mirror_ref(entry.get(role))
        if pair is None:
            continue
        chat_id, message_id = pair
        try:
            ok = await _try_edit_mirror_message(
                bot, chat_id, message_id, text, None
            )
        except Exception:
            logger.debug("close russian panel failed key=%s", key, exc_info=True)
            continue
        edited = edited or ok
    if edited:
        entry["text"] = text


async def _close_slot(bot: Bot, game: Game, slot: str) -> None:
    current = _ui_key(game, slot)
    legacy = _legacy_ui_key(game.room_code, slot)
    for key in (current, current + ":obs", legacy, legacy + ":obs"):
        await _close_existing_prompt(bot, game, key)


async def open_night(bot: Bot, game: Game) -> None:
    if game.phase == Phase.ENDED:
        return
    await _close_slot(bot, game, "terror")
    game.russian_mafia_terror_day_active = False
    reset_russian_night_actions(game)
    game.russian_mafia_night_index += 1
    game.phase = Phase.NIGHT
    game.bazpors_alive_at_night_start = {
        uid: player.is_alive for uid, player in game.players.items()
    }
    holder = mafia_shot_holder(game)
    game.phase_resolution_lock = False
    if (
        holder is None
        and not required_night_slots(game)
        and not required_waiting_player_ids(game)
    ):
        await open_day(bot, game)
        return
    if holder is not None and holder.role == ROLE_GODFATHER:
        logger.info("Russian Mafia night: mafia_holder=Godfather")
    elif holder is not None and holder.role == ROLE_TERROR:
        logger.info("Russian Mafia night: Godfather dead, mafia_holder=Terror")
    elif holder is not None:
        logger.info(
            "Russian Mafia night: Godfather dead, mafia_holder=SimpleMafia seat=%s",
            holder.seat,
        )
    if holder is not None:
        game.russian_mafia_mafia_action_holder = holder.user_id
    game.bazpors_night_discipline_kick_uid = None
    game.russian_mafia_post_night_stage = None
    game.russian_mafia_discipline_target = None
    game.russian_mafia_table_inquiry_pending = None
    game.russian_mafia_citizen_ack_uids = set()
    opened: list[str] = []
    for slot in ("mafia", "doctor", "detective"):
        if slot in required_night_slots(game):
            await _emit_russian_night_slot(bot, game, slot)
            opened.append(slot)
    logger.info(
        "Russian Mafia room=%s night panels opened night=%s slots=%s",
        game.room_code,
        game.russian_mafia_night_index,
        ",".join(opened),
    )
    await send_russian_citizen_wait_panels(bot, game)


def _fa(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _russian_night_title_fa(night_count: int) -> str:
    if night_count == 1:
        return "شب اول"
    if night_count == 2:
        return "شب دوم"
    if night_count == 3:
        return "شب سوم"
    return f"شب {_fa(night_count)}"


def _russian_pick_ordinal_fa(step: int) -> str:
    return {1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم"}.get(step, str(step))


def _doctor_selected_exclude(game: Game, doctor_uid: int) -> set[int]:
    skipped = set(game.russian_mafia_doctor_targets or [])
    if not doctor_self_save_allowed(game, doctor_uid, doctor_uid):
        skipped.add(doctor_uid)
    return skipped


def build_russian_doctor_pick_html(game: Game) -> str:
    """پنل پزشک مافیای روسی — ظاهر هم‌سبک مذاکره، قوانین ظرفیت روسی."""
    night = max(1, int(game.russian_mafia_night_index or 1))
    night_lbl = _russian_night_title_fa(night)
    capacity = int(game.russian_mafia_doctor_night_capacity or 0) or russian_doctor_heal_capacity(
        game
    )
    alive = russian_alive_player_count(game)
    used = int(game.russian_mafia_doctor_self_save_count or 0)
    limit = russian_doctor_self_save_limit(game)
    step = len(game.russian_mafia_doctor_targets or []) + 1
    if capacity >= 2:
        pick_line = (
            f"🛡️ لطفاً <b>نفر {_russian_pick_ordinal_fa(step)}</b> را "
            "از لیست زیر برای نجات انتخاب کنید."
        )
    else:
        pick_line = "🛡️ لطفاً <b>یک نفر</b> را از لیست زیر برای نجات انتخاب کنید."
    return (
        f"💉 {night_lbl} - ثبت انتخاب پزشک\n\n"
        f"{pick_line}\n\n"
        f"👤 با {_fa(alive)} بازیکن زنده، امشب تا {_fa(capacity)} نجات دارید.\n\n"
        "همچنین در طول بازی، می‌توانید تا یک بار خودتان را نجات دهید.\n"
        f"📊 تعداد دفعات نجات خود تا این لحظه: {_fa(used)} از {_fa(limit)}\n\n"
        "📩 انتخاب شما پس از پایان فاز امشب اعمال خواهد شد."
    )


def build_russian_doctor_confirm_html(game: Game, target_uid: int) -> str:
    player = game.players.get(target_uid)
    name = html.escape(player.full_name if player is not None else str(target_uid))
    return (
        f"{build_russian_doctor_pick_html(game)}\n\n"
        f"🛡️ نجات: <b>{name}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


async def open_day(bot: Bot, game: Game) -> None:
    """روز بعد: پنل دفاعیهٔ مشترک و، در بازی ۸نفره، توان روز ترور."""
    if game.phase == Phase.ENDED:
        return
    reset_russian_day_actions(game)
    if game.russian_mafia_night_index and (
        game.russian_mafia_day_index <= game.russian_mafia_night_index
    ):
        game.russian_mafia_day_index = game.russian_mafia_night_index + 1
    else:
        game.russian_mafia_day_index += 1
    game.bazpors_narrator_host_day = game.russian_mafia_day_index
    game.phase = Phase.DAY_DISCUSSION
    game.russian_mafia_day_result_applied = False
    game.bazpors_alive_at_day_start = {
        uid: player.is_alive for uid, player in game.players.items()
    }
    from bot.no_host_day_vote import (
        clear_no_host_day_mirror_prompts,
        reset_no_host_day_vote_prompt_state,
    )

    reset_no_host_day_vote_prompt_state(game)
    clear_no_host_day_mirror_prompts(game)
    logger.info(
        "Russian Mafia room=%s starting day=%s",
        game.room_code,
        game.russian_mafia_day_index,
    )
    from bot.no_host_night_resolve import build_no_host_day_started_broadcast_html
    from bot.observer_delivery import broadcast_to_alive_players

    await broadcast_to_alive_players(
        bot,
        game,
        f"☀️ {build_no_host_day_started_broadcast_html(game)}",
        exclude=game.bot_assistant_user_id,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await send_russian_day_defense_panel(bot, game)
    await _open_terror_day_panel(bot, game)


async def _open_terror_day_panel(bot: Bot, game: Game) -> None:
    """پنل روز ترور، جدا از پنل دفاعیه. بازی ۹نفره ترور ندارد."""
    if game.phase == Phase.ENDED:
        return
    terror = find_alive_role(game, ROLE_TERROR)
    if terror is None:
        return
    game.russian_mafia_terror_day_active = True
    if game.russian_mafia_terror_confirmed or _current_panel_open(game, "terror"):
        return
    await _send_pair(
        bot,
        game,
        player_uid=terror.user_id,
        slot="terror",
        text=_TERROR_DAY_TEXT,
        act="zrm_ter",
        exclude=terror.user_id,
    )
    logger.info(
        "Russian Mafia room=%s terror day panel opened day=%s user_id=%s",
        game.room_code,
        game.russian_mafia_day_index,
        terror.user_id,
    )


async def send_russian_day_defense_panel(bot: Bot, game: Game) -> None:
    """همان پنل دفاعیه که مذاکره در روز اول و روزهای بعد برای کمک‌کننده می‌فرستد."""
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.phase == Phase.ENDED:
        return
    if game.no_host_day1_defense_active:
        logger.info(
            "Russian Mafia room=%s day defense panel already active; skipping duplicate",
            game.room_code,
        )
        return
    from bot.bazpors_narrator import begin_no_host_day1_defense_pick
    from bot.main import send_no_host_day1_defense_pick_panel

    logger.info(
        "Russian Mafia room=%s sending day defense panel to bot_assistant_user_id=%s",
        game.room_code,
        assistant_uid,
    )
    if russian_mafia_observer_registered(game) and game.observer_user_id is not None:
        logger.info(
            "Russian Mafia room=%s mirroring day panel to observer_user_id=%s",
            game.room_code,
            game.observer_user_id,
        )
    begin_no_host_day1_defense_pick(game)
    await send_no_host_day1_defense_pick_panel(bot, game)


async def continue_russian_mafia_after_night(bot: Bot, game: Game) -> None:
    """شب حل شد؛ اخراج انضباطی و استعلام قبل از گزارش نهایی و روز بعد."""
    from bot.russian_mafia_post_night import begin_russian_post_night

    await begin_russian_post_night(bot, game)


def _slot_confirmed(game: Game, slot: str) -> bool:
    return {
        "mafia": game.russian_mafia_mafia_confirmed,
        "doctor": game.russian_mafia_doctor_confirmed,
        "detective": game.russian_mafia_detective_confirmed,
        "terror": game.russian_mafia_terror_confirmed,
    }[slot]


async def _emit_russian_night_slot(bot: Bot, game: Game, slot: str) -> None:
    if slot == "mafia":
        holder = mafia_shot_holder(game)
        if holder is None:
            return
        game.russian_mafia_mafia_action_holder = holder.user_id
        label = russian_role_label_fa(holder.role)
        await _send_pair(
            bot,
            game,
            player_uid=holder.user_id,
            slot="mafia",
            text=f"شب {_fa(game.russian_mafia_night_index)} — شلیک مافیا ({label}). یک هدف زنده را انتخاب کنید.",
            act="zrm_shot",
            exclude=None,
        )
        return
    if slot == "doctor":
        doctor = find_alive_role(game, Role.DOCTOR)
        if doctor is None:
            return
        game.russian_mafia_doctor_targets = []
        game.russian_mafia_doctor_target = None
        game.russian_mafia_doctor_confirmed = False
        game.russian_mafia_doctor_night_capacity = russian_doctor_heal_capacity(game)
        doctor_exclude = (
            doctor.user_id
            if not doctor_self_save_allowed(game, doctor.user_id, doctor.user_id)
            else None
        )
        await _send_pair(
            bot,
            game,
            player_uid=doctor.user_id,
            slot="doctor",
            text=build_russian_doctor_pick_html(game),
            act="zrm_doc",
            exclude=doctor_exclude,
            exclude_uids=_doctor_selected_exclude(game, doctor.user_id),
        )
        return
    if slot == "detective":
        detective = find_alive_role(game, Role.DETECTIVE)
        if detective is None:
            return
        await _send_pair(
            bot,
            game,
            player_uid=detective.user_id,
            slot="detective",
            text="استعلام کارآگاه: یک بازیکن زنده را انتخاب کنید.",
            act="zrm_det",
            exclude=None,
        )


async def reissue_open_russian_action_panels(bot: Bot, game: Game) -> bool:
    """پنل نسل‌دار شب/روز جاری را فقط اگر هنوز تأیید نشده و پنل جدید ندارد می‌فرستد.

    شمارنده، زنده‌ها، نقش‌ها و نتیجهٔ شب را عوض نمی‌کند و اقدامی را تأیید نمی‌کند.
    """
    if not is_russian_mafia_game(game) or game.phase == Phase.ENDED:
        return False
    sent: list[str] = []
    if game.phase == Phase.NIGHT and game.russian_mafia_night_index >= 1:
        if game.russian_mafia_night_result_sent_index != game.russian_mafia_night_index:
            needed = required_night_slots(game)
            for slot in ("mafia", "doctor", "detective"):
                if slot not in needed or _slot_confirmed(game, slot):
                    continue
                if _current_panel_open(game, slot):
                    continue
                legacy = _legacy_ui_key(game.room_code, slot)
                await _close_existing_prompt(bot, game, legacy)
                await _close_existing_prompt(bot, game, legacy + ":obs")
                await _emit_russian_night_slot(bot, game, slot)
                sent.append(slot)
    elif (
        game.phase in (Phase.DAY_DISCUSSION, Phase.DAY_VOTE)
        and game.russian_mafia_terror_day_active
        and not game.russian_mafia_terror_confirmed
        and find_alive_role(game, ROLE_TERROR) is not None
        and game.russian_mafia_day_index >= 1
        and not _current_panel_open(game, "terror")
    ):
        terror = find_alive_role(game, ROLE_TERROR)
        if terror is None:
            return False
        legacy = _legacy_ui_key(game.room_code, "terror")
        await _close_existing_prompt(bot, game, legacy)
        await _close_existing_prompt(bot, game, legacy + ":obs")
        await _send_pair(
            bot,
            game,
            player_uid=terror.user_id,
            slot="terror",
            text="توان روز ترور: یک بازیکن دیگر را انتخاب کنید تا هر دو از بازی خارج شوید.",
            act="zrm_ter",
            exclude=terror.user_id,
        )
        sent.append("terror")
    if not sent:
        return False
    logger.info(
        "Russian Mafia room=%s reissued current panels slots=%s night=%s day=%s",
        game.room_code,
        ",".join(sent),
        game.russian_mafia_night_index,
        game.russian_mafia_day_index,
    )
    from bot.game_snapshot import persist_game_snapshot

    persist_game_snapshot(game, reason="russian_panel_reissue")
    return True


def host_day_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="شروع رأی‌گیری",
                    callback_data=f"rmh:{game.room_code}:vote",
                )
            ],
            [
                InlineKeyboardButton(
                    text="بدون حذف به شب برو",
                    callback_data=f"rmh:{game.room_code}:night",
                )
            ],
        ]
    )


def host_elim_keyboard(game: Game) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for player in _alive_targets(game):
        row.append(
            InlineKeyboardButton(
                text=f"حذف {player.full_name}"[:40],
                callback_data=f"rmh:{game.room_code}:elim:{player.user_id}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="کسی حذف نشود",
                callback_data=f"rmh:{game.room_code}:night",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _after_elimination(bot: Bot, game: Game) -> str | None:
    from bot.observer_delivery import flush_elimination_notifications

    await flush_elimination_notifications(bot, game)
    winner = finish_if_won(game)
    if winner is not None:
        await safe_send_message(
            bot,
            russian_helper_user_id(game),
            "شهروندها برنده شدند." if winner == "town" else "مافیا برنده شد.",
        )
        return winner
    await open_night(bot, game)
    return None


async def complete_slot(
    bot: Bot,
    game: Game,
    *,
    slot: str,
    actor_uid: int,
    as_uid: int,
    target_uid: int,
    generation: int | None | _UseCurrentGeneration = _USE_CURRENT,
) -> str:
    terror_winner: str | None = None
    night_winner: str | None = None
    should_resolve = False
    async with room_lock(game.room_code):
        if game.phase == Phase.ENDED:
            return "stale"
        result = try_confirm_action(
            game,
            slot=slot,
            actor_uid=actor_uid,
            as_uid=as_uid,
            target_uid=target_uid,
            generation=generation,
        )
        if result != "ok":
            return result
        doctor_partial = slot == "doctor" and not game.russian_mafia_doctor_confirmed
        if slot == "terror":
            terror_winner = apply_terror_eliminations(game)
            game.russian_mafia_day_result_applied = True
            game.no_host_day1_defense_active = False
            game.no_host_day1_defense_phase = None
        should_resolve = (
            not doctor_partial
            and slot != "terror"
            and game.phase == Phase.NIGHT
            and not getattr(game, "phase_resolution_lock", False)
            and night_ready_to_resolve(game)
        )
        if should_resolve:
            game.phase_resolution_lock = True
            night_winner = resolve_night_state(game)
        elif (
            slot != "terror"
            and game.phase == Phase.NIGHT
            and night_slots_complete(game)
            and not waiting_acks_complete(game)
        ):
            logger.info(
                "Russian Mafia room=%s night actions complete but acknowledgements pending %s",
                game.room_code,
                explain_russian_mafia_night_readiness(game)["pending_player_ids"],
            )
    if slot == "terror":
        from bot.observer_delivery import flush_elimination_notifications

        await flush_elimination_notifications(bot, game)
    if slot == "doctor" and not game.russian_mafia_doctor_confirmed:
        await _refresh_slot_markup(
            bot,
            game,
            "doctor",
            as_uid,
            build_russian_doctor_pick_html(game),
            confirm_target=None,
        )
        return "ok"
    await _close_slot(bot, game, slot)
    if slot == "terror":
        await _close_russian_defense_panels(bot, game)
        if terror_winner is not None:
            await safe_send_message(
                bot,
                russian_helper_user_id(game),
                "شهروندها برنده شدند." if terror_winner == "town" else "مافیا برنده شد.",
            )
            return "ok"
        await open_night(bot, game)
        return "ok"
    if slot == "detective" and game.russian_mafia_detective_alignment:
        word = (
            "مثبت (مافیا)"
            if game.russian_mafia_detective_alignment == "positive"
            else "منفی (شهروند)"
        )
        detective = game.players.get(as_uid)
        if detective is not None and not is_synthetic_player_uid(as_uid):
            await safe_send_message(bot, as_uid, f"نتیجهٔ استعلام: {word}")
        if russian_mafia_observer_registered(game) and game.observer_user_id is not None:
            await safe_send_message(
                bot,
                game.observer_user_id,
                f"ناظر — نتیجهٔ استعلام کارآگاه: {word}",
            )
    if should_resolve:
        await continue_russian_mafia_after_night(bot, game)
    return "ok"


async def _answer_player_result(callback: CallbackQuery, result: str) -> None:
    if result == "ok":
        await safe_callback_answer(callback, "ثبت شد.")
    elif result == "pending":
        await safe_callback_answer(callback, "هدف انتخاب شد.")
    elif result == "back":
        await safe_callback_answer(callback, "بازگشت.")
    elif result == "ack":
        await safe_callback_answer(callback, "متوجه شدم.")
    elif result == "duplicate":
        await safe_callback_answer(callback, "قبلاً ثبت شده.")
    elif result == "rejected":
        await safe_callback_answer(callback, "این انتخاب مجاز نیست.", show_alert=True)
    else:
        await safe_callback_answer(callback, STALE_ACTION_FA, show_alert=True)


async def handle_player_action(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    parsed = parse_player_action(callback.data or "")
    if parsed is None or not callback.from_user:
        await safe_callback_answer(callback, "دکمه نامعتبر.", show_alert=True)
        return
    _room, act, as_uid, tid, generation = parsed
    if game.room_code != _room or not is_russian_mafia_game(game):
        await safe_callback_answer(callback, "این دکمه برای این اتاق نیست.", show_alert=True)
        return
    result = await route_russian_player_callback(
        bot,
        game,
        act=act,
        as_uid=as_uid,
        actor_uid=callback.from_user.id,
        target_uid=tid,
        generation=generation,
    )
    await _answer_player_result(callback, result)


async def dispatch_russian_mafia_mirror(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    *,
    as_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
    generation: int | None = None,
) -> bool:
    if not is_russian_mafia_game(game) or act not in _ACTS:
        return False
    result = await route_russian_player_callback(
        bot,
        game,
        act=act,
        as_uid=as_uid,
        actor_uid=actor_uid,
        target_uid=tid,
        generation=generation,
    )
    await _answer_player_result(callback, result)
    return True


def russian_intro_start_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌙 شروع شب معارفه",
                    callback_data=f"rmh:{game.room_code}:intro",
                )
            ]
        ]
    )


def russian_intro_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ ادامه",
                    callback_data=f"rmh:{game.room_code}:intro_ok",
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=f"rmh:{game.room_code}:intro_back",
                )
            ],
        ]
    )


async def notify_mafia_teammates(bot: Bot, game: Game) -> None:
    """فقط یک بار، بعد از تأیید شب معارفه. کمک‌کننده به‌صرف کمک‌کننده این پیام را نمی‌گیرد."""
    if game.russian_mafia_mafia_team_revealed:
        return
    mates = [p for p in game.players.values() if is_russian_mafia_role(p.role)]
    game.russian_mafia_mafia_team_revealed = True
    if len(mates) < 2:
        return
    from bot.main import build_no_host_intro_night_mafia_dm_html

    text = build_no_host_intro_night_mafia_dm_html(game)
    for player in mates:
        if is_synthetic_player_uid(player.user_id):
            continue
        await safe_send_message(bot, player.user_id, text, parse_mode="HTML")
    observer_id = game.observer_user_id
    if (
        russian_mafia_observer_registered(game)
        and observer_id is not None
        and observer_id not in {p.user_id for p in mates}
    ):
        await safe_send_message(
            bot,
            observer_id,
            "ناظر — معرفی تیم مافیا:\n" + text,
            parse_mode="HTML",
        )


def russian_helper_user_id(game: Game) -> int:
    """کمک‌کننده انتخاب‌شده؛ تا قبل از انتخاب، سازندهٔ اتاق."""
    selected = game.bot_assistant_user_id
    if selected is not None:
        return int(selected)
    return game.host_id


_RUSSIAN_HELPER_ANNOUNCED: set[str] = set()


async def finalize_russian_bot_helper(
    bot: Bot, game: Game, assistant_uid: int, *, random_pick: bool = True
) -> None:
    """انتخاب کمک‌کننده بعد از ناظر؛ بلافاصله شب معارفه برای اوست."""
    if not is_russian_host_helper(game):
        return
    if game.room_code in _RUSSIAN_HELPER_ANNOUNCED:
        return
    if game.bot_assistant_user_id not in (None, assistant_uid):
        return
    _RUSSIAN_HELPER_ANNOUNCED.add(game.room_code)
    game.bot_assistant_user_id = assistant_uid
    from bot.main import (
        build_no_host_assistant_announcement_html,
        build_no_host_bot_assistant_private_html,
    )
    from bot.observer_delivery import broadcast_to_players

    await safe_send_message(
        bot,
        assistant_uid,
        build_no_host_bot_assistant_private_html(random_pick=random_pick),
        parse_mode="HTML",
    )
    await broadcast_to_players(
        bot,
        game,
        build_no_host_assistant_announcement_html(game, assistant_uid),
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    await continue_russian_mafia_after_bot_assistant(bot, game)


def _russian_intro_phase_ready(game: Game) -> bool:
    return game.roles_dealt and game.phase in (Phase.LOBBY, Phase.MANUAL)


async def send_russian_intro_prompt(bot: Bot, game: Game) -> None:
    if game.russian_mafia_mafia_team_revealed:
        return
    if game.russian_mafia_intro_prompt_sent:
        logger.info(
            "Russian Mafia room=%s intro already sent; skipping duplicate",
            game.room_code,
        )
        return
    if not _russian_intro_phase_ready(game):
        logger.info(
            "Russian Mafia room=%s intro waiting roles_dealt=%s phase=%s",
            game.room_code,
            game.roles_dealt,
            game.phase,
        )
        return
    from bot.main import build_no_host_intro_night_start_html

    recipient = russian_helper_user_id(game)
    game.russian_mafia_intro_prompt_sent = True
    await safe_send_message(
        bot,
        recipient,
        build_no_host_intro_night_start_html(),
        parse_mode="HTML",
        reply_markup=russian_intro_start_keyboard(game),
    )
    logger.info(
        "Russian Mafia room=%s intro_night_prompt_sent recipient=%s",
        game.room_code,
        recipient,
    )


async def accept_russian_host_mode(callback, bot, callback_data) -> None:
    """ساخت اتاق فقط در حالت بازیکن گرداننده."""
    from bot.app_state import manager
    from bot.main import build_host_mode_created_room_html
    from bot.game import role_roster_banner_text
    from bot.russian_mafia import PLAYER_COUNTS, host_mode_rejection_reason

    reason = host_mode_rejection_reason(callback_data.mode)
    if callback_data.count not in PLAYER_COUNTS:
        await callback.answer("مافیای روسی: فقط ۸ یا ۹ بازیکن.", show_alert=True)
        return
    if reason:
        await callback.answer(reason, show_alert=True)
        return
    uid = callback.from_user.id
    if manager.get_room_for_user(uid) or manager.get_room_for_host(uid):
        await callback.answer("شما همین الان در یک اتاق هستید. اول /leave بزنید.", show_alert=True)
        return
    game = manager.create_game(
        host_id=uid,
        scenario_name="russian_mafia",
        max_players=callback_data.count,
        host_full_name=callback.from_user.full_name or "",
        host_username=callback.from_user.username,
        bazpors_host_mode=callback_data.mode,
    )
    if not game or callback.message is None:
        await callback.answer("امکان ساخت اتاق نیست.", show_alert=True)
        return
    await callback.answer()
    from bot.models import Player

    creator = Player(
        user_id=uid,
        full_name=(callback.from_user.full_name or "").strip() or "بازیکن",
        username=callback.from_user.username,
    )
    join_err = manager.add_player(game, creator)
    if join_err and join_err != "already_in_room":
        await callback.message.edit_text(
            "اتاق ساخته شد اما ثبت شما به‌عنوان بازیکن ناموفق بود. "
            f"کد: <code>{game.room_code}</code>",
            parse_mode="HTML",
        )
        return
    bot_username = (await bot.get_me()).username or "YourBot"
    invite_link = f"https://t.me/{bot_username}?start={game.room_code}"
    roster_plain = role_roster_banner_text(game.scenario_name, game.max_players, manager)
    from bot.main import format_roster_plain_to_html

    text = build_host_mode_created_room_html(
        game,
        mode="no_host",
        invite_link=invite_link,
        host_label=manager.get_user_display_name(
            uid, (callback.from_user.full_name or "").strip() or "—"
        ),
        scenario_label=manager.scenario_display_name(game.scenario_name),
        roster_html=format_roster_plain_to_html(roster_plain),
        creator_registered=True,
    )
    from bot.main import semi_auto_lobby_dev_keyboard
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=semi_auto_lobby_dev_keyboard(game),
    )


_RUSSIAN_OBSERVER_PROMPTED: set[str] = set()
_RUSSIAN_ROLE_MENU_SENT: set[str] = set()
_RUSSIAN_HELPER_PROMPTED: set[str] = set()


def _observer_step_complete(game: Game) -> bool:
    return game.observer_prompt_status in ("skipped", "code_sent", "registered")


async def _ensure_russian_roles_ready(bot: Bot, game: Game) -> None:
    """نقش‌ها قبل از شب معارفه خصوصی می‌شوند؛ پنل انتخاب نقش بین کمک‌کننده و معارفه نیست."""
    if game.roles_dealt:
        return
    from bot.app_state import manager
    from bot.main import send_private_role

    if any(player.role is None for player in game.players.values()):
        manager.assign_roles(game)
    for player in game.players.values():
        if player.role is None or is_synthetic_player_uid(player.user_id):
            continue
        await send_private_role(bot, player.user_id, player.role, game=game)
    if not game.roles_dealt:
        manager.finalize_deal_roles_phase(game)


async def continue_russian_mafia_after_seat_confirmation(bot: Bot, game: Game) -> None:
    if not is_russian_host_helper(game) or not game.seats_finalized:
        return
    logger.info(
        "Russian Mafia room=%s seats_confirmed=True → observer_prompt",
        game.room_code,
    )
    if not game.roles_dealt and not game.russian_mafia_player_role_pick_active:
        if game.room_code in _RUSSIAN_ROLE_MENU_SENT:
            logger.info(
                "Russian Mafia room=%s role distribution menu already sent",
                game.room_code,
            )
            return
        from bot.main import host_deal_roles_keyboard

        sent_menu = await safe_send_message(
            bot,
            game.host_id,
            "🎭 برای ادامه پخش نقش‌های تصادفی را بزنید:",
            reply_markup=host_deal_roles_keyboard(game),
        )
        if sent_menu:
            _RUSSIAN_ROLE_MENU_SENT.add(game.room_code)
            logger.info(
                "Russian Mafia room=%s role distribution menu sent",
                game.room_code,
            )
        else:
            logger.info(
                "Russian Mafia room=%s role distribution menu was not delivered",
                game.room_code,
            )
        return
    if (
        game.room_code in _RUSSIAN_OBSERVER_PROMPTED
        or game.observer_prompt_status == "pending"
    ):
        logger.info(
            "Russian Mafia room=%s observer prompt already sent; skipping duplicate",
            game.room_code,
        )
        return
    if game.observer_prompt_status == "skipped":
        await continue_russian_mafia_after_observer(bot, game)
        return
    from bot.app_state import manager
    from bot.main import (
        build_no_host_observer_prompt_html,
        no_host_observer_prompt_keyboard,
    )

    _RUSSIAN_OBSERVER_PROMPTED.add(game.room_code)
    manager.ensure_observer_code(game)
    if not game.observer_prompt_status:
        game.observer_prompt_status = "pending"
    await safe_send_message(
        bot,
        game.host_id,
        build_no_host_observer_prompt_html(game),
        parse_mode="HTML",
        reply_markup=no_host_observer_prompt_keyboard(game),
    )


async def continue_russian_mafia_after_observer(bot: Bot, game: Game) -> None:
    if not is_russian_host_helper(game):
        return
    logger.info(
        "Russian Mafia room=%s observer_step_complete=True → bot_helper_prompt",
        game.room_code,
    )
    if game.bot_assistant_user_id is not None:
        await continue_russian_mafia_after_bot_assistant(bot, game)
        return
    if game.room_code in _RUSSIAN_HELPER_PROMPTED:
        logger.info(
            "Russian Mafia room=%s helper prompt already sent; skipping duplicate",
            game.room_code,
        )
        return
    from bot.main import (
        build_no_host_bot_assistant_prompt_html,
        no_host_bot_assistant_pick_keyboard,
    )

    _RUSSIAN_HELPER_PROMPTED.add(game.room_code)
    await safe_send_message(
        bot,
        game.host_id,
        build_no_host_bot_assistant_prompt_html(),
        parse_mode="HTML",
        reply_markup=no_host_bot_assistant_pick_keyboard(game),
    )


async def continue_russian_mafia_after_bot_assistant(bot: Bot, game: Game) -> None:
    if not is_russian_host_helper(game) or game.bot_assistant_user_id is None:
        return
    logger.info(
        "Russian Mafia room=%s bot_assistant_user_id=%s → intro_night_prompt",
        game.room_code,
        game.bot_assistant_user_id,
    )
    await _ensure_russian_roles_ready(bot, game)
    await send_russian_intro_prompt(bot, game)


async def begin_after_roles(bot: Bot, game: Game) -> None:
    if not is_russian_host_helper(game):
        return
    if (
        not game.russian_mafia_intro_prompt_sent
        and not game.russian_mafia_mafia_team_revealed
    ):
        initialize_russian_mafia_state(game)
    if game.bot_assistant_user_id is not None:
        await continue_russian_mafia_after_bot_assistant(bot, game)
        return
    if _observer_step_complete(game):
        await continue_russian_mafia_after_observer(bot, game)
        return
    await continue_russian_mafia_after_seat_confirmation(bot, game)


async def on_observer_prompt_done(bot: Bot, game: Game) -> None:
    if game.russian_mafia_day_index or game.russian_mafia_night_index:
        return
    if game.russian_mafia_mafia_team_revealed:
        await open_day(bot, game)
        return
    await continue_russian_mafia_after_observer(bot, game)




async def send_russian_post_intro_helper_panel(bot: Bot, game: Game) -> None:
    """همان پنل دفاعیهٔ پایان روز که مذاکره/بازپرس بعد از شب معارفه می‌فرستد."""
    if game.no_host_day1_defense_active:
        logger.info(
            "Russian Mafia room=%s post-intro panel already active; skipping duplicate",
            game.room_code,
        )
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    from bot.bazpors_narrator import begin_no_host_day1_defense_pick
    from bot.main import (
        _no_host_day1_defense_pick_ui_key,
        send_no_host_day1_defense_pick_panel,
    )

    logger.info(
        "Russian Mafia room=%s sending post-intro helper panel to bot_assistant_user_id=%s",
        game.room_code,
        assistant_uid,
    )
    if russian_mafia_observer_registered(game) and game.observer_user_id is not None:
        logger.info(
            "Russian Mafia room=%s mirroring post-intro panel to observer_user_id=%s",
            game.room_code,
            game.observer_user_id,
        )
    game.no_host_intro_night_started = True
    game.no_host_day1_vote_resolved = True
    if game.russian_mafia_day_index < 1:
        game.russian_mafia_day_index = 1
    if game.bazpors_narrator_host_day < 1:
        game.bazpors_narrator_host_day = game.russian_mafia_day_index
    if game.bazpors_alive_at_day_start is None:
        game.bazpors_alive_at_day_start = {
            uid: player.is_alive for uid, player in game.players.items()
        }
    if game.phase != Phase.ENDED:
        game.phase = Phase.DAY_DISCUSSION
    begin_no_host_day1_defense_pick(game)
    await send_no_host_day1_defense_pick_panel(bot, game)
    entry = game.mirror_prompt_messages.get(
        _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    ) or {}
    player_ref = entry.get("player")
    message_id = (
        player_ref[1]
        if isinstance(player_ref, tuple) and len(player_ref) == 2
        else None
    )
    logger.info(
        "Russian Mafia room=%s post-intro panel sent message_id=%s",
        game.room_code,
        message_id,
    )
    await _open_terror_day_panel(bot, game)



def note_russian_defense_candidates(game: Game, picked: set[int]) -> None:
    if game.scenario_name != "russian_mafia":
        return
    logger.info(
        "Russian Mafia room=%s defense candidates=%s",
        game.room_code,
        sorted(picked),
    )


async def _close_russian_defense_panels(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    from bot.main import (
        _no_host_day1_confirm_elim_ui_key,
        _no_host_day1_defense_outcome_ui_key,
        _no_host_day1_defense_pick_ui_key,
        _no_host_day1_pick_elim_ui_key,
    )
    from bot.observer_delivery import close_mirror_prompt_keyboards

    for key in (
        _no_host_day1_defense_pick_ui_key(game, assistant_uid),
        _no_host_day1_defense_outcome_ui_key(game, assistant_uid),
        _no_host_day1_pick_elim_ui_key(game, assistant_uid),
        _no_host_day1_confirm_elim_ui_key(game, assistant_uid),
    ):
        try:
            await close_mirror_prompt_keyboards(bot, game, key)
        except Exception:
            logger.debug("close russian defense panel failed", exc_info=True)


async def apply_russian_day_result(
    bot: Bot,
    game: Game,
    *,
    eliminated_uid: int | None,
    reason: str,
) -> bool:
    """نتیجهٔ روز مشترک را برای مافیای روسی می‌بندد. برای سناریوهای دیگر False."""
    if game.scenario_name != "russian_mafia":
        return False
    async with room_lock(game.room_code):
        if game.russian_mafia_day_result_applied or game.phase == Phase.ENDED:
            logger.info(
                "Russian Mafia room=%s day result already applied; skipping duplicate",
                game.room_code,
            )
            return True
        game.russian_mafia_day_result_applied = True
        game.no_host_day1_defense_active = False
        game.no_host_day1_defense_phase = None
        game.russian_mafia_terror_day_active = False
        if reason == "none":
            logger.info(
                "Russian Mafia room=%s day defense none → starting night",
                game.room_code,
            )
        if eliminated_uid is None:
            logger.info(
                "Russian Mafia room=%s no day elimination",
                game.room_code,
            )
        else:
            logger.info(
                "Russian Mafia room=%s day elimination user_id=%s",
                game.room_code,
                eliminated_uid,
            )
            eliminate(game, eliminated_uid, source="day_vote")
        logger.info(
            "Russian Mafia room=%s day result complete → win check",
            game.room_code,
        )
        winner = finish_if_won(game)
    await _close_slot(bot, game, "terror")
    await _close_russian_defense_panels(bot, game)
    from bot.observer_delivery import flush_elimination_notifications

    await flush_elimination_notifications(bot, game)
    if winner is not None:
        await safe_send_message(
            bot,
            russian_helper_user_id(game),
            "شهروندها برنده شدند." if winner == "town" else "مافیا برنده شد.",
        )
        return True
    logger.info(
        "Russian Mafia room=%s starting Russian night",
        game.room_code,
    )
    await open_night(bot, game)
    return True


async def finish_russian_confirmed_elimination(
    callback,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    target_uid: int,
) -> bool:
    """حذف عادی رأی روز؛ زره و شب مذاکره اجرا نمی‌شود."""
    if game.scenario_name != "russian_mafia":
        return False
    await callback.answer("حذف ثبت شد.")
    try:
        if callback.message is not None:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ حذف بازیکن تأیید و ثبت شد.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    from bot.game import is_synthetic_player_uid as _synthetic
    from bot.main import (
        _no_host_day1_confirm_elim_ui_key,
        _no_host_day1_defense_outcome_ui_key,
        _no_host_day1_pick_elim_ui_key,
        broadcast_to_alive_players,
        build_no_host_day1_elim_broadcast_html,
    )
    from bot.observer_delivery import close_mirror_prompt_keyboards

    skip_mid = (
        frozenset({callback.message.message_id})
        if callback.message is not None
        else frozenset()
    )
    for key in (
        _no_host_day1_defense_outcome_ui_key(game, assistant_uid),
        _no_host_day1_pick_elim_ui_key(game, assistant_uid),
        _no_host_day1_confirm_elim_ui_key(game, assistant_uid),
    ):
        await close_mirror_prompt_keyboards(
            bot, game, key, skip_message_ids=skip_mid
        )
    await broadcast_to_alive_players(
        bot,
        game,
        build_no_host_day1_elim_broadcast_html(game, assistant_uid, target_uid),
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=_synthetic,
    )
    await apply_russian_day_result(
        bot, game, eliminated_uid=target_uid, reason="elim"
    )
    return True


async def _handle_intro_host_action(callback, bot: Bot, game: Game, act: str) -> None:
    from bot.main import (
        build_no_host_intro_night_confirm_html,
        build_no_host_intro_night_start_html,
    )

    if not _russian_intro_phase_ready(game):
        await safe_callback_answer(callback, STALE_ACTION_FA, show_alert=True)
        return
    if game.russian_mafia_mafia_team_revealed or game.no_host_day1_vote_prompt_sent:
        if game.no_host_day1_vote_prompt_sent or game.no_host_day1_defense_active:
            logger.info(
                "Russian Mafia room=%s post-intro panel already active; skipping duplicate",
                game.room_code,
            )
        await safe_callback_answer(callback, STALE_ACTION_FA, show_alert=True)
        return
    if act == "intro":
        await safe_callback_answer(callback, "تأیید را بزنید.")
        if callback.message is not None:
            try:
                await callback.message.edit_text(
                    build_no_host_intro_night_confirm_html(),
                    parse_mode="HTML",
                    reply_markup=russian_intro_confirm_keyboard(game),
                )
            except Exception:
                pass
        return
    if act == "intro_back":
        await safe_callback_answer(callback, "بازگشت.")
        if callback.message is not None:
            try:
                await callback.message.edit_text(
                    build_no_host_intro_night_start_html(),
                    parse_mode="HTML",
                    reply_markup=russian_intro_start_keyboard(game),
                )
            except Exception:
                pass
        return
    game.no_host_day1_vote_prompt_sent = True
    logger.info("Russian Mafia room=%s intro completed", game.room_code)
    await notify_mafia_teammates(bot, game)
    await safe_callback_answer(callback, "شب معارفه شروع شد.")
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await send_russian_post_intro_helper_panel(bot, game)


def assign_roles_on_game(game: Game, role_by_player: dict[int, Role] | None = None) -> None:
    game.mafia_ids.clear()
    if role_by_player is None:
        import random

        from bot.russian_mafia import russian_roles_for_count

        roles = russian_roles_for_count(len(game.players))
        ids = list(game.players.keys())
        random.shuffle(ids)
        random.shuffle(roles)
        role_by_player = dict(zip(ids, roles))
    for pid, player in game.players.items():
        role = role_by_player.get(pid)
        if role is None:
            raise ValueError("همهٔ بازیکن‌ها باید نقش داشته باشند.")
        if pid == game.observer_user_id:
            raise ValueError("ناظر نقش بازی نمی‌گیرد.")
        player.role = role
        if is_russian_mafia_role(role):
            game.mafia_ids.add(pid)
    initialize_russian_mafia_state(game)


async def handle_host_action(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    if not callback.from_user or callback.from_user.id != russian_helper_user_id(game):
        await safe_callback_answer(callback, "فقط کمک‌کننده ربات.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) < 3 or parts[0] != "rmh" or parts[1] != game.room_code:
        await safe_callback_answer(callback, "دکمه نامعتبر.", show_alert=True)
        return
    act = parts[2]
    async with room_lock(game.room_code):
        if game.phase == Phase.ENDED or not is_russian_host_helper(game):
            await safe_callback_answer(callback, STALE_ACTION_FA, show_alert=True)
            return
        if act in ("intro", "intro_back", "intro_ok"):
            await _handle_intro_host_action(callback, bot, game, act)
            return
        if act.startswith("disc_") or act.startswith("inq_"):
            from bot.russian_mafia_post_night import handle_russian_host_post_night

            await handle_russian_host_post_night(callback, bot, game, act, parts)
            return
        if act == "vote" and game.phase == Phase.DAY_DISCUSSION:
            game.phase = Phase.DAY_VOTE
            game.russian_mafia_terror_day_active = False
            await _close_slot(bot, game, "terror")
            await safe_callback_answer(callback, "رأی‌گیری شروع شد.")
            if callback.message is not None:
                try:
                    await callback.message.edit_reply_markup(
                        reply_markup=host_elim_keyboard(game)
                    )
                except Exception:
                    pass
            return
        if act == "elim" and len(parts) == 4 and game.phase == Phase.DAY_VOTE:
            try:
                uid = int(parts[3])
            except ValueError:
                await safe_callback_answer(callback, "دکمه نامعتبر.", show_alert=True)
                return
            eliminate(game, uid)
            await safe_callback_answer(callback, "حذف ثبت شد.")
        elif act == "night" and game.phase in (Phase.DAY_DISCUSSION, Phase.DAY_VOTE):
            game.russian_mafia_terror_day_active = False
            await _close_slot(bot, game, "terror")
            await safe_callback_answer(callback, "شب شروع می‌شود.")
        else:
            await safe_callback_answer(callback, "الان مجاز نیست.", show_alert=True)
            return
    await _after_elimination(bot, game)


def _ready_ui_key(game: Game, uid: int) -> str:
    return f"russian:{game.room_code}:night:{game.russian_mafia_night_index}:ready:{uid}"


def _citizen_ui_key(game: Game, uid: int) -> str:
    return _ready_ui_key(game, uid)


def _slot_exclude(game: Game, slot: str, as_uid: int) -> int | None:
    if slot == "terror":
        return as_uid
    if slot == "doctor" and not doctor_self_save_allowed(game, as_uid, as_uid):
        return as_uid
    return None


def _slot_exclude_uids(game: Game, slot: str, as_uid: int) -> set[int]:
    if slot != "doctor":
        return set()
    return _doctor_selected_exclude(game, as_uid)


def _target_allowed(game: Game, slot: str, as_uid: int, target_uid: int) -> bool:
    player = game.players.get(target_uid)
    if player is None or not player.is_alive or player.role == Role.OBSERVER:
        return False
    excluded = _slot_exclude(game, slot, as_uid)
    if excluded is not None and target_uid == excluded:
        return False
    if slot == "doctor" and target_uid in (game.russian_mafia_doctor_targets or []):
        return False
    return True


_TERROR_DAY_TEXT = "توان روز ترور: یک بازیکن دیگر را انتخاب کنید تا هر دو از بازی خارج شوید."


def _night_slot_text(game: Game, slot: str) -> str:
    if slot == "terror":
        return _TERROR_DAY_TEXT
    if slot == "mafia":
        holder = mafia_shot_holder(game)
        label = russian_role_label_fa(holder.role) if holder is not None else ""
        return (
            f"شب {_fa(game.russian_mafia_night_index)} — شلیک مافیا ({label}). "
            "یک هدف زنده را انتخاب کنید."
        )
    if slot == "doctor":
        return build_russian_doctor_pick_html(game)
    return "استعلام کارآگاه: یک بازیکن زنده را انتخاب کنید."


def _confirm_keyboard(
    game: Game, *, slot: str, as_uid: int, target_uid: int, mirror: bool
) -> InlineKeyboardMarkup:
    generation = _expected_generation(game, slot)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(
                    game,
                    act={v: k for k, v in _CONFIRM_ACTS.items()}[slot],
                    as_uid=as_uid,
                    target_uid=target_uid,
                    label="✅ بله، تأیید",
                    mirror=mirror,
                    generation=generation,
                ),
                _button(
                    game,
                    act={v: k for k, v in _BACK_ACTS.items()}[slot],
                    as_uid=as_uid,
                    target_uid=target_uid,
                    label="↩️ بازگشت",
                    mirror=mirror,
                    generation=generation,
                ),
            ]
        ]
    )


async def _refresh_slot_markup(
    bot: Bot,
    game: Game,
    slot: str,
    as_uid: int,
    text: str,
    *,
    confirm_target: int | None,
) -> None:
    exclude = _slot_exclude(game, slot, as_uid)
    exclude_uids = _slot_exclude_uids(game, slot, as_uid)
    if confirm_target is None:
        player_kb = action_keyboard(
            game,
            act=_SLOT_ACT[slot],
            as_uid=as_uid,
            exclude=exclude,
            mirror=False,
            exclude_uids=exclude_uids,
        )
        observer_kb = action_keyboard(
            game,
            act=_SLOT_ACT[slot],
            as_uid=as_uid,
            exclude=exclude,
            mirror=True,
            exclude_uids=exclude_uids,
        )
    else:
        player_kb = _confirm_keyboard(
            game, slot=slot, as_uid=as_uid, target_uid=confirm_target, mirror=False
        )
        observer_kb = _confirm_keyboard(
            game, slot=slot, as_uid=as_uid, target_uid=confirm_target, mirror=True
        )
    base = _ui_key(game, slot)
    await update_mirror_prompt_pair(
        bot,
        game,
        base,
        text,
        player_kb,
        assistant_uid=as_uid,
        parse_mode="HTML",
    )
    if russian_mafia_observer_registered(game):
        await update_mirror_prompt_pair(
            bot,
            game,
            base + ":obs",
            text,
            observer_kb,
            assistant_uid=as_uid,
            parse_mode="HTML",
            observer_same_text=True,
        )


def _selection_is_current(game: Game, slot: str, generation: int | None) -> bool:
    if slot == "terror":
        if game.phase not in (Phase.DAY_DISCUSSION, Phase.DAY_VOTE):
            return False
        if not game.russian_mafia_terror_day_active or game.russian_mafia_terror_confirmed:
            return False
    elif game.phase != Phase.NIGHT:
        return False
    return generation == _expected_generation(game, slot)


async def present_russian_target_confirmation(
    bot: Bot,
    game: Game,
    *,
    slot: str,
    actor_uid: int,
    as_uid: int,
    target_uid: int,
    generation: int | None,
) -> str:
    if not _selection_is_current(game, slot, generation):
        logger.info(
            "Russian Mafia room=%s blocked stale callback slot=%s generation=%s expected=%s",
            game.room_code,
            slot,
            generation,
            _expected_generation(game, slot),
        )
        return "stale"
    if _slot_confirmed(game, slot):
        return "stale"
    if not _actor_allowed(game, actor_uid, as_uid):
        return "rejected"
    if not _target_allowed(game, slot, as_uid, target_uid):
        return "rejected"
    target = game.players.get(target_uid)
    name = target.full_name if target is not None else str(target_uid)
    logger.info(
        "Russian Mafia room=%s pending target slot=%s target_user_id=%s",
        game.room_code,
        slot,
        target_uid,
    )
    if slot == "doctor":
        confirm_text = build_russian_doctor_confirm_html(game, target_uid)
    else:
        confirm_text = f"هدف: {name}\nاین انتخاب را تأیید می‌کنید؟"
    await _refresh_slot_markup(
        bot,
        game,
        slot,
        as_uid,
        confirm_text,
        confirm_target=target_uid,
    )
    return "pending"


async def restore_russian_target_selection(
    bot: Bot,
    game: Game,
    *,
    slot: str,
    actor_uid: int,
    as_uid: int,
    generation: int | None,
) -> str:
    if not _selection_is_current(game, slot, generation) or _slot_confirmed(game, slot):
        logger.info(
            "Russian Mafia room=%s blocked stale callback slot=%s generation=%s",
            game.room_code,
            slot,
            generation,
        )
        return "stale"
    if not _actor_allowed(game, actor_uid, as_uid):
        return "rejected"
    await _refresh_slot_markup(
        bot,
        game,
        slot,
        as_uid,
        _night_slot_text(game, slot),
        confirm_target=None,
    )
    logger.info(
        "Russian Mafia room=%s target selection restored slot=%s",
        game.room_code,
        slot,
    )
    return "back"


async def send_russian_citizen_wait_panels(bot: Bot, game: Game) -> None:
    """پنل انتظار برای هر زندهٔ بدون عمل فعال. مصنوعی فقط از راه ناظر اوکی می‌شود."""
    text_body = "🌙 لطفاً منتظر اتمام فاز شب بمانید."
    sent = 0
    for player in alive_players(game):
        if player.user_id not in required_waiting_player_ids(game):
            continue
        synthetic = is_synthetic_player_uid(player.user_id)
        if synthetic and not russian_mafia_observer_registered(game):
            continue
        generation = game.russian_mafia_night_index
        player_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _button(
                        game,
                        act="zrm_cit",
                        as_uid=player.user_id,
                        target_uid=0,
                        label="✅ اوکی",
                        mirror=False,
                        generation=generation,
                    )
                ]
            ]
        )
        observer_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _button(
                        game,
                        act="zrm_cit",
                        as_uid=player.user_id,
                        target_uid=0,
                        label="✅ اوکی",
                        mirror=True,
                        generation=generation,
                    )
                ]
            ]
        )
        ui_key = _ready_ui_key(game, player.user_id)
        try:
            await register_mirror_prompt_pair(
                bot,
                game,
                player.user_id,
                ui_key,
                text_body,
                observer_kb if synthetic else player_kb,
                send_player=not synthetic,
                send_observer=False,
                parse_mode="HTML",
            )
            if russian_mafia_observer_registered(game):
                await register_mirror_prompt_pair(
                    bot,
                    game,
                    player.user_id,
                    ui_key + ":obs",
                    text_body,
                    observer_kb,
                    send_player=False,
                    send_observer=True,
                    parse_mode="HTML",
                )
        except Exception:
            logger.exception(
                "Russian Mafia room=%s waiting panel failed user_id=%s",
                game.room_code,
                player.user_id,
            )
            continue
        sent += 1
    logger.info(
        "Russian Mafia room=%s waiting panels sent count=%s required=%s night=%s",
        game.room_code,
        sent,
        len(required_waiting_player_ids(game)),
        game.russian_mafia_night_index,
    )


async def _settle_ready_panel(bot: Bot, game: Game, uid: int) -> None:
    text_body = "✅ متوجه شدم"
    for key in (_ready_ui_key(game, uid), _ready_ui_key(game, uid) + ":obs"):
        entry = game.mirror_prompt_messages.get(key)
        if not isinstance(entry, dict):
            continue
        for role in ("player", "observer"):
            pair = _coerce_mirror_ref(entry.get(role))
            if pair is None:
                continue
            await _try_edit_mirror_message(bot, pair[0], pair[1], text_body, None)
        entry["text"] = text_body


async def ack_russian_citizen(
    bot: Bot,
    game: Game,
    *,
    actor_uid: int,
    as_uid: int,
    generation: int | None,
) -> str:
    should_resolve = False
    async with room_lock(game.room_code):
        if generation != game.russian_mafia_night_index or game.phase != Phase.NIGHT:
            logger.info(
                "Russian Mafia room=%s blocked stale citizen callback generation=%s expected=%s",
                game.room_code,
                generation,
                game.russian_mafia_night_index,
            )
            return "stale"
        player = game.players.get(as_uid)
        if (
            player is None
            or not player.is_alive
            or as_uid not in required_waiting_player_ids(game)
            or not _actor_allowed(game, actor_uid, as_uid)
        ):
            return "rejected"
        if as_uid in game.russian_mafia_citizen_ack_uids:
            return "duplicate"
        game.russian_mafia_citizen_ack_uids.add(as_uid)
        logger.info(
            "Russian Mafia room=%s night acknowledgement user_id=%s night=%s by_observer=%s",
            game.room_code,
            as_uid,
            game.russian_mafia_night_index,
            actor_uid == game.observer_user_id,
        )
        if (
            not getattr(game, "phase_resolution_lock", False)
            and night_ready_to_resolve(game)
        ):
            game.phase_resolution_lock = True
            resolve_night_state(game)
            should_resolve = True
        elif not night_slots_complete(game) or not waiting_acks_complete(game):
            logger.info(
                "Russian Mafia room=%s night not ready pending=%s",
                game.room_code,
                explain_russian_mafia_night_readiness(game)["pending_player_ids"],
            )
    await _settle_ready_panel(bot, game, as_uid)
    if should_resolve:
        await continue_russian_mafia_after_night(bot, game)
    return "ack"


async def route_russian_player_callback(
    bot: Bot,
    game: Game,
    *,
    act: str,
    as_uid: int,
    actor_uid: int,
    target_uid: int,
    generation: int | None,
) -> str:
    if act == "zrm_cit":
        return await ack_russian_citizen(
            bot,
            game,
            actor_uid=actor_uid,
            as_uid=as_uid,
            generation=generation,
        )
    if act in _BACK_ACTS:
        return await restore_russian_target_selection(
            bot,
            game,
            slot=_BACK_ACTS[act],
            actor_uid=actor_uid,
            as_uid=as_uid,
            generation=generation,
        )
    if act in _SELECT_ACTS:
        return await present_russian_target_confirmation(
            bot,
            game,
            slot=_SELECT_ACTS[act],
            actor_uid=actor_uid,
            as_uid=as_uid,
            target_uid=target_uid,
            generation=generation,
        )
    if act in _CONFIRM_ACTS:
        return await complete_slot(
            bot,
            game,
            slot=_slot_for_act(act),
            actor_uid=actor_uid,
            as_uid=as_uid,
            target_uid=target_uid,
            generation=generation,
        )
    return "stale"
