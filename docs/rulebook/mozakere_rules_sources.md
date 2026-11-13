# Mozakere Rules — Technical Verification Appendix (English)

Purpose: map every substantial gameplay rule of the **Mozakere (مذاکره)** scenario
to the authoritative implementation in `/root/mafia-telegram-bot` (branch `main`),
with file/function/line references, test evidence, and explicitly flagged
ambiguities. Companion documents:

- `mozakere_rules_complete.md` — Persian full rulebook (player-facing).
- `mozakere_rules_reference.md` — Persian quick-reference tables.

All line numbers refer to the working tree as of November 2026 (pre-backup state).

---

## 1. Legend

- **[RULE]** — confirmed gameplay rule (implementation +, where available, test evidence).
- **[BOT]** — bot operating detail (not a gameplay rule; may change without rule changes).
- **[AMBIG]** — ambiguity / known inconsistency requiring clarification.

---

## 2. Scenario identity and routing

| Fact | Reference |
|---|---|
| Scenario string `"mozakere"`; single source of scenario routing | `bot/room_mode.py:57-59` (`is_mozakere_scenario`) |
| Host mode for player rooms: `no_host` | `bot/room_mode.py` (`is_mozakere_no_host_room`, `is_no_host_player_room`) |
| Yakuza/Boss-automation disabled in Mozakere (`yaku_boss_uid` → None) | `bot/roles/mafia_boss.py:195-200` |
| Chaos (کی‌آس) phase NOT supported: `bazpors_chaos_phase_enabled` requires `scenario_name == "bazpors"` | `bot/bazpors_narrator.py:146-153` |

## 3. Role composition by player count

**[RULE]** Composition function: `mozakere_roles_for_count` — `bot/game.py:360-436`.

| Players | Mafia roles | Town roles | Totals |
|---|---|---|---|
| 10 | MAFIA_BOSS 1, MAFIA_NEGOTIATOR 1, MAFIA_SIMPLE 1 | DOCTOR 1, DETECTIVE 1, SNIPER 1, JOURNALIST 1, ARMORED 1, CITIZEN 2 | 3 / 7 |
| 11 | same as 10 | same + CITIZEN 3 | 3 / 8 |
| 12 | MAFIA_BOSS 1, MAFIA_NEGOTIATOR 1, MAFIA_SIMPLE 1, MAFIA_SIMPLE_2 1 | DOCTOR/DETECTIVE/SNIPER/JOURNALIST/ARMORED 1 each, CITIZEN 3 | 4 / 8 |
| 13 | same as 12 | CITIZEN 4 | 4 / 9 |
| 15 | same as 12 | CITIZEN 6 | 4 / 11 |

- Role enum values: `bot/models.py` (`Role`).
- Persian role labels: `bot/mozakere_role_descriptions.py` (`MOZAKERE_ROLE_DESCRIPTIONS_FA` — full role-broadcast texts for all roles).

## 4. Negotiation (core mechanic)

All in `bot/roles/mozakere_negotiator.py` unless noted.

| Rule | Status | Reference |
|---|---|---|
| Valid targets = CITIZEN or ARMORED | **[RULE]** | `VALID_NEGOTIATION_TARGET_ROLES:13-14` |
| ARMORED only valid while armor active | **[RULE]** | `is_valid_mozakere_negotiation_target:128-141` → `bot/roles/mozakere_armored.py` (`can_mozakere_negotiate_with_armored`) |
| Threshold: 10/11 → 1 eliminated original mafia; 12/13/15 → 2 (default 2) | **[RULE]** | `required_eliminated_mafia_count:58-66` |
| Only ORIGINAL mafia count toward threshold; recruits explicitly excluded (`mafia_ids - mozakere_mafia_recruit_ids`, role scan skips recruits, uses `mozakere_original_role`) | **[RULE]** | `original_mozakere_mafia_uids:69-83`, `eliminated_mafia_teammate_count:86-97`, `mafia_elimination_threshold_met:100-102` |
| Negotiator must be alive and unused | **[RULE]** | `can_mozakere_negotiate:112-119`, `negotiation_allowed:121-126` |
| Boss elimination has no special effect beyond counting as 1 original mafia death | **[RULE]** | follows from §4 threshold logic |
| Panel pool = ALL alive non-mafia players (not only valid targets) | **[RULE]** | `negotiation_panel_target_pool:144-157` |
| Validation pool = only valid targets (used for commit) | **[RULE]** | `negotiation_target_pool:160-168` |
| Recruit: original role saved to `mozakere_original_role`, `mozakere_converted_by_negotiation = True`, role → MAFIA_SIMPLE, added to `mozakere_mafia_recruit_ids` + `mafia_ids` | **[RULE]** | `apply_mozakere_negotiation_recruit:171-179` |
| Recruit loses original ability (role replaced) | **[RULE]** | §4 recruit conversion; ARMORED loses armor since role no longer ARMORED |
| Once per game — `used` flag set at commit time, BEFORE target validation | **[RULE]** (confirmed behavior; see §12) | `mark_mozakere_negotiation_used:182-185`, `commit_mozakere_negotiation:190-215` |
| Commit ALWAYS closes the mafia shot that night (docstring) — success, failure, and invalid target alike | **[RULE]** | `commit_mozakere_negotiation:190-215` docstring |
| Failed commit = `INVALID_TARGET`, `state.night_success = False`; negotiation consumed | **[RULE]** | `commit_mozakere_negotiation:201-209` |
| `NOT_ALLOWED` does NOT consume (mark happens after the guard) | **[RULE]** | `commit_mozakere_negotiation:196-200` |
| Recruit reads as mafia: detective positive, `_visually_mafia` true, `bazpors_counts_as_mafia_faction` true | **[RULE]** | `mozakere_recruit_reads_as_mafia:218-219`; `bot/roles/detective.py:88-103`; `bot/bazpors_narrator.py:467-481`; `bot/game.py:281-286` |
| Negotiation used → journalist activates (any commit, success or fail) | **[RULE]** | `bot/roles/mozakere_journalist.py` (`mozakere_journalist_active`); `bot/no_host_journalist_night.py:206-260` (`activate_journalist_after_mozakere_negotiation`) |
| Mafia night action gate: shot done OR negotiation committed | **[BOT]** | `bot/no_host_mozakere_mafia_gate.py:8-27` (`mozakere_mafia_night_action_finalized`) |
| Night-state fields: `mozakere_negotiation_night_state` (`tonight`, `used`, `target_uid`, `night_success`) | **[BOT]** | `bot/roles/night_state.py` |
| Reset after commit: doctor panel skipped/cleared, detective inquiry voided, sniper pick reset; panels suspended at negotiation initiation | **[BOT]** | `bot/no_host_mozakere_negotiation_reset.py` (`MOZAKERE_DOCTOR_NEGOTIATION_SKIP_HTML`, cleared variants); `bot/bazpors_detective_inquiry.py` (`void_detective_inquiry_pick`) |
| Dispatch: negp toggle (deselect red), negc commit, negb back | **[BOT]** | `bot/no_host_mozakere_negotiation.py` |
| Notifications: success text to recruit, existing-mafia text to mafia team (on commit) | **[BOT]** | `bot/no_host_mozakere_negotiation.py:140-180` |
| Force-finish: pending unconfirmed negotiation → "negotiation not done tonight, shot closed" | **[BOT]** | `bot/mozakere_force_finish_night.py:174-230` (`_normalize_pending_mozakere_mafia_actions`) |
| Uncommitted negotiation does NOT consume the once-per-game use | **[RULE]** | force-finish path only sets dispositions; `used` set only in `commit_mozakere_negotiation` |

### Tests (evidence)

- `tests/test_mozakere_negotiator.py` — threshold/target/commit semantics.
- `tests/test_mozakere_mafia_shot_negotiation.py` — shot closed when negotiation chosen.
- `tests/test_mozakere_negotiation_notifications.py` — recruit + existing-mafia messages.
- `tests/test_mozakere_negotiation_role_reset.py` — doctor/detective/sniper resets.
- `tests/test_mozakere_negotiation_suspension.py` — panel suspension at initiation.
- `tests/test_mozakere_negotiation_panel_lifecycle.py` — panel open/close lifecycle.
- `tests/test_mozakere_night2_negotiate_resolve.py` — negotiate path resolve on night 2.
- `tests/test_threshold_12p_requires_two_dead_mafia` (in `test_mozakere_negotiator.py`) — pins the 12p threshold=2 as deliberate.

## 5. Mafia night flow

| Rule | Status | Reference |
|---|---|---|
| Mafia decision menu (shot / negotiate) every night in no_host | **[BOT]** | `bot/no_host_mafia_night1.py` (`MAFIA_ACTION_SHOT`, `MAFIA_ACTION_NEGOTIATE`) |
| Chooser = alive MAFIA_BOSS, else first alive mafia by seat | **[RULE]** | `bot/roles/mafia_boss.py:73-79,103-106` (`resolve_mafia_shot_chooser` usage in `bot/no_host_mafia_chooser.py`) |
| Shot finalize: `mafia.finalize_no_host_shot()`, target applied, mirrored panel finalized | **[BOT]** | `bot/no_host_mafia_shot.py:279-340` (`_finalize_mafia_shot`) |
| Mafia team notified of shot result | **[BOT]** | `notify_mafia_team_shot_result` (same file) |
| Direct-shot panel to Boss when threshold not met at 12p (Room 57 observation) | **[BOT]** | pinned by `test_boss_gets_direct_shot_when_threshold_not_met` |

## 6. Doctor

| Rule | Status | Reference |
|---|---|---|
| Save capacity by ALIVE count at panel delivery: ≤7→1, 8–11→2, 12–15→3, 16+→4 | **[RULE]** | `bot/roles/doctor_alive_save_capacity.py:14-20`; `bot/roles/doctor.py:22-27`; `bot/roles/mozakere_doctor.py` (`mozakere_doctor_save_capacity`) |
| Max 2 self-saves per game (Mozakere limit) | **[RULE]** | `bot/roles/doctor.py:13` (`MAX_SELF_SAVES=2` generic; Mozakere limit `MOZAKERE_MAX_SELF_SAVES` in `bot/roles/mozakere_doctor.py`), `self_save_limit_reached:178-180` |
| Self-save counted at end of night (resolve), pending during night | **[BOT]** | `can_register_self_save_this_night:183-184`, commit path in resolve |
| Doctor save blocks mafia shot | **[RULE]** | resolution order §8; night report doctor section |
| Tests: `tests/test_mozakere_doctor.py`, `test_mozakere_doctor_night_ui.py` | — | — |

## 7. Detective

| Rule | Status | Reference |
|---|---|---|
| One inquiry/night, target pool alive players | **[RULE]** | `bot/roles/detective.py` (core night logic) |
| Boss always reads NEGATIVE | **[RULE]** | `bot/roles/mafia_boss.py:191-192` (`reads_negative_for_detective`) |
| Mozakere recruit reads POSITIVE | **[RULE]** | `bot/roles/detective.py:88-103` (`target_reads_as_mafia_for_detective` — mozakere branch before generic mafia check) |
| `bazpors_sniper_eliminated_uids` reads False (bazpors-only vestige) | **[BOT]** | same function; list unused in Mozakere |
| Inquiry voided on negotiation commit | **[BOT]** | `bot/bazpors_detective_inquiry.py` (`void_detective_inquiry_pick`), `no_host_mozakere_negotiation_reset.py` |
| Tests: `tests/test_mozakere_detective_citizen.py` | — | — |

## 8. Night resolution order and sniper

`bot/bazpors_narrator.py` `_apply_night_resolution` (≈2110-2160):

1. yaku/NATO/shiad steps — n/a in Mozakere.
2. Mafia shot: doctor saves → ARMORED armor → ruintan (n/a in Mozakere).
3. Sniper resolution (`bot/roles/sniper.py:164-330` `apply_night_resolution`).

**Sniper [RULE]s** (`bot/roles/sniper.py:164-330`, `bot/roles/mozakere_sniper.py`):

- Shot limit: 10/11 → 1 bullet; 12/13/15 → 2 bullets (`mozakere_sniper_shot_limit:15-20`).
- In Mozakere the generic `bullet_used`/`mark_bullet_used` path is skipped; consumption tracked by `mozakere_sniper_shots_used` (+ `_at_night_start`) (`sniper.py:167-172`).
- Target pool: alive players excluding sniper self (`sniper.py:103-109`).
- Alive non-boss mafia-faction target (incl. recruits): eliminated, unless doctor-saved → nobody dies and sniper survives (`sniper.py:227-247`; doctor-save guard `bot/roles/doctor.py:168-175` `mafia_kill_blocked_by_doctor_save` — explicitly prevents sniper kill on non-boss mafia, sniper stays).
- Alive BOSS target: nobody exits (boss immunity) (`sniper.py:214-222`; `sniper_boss_immune` `bot/roles/mafia_boss.py:187-188`).
- Alive TOWN target: SNIPER dies (miss) — regardless of any doctor save (`sniper.py:249-252` final fallthrough; doctor save only guards the mafia branch).
- Dead target + boss: nobody exits, announce "هدف از قبل مرده بود" (`sniper.py:201-210`).
- Dead target + mafia: nobody exits (`sniper.py:212-217`).
- Dead target + town: SNIPER dies ("هدف از قبل مرده بود و خود تک‌تیرانداز از بازی خارج شد") (`sniper.py:218-233`).
- Tests: `tests/test_mozakere_sniper.py`.

## 9. Armored

| Rule | Status | Reference |
|---|---|---|
| Armor active = alive ARMORED with `mozakere_armored_armor_used` False | **[RULE]** | `bot/roles/mozakere_armored.py` (`mozakere_armored_armor_active`) |
| Blocks first mafia night shot while active (consumed automatically) | **[RULE]** | resolution step 2 (`_apply_night_resolution`), `consume_mozakere_armored_armor` |
| Blocks first day-vote elimination: survives, armor consumed | **[RULE]** | `bot/bazpors_narrator.py:1367-1370` (`_eliminate_player` `elim_source == "day_vote"` → `try_survive_mozakere_day_vote_elimination`) |
| After armor consumed: no night-shot protection, NOT negotiable | **[RULE]** | `can_mozakere_negotiate_with_armored` (armor-active check) |
| No role panel; passive | **[RULE]** | no pick functions in `mozakere_armored.py` |
| Tests: `tests/test_mozakere_armored.py` | — | — |

## 10. Journalist

| Rule | Status | Reference |
|---|---|---|
| Inactive until any negotiation commit; then permanently active | **[RULE]** | `bot/roles/mozakere_journalist.py` (`mozakere_journalist_active` keyed on `mozakere_negotiation_used`) |
| Check result: positive only if target joined via negotiation (`mozakere_mafia_recruit_ids`); never positive for original mafia | **[RULE]** | same module |
| Pool: all alive except self | **[RULE]** | pick pool in `bot/no_host_journalist_night.py` |
| Activation panel replaces idle/OK panel in place; resets idle/pick confirm flags | **[BOT]** | `bot/no_host_journalist_night.py:206-260` |
| Night report line only when negotiation used | **[BOT]** | `bot/bazpors_narrator.py:2309-2326` (`_night_report_mozakere_journalist_line`) |
| Tests: `tests/test_mozakere_journalist.py` | — | — |

## 11. Night readiness, force-finish, night-end sequence

| Rule | Status | Reference |
|---|---|---|
| Parallel night collect; readiness per actor group | **[BOT]** | `bot/no_host_night_ready.py:40-260` (`_citizens_ready`, `_ruintan_ready` (n/a), `_mafia_night1_parallel_ready`, `_detective_ready`, `_sniper_ready`, `_journalist_ready`, `_doctor_ready`, `pending_no_host_night_actor_labels`, `maybe_finish_no_host_parallel_night`, `finish_no_host_parallel_night_collect`) |
| Pending labels (Persian): «شهروندان ساده», «تیم مافیا», «کارآگاه», «پزشک», «اسنایپر», «خبرنگار» | **[BOT]** | `pending_no_host_night_actor_labels` |
| Force-finish normalization defaults: unconfirmed mafia menu → no shot/no negotiation; pending negotiation → negotiation not done tonight + shot closed; doctor → no save; detective/sniper/journalist → no action; citizens auto-confirmed; ammo/armor counters untouched; mirror panels locked with `kb=None` | **[BOT]** | `bot/mozakere_force_finish_night.py:174-420` (`normalize_pending_mozakere_night_actions`, `_force_finish_mozakere_night_locked`, `MOZAKERE_FORCE_FINISH_*` texts) |
| Force-finish flags: `mozakere_night_force_finished`, `mozakere_night_force_finished_night` | **[BOT]** | reset at `bot/bazpors_narrator.py:1998-1999` |
| Night-end: collect → discipline ask (substep `NS_DISCIPLINE_ASK`, acts `disc_yes`/`disc_no`) → `NS_RESOLVE` (`apply_resolve` → `_finish_resolve_to_extra`) → `ASK_NIGHT_EXTRA` (`nx_yes`/`nx_no`/`nx_pick`) → next day | **[BOT]** | `bot/bazpors_narrator.py:120` (constants), `4336-4420` (panel), `5326-5480` (acts), `2964-2983` (`_finish_resolve_to_extra`), `go_day_after_night_extra` (≈4535) |
| Night report section order: hunter → mafia (shot + negotiation line) → shiad → detective → doctor → interrog → journalist line → sniper | **[BOT]** | `bot/bazpors_narrator.py:2222-2627`, `_compose_full_night_report:2628`; negotiation line `2283-2307` |
| Tests: `tests/test_mozakere_force_finish.py`, `test_mozakere_force_finish_night_scoping.py`, `test_mozakere_night_ui.py`, `test_mozakere_night_start_helper_suppressed.py`, `test_mozakere_det_sniper_defer.py` | — | — |

## 12. Day flow

| Rule | Status | Reference |
|---|---|---|
| Day-1 defence flow (also reused day 2+ with day-indexed mirrors): `d1dt` toggle pick → `d1dc` confirm → outcome panel → `d1d0` (no-exit, straight to night) or `d1d1` (has exit) → `d1el` pick eliminated → `d1ey` confirm eliminate → armor day-save check → broadcast → win-check → night entry | **[BOT]** (flow) / **[RULE]** (armor day save) | `bot/main.py:3482` (`_dispatch_no_host_day1_defense_act`), defence phase handlers `bot/main.py:2841-3466` (`_no_host_day1_defense_toggle`, `_confirm`, `_no_votes`, `_none_confirm_*`, `_outcome_no_exit_*`, `_outcome_has_exit`, `_pick_elim`, `_confirm_elim_yes`, `_confirm_elim_no`); panel setup `bot/bazpors_narrator.py:6297-6359` (`begin_no_host_day1_defense_pick`, `no_host_day1_defense_no_votes_enter_night`, `no_host_day1_after_elim_enter_night`, `no_host_day1_no_exit_enter_night`); day 2+ mirrors `bot/no_host_day_vote.py`; day-vote prompt/choice `bot/no_host_day_vote.py:99-192` |
| Callback routing for no-host day1 defence | **[BOT]** | `bot/handlers/no_host_player.py:315-420,897-937` (`cb_no_host_day1_defense`) |
| Day vote elimination consumes Armored armor | **[RULE]** | `bot/bazpors_narrator.py:1367-1370` |
| Bazpors-only two-step branches (discipline confirm chains etc.) do not apply to Mozakere | **[BOT]** | same dispatch function, mozakere skips those branches |
| Mid-game elimination report invite (Mozakere-only) with immutable cutoff | **[BOT]** | `bot/mozakere_elim_report.py` (router `mzrep`, `MOZAKERE_ELIM_REPORT_INVITE_HTML`) |
| Intro night: assistant confirms start (`NoHostIntroNightStart` act `go`/`ok`/`back`); mafia team DM lists alive mafia (boss first, then seat order); civilians get sleep notice; then night 1 | **[BOT]** | `bot/main.py:1691-1830` (`build_no_host_intro_night_*`, `intro_night_start_keyboard_for`, `_no_host_alive_mafia_for_intro`, `build_no_host_intro_night_mafia_dm_html`, `deliver_no_host_intro_night_started_messages`), `send_no_host_intro_night_start_prompt:1819` |
| Tests: `tests/test_mozakere_intro_night.py`, `test_mozakere_lobby_flow.py`, `test_mozakere_create_ui.py`, `test_mozakere_role_deal.py`, `test_mozakere_player_role_pick.py`, `test_mozakere_elim_report.py`, `test_mozakere_game_end_report.py` | — | — |

## 13. Victory conditions

`bot/game.py:1967-2009` `check_winner` (GameManager method):

- **Town win:** alive mafia count == 0 → town wins.
- **Mafia win:** alive mafia count >= alive citizen count → mafia wins (covers final 1v1 → mafia).
- **Recruits count as mafia:** `bazpors_counts_as_mafia_faction` — `bot/game.py:281-286` (Mozakere branch: `user_id in mozakere_mafia_recruit_ids` → True, else `is_mafia_team(role)`; `is_mafia_team` includes MAFIA_SIMPLE/2/NEGOTIATOR/BOSS — `bot/game.py:254-276`).
- Visual mafia identity (dead-reports, table checks): `_visually_mafia` — `bot/bazpors_narrator.py:467-481` (Mozakere recruit branches at 468-471).
- Chaos win path (`win_via_chaos`, `_ki_as_chaos_win_keyboard` — `bot/bazpors_narrator.py:608-648` etc.) unreachable in Mozakere because `bazpors_chaos_phase_enabled` requires scenario `"bazpors"` (`bot/bazpors_narrator.py:146-153`).
- Tests: `tests/test_mozakere_game_end_report.py`, `test_mozakere_mafia_boss.py`.

## 14. Player-count-specific conditions (summary)

| Condition | 10/11 | 12/13/15 | Reference |
|---|---|---|---|
| Mafia team size (original) | 3 | 4 | `bot/game.py:360-436` |
| Negotiation threshold (dead original mafia) | 1 | 2 | `bot/roles/mozakere_negotiator.py:58-66` |
| Sniper total bullets | 1 | 2 | `bot/roles/mozakere_sniper.py:15-20` |
| Doctor save capacity | dynamic by alive count (≤7→1, 8–11→2, 12–15→3) | same | `bot/roles/doctor_alive_save_capacity.py:14-20` |
| Citizens | 2 / 3 | 3 / 4 / 6 | `bot/game.py:360-436` |

## 15. Known ambiguities and clarification questions

1. **[AMBIG] Negotiation consumed on invalid target.** `commit_mozakere_negotiation` calls `mark_mozakere_negotiation_used` BEFORE validating the target, so choosing an invalid target (e.g., Doctor) burns the once-per-game use AND closes that night's shot. The docstring ("همیشه شلیک همان شب را می‌بندد") confirms shot-closing is deliberate, but whether burning the use on failure is intended design or a bug is not stated anywhere. *Question for the rulebook author: is failed-negotiation-consumes-intended?* Currently documented in the Persian rulebook as a rule (per implementation).
2. **[AMBIG] 12/13/15p threshold = 2 dead original mafia.** Pinned deliberately by `test_threshold_12p_requires_two_dead_mafia`, but players often expect 1 (as in 10/11p). Documented as intended; worth an explicit designer confirmation.
3. **[AMBIG] Sniper vs doctor-saved TOWN target.** Doctor save only guards the mafia branch (`doctor.py:168-175` docstring targets mafia). A doctor-saved town target hit by the sniper still causes the sniper's death (final fallthrough at `sniper.py:249-252` ignores saves). This looks intentional (miss = miss) but is an unusual interaction worth flagging.
4. **[AMBIG] Sniper shooting a DEAD TOWN player kills the sniper** (`sniper.py:218-233`), while shooting a dead mafia/boss kills nobody. Asymmetric edge rule; implemented as above; no test asserts the dead-town case explicitly (verify against `test_mozakere_sniper.py` coverage).
5. **[AMBIG] Direct-shot panel path logs no audit event.** Observed in Room 57 audit: when threshold not met at 12p, the Boss receives a direct shot panel (no shot/negotiate menu) and this path emits no `log_no_host_day1_defense`-style audit record. Cosmetic/observability gap, not a rule problem.
6. **[AMBIG] Bullet consumption for no-op sniper shots.** In Mozakere the `mark_bullet_used` generic path is skipped; consumption is via `mozakere_sniper_shots_used` at pick-confirm time. Whether a shot at a dead/boss target consumes a bullet depends on when the counter increments (at confirm). Rulebook documents "bullet consumed"; verify counter timing if precision matters.
7. **[AMBIG] Mafia shot pool exact membership.** Shot target pool assumed "alive non-mafia-faction players" (recruits excluded from own-team shooting). Matches `bazpors_counts_as_mafia_faction` usage and `_visually_mafia`, but the exact pool builder for the Mozakere shot panel was not line-verified in this pass.
8. **[AMBIG] Recruit's voting/day behaviour.** Recruit keeps seat and votes normally; no day-ability vestige. No rule contradicts this, but no test explicitly covers a recruit being day-voted (armor is irrelevant post-conversion since role changed).
9. **[AMBIG] Interrogation/`bazpors_interrog_*` fields** exist in shared narrator state but are inert in Mozakere (`nx_no` guards reference them; Mozakere never sets `bazpors_interrog_ready_for_day`). Treat as dead state for this scenario.
10. **Missing/undocumented rule discovered:** journalist's activation panel replaces its already-confirmed idle panel *in place* even after the journalist pressed OK — i.e., the journalist can be forced into a check the same night negotiation committed, even if they had "finished" their turn. Documented in rulebook §5.9/§7.7; confirm this is intended UX.

## 16. Suggested questions for the rulebook author

1. Should a failed negotiation really consume the once-per-game use? (public-facing fairness)
2. Confirm the 12/13/15p threshold of 2 is the desired public rule (players compare with 10/11p = 1).
3. Should the sniper die when shooting an already-dead town player? (current: yes)
4. Should the doctor's save protect a town target from the sniper at all? (current: no effect either way)
5. Preferred public wording for the journalist: "detects negotiated players only" — confirm it should never read original mafia.
6. Should the intro night remain completely action-free (current) or gain any acknowledgement step?

## 17. Source-file inventory used for this appendix

- `bot/game.py` — composition, victory, faction helpers
- `bot/room_mode.py` — scenario identity
- `bot/models.py` — Role enum, per-player Mozakere fields (`mozakere_original_role`, `mozakere_converted_by_negotiation`, `mozakere_armored_armor_used`)
- `bot/roles/mozakere_negotiator.py`, `mozakere_armored.py`, `mozakere_doctor.py`, `mozakere_journalist.py`, `mozakere_sniper.py`
- `bot/roles/doctor.py`, `doctor_alive_save_capacity.py`, `detective.py`, `sniper.py`, `mafia_boss.py`, `simple_mafia.py`, `night_state.py`, `registry.py`
- `bot/bazpors_narrator.py` — resolution, reports, day flow, night substeps, `_visually_mafia`
- `bot/no_host_mafia_night1.py`, `no_host_mafia_shot.py`, `no_host_mafia_chooser.py`, `no_host_mozakere_mafia_gate.py`
- `bot/no_host_mozakere_negotiation.py`, `no_host_mozakere_negotiation_reset.py`
- `bot/no_host_journalist_night.py`, `no_host_night_ready.py`, `no_host_day_vote.py`, `no_host_phase.py`
- `bot/mozakere_force_finish_night.py`, `mozakere_elim_report.py`, `mozakere_role_descriptions.py`, `mozakere_player_role_pick.py`
- `bot/main.py` — intro night, day-1 defence dispatch
- `bot/handlers/no_host_player.py` — day-1 defence callbacks
- `tests/test_mozakere_*.py` — 27 test files (list in §4/§6/§10/§11/§12/§13)
