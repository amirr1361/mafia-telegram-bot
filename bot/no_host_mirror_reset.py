"""پاک‌سازی آینهٔ پنل‌های نقش هنگام ورود به شب جدید (no_host)."""

from __future__ import annotations

from bot.models import Game


def reset_no_host_night_mirror_prompts(game: Game) -> None:
    """پنل‌های آینهٔ شب قبل را پاک کن تا ارسال شب جدید همیشه پیام تازه بسازد."""
    if game.bazpors_host_mode != "no_host":
        return
    game.mirror_prompt_messages.clear()
    game.mirror_action_claims.clear()
