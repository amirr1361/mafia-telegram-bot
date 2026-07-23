"""قوانین نقش ماسون و تیم ماسون — فقط سناریوی ماسون."""

from __future__ import annotations

import html
from dataclasses import dataclass

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = True
HAS_DAY_ACTION = False

MASON_NO_RECRUIT_LABEL = "❌ انتخابی ندارم"
MASON_TAILOR_RECRUIT_LABEL = "تایلر"
MASON_DEAD_TAILOR_UNAVAILABLE_TEXT = "تایلر در بازی نیست."


@dataclass(frozen=True)
class MasonRecruitmentResolution:
    collapsed: bool
    eliminated_uids: tuple[int, ...]
    pending_recruit_uid: int | None
    spy_recruit_safe: bool


def is_mason_role_holder(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.MASON
    )


def find_mason_role_holder(game: Game) -> Player | None:
    for p in game.players.values():
        if p.role == Role.MASON:
            return p
    return None


def find_alive_mason_role_holder(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_role_holder(game, p):
            return p
    return None


def sync_mason_team_alive_only(game: Game) -> None:
    if not is_mason_scenario(game):
        return
    game.mason_team_member_ids = {
        uid
        for uid in game.mason_team_member_ids
        if uid in game.players and game.players[uid].is_alive
    }


def initialize_mason_team_for_new_game(game: Game) -> None:
    """پس از پخش نقش — فقط دارندهٔ نقش ماسون در تیم."""
    if not is_mason_scenario(game):
        return
    holder = find_mason_role_holder(game)
    game.mason_team_member_ids = {holder.user_id} if holder else set()
    game.mason_pending_recruit_uid = None
    game.mason_mason_night_no_recruit = False


def is_mason_team_member(game: Game, player: Player) -> bool:
    if not is_mason_scenario(game):
        return False
    sync_mason_team_alive_only(game)
    return player.is_alive and player.user_id in game.mason_team_member_ids


def alive_mason_team_members(game: Game) -> list[Player]:
    sync_mason_team_alive_only(game)
    members: list[Player] = []
    for uid in sorted(game.mason_team_member_ids):
        p = game.players.get(uid)
        if p is not None and p.is_alive:
            members.append(p)
    return members


def remove_dead_from_mason_team(game: Game) -> None:
    sync_mason_team_alive_only(game)


def _add_mason_team_member(game: Game, uid: int) -> None:
    p = game.players.get(uid)
    if p is None or not p.is_alive:
        return
    game.mason_team_member_ids.add(uid)


def find_mason_tailor(game: Game) -> Player | None:
    if not is_mason_scenario(game):
        return None
    for p in game.players.values():
        if p.role == Role.TAILOR:
            return p
    return None


def find_alive_mason_tailor(game: Game) -> Player | None:
    tailor = find_mason_tailor(game)
    if tailor is None or not tailor.is_alive:
        return None
    return tailor


def _consume_mason_tyler_button(game: Game) -> None:
    game.mason_tyler_button_consumed = True


def mason_tailor_in_room_roles(game: Game) -> bool:
    """آیا تایلر در ترکیب نقش‌های همین اتاق هست."""
    if not is_mason_scenario(game):
        return False
    if any(p.role == Role.TAILOR for p in game.players.values()):
        return True
    from bot.mason_roles import masoon_roles_for_count

    try:
        return Role.TAILOR in masoon_roles_for_count(game.max_players)
    except ValueError:
        return False


def mason_show_tailor_recruit_button(game: Game, mason: Player) -> bool:
    """دکمهٔ «تایلر» — تایلر زندهٔ قابل جذب، یا تایلر مرده/غایب هنوز مصرف‌نشده."""
    if not is_mason_role_holder(game, mason):
        return False
    if game.mason_tyler_button_consumed:
        return False
    if not mason_tailor_in_room_roles(game):
        return False
    tailor = find_mason_tailor(game)
    if tailor is not None and is_mason_team_member(game, tailor):
        return False
    return True


def mason_show_alive_tailor_recruit_button(game: Game, mason: Player) -> bool:
    if not mason_show_tailor_recruit_button(game, mason):
        return False
    tailor = find_mason_tailor(game)
    return tailor is not None and tailor.is_alive


def mason_is_dead_tailor_recruit_button(game: Game, mason: Player) -> bool:
    if not mason_show_tailor_recruit_button(game, mason):
        return False
    tailor = find_mason_tailor(game)
    return tailor is None or not tailor.is_alive


def mason_recruit_panel_button_labels(game: Game, mason: Player) -> list[str]:
    """برچسب دکمه‌های پنل جذب شبانه — برای UI و تست."""
    labels = [_player_display_name(p) for p in mason_recruit_target_pool(game, mason)]
    if mason_show_tailor_recruit_button(game, mason):
        labels.append(MASON_TAILOR_RECRUIT_LABEL)
    labels.append(MASON_NO_RECRUIT_LABEL)
    return labels


def build_mason_recruit_panel_html(game: Game) -> str:
    """متن پنل جذب شبانهٔ ماسون — شامل اعضای زندهٔ تیم."""
    parts = [
        "🧱 <b>ماسون</b>",
        "",
        "یک بازیکن را به تیم ماسون دعوت کنید.",
        "اعضای کنونی تیم ماسون:",
    ]
    members = alive_mason_team_members(game)
    if not members:
        parts.append("هیچ عضوی ثبت نشده است.")
    else:
        for member in members:
            parts.append(html.escape(_player_display_name(member)))
    return "\n".join(parts)


def commit_mason_recruit_tailor(game: Game, mason: Player) -> str | None:
    """جذب تایلر از دکمهٔ اختصاصی — همان پیام و state جذب شهروند امن."""
    if not mason_show_alive_tailor_recruit_button(game, mason):
        return None
    tailor = find_alive_mason_tailor(game)
    if tailor is None:
        return None
    welcome = commit_mason_recruit(game, mason, tailor)
    if welcome is not None:
        _consume_mason_tyler_button(game)
    return welcome


def commit_mason_recruit_dead_tailor(game: Game, mason: Player) -> bool:
    """انتخاب تایلر مرده/غایب — بدون جذب، مصرف دکمه، بدون اقدام شبانه."""
    if not mason_is_dead_tailor_recruit_button(game, mason):
        return False
    game.mason_pending_recruit_uid = None
    game.mason_mason_night_no_recruit = True
    _consume_mason_tyler_button(game)
    return True


def mason_recruit_target_pool(game: Game, mason: Player) -> list[Player]:
    if not is_mason_role_holder(game, mason):
        return []
    sync_mason_team_alive_only(game)
    team_ids = game.mason_team_member_ids
    return [
        p
        for p in game.players.values()
        if p.is_alive and p.user_id != mason.user_id and p.user_id not in team_ids
    ]


def mason_can_recruit_target(game: Game, mason: Player, target: Player) -> bool:
    if not is_mason_role_holder(game, mason):
        return False
    if not target.is_alive or target.user_id == mason.user_id:
        return False
    if is_mason_team_member(game, target):
        return False
    return any(p.user_id == target.user_id for p in mason_recruit_target_pool(game, mason))


def _player_display_name(player: Player) -> str:
    return player.full_name or str(player.user_id)


def build_mason_recruit_welcome_message(game: Game, recruit_uid: int) -> str:
    """متن پیام خصوصی پس از تأیید جذب."""
    recruit = game.players.get(recruit_uid)
    if recruit is None:
        return ""
    holder = find_mason_role_holder(game)
    members = alive_mason_team_members(game)
    other_than_recruit = [m for m in members if m.user_id != recruit_uid]

    if len(other_than_recruit) == 1 and holder and other_than_recruit[0].user_id == holder.user_id:
        holder_name = _player_display_name(holder)
        return (
            "شما عضو تیم ماسون شدید.\n\n"
            f"نقش ماسون متعلق به:\n({holder_name})"
        )

    lines = ["شما عضو تیم ماسون شدید.", "", "اعضای تیم ماسون:", ""]
    for member in members:
        name = _player_display_name(member)
        if holder and member.user_id == holder.user_id:
            lines.append(f"{name} - ماسون")
        else:
            lines.append(name)
    return "\n".join(lines)


def commit_mason_recruit(
    game: Game, mason: Player, target: Player | None
) -> str | None:
    """ثبت جذب شبانه — پیام خوش‌آمد برای هدف (اگر انتخاب شده)."""
    if not is_mason_role_holder(game, mason):
        return None
    if target is None:
        game.mason_pending_recruit_uid = None
        game.mason_mason_night_no_recruit = True
        return None
    if not mason_can_recruit_target(game, mason, target):
        return None
    game.mason_pending_recruit_uid = target.user_id
    game.mason_mason_night_no_recruit = False
    _add_mason_team_member(game, target.user_id)
    return build_mason_recruit_welcome_message(game, target.user_id)


def _was_alive_at_night_start(game: Game, uid: int) -> bool:
    """برای ارزیابی جذب/فروپاشی — نه وضعیت پس از مرگ‌های معلق همان شب."""
    snap = game.bazpors_alive_at_night_start
    if not snap:
        pl = game.players.get(uid)
        return pl is not None and pl.is_alive
    return bool(snap.get(uid, False))


def _town_mason_team_member_uids(
    game: Game, *, at_night_start: bool = False
) -> list[int]:
    sync_mason_team_alive_only(game)
    out: list[int] = []
    snap = game.bazpors_alive_at_night_start if at_night_start else None
    for uid in game.mason_team_member_ids:
        p = game.players.get(uid)
        if p is None:
            continue
        if snap is not None:
            if not snap.get(uid, False):
                continue
        elif not p.is_alive:
            continue
        if is_mafia_team(p.role):
            continue
        out.append(uid)
    return sorted(out)


def resolve_mason_recruitment_result(game: Game) -> MasonRecruitmentResolution:
    """ارزیابی جذب پس از شب — فروپاشی در صورت جذب مافیا (به‌جز جاسوس)."""
    if not is_mason_scenario(game):
        return MasonRecruitmentResolution(False, (), None, False)

    remove_dead_from_mason_team(game)
    pending = game.mason_pending_recruit_uid
    no_recruit = game.mason_mason_night_no_recruit

    if no_recruit or pending is None:
        clear_mason_recruit_night_state(game)
        return MasonRecruitmentResolution(False, (), None, False)

    recruit = game.players.get(pending)
    if recruit is None or not _was_alive_at_night_start(game, pending):
        clear_mason_recruit_night_state(game)
        return MasonRecruitmentResolution(False, (), pending, False)

    from bot.roles.mason_spy import is_mason_spy

    if not is_mafia_team(recruit.role):
        clear_mason_recruit_night_state(game)
        return MasonRecruitmentResolution(False, (), pending, False)

    if is_mason_spy(game, recruit):
        clear_mason_recruit_night_state(game)
        return MasonRecruitmentResolution(False, (), pending, True)

    victims = tuple(_town_mason_team_member_uids(game, at_night_start=True))
    clear_mason_recruit_night_state(game)
    return MasonRecruitmentResolution(
        collapsed=True,
        eliminated_uids=victims,
        pending_recruit_uid=pending,
        spy_recruit_safe=False,
    )


def clear_mason_recruit_night_state(game: Game) -> None:
    game.mason_pending_recruit_uid = None
    game.mason_mason_night_no_recruit = False


def clear_mason_fraternity_state(game: Game) -> None:
    game.mason_team_member_ids = set()
    clear_mason_recruit_night_state(game)
