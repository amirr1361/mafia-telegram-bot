"""همگام‌سازی وضعیت بازی برای گردانندگی خودکار مستقل پس از no_host."""

from __future__ import annotations

from bot.models import Game
from bot.roles.night_state import doctor_night_state, yaku_night_state


def sync_bazpors_semi_auto_after_handoff(game: Game) -> None:
    """پرچم‌ها و شمارنده‌های مشترک را از تاریخچهٔ بازی no_host بارگذاری کن."""
    doc_state = doctor_night_state(game)
    if doc_state.pending_self_save:
        doc_state.commit_pending_self_save()

    doc_state.baseline_self_saves = doc_state.self_save_count

    if (
        game.bazpors_sniper_night_target_uid is not None
        and not game.bazpors_sniper_shot_used
        and game.bazpors_narrator_night_count > 0
    ):
        game.bazpors_sniper_shot_used = True

    if game.no_host_interrog_day_decision is not None:
        game.bazpors_interrog_once_done = True

    game.bazpors_nato_action_registered = False
    yaku_night_state(game).clear_handoff_night_pick()
    game.bazpors_hunter_linked_this_night = False
