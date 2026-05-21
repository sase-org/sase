---
create_time: 2026-05-21 09:57:52
status: done
prompt: sdd/prompts/202605/agents_tab_full_refresh_elimination.md
bead_id: sase-3t
tier: epic
---
# Plan: Eliminate Routine Full Refreshes For ACE Agents Tab

## Goal

Make the normal ACE Agents tab treat the persistent artifact index as the authoritative source for the visible inbox, so
ordinary startup, manual refresh, notifications, search/filtering, and lifecycle updates almost never require a Tier 2
full source scan.

Full source scans should remain available only for explicit repair, archive, revive, debug, or verification workflows.
The user-facing normal Agents tab should stay correct for visible agent entries without walking the full historical
artifact tree.

## Background

The `sase-3s` epic added a Tier 1 index-backed path for the Agents tab, but follow-up research in
`sdd/research/202605/agents_tab_full_refresh_elimination.md` shows the current path is still not authoritative for the
visible inbox:

- `AgentLoadState.needs_full_history_reconcile` is currently `not complete_history`, so every index load is treated as
  incomplete.
- `_loading_apply.py` re-arms `_agents_history_reconcile_pending` after every Tier 1 apply.
- Manual `y` refresh promotes to Tier 2 whenever that pending flag is set.
- Startup and idle timers schedule Tier 2 automatically after the first incomplete Tier 1 apply.
- Search currently passes `full_history=True` for any non-empty Agents query.
- The index query uses one `recent_completed_limit` for both active and completed selections, so stale active-like rows
  can consume the cap before Python post-filters them.
- The artifact-index dismissed projection is not synced on TUI startup and does not include dismissed bundle summaries
  unless the user runs the CLI GC path.
- Per-agent attempt-history hydration still performs filesystem work for each row on the normal refresh hot path.

The desired shape is a distinct visible-inbox contract, not another scheduling tweak. A Tier 1 load can be incomplete
for archive/history while still complete for what the normal Agents tab shows.

## Design Principles

- Normal refresh cost should be `O(number of visible rows)`, not `O(historical artifacts)`.
- Rust core owns shared artifact-index visibility semantics; Python owns TUI scheduling, UI state, and thin lifecycle
  adapters.
- The index may report repair needs, truncation, or corruption, but ordinary refresh should not silently fall back to a
  full scan unless the index is missing and the bounded fallback is still in use.
- Dismissed identity projection must be brought up to date before the index is trusted as the visible-inbox source.
- Revive/archive/debug flows may still opt into full history deliberately.

## Phase 1 - Visible-Inbox Contract And Wire Shape

Owner: Rust/core plus Python wire-boundary agent.

Scope:

- Extend the index query/load-state model with explicit visible-inbox completeness fields:
  - `complete_visible_inbox`
  - `complete_history`
  - `repair_recommended`
  - `repair_reason`
  - `truncated`
- Add distinct query limits for active/incomplete rows and completed rows. The existing `recent_completed_limit` should
  no longer also bound active rows.
- Keep backward-compatible defaults where practical, but update Python wire conversion and facade code together with the
  Rust serde contract.
- Update `AgentLoadState.needs_full_history_reconcile` to derive from visible-inbox incompleteness or repair state, not
  from `not complete_history`.
- Update trace counters and repro schema/capture fields enough that future phases can assert visible-inbox completeness.

Acceptance:

- A successful normal artifact-index load can report `complete_visible_inbox=True` and `complete_history=False`.
- Missing/corrupt indexes report a repair reason or bounded fallback state without implying that history is complete.
- Rust and Python unit tests cover serialization/deserialization of the new query and load-state fields.

## Phase 2 - Authoritative Dismissed Projection

Owner: dismissed-state/index lifecycle agent.

Scope:

- Add a reusable Python helper that builds artifact-index dismissed projection inputs from both:
  - `~/.sase/dismissed_agents.json`
  - dismissed bundle summaries exposed by `load_dismissed_bundle_summaries(limit=None)`
- Reuse the CLI GC conversion logic instead of leaving it isolated in `src/sase/agents/cli_index.py`.
- Sync the dismissed projection during TUI state initialization after `load_dismissed_agents()`, before the first
  index-backed load trusts normal visibility.
- Store enough projection metadata in the artifact index to avoid unnecessary repeated full projection writes:
  dismissed-agents file signature, dismissed-bundle index signature or rebuild/version metadata, projected identity
  count, and last-sync timestamp.
- If the dismissed bundle index is missing or stale, rebuild only that bundle summary index as needed. Do not rebuild
  the artifact index during normal startup.
- Keep lifecycle hooks for dismiss/kill/revive updating the same projection helper so TUI changes and startup sync use
  one path.

Acceptance:

- A workstation with zero `dismissed_agents` rows in the artifact index but existing dismissed stores gets a populated
  projection on TUI startup without an artifact source scan.
- Dismissed bundle summaries are projected into the artifact index.
- Startup sync is idempotent and skipped when signatures indicate no dismissed state changed.
- Tests cover JSON-only, bundle-only, and combined dismissed projection sources.

## Phase 3 - Core Index Query Semantics For Visible Inbox

Owner: Rust/core index agent.

Scope:

- Add or refine the normal visible-inbox query in `../sase-core/crates/sase_core/src/agent_scan/index.rs` so it returns:
  - all non-hidden live/incomplete/waiting/input-needed rows that are not dismissed;
  - bounded recent non-hidden completed/failed rows that are not dismissed;
  - no dismissed stale historical rows before limits are applied.
- Fix dismissed matching so stale rows cannot bypass exclusion due to unstable `agent_type` or `cl_name` shape. Raw
  suffix should be the stable broad key for terminal/stale artifact rows, while truly live rows can remain protected by
  stronger identity/liveness handling.
- Keep hidden-inclusive full-history/debug queries capable of inspecting dismissed rows when explicitly requested.
- Add active and completed limits as independent SQL parameters. If an active cap remains as a guardrail, mark
  `truncated=True` rather than calling the result complete.
- Preserve deterministic ordering and de-duplication by artifact directory.

Acceptance:

- A test index with thousands of stale dismissed active-like rows and a handful of real visible rows returns the real
  rows from Tier 1 without requiring Tier 2.
- The active row budget is not consumed by rows later excluded as dismissed.
- Hidden-inclusive full-history queries still support repair/debug inspection.
- Existing `sase agents index gc/rebuild/verify` behavior remains compatible.

## Phase 4 - TUI Refresh Scheduling Becomes Tier 1 By Default

Owner: TUI loading/scheduling agent.

Scope:

- Update `_loading_apply.py` so a complete visible-inbox Tier 1 apply does not arm `_agents_history_reconcile_pending`.
- Remove or hard-gate the startup Tier 2 timer and idle Tier 2 scheduler. They should only run when the load state
  explicitly reports `repair_recommended=True` or visible-inbox incompleteness that cannot be fixed by the index.
- Restore manual `y` refresh semantics so it always requests the normal Tier 1 visible-inbox path.
- Add an explicit full-history/repair command or action for the rare case where a user intentionally wants a full source
  scan. This can be a distinct binding, command-palette action, or internal action used by repair flows; do not overload
  normal refresh.
- Keep refresh coalescing behavior intact for notification-driven refreshes, launches, kills, dismissals, and revives.

Acceptance:

- Startup followed by idle time does not automatically schedule Tier 2 when Tier 1 reports a complete visible inbox.
- Pressing `y` on the Agents tab does not promote to `full_history=True` in the normal case.
- A Tier 2 reconcile followed by many normal lifecycle refreshes does not re-arm the next manual refresh into Tier 2.
- Tests cover pending-flag behavior and refresh scheduling.

## Phase 5 - Search And Archive Paths Are Split

Owner: TUI search/revive agent.

Scope:

- Remove the `or bool(_agent_search_query)` promotion from both sync and async load paths in
  `src/sase/ace/tui/actions/agents/_loading_disk.py`.
- Keep normal `/` Agents search scoped to the visible inbox plus existing in-memory/content-search cache behavior.
- Ensure content-search background workers do not force a source scan to answer normal visible-inbox search.
- Preserve archive/revive search as an explicit history-bearing flow. If needed, add a separate command/modal label and
  code path that intentionally queries dismissed bundles or full history.
- Update repro/capture expectations that currently equate active search with full-history loading.

Acceptance:

- Non-empty Agents search does not pass `full_history=True`.
- Visible rows continue to filter correctly by text and content cache.
- Revive/archive flows still surface dismissed historical entries intentionally.
- Tests cover sync and async search-triggered refreshes.

## Phase 6 - Lazy Detail Hydration For Normal Rows

Owner: TUI loader/performance agent.

Scope:

- Remove eager `attempt_history_for()` calls from the normal list refresh path for every loaded agent.
- Load attempt history lazily for selected-row detail views, attempts/retry modals, explicit content-search workers, and
  any action that truly needs it.
- Keep retry state eager only where it changes the visible row status, such as `RUNNING` to `RETRYING`.
- Preserve existing cache invalidation behavior in `_snapshot_cache.py`.
- Add trace counters that make it obvious when normal refreshes stat/list attempt directories.

Acceptance:

- Normal visible-inbox refresh does not list/stat `attempts/<N>/` for unselected rows.
- Selected-row detail and attempts/retry workflows still show attempt history.
- Performance tests or focused unit tests catch accidental reintroduction of per-row attempt-history hydration.

## Phase 7 - Repair, Diagnostics, And Operator UX

Owner: CLI/TUI diagnostics agent.

Scope:

- Keep `sase agents index gc/rebuild/verify` as the heavy repair hammer.
- Add a lightweight TUI-visible repair indication only when `repair_recommended=True`; do not auto-run full scans for
  ordinary refresh.
- Ensure explicit repair/full-history actions log and trace why they are running.
- Consider adding a small `sase agents index status --json` or extending `verify --json` with dismissed projection
  metadata if Phase 2 metadata needs operator visibility.
- Update documentation/help text for normal refresh versus repair/archive refresh.

Acceptance:

- Users can deliberately repair or verify the index when diagnostics say it is needed.
- Ordinary notification/startup/manual refresh traces remain Tier 1 and do not contain `tier2/source_scan` spans.
- Documentation and command help distinguish normal visible-inbox refresh from full-history repair.

## Phase 8 - End-To-End Verification And Rollout

Owner: final integration agent.

Scope:

- Run focused Rust tests in `../sase-core` for artifact-index query semantics.
- Run focused Python tests for wire conversion, dismissed projection sync, scheduling, search, and lazy hydration.
- In this repo, run `just install` first if the workspace may be stale, then `just check`.
- Exercise the live TUI by running the `sase ace --tmux` command, emulating keypresses on the new tmux pane, and then
  (for each action/behavior we need to verify) capturing the tmux pane contents for inspection/verification:
  - startup on Agents tab;
  - manual `y`;
  - notification-triggered refresh;
  - normal search;
  - dismiss/kill/revive refreshes;
  - explicit repair/full-history action.
- Confirm normal paths use `artifact_source=artifact_index`, `complete_visible_inbox=True`, and do not schedule later
  Tier 2 work.
- If the current workstation index is stale, run the explicit repair/GC command once as a rollout step and record the
  before/after counts.

Acceptance:

- Normal Agents-tab interactions no longer require full refreshes for visible entries.
- Full source scans are limited to explicit repair/archive/revive/debug flows.
- Existing visible agent entries remain present unless intentionally dismissed/hidden.
- The final handoff documents any residual cases where full history is still required.

## Cross-Phase Dependencies

- Phase 1 should land before Phases 3 through 5 because it defines the shared completeness state.
- Phase 2 can begin after Phase 1 wire decisions are clear, and should land before Phase 3 is judged complete.
- Phase 3 should land before Phase 4 fully disables automatic Tier 2 promotion, so the index is trustworthy first.
- Phase 5 can land after Phase 1 and Phase 4, but should verify archive/revive behavior with Phase 2 projection in
  place.
- Phase 6 is performance cleanup and can land after correctness is established.
- Phase 7 can proceed once repair metadata exists.
- Phase 8 must be last.

## Risks

- Broad suffix-based dismissed exclusion could hide a truly live artifact if raw suffixes collide or a live row reuses a
  dismissed suffix. Tests should distinguish terminal/stale artifact rows from live rows with strong liveness evidence.
- TUI startup dismissed projection must not become the new slow path. Metadata-based skipping is part of Phase 2, and
  startup should not rebuild the artifact index.
- Repro tooling currently encodes `complete_history`; Phase 1 must update it carefully to avoid making regression
  captures ambiguous.
- Cross-repo changes touch `../sase-core` and this Python repo. Phase agents must respect the Rust core backend boundary
  and avoid duplicating shared visibility logic in Python.
- Existing worktrees may be dirty. Phase agents must not revert unrelated edits.
