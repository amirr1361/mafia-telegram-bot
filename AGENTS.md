# AGENTS.md — Telegram Mafia Bot (production server: dns-vpn)

This is the permanent instruction file for all AI coding agents (OpenCode and
others). Every development task on this repository MUST follow this file.

- Server: SSH host `dns-vpn`
- Project path: `/root/mafia-telegram-bot`
- Branch: `main`
- Service: `mafia-bot.service` (systemd)
- Stable recovery baseline (GitHub commit): `4acc6598c6e90567cdf5b1f44c4f4c365cca3333`
- Stable recovery tag: `pre-opencode-migration-2026-10-19`
- Legacy rule kept intact: `.cursor/rules/bazpors-hunter-rules.mdc`

---

## 1. Project architecture

- Python 3 (server: 3.12) with **aiogram 3.x** and python-dotenv.
- Virtualenv: `/root/mafia-telegram-bot/.venv`.
- Entrypoint: `python -m bot.main` (i.e. `bot/main.py`).
- Game engine: `bot/game.py` (`GameManager`); state models in `bot/models.py`
  (`Game`, `Phase`, per-player and per-phase fields).
- In-memory rooms live in `bot/app_state.py` (`manager = GameManager()`).
- Scenario routing: `bot/room_mode.py` (single source of truth for mode checks).
- Roles: `bot/roles/` (registry dispatch via `bot/roles/registry.py`,
  per-role night state in `bot/roles/night_state.py`).
- Persistence: SQLite in `data/mafia_bot.sqlite3` via `bot/db.py` (tables:
  `game_sessions`, `narrator_ratings`, `rating_invites`, `session_medals`,
  `user_display_names`, `host_timer_settings`, `active_game_snapshots`).
  Game snapshots (persist/restore of live rooms) via `bot/game_snapshot.py`
  (`persist_game_snapshot`, `restore_games_into_manager`).
- Audit logging: `bot/game_audit_log.py` writes per-match JSONL files into
  `data/game_logs/`; use these for diagnosing stuck glue/phase problems.
- Night readiness / phase progression: `bot/no_host_night_ready.py` (parallel
  collection gate), `bot/mason_night_ready.py`, `bot/mason_night_reminder.py`,
  `bot/mason_force_finish_night.py`, narrator state machine in
  `bot/bazpors_narrator.py` (`bazpors_narrator_step`).
- Observer architecture: `bot/observer_delivery.py` plus the no_host observer
  mirror/two-step policy. Synthetic players: `bot/mason_synthetic_names.py`
  and lobby dev-fill buttons (`bot/room_mode.py::lobby_dev_fill_enabled`).

## 2. Deployment (systemd, NOT Docker)

- Unit: `/etc/systemd/system/mafia-bot.service`
  (`Type=simple`, `Restart=always`, `RestartSec=3`,
  `ExecStart=/root/mafia-telegram-bot/.venv/bin/python -m bot.main`).
- Verify state with: `systemctl is-active mafia-bot.service` and
  `journalctl -u mafia-bot.service -n <N> --no-pager`.
- Confirm exactly one instance runs before reporting completion (check the
  service's Main PID; do not run duplicate `python -m bot.main` manually).

## 3. Scenario isolation

Supported scenarios (never merge or cross-wire their logic):

| Scenario | Internal identifier | Host modes |
|---|---|---|
| Namayande | `namayande` | default/classic |
| Takavar | `takavar` | create UI in `bot/main.py` |
| Russian Mafia | `russian_mafia` | `host_helper` |
| Bazpors | `bazpors` | `semi_auto`, `no_host`, narrator `bazpors_salamat_test` |
| Mozakere | `mozakere` | `no_host` (parallel negotiation) |
| Mason | `masoon` | `no_host` |

- The Mason scenario identifier is the literal string `"masoon"` in
  `bot/room_mode.py` (`is_mason_scenario`). Never "fix" this spelling.
- Do not change unrelated scenarios while fixing one. Keep mode gates in
  `bot/room_mode.py` intact.
- Inspect the existing implementation of the affected scenario before editing.
- Reuse proven features from other scenarios where appropriate, without
  unintentionally changing their behavior.

## 4. Permanent Git policy

The GitHub commit `4acc6598c6e90567cdf5b1f44c4f4c365cca3333` (tag
`pre-opencode-migration-2026-10-19`) is the stable recovery baseline.

NEVER run, unless the user explicitly authorizes that specific operation:

- `git add`
- `git commit`
- `git push`
- `git tag`
- `git reset`
- `git checkout` / `git switch` (to change versions)
- `git clean`
- `git pull`
- `git merge`
- `git rebase`
- `git stash`

Read-only Git inspection (`git status`, `git diff`, `git log`, `git show`) is
allowed at any time. Do not automatically create checkpoints, branches,
commits, or tags. Preserve uncommitted development changes on the server.

## 5. Production development workflow

For every implementation request:

1. Connect to `dns-vpn` using SSH.
2. Inspect the actual server files and the relevant existing implementation
   (scenario module, `bot/room_mode.py`, narrator/engine paths, existing
   regression tests for that area).
3. Understand affected scenarios and dependencies.
4. Implement the requested changes directly on the server files.
5. Prefer minimal, focused changes; no opportunistic refactoring.
6. Do not modify unrelated gameplay, message texts, or keyboards.
7. Add or update appropriate regression tests under `tests/`.
8. Verify tests use isolated temporary storage (e.g. pytest `tmp_path`,
   temporary SQLite files). Tests must NEVER touch `data/mafia_bot.sqlite3`,
   `active_game_snapshots` production data, or production log paths on disk.
9. Run the appropriate targeted tests, and the full test suite where feasible;
   report results exactly as executed.
10. Report failures accurately; fix relevant regressions before continuing.
11. After successful implementation and safe verification, restart the
    service: `systemctl restart mafia-bot.service`. This standing restart is
    explicitly authorized by the user — no separate approval is needed, but
    it must happen only after tests pass on the changed code.
12. Confirm the service is active afterwards.
13. Inspect startup logs (`journalctl -u mafia-bot.service`) for exceptions.
14. Confirm only one bot instance is running (single Main PID in the unit).
15. Report the final PID and implementation results.
16. Stop and wait for the user's live Telegram testing.

**Never** delete, reset, recover, or manipulate existing game rooms, snapshot
rows, or log files unless explicitly requested. Diagnose stuck rooms through
`data/game_logs/` JSONL and snapshot state, then fix the **code**.

**Secrets:** never read, print, store, or modify `.env`, SSH keys, tokens, or
any credentials. Do not log them.

## 6. Telegram UI language policy

- ALL Telegram user-facing strings (messages, buttons, notifications,
  reports, role labels) must remain Persian. Never translate existing
  Persian UI strings unless explicitly requested.
- Agent responses, technical explanations, agent-written code comments,
  implementation reports, and planning documents are in English.

## 7. Observer and synthetic players

- Maintain compatibility with the existing Observer architecture
  (`bot/observer_delivery.py`, no_host observer mirror/two-step policy).
- Evaluate any player-facing feature for Observer support when relevant.
- Maintain synthetic-player / dev-fill behavior (`bot/mason_synthetic_names.py`,
  lobby dev-fill buttons) — they are the official testing mechanism.
- Never expose privileged role information to unauthorized players (role
  delivery is private; use existing private-delivery paths in
  `bot/player_role_pick_common.py` and role pick flows).

## 8. Testing notes

- Test files live in `tests/` (~190 files, plus harnesses:
  `mason_simulation_harness.py`, `no_host_flow_harness.py`,
  `no_host_game_loop.py`). Historical stuck rooms have pinned regression
  tests (e.g. `test_mason_room08_night4_stuck.py`,
  `test_mason_room99_stuck.py`, `test_bazpors_room80_stuck.py`,
  `test_mason_night_readiness_stuck.py`) — keep them green.
- The whole suite is plain `unittest` (pytest is NOT installed and is NOT
  required — do not install it without explicit approval).
- Targeted tests: `.venv/bin/python -m unittest tests.<module_name>`.
- Full suite (ALWAYS with isolated storage first):
  `export DATABASE_PATH=$(mktemp -d)/t.sqlite3`,
  `export GAME_AUDIT_LOG_DIR=$(mktemp -d)`,
  `export GAME_AUDIT_LOG_ENABLED=0`, then
  `.venv/bin/python -m unittest discover -s tests`.
- Known baseline: the full suite has a set of pre-existing
  failures/errors (58 failing test IDs as of 2026-10-19) unrelated to
  current work; when triaging new failures, diff your failing test IDs
  against a sandbox run of the untouched baseline before blaming a change.

### Bazpors role-panel button styling (cosmetic contract)

- All no_host Bazpors role panels use native button styles: picks blue
  (`style="primary"`), tentative selection red (`style="danger"`),
  exactly ONE green confirm (`style="success"`, text «✅ تأیید انتخاب»)
  visible from the INITIAL rendering of every selection panel; legacy
  confirm screens remain in code but are unused by the Bazpors flow.
  Back/ok/nav stay blue. Gated only on `game.scenario_name == "bazpors"`.
- Commit semantics: committing happens ONLY through the green confirm act
  (`ndc`, `skc`, `dkc`, `sgc`, `hnc`, `nmc`, `msc`, `n1c`, `n2c`, `ysc`,
  `ycc`, `niisk`, `ihck`); tentative picks are reversible (re-press
  deselects) and finalize nothing. Interrogator panel: up to TWO distinct
  nominees or the «⭕ کسی را انتخاب نکردم» opt-out (also confirmed via
  `niisk`).
- Room-97 follow-ups (2026-11-05, Bazpors-only, Room 97 regression set):
  (a) `no_exit` / `d1d0` («خروجی نداشتیم. شب کن») on the day-1 defence
  OUTCOME panel is now a tentative selectable option too — red restyle on
  the SAME panel (`no_host_day1_pending_no_elim`), mutually exclusive with
  the elimination pending pick; the night starts only after the green
  `d1ey`/`elim_yes` confirm. Every other scenario keeps the direct
  action.
  (b) Hunter night-1 `hns` («⭕ به کسی وصل نمی‌شوم») is a tentative pick
  as well (red via `no_host_hunter_pending_none`); it finalizes only via
  green `hnc`. Other scenarios keep the instant finalize.
  (c) Interrog-day session-result panel: selection clicks edit the SAME
  host panel in place (`_bazpors_interrog_vote_panel_edit_in_place` gate
  in `_deliver_host_narrator_panel`, incl. `not force_new_message`);
  after `ih_vok` the panel is closed and a short non-interactive ack
  (`build_no_host_interrog_result_ack_text`) is sent; `ih_vok` is
  idempotent via `no_host_interrog_day_vote_committed` (duplicate
  callback cannot re-apply the result).
  (d) Table-inquiry `tinq_ok` is idempotent: `apply_no_host_table_inquiry_confirm`
  captures the pending choice synchronously before the first await, so a
  duplicate delivery cannot re-run the resolution / day start. New panels
  are never delivered while `bazpors_narrator_step == NO_HOST_TABLE_INQUIRY` 
  (`send_no_host_day_vote_prompt` guard).
  (e) Role-pick «انتخابی ندارم» rows honor `none_selected` — red while it
  is the tentative pick (doctor/sniper pass `*_pending_none`).
- Room-60 follow-ups (2026-11-05, Bazpors-only, Room 60 regression set):
  (a) Interrogator NO-action / already-used night commits finalize the
  SAME panel via `finalize_no_host_role_pick_message` (kb=None, closed
  for player + observer) — never re-opened as OK panels.
  (b) Assistant force-finish reminder («🌙 قابلیت اتمام شب») is ONE
  message for the whole lifecycle: the «اتمام شب» press EDITS the same
  reminder message into «⚠️ تأیید اتمام شب»; cancel restores the counted
  reminder text with a recalculated counter; success deletes the message.
  `refresh_night_helper_reminder` never overwrites an open confirmation
  (flag `night_helper_reminder_force_confirm_open`) but cleanup branches
  still run.
  (c) Interrog-day decision panel: `ihco`/`ihdi` are REPLACEABLE pending
  toggles (red while pending), commit only via green `ihck`;
  `no_host_interrog_day_decision` is set only on `ihck`.
  (d) Interrog-day VOTE panel: `ih_vtie`/`ih_velim` keep the pending
  result in phase `vote` (red); commit only via green `ih_vok` (also
  valid in legacy `vote_confirm`).
  (e) Day-1 defence OUTCOME panel: `d1el` sets a replaceable pending
  (`no_host_day1_pending_elim_uid`, red on the SAME panel); commit only
  via the green confirm which reuses the existing `d1ey`/`elim_yes`
  commit path. «خروجی نداشتیم. شب کن» is ALSO confirm-gated since the
  Room-97 set (see Room-97 (a) above).
  All of the above are gated on `game.scenario_name == "bazpors"`
  (Russian Mafia shares the defence panels and keeps old behaviour).
  (f) Doctor NATO-blocked panel: after the `dko` ack the panel closes for
  player + observer on the same message; `apply_no_host_doctor_nato_blocked_panel`
  syncs the closed state when the blocked panel is already acked.
- Central helpers: `build_target_button_rows` (optional `selected_uids`),
  `build_pick_keyboard`, `build_confirm_cancel_keyboard`,
  `build_single_action_keyboard` in `bot/no_host_role_pick_common.py`;
  `no_host_role_ack_keyboard` / `no_host_simple_ok_keyboard` in
  `bot/no_host_night_common.py`; plus `apply_bazpors_panel_styles(game, kb,
  pick_acts=..., selected_uids=..., ok_acts=..., selected_acts=...)` for
  hand-rolled keyboards (interrogator night, mafia night1/shot/nato/yaku,
  interrog-day acks) and `with_inline_confirm_row(...)` for the inline
  green confirm.
- Never change labels, callback data, layout, eligibility or flow of these
  panels; only the `style` attribute may differ from unstyled output.
- Contract tests: `tests/test_bazpors_role_panel_styles.py`,
  `tests/test_bazpors_hunter_panel_styles.py`,
  `tests/test_bazpors_confirm_inline.py` and
  `tests/test_bazpors_room60_panels.py`.

## 9. Final response format (mandatory)

After each implementation, report:

1. Summary of implemented behavior.
2. Relevant implementation details.
3. Files created or modified.
4. Targeted test results.
5. Regression and full-suite results.
6. Confirmation that production data was not modified by tests.
7. `git status --short` output.
8. Service restart result.
9. New PID and startup-log status.
10. Confirmation that no Git commit, tag, or push was performed.
11. Anything the user should verify in a fresh Telegram game room.

Never claim a test passed unless it actually ran and exited 0.
