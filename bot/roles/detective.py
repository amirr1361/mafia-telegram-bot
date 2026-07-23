"""منطق هستهٔ شب کارآگاه — مشترک semi_auto و no_host."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bot.models import Game, Player, Role
from bot.roles import mafia_boss as _boss_role
from bot.roles.night_state import detective_night_state


def scenario_has_shiad(game: Game) -> bool:
    """فقط سناریوهای بازپرس از اثر شیاد روی کارآگاه پشتیبانی می‌کنند."""
    return game.scenario_name in ("bazpors", "bazpors_salamat_test")


class DetectiveInquiryKind(str, Enum):
    POSITIVE = "positive"
    NEGATIVE_TOWN = "negative_town"
    NEGATIVE_BOSS = "negative_boss"
    NEGATIVE_SHIAD = "negative_shiad"


@dataclass(frozen=True)
class DetectiveInquiryResult:
    kind: DetectiveInquiryKind
    target_uid: int

    @property
    def is_positive(self) -> bool:
        return self.kind == DetectiveInquiryKind.POSITIVE

    def label_fa(self) -> str:
        return "مثبت" if self.is_positive else "منفی"

    def detail_fa(self) -> str:
        if self.kind == DetectiveInquiryKind.POSITIVE:
            return "مثبت (مافیایی)"
        if self.kind == DetectiveInquiryKind.NEGATIVE_SHIAD:
            return "منفی (شهروندی — اثر شیاد)"
        if self.kind == DetectiveInquiryKind.NEGATIVE_BOSS:
            return "منفی (شهروندی — رئیس مافیا)"
        return "منفی (شهروندی)"

    def host_answer_fa(self) -> str:
        if self.kind == DetectiveInquiryKind.POSITIVE:
            return "مثبت / مافیایی"
        if self.kind == DetectiveInquiryKind.NEGATIVE_SHIAD:
            return "منفی / شهروندی (استعلام خراب — شیاد)"
        if self.kind == DetectiveInquiryKind.NEGATIVE_BOSS:
            return "منفی / شهروندی (رئیس برای کارآگاه)"
        return "منفی / شهروندی"

    def private_line_fa(self, target_name_html: str) -> str:
        return f"استعلام شما از {target_name_html} {self.label_fa()} است."


def find_alive_detective(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.DETECTIVE:
            return p
    return None


def alive_players(game: Game) -> list[Player]:
    return [p for p in game.players.values() if p.is_alive]


def investigation_pool(game: Game) -> list[Player]:
    """بازیکنان قابل استعلام — در ماسون به‌جز خود کارآگاه."""
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.roles.mason_detective import mason_detective_investigation_pool

        return mason_detective_investigation_pool(game)
    return alive_players(game)


def committed_target_uid(game: Game) -> int | None:
    return detective_night_state(game).target_uid


def target_reads_as_mafia_for_detective(game: Game, p: Player) -> bool:
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.roles.mason_detective import mason_detective_reads_positive

        return mason_detective_reads_positive(game, p)
    if p.user_id in game.bazpors_sniper_eliminated_uids:
        return False
    if game.scenario_name == "mozakere" and p.user_id in game.mozakere_mafia_recruit_ids:
        return True
    if p.user_id in game.bazpors_mafia_recruit_ids:
        return True
    if getattr(p, "bazpors_converted_by_yakuza", False):
        return True
    if not p.role:
        return False
    from bot.game import is_mafia_team

    return is_mafia_team(p.role)


def _reads_negative_for_detective(game: Game, tgt: Player | None) -> bool:
    if tgt is None:
        return False
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.roles.mason_detective import mason_reads_negative_for_detective

        return mason_reads_negative_for_detective(game, tgt)
    return _boss_role.reads_negative_for_detective(tgt)


def evaluate_inquiry(game: Game, target_uid: int) -> DetectiveInquiryResult:
    """محاسبهٔ نتیجهٔ استعلام — فقط هنگام ثبت انتخاب کارآگاه."""
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.roles.mason_detective import evaluate_mason_detective_inquiry

        return evaluate_mason_detective_inquiry(game, target_uid)
    tgt = game.players.get(target_uid)
    if tgt is None:
        raise ValueError(f"detective inquiry target {target_uid} not in game")
    if scenario_has_shiad(game) and detective_night_state(game).blocked:
        return DetectiveInquiryResult(DetectiveInquiryKind.NEGATIVE_SHIAD, target_uid)
    if _reads_negative_for_detective(game, tgt):
        return DetectiveInquiryResult(DetectiveInquiryKind.NEGATIVE_BOSS, target_uid)
    if target_reads_as_mafia_for_detective(game, tgt):
        return DetectiveInquiryResult(DetectiveInquiryKind.POSITIVE, target_uid)
    return DetectiveInquiryResult(DetectiveInquiryKind.NEGATIVE_TOWN, target_uid)


def commit_pick(game: Game, target_uid: int) -> DetectiveInquiryResult:
    """ثبت استعلام شب روی ``target_uid`` و به‌روزرسانی state بازی."""
    result = evaluate_inquiry(game, target_uid)
    detective_night_state(game).set_committed(
        target_uid,
        positive=result.is_positive,
        last_answer=result.host_answer_fa(),
    )
    return result


def load_result(game: Game) -> DetectiveInquiryResult | None:
    """خواندن نتیجهٔ ثبت‌شده — بدون محاسبهٔ مجدد روی فکشن هدف."""
    state = detective_night_state(game)
    if state.no_inquiry:
        return None
    target_uid = state.target_uid
    if target_uid is None:
        return None
    if scenario_has_shiad(game) and state.blocked:
        return DetectiveInquiryResult(DetectiveInquiryKind.NEGATIVE_SHIAD, target_uid)
    tgt = game.players.get(target_uid)
    if _reads_negative_for_detective(game, tgt):
        return DetectiveInquiryResult(DetectiveInquiryKind.NEGATIVE_BOSS, target_uid)
    if state.ack_positive:
        return DetectiveInquiryResult(DetectiveInquiryKind.POSITIVE, target_uid)
    return DetectiveInquiryResult(DetectiveInquiryKind.NEGATIVE_TOWN, target_uid)


def load_label_from_snapshot(bz: dict) -> str | None:
    """برچسب «مثبت»/«منفی» از snapshot لاگ — برای timeline."""
    if bz.get("det_no_inquiry"):
        return None
    if bz.get("detective_check") is None:
        return None
    if bz.get("detective_blocked"):
        return "منفی"
    if bz.get("det_ack_positive"):
        return "مثبت"
    return "منفی"


def block_inquiry_by_shiad(game: Game) -> None:
    """شیاد کارآگاه را درست حدس زده — استعلام این شب باطل می‌شود."""
    if not scenario_has_shiad(game):
        return
    detective_night_state(game).block_by_shiad()


def void_pick(game: Game) -> None:
    detective_night_state(game).void_pick()


def mark_no_inquiry(game: Game) -> None:
    detective_night_state(game).mark_no_inquiry()


def commit_shiad_voided_inquiry_note(game: Game) -> None:
    """نیمه‌خودکار — پس از sdp_ok وقتی شیاد کارآگاه را شناسایی کرده."""
    if not scenario_has_shiad(game):
        return
    detective_night_state(game).commit_shiad_voided_note()


def committed_positive(game: Game) -> bool | None:
    result = load_result(game)
    if result is None:
        return None
    return result.is_positive


def result_label_fa(game: Game) -> str | None:
    result = load_result(game)
    if result is None:
        return None
    return result.label_fa()
