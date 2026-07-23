"""گزارش کامل شب — فقط سناریوی ماسون (ناظر / گرداننده)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.models import Game, Role
from bot.room_mode import is_mason_scenario

if TYPE_CHECKING:
    from bot.game import GameManager


def clear_mason_night_report_snapshot(game: Game) -> None:
    game.mason_night_report_frozen = False
    game.mason_night_report_doctor_save_uids = []
    game.mason_night_report_sniper_selected_uids = []
    game.mason_night_report_commander_approved_uids = []
    game.mason_night_report_gunner_target_uid = None
    game.mason_night_report_guardian_target_uid = None
    game.mason_night_report_recruit_uid = None
    game.mason_night_report_no_recruit = False
    game.mason_night_report_natasha_target_uid = None
    game.mason_night_report_natasha_pick_confirmed = False
    game.mason_night_report_priest_target_uid = None
    game.mason_night_report_priest_pick_confirmed = False
    game.mason_night_report_saboteur_target_uid = None
    game.mason_night_report_nato_guess_role = None
    game.mason_night_report_nato_guess_target_uid = None
    game.mason_night_report_nato_tonight = False


def freeze_mason_night_report_snapshot(game: Game) -> None:
    """قبل از اعمال مرگ‌های شب — نگه‌داری اقدامات برای گزارش پایان شب."""
    if not is_mason_scenario(game) or game.mason_night_report_frozen:
        return
    game.mason_night_report_doctor_save_uids = list(game.mason_doctor_night_save_uids)
    game.mason_night_report_sniper_selected_uids = list(
        game.mason_sniper_night_selected_uids
    )
    game.mason_night_report_commander_approved_uids = list(
        game.mason_commander_night_approved_uids
    )
    game.mason_night_report_gunner_target_uid = game.mason_gunner_night_target_uid
    game.mason_night_report_guardian_target_uid = game.mason_guardian_night_target_uid
    game.mason_night_report_recruit_uid = game.mason_pending_recruit_uid
    game.mason_night_report_no_recruit = game.mason_mason_night_no_recruit
    game.mason_night_report_natasha_target_uid = game.mason_natasha_target_uid
    game.mason_night_report_natasha_pick_confirmed = (
        game.mason_natasha_pick_confirmed or game.mason_night_natasha_confirmed
    )
    game.mason_night_report_priest_target_uid = game.mason_priest_target_uid
    game.mason_night_report_priest_pick_confirmed = game.mason_priest_pick_confirmed
    game.mason_night_report_saboteur_target_uid = game.mason_saboteur_night_target_uid
    game.mason_night_report_nato_guess_role = game.mason_nato_guess_role
    game.mason_night_report_nato_guess_target_uid = game.mason_nato_guess_target_uid
    game.mason_night_report_nato_tonight = game.mason_nato_tonight
    game.mason_night_report_frozen = True


def _join_fa_names(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} و {names[1]}"
    return "، ".join(names[:-1]) + f" و {names[-1]}"


def _join_fa_comma_names(names: list[str]) -> str:
    """نام‌ها در یک خط — جداشده با ویرگول فارسی."""
    return "، ".join(names)


def _mason_night_report_resolved_natasha_target(game: Game) -> int | None:
    if game.mason_night_report_frozen:
        return game.mason_night_report_natasha_target_uid
    return game.mason_natasha_target_uid


def _mason_night_report_resolved_natasha_confirmed(game: Game) -> bool:
    if game.mason_night_report_frozen:
        return game.mason_night_report_natasha_pick_confirmed
    return game.mason_natasha_pick_confirmed or game.mason_night_natasha_confirmed


def _mason_night_report_doctor_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_report_name, _nr_uid_for_role

    doc_uid = _nr_uid_for_role(game, Role.DOCTOR)
    if doc_uid is None or not alive_before.get(doc_uid, False):
        return []
    save_uids = [
        uid
        for uid in game.mason_night_report_doctor_save_uids
        if uid in game.players
    ]
    if not save_uids:
        return ["💉 نجات پزشک: انتخابی نداشت"]
    names = [_nr_report_name(game, gm, uid) for uid in save_uids]
    return [f"💉 نجات پزشک: {_join_fa_comma_names(names)}"]


def _mason_night_report_sniper_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_player_name_only, _nr_uid_for_role

    sn_uid = _nr_uid_for_role(game, Role.SNIPER)
    if sn_uid is None or not alive_before.get(sn_uid, False):
        return []
    selected = [
        uid
        for uid in game.mason_night_report_sniper_selected_uids
        if uid in game.players
    ]
    if not selected:
        return []
    names = [_nr_player_name_only(game, uid) for uid in selected]
    return [f"🎯 اسنایپر: {_join_fa_names(names)}"]


def _mason_night_report_commander_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_player_name_only, _nr_uid_for_role

    cmd_uid = _nr_uid_for_role(game, Role.COMMANDER)
    if cmd_uid is None or not alive_before.get(cmd_uid, False):
        return []
    approved = [
        uid
        for uid in game.mason_night_report_commander_approved_uids
        if uid in game.players
    ]
    if not approved:
        return []
    names = [_nr_player_name_only(game, uid) for uid in approved]
    return [f"🪖 فرمانده: {_join_fa_names(names)}"]


def _mason_night_report_gunner_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_report_name, _nr_uid_for_role

    gun_uid = _nr_uid_for_role(game, Role.GUNMAN)
    if gun_uid is None or not alive_before.get(gun_uid, False):
        return []
    tgt = game.mason_night_report_gunner_target_uid
    if tgt is None or tgt not in game.players:
        return []
    return [f"🔫 تفنگدار: {_nr_report_name(game, gm, tgt)}"]


def _mason_night_report_guardian_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_report_name, _nr_uid_for_role

    gd_uid = _nr_uid_for_role(game, Role.BODYGUARD)
    if gd_uid is None or not alive_before.get(gd_uid, False):
        return []
    tgt = game.mason_night_report_guardian_target_uid
    if tgt is None or tgt not in game.players:
        return []
    return [f"🛡️ محافظ: {_nr_report_name(game, gm, tgt)}"]


def _mason_night_report_mason_recruit_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_report_name, _nr_uid_for_role

    mason_uid = _nr_uid_for_role(game, Role.MASON)
    if mason_uid is None or not alive_before.get(mason_uid, False):
        return []
    if game.mason_night_report_no_recruit:
        return []
    tgt = game.mason_night_report_recruit_uid
    if tgt is None or tgt not in game.players:
        return []
    return [f"🧱 ماسون: {_nr_report_name(game, gm, tgt)}"]


def _mason_night_report_natasha_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_report_name, _nr_uid_for_role

    nat_uid = _nr_uid_for_role(game, Role.NATASHA)
    if nat_uid is None or not alive_before.get(nat_uid, False):
        return []
    tgt = _mason_night_report_resolved_natasha_target(game)
    if tgt is None or tgt not in game.players:
        return []
    # گزارش اقدام — مستقل از خنثی‌سازی کشیش یا اثر سکوت روز بعد.
    if not _mason_night_report_resolved_natasha_confirmed(game):
        return []
    return [f"🤐 ناتاشا: {_nr_report_name(game, gm, tgt)}"]


def _mason_night_report_priest_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_report_name, _nr_uid_for_role

    pr_uid = _nr_uid_for_role(game, Role.PRIEST)
    if pr_uid is None or not alive_before.get(pr_uid, False):
        return []
    tgt = game.mason_night_report_priest_target_uid
    if tgt is None or tgt not in game.players:
        return []
    if not game.mason_night_report_priest_pick_confirmed:
        return []
    return [f"⛪ کشیش: {_nr_report_name(game, gm, tgt)}"]


def _mason_night_report_saboteur_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    from bot.bazpors_narrator import _nr_report_name, _nr_uid_for_role

    sab_uid = _nr_uid_for_role(game, Role.SABOTEUR)
    if sab_uid is None or not alive_before.get(sab_uid, False):
        return []
    tgt = game.mason_night_report_saboteur_target_uid
    if tgt is None or tgt not in game.players:
        return []
    return [f"🔧 خرابکار: {_nr_report_name(game, gm, tgt)}"]


def mason_night_report_natasha_silence_outcome_line(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> str | None:
    """جملهٔ سکوت ناتاشا در خلاصهٔ پایان شب — فقط اگر اثر فعال باشد."""
    from bot.bazpors_narrator import _nr_player_name_only, _nr_uid_for_role
    from bot.roles.mason_priest import mason_priest_blocks_natasha_report

    nat_uid = _nr_uid_for_role(game, Role.NATASHA)
    if nat_uid is None or not alive_before.get(nat_uid, False):
        return None
    tgt = _mason_night_report_resolved_natasha_target(game)
    if tgt is None or not _mason_night_report_resolved_natasha_confirmed(game):
        return None
    target = game.players.get(tgt)
    if target is None or not target.is_alive:
        return None
    if mason_priest_blocks_natasha_report(game):
        return None
    name = _nr_player_name_only(game, tgt)
    return (
        f"به دستور ناتاشا، {name} باید سکوت کند و فقط مجاز به شرکت در "
        "رای‌گیری آخر روز خواهد بود."
    )


def _mason_night_report_nato_line(
    game: Game, gm: "GameManager"
) -> str | None:
    from bot.bazpors_narrator import _nr_report_name, role_label_fa

    if not game.mason_night_report_nato_tonight:
        return None
    guess_role = game.mason_night_report_nato_guess_role
    tgt_uid = game.mason_night_report_nato_guess_target_uid
    if guess_role is None or tgt_uid is None or tgt_uid not in game.players:
        return None
    tgt_name = _nr_report_name(game, gm, tgt_uid)
    role_txt = role_label_fa(guess_role)
    target = game.players[tgt_uid]
    if target.role == guess_role:
        return f"🔴 ناتو: {tgt_name} خارج شد"
    return f"⚪ ناتویی ناموفق — حدس نقش {role_txt} — هدف {tgt_name}"


def _mason_night_report_collapse_section(
    game: Game, gm: "GameManager", alive_before: dict[int, bool]
) -> list[str]:
    del alive_before
    if not game.mason_last_night_had_collapse:
        return []
    from bot.bazpors_narrator import _nr_report_name

    recruit_uid = game.mason_night_report_recruit_uid
    if recruit_uid is not None and recruit_uid in game.players:
        return [
            f"💥 مرگ ماسونی: {_nr_report_name(game, gm, recruit_uid)} "
            "به تیم ماسون اضافه شد"
        ]
    return ["💥 مرگ ماسونی"]


def mason_night_report_section_builders() -> tuple:
    """ترتیب بخش‌های گزارش شب ماسون."""
    return (
        _mason_night_report_doctor_section,
        _mason_night_report_sniper_section,
        _mason_night_report_commander_section,
        _mason_night_report_gunner_section,
        _mason_night_report_guardian_section,
        _mason_night_report_mason_recruit_section,
        _mason_night_report_natasha_section,
        _mason_night_report_priest_section,
        _mason_night_report_saboteur_section,
        _mason_night_report_collapse_section,
    )


def build_mason_night_timeline_lines(
    game: Game, gm: "GameManager"
) -> list[str]:
    """خطوط خلاصهٔ اقدامات یک شب — برای تایم‌لاین پایان بازی ماسون."""
    from bot.bazpors_narrator import (
        _night_report_detective_section,
        _night_report_mafia_section,
    )

    alive_before = game.bazpors_alive_at_night_start
    if not alive_before:
        alive_before = {uid: p.is_alive for uid, p in game.players.items()}
    lines: list[str] = []
    lines.extend(_night_report_mafia_section(game, gm))
    for section in mason_night_report_section_builders():
        lines.extend(section(game, gm, alive_before))
    lines.extend(_night_report_detective_section(game, gm, alive_before))
    nato_line = _mason_night_report_nato_line(game, gm)
    if nato_line:
        lines.append(nato_line)
    return lines
