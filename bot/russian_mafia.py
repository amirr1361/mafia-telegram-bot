"""مافیای روسی — ترکیب نقش، برد، و وضعیت سناریو. جدا از بازپرس/مذاکره/ماسون."""

from __future__ import annotations

import logging

from bot.models import Game, Player, Role

logger = logging.getLogger(__name__)

SCENARIO_KEY = "russian_mafia"
HOST_HELPER_MODE = "host_helper"
PLAYER_COUNTS = frozenset({8, 9})

ROLE_GODFATHER = Role.RUSSIAN_GODFATHER
ROLE_TERROR = Role.TERROR
ROLE_SIMPLE_MAFIA = Role.MAFIA_BASIC

RUSSIAN_ROLE_LABELS_FA: dict[Role, str] = {
    ROLE_GODFATHER: "گادفادر",
    ROLE_TERROR: "ترور",
    ROLE_SIMPLE_MAFIA: "مافیا ساده",
    Role.DOCTOR: "دکتر",
    Role.DETECTIVE: "کارآگاه",
    Role.CITIZEN: "شهروند ساده",
}

RUSSIAN_ROLE_DESCRIPTIONS_FA: dict[Role, str] = {
    ROLE_GODFATHER: (
        "شما گادفادر هستید.\n"
        "تا وقتی زنده هستید، شلیک شبانهٔ مافیا با شماست و یک بازیکن زنده را انتخاب می‌کنید."
    ),
    ROLE_TERROR: (
        "شما ترور هستید.\n"
        "در طول روز می‌توانید یک بازیکن را همراه خود از بازی خارج کنید."
    ),
    ROLE_SIMPLE_MAFIA: (
        "شما مافیا ساده هستید.\n"
        "توان ویژهٔ جداگانه‌ای ندارید. اگر گادفادر زنده نباشد، "
        "شلیک شبانهٔ مافیا ممکن است به شما برسد."
    ),
    Role.DOCTOR: (
        "شما دکتر هستید.\n"
        "هر شب بر اساس تعداد بازیکنان زنده می‌توانید یک یا دو نفر را نجات دهید.\n"
        "در طول کل بازی فقط یک بار می‌توانید خودتان را نجات دهید."
    ),
    Role.DETECTIVE: (
        "شما کارآگاه هستید.\n"
        "هر شب می‌توانید از یک بازیکن استعلام بگیرید."
    ),
    Role.CITIZEN: "شما شهروند ساده هستید.",
}

DOCTOR_DESCRIPTION_TWO_SAVES_FA = (
    "شما دکتر هستید.\n"
    "هر شب می‌توانید یک نفر را نجات دهید.\n"
    "در طول کل بازی دو بار می‌توانید خودتان را نجات دهید."
)

STALE_ACTION_FA = "این اقدام قبلاً انجام شده است."


def is_russian_mafia_game(game: Game) -> bool:
    return game.scenario_name == SCENARIO_KEY


def is_russian_host_helper(game: Game) -> bool:
    return is_russian_mafia_game(game) and game.bazpors_host_mode == HOST_HELPER_MODE


def russian_mafia_observer_registered(game: Game) -> bool:
    """ناظر مافیای روسی — همان شناسهٔ عمومی ناظر، بدون حالت no_host."""
    return (
        is_russian_host_helper(game)
        and game.observer_user_id is not None
        and game.observer_prompt_status != "skipped"
    )


def russian_host_mode_keyboard(count: int):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from bot.main import CreatePickHostMode

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="بازیکن گرداننده",
                    callback_data=CreatePickHostMode(
                        slug=SCENARIO_KEY,
                        count=count,
                        mode=HOST_HELPER_MODE,
                    ).pack(),
                )
            ]
        ]
    )


def host_mode_rejection_reason(mode: str) -> str | None:
    if mode == HOST_HELPER_MODE:
        return None
    if mode == "no_host":
        return "مافیای روسی فقط حالت بازیکن گرداننده دارد."
    return "برای مافیای روسی فقط حالت بازیکن گرداننده مجاز است."


def russian_roles_for_count(n: int) -> list[Role]:
    if n not in PLAYER_COUNTS:
        raise ValueError(f"مافیای روسی فقط ۸ یا ۹ بازیکن؛ الان {n}")
    citizens = [Role.CITIZEN] * 4
    if n == 8:
        mafia = [ROLE_GODFATHER, ROLE_TERROR]
    else:
        mafia = [ROLE_GODFATHER, ROLE_SIMPLE_MAFIA, ROLE_SIMPLE_MAFIA]
    return [*mafia, Role.DOCTOR, Role.DETECTIVE, *citizens]


def russian_role_label_fa(role: Role | None) -> str:
    if role is None:
        return "—"
    return RUSSIAN_ROLE_LABELS_FA.get(role, role.value)




def is_russian_mafia_role(role: Role | None) -> bool:
    return role in (ROLE_GODFATHER, ROLE_TERROR, ROLE_SIMPLE_MAFIA)


def alive_players(game: Game) -> list[Player]:
    return [p for p in game.players.values() if p.is_alive and p.role != Role.OBSERVER]


def russian_doctor_self_save_limit(game: Game | None) -> int:
    """نجات خود پزشک مافیای روسی: فقط یک بار در کل بازی (۸ و ۹ نفر یکسان)."""
    del game
    return 1


def russian_alive_player_count(game: Game) -> int:
    """تعداد صندلی‌های بازیکن زنده؛ ناظر و غیرصندلی حذف می‌شوند."""
    return len(alive_players(game))


def russian_doctor_heal_capacity(game: Game) -> int:
    """ظرفیت نجات همان شب بر اساس زنده‌ها در لحظهٔ ارسال پنل.

    دقیقاً ۹ زنده → ۲ نجات متمایز؛ ۸ یا کمتر → ۱ نجات؛ بیش از ۹ → رفتار قبلی (۱ نجات).
    """
    alive = russian_alive_player_count(game)
    if alive == 9:
        return 2
    return 1


def ensure_russian_doctor_night_capacity(game: Game) -> int:
    """ظرفیت شب جاری؛ اگر هنوز ست نشده از شمار زنده محاسبه می‌شود."""
    if int(game.russian_mafia_doctor_night_capacity or 0) <= 0:
        game.russian_mafia_doctor_night_capacity = russian_doctor_heal_capacity(game)
    return int(game.russian_mafia_doctor_night_capacity)


def russian_doctor_save_uids(game: Game) -> list[int]:
    """اهداف تأییدشدهٔ نجات امشب."""
    targets = [int(uid) for uid in (game.russian_mafia_doctor_targets or [])]
    if targets:
        return targets
    if game.russian_mafia_doctor_target is not None:
        return [int(game.russian_mafia_doctor_target)]
    return []


def russian_role_description_fa(role: Role, game: Game | None = None) -> str:
    del game
    return RUSSIAN_ROLE_DESCRIPTIONS_FA.get(role, "نقش شما در مافیای روسی.")

def find_alive_role(game: Game, role: Role) -> Player | None:
    for player in alive_players(game):
        if player.role == role:
            return player
    return None


def faction_counts(game: Game) -> tuple[int, int]:
    mafia = 0
    town = 0
    for player in alive_players(game):
        if is_russian_mafia_role(player.role):
            mafia += 1
        else:
            town += 1
    return mafia, town


def winner_of(game: Game) -> str | None:
    """town وقتی مافیا صفر است؛ وگرنه mafia وقتی شمار مافیا به شهروند برسد."""
    mafia, town = faction_counts(game)
    if mafia == 0:
        return "town"
    if mafia >= town:
        return "mafia"
    return None


def alive_simple_mafia(game: Game) -> list[Player]:
    """مافیای سادهٔ زنده، به ترتیب شمارهٔ صندلی سپس شناسه."""
    found = [p for p in alive_players(game) if p.role == ROLE_SIMPLE_MAFIA]
    found.sort(
        key=lambda p: (p.seat if p.seat is not None else 10**9, p.user_id)
    )
    return found


def mafia_shot_holder(game: Game) -> Player | None:
    """گادفادر زنده؛ وگرنه ترور (۸ نفر) یا کم‌شماره‌ترین مافیای سادهٔ زنده (۹ نفر)."""
    godfather = find_alive_role(game, ROLE_GODFATHER)
    if godfather is not None:
        return godfather
    terror = find_alive_role(game, ROLE_TERROR)
    if terror is not None:
        return terror
    simples = alive_simple_mafia(game)
    return simples[0] if simples else None


def reset_russian_night_actions(game: Game) -> None:
    game.russian_mafia_mafia_target = None
    game.russian_mafia_mafia_confirmed = False
    game.russian_mafia_mafia_action_holder = None
    game.russian_mafia_doctor_target = None
    game.russian_mafia_doctor_targets = []
    game.russian_mafia_doctor_night_capacity = 0
    game.russian_mafia_doctor_confirmed = False
    game.russian_mafia_detective_target = None
    game.russian_mafia_detective_confirmed = False
    game.russian_mafia_detective_alignment = None


def reset_russian_day_actions(game: Game) -> None:
    game.russian_mafia_terror_day_active = False
    game.russian_mafia_terror_target = None
    game.russian_mafia_terror_confirmed = False


def initialize_russian_mafia_state(game: Game) -> None:
    """شروع دست — نجات خودی پزشک و هویت ناظر از نو صفر می‌شود فقط در تخصیص نقش."""
    game.russian_mafia_doctor_self_save_count = 0
    game.russian_mafia_doctor_targets = []
    game.russian_mafia_doctor_night_capacity = 0
    game.russian_mafia_mafia_team_revealed = False
    game.russian_mafia_intro_prompt_sent = False
    game.russian_mafia_day_result_applied = False
    game.russian_mafia_night_result_sent_index = 0
    reset_russian_night_actions(game)
    reset_russian_day_actions(game)
    game.russian_mafia_night_index = 0
    game.russian_mafia_day_index = 0
    game.russian_mafia_post_night_stage = None
    game.russian_mafia_discipline_prompt_night = 0
    game.russian_mafia_discipline_target = None
    game.russian_mafia_table_inquiry_used = 0
    game.russian_mafia_table_inquiry_pending = None
    game.russian_mafia_inquiry_completed_night = 0
    game.russian_mafia_citizen_ack_uids = set()
    game.russian_mafia_winner_announced = False
    game.russian_mafia_observer_roster_sent = False
    game.bazpors_night_discipline_kick_uid = None
    game.phase_resolution_lock = False
    holder = mafia_shot_holder(game)
    observer = game.observer_user_id
    logger.info(
        "Russian Mafia started: room=%s, players=%s, observer=%s",
        game.room_code,
        len([p for p in game.players.values() if p.role != Role.OBSERVER]),
        observer,
    )
    if holder is not None and holder.role == ROLE_GODFATHER:
        logger.info("Russian Mafia night: mafia_holder=Godfather")
    elif holder is not None and holder.role == ROLE_TERROR:
        logger.info("Russian Mafia night: Godfather dead, mafia_holder=Terror")
    elif holder is not None:
        logger.info(
            "Russian Mafia night: Godfather dead, mafia_holder=SimpleMafia seat=%s",
            holder.seat,
        )


def detective_alignment(role: Role | None) -> str:
    """گادفادر همیشه منفی است. ترور و مافیای ساده مثبت‌اند."""
    if role in (ROLE_TERROR, ROLE_SIMPLE_MAFIA):
        return "positive"
    return "negative"


def record_russian_elimination(
    game: Game, uid: int, *, source: str
) -> bool:
    """ثبت قطعی حذف روسی: وضعیت، audit و صف پیام؛ تکرار امن است."""
    player = game.players.get(uid)
    if player is None or not player.is_alive or player.role == Role.OBSERVER:
        return False
    player.is_alive = False
    from bot.observer_delivery import queue_player_elimination_notify

    queue_player_elimination_notify(game, uid)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "player.eliminated",
            uid=uid,
            source=source,
            role=player.role.value if player.role else None,
            name=player.full_name,
            russian={
                "day": int(game.russian_mafia_day_index or 1),
                "night": int(game.russian_mafia_night_index or 0),
                "phase": game.phase.value,
            },
        )
    except Exception:
        logger.exception(
            "Russian Mafia elimination audit failed room=%s uid=%s",
            game.room_code,
            uid,
        )
    return True


def doctor_self_save_allowed(game: Game, doctor_uid: int, target_uid: int) -> bool:
    if target_uid != doctor_uid:
        return True
    return game.russian_mafia_doctor_self_save_count < russian_doctor_self_save_limit(game)


def required_night_slots(game: Game) -> set[str]:
    slots: set[str] = set()
    if mafia_shot_holder(game) is not None:
        slots.add("mafia")
    if find_alive_role(game, Role.DOCTOR) is not None:
        slots.add("doctor")
    if find_alive_role(game, Role.DETECTIVE) is not None:
        slots.add("detective")
    return slots


def night_slots_complete(game: Game) -> bool:
    needed = required_night_slots(game)
    done = set()
    if game.russian_mafia_mafia_confirmed or "mafia" not in needed:
        if "mafia" in needed and game.russian_mafia_mafia_confirmed:
            done.add("mafia")
        elif "mafia" not in needed:
            pass
    if "doctor" in needed and game.russian_mafia_doctor_confirmed:
        done.add("doctor")
    if "detective" in needed and game.russian_mafia_detective_confirmed:
        done.add("detective")
    return needed <= done


def active_night_actor_uids(game: Game) -> set[int]:
    """بازیکنانی که همین شب پنل عمل فعال دارند، نه پنل انتظار."""
    uids: set[int] = set()
    holder = mafia_shot_holder(game)
    if holder is not None:
        uids.add(holder.user_id)
    for role in (Role.DOCTOR, Role.DETECTIVE):
        actor = find_alive_role(game, role)
        if actor is not None:
            uids.add(actor.user_id)
    return uids


def required_waiting_player_ids(game: Game) -> set[int]:
    """زنده‌هایی که عمل شب ندارند و باید اوکی بزنند."""
    active = active_night_actor_uids(game)
    return {player.user_id for player in alive_players(game) if player.user_id not in active}


def waiting_acks_complete(game: Game) -> bool:
    return required_waiting_player_ids(game) <= set(game.russian_mafia_citizen_ack_uids)


def night_ready_to_resolve(game: Game) -> bool:
    return night_slots_complete(game) and waiting_acks_complete(game)


def explain_russian_mafia_night_readiness(game: Game, gm: object | None = None) -> dict:
    """تشخیص آمادگی شب. نقش مخفی را در متن عمومی نمی‌گذارد."""
    del gm
    type_by_slot = {
        "mafia": "mafia_shot",
        "doctor": "doctor_save",
        "detective": "detective_inquiry",
    }
    confirmed = {
        "mafia": game.russian_mafia_mafia_confirmed,
        "doctor": game.russian_mafia_doctor_confirmed,
        "detective": game.russian_mafia_detective_confirmed,
    }
    needed = required_night_slots(game)
    holder = mafia_shot_holder(game)
    actors = {
        "mafia": holder.user_id if holder is not None else None,
        "doctor": (
            find_alive_role(game, Role.DOCTOR).user_id
            if find_alive_role(game, Role.DOCTOR) is not None
            else None
        ),
        "detective": (
            find_alive_role(game, Role.DETECTIVE).user_id
            if find_alive_role(game, Role.DETECTIVE) is not None
            else None
        ),
    }
    pending_action_ids = [
        actors[slot]
        for slot in ("mafia", "doctor", "detective")
        if slot in needed and not confirmed[slot] and actors[slot] is not None
    ]
    waiting = required_waiting_player_ids(game)
    acked = set(game.russian_mafia_citizen_ack_uids) & waiting
    pending_wait = sorted(waiting - acked)
    pending_types = [
        type_by_slot[slot]
        for slot in ("mafia", "doctor", "detective")
        if slot in needed and not confirmed[slot]
    ]
    if pending_wait:
        pending_types.append("waiting_ok")
    return {
        "room_code": game.room_code,
        "night_index": int(game.russian_mafia_night_index),
        "required_waiting_player_ids": sorted(waiting),
        "completed_actions": [
            type_by_slot[slot] for slot in ("mafia", "doctor", "detective") if slot in needed and confirmed[slot]
        ],
        "completed_acknowledgements": sorted(acked),
        "pending_player_ids": sorted(set(pending_action_ids) | set(pending_wait)),
        "pending_responsibility_types": pending_types,
        "ready": night_ready_to_resolve(game),
    }


def apply_night_resolution(game: Game) -> str | None:
    """حذف شلیک مافیا مگر پزشک همان هدف را نجات داده باشد. برنده یا None."""
    target = game.russian_mafia_mafia_target
    saved = (
        target is not None
        and game.russian_mafia_doctor_confirmed
        and target in russian_doctor_save_uids(game)
    )
    eliminated_uid: int | None = None
    if target is not None and not saved:
        if record_russian_elimination(game, target, source="night_shot"):
            eliminated_uid = target
    if game.russian_mafia_detective_confirmed and game.russian_mafia_detective_target is not None:
        investigated = game.players.get(game.russian_mafia_detective_target)
        role = investigated.role if investigated is not None else None
        game.russian_mafia_detective_alignment = detective_alignment(role)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "russian.night_resolved",
            night=int(game.russian_mafia_night_index),
            eliminated_uid=eliminated_uid,
            mafia_target=game.russian_mafia_mafia_target,
            doctor_targets=list(game.russian_mafia_doctor_targets or []),
            detective_target=game.russian_mafia_detective_target,
            detective_alignment=game.russian_mafia_detective_alignment,
            russian={
                "day": int(game.russian_mafia_day_index or 1),
                "night": int(game.russian_mafia_night_index),
                "phase": game.phase.value,
            },
        )
    except Exception:
        logger.exception(
            "Russian Mafia night audit failed room=%s", game.room_code
        )
    return winner_of(game)
