"""پاک‌سازی آینهٔ پنل‌های نقش هنگام ورود به شب جدید (no_host)."""

from __future__ import annotations

from bot.models import Game


def reset_no_host_night_mirror_prompts(game: Game) -> None:
    """پنل‌های آینهٔ شب قبل را پاک کن تا ارسال شب جدید همیشه پیام تازه بسازد."""
    if game.nmnd_host_mode != "no_host":
        return
    # Lifetime keys (e.g. the one-time Rebel activation notice) survive
    # the per-night mirror reset; per-night panels are wiped as before.
    from bot.nam10.nmnd_night_panel_purge import persistent_mirror_keys

    persistent = persistent_mirror_keys(game)
    for key in list(game.mirror_prompt_messages):
        if key not in persistent:
            game.mirror_prompt_messages.pop(key, None)
    for key in list(game.mirror_action_claims):
        if key not in persistent:
            game.mirror_action_claims.pop(key, None)
