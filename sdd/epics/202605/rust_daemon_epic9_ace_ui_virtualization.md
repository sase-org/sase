---
create_time: 2026-05-14 07:15:47
status: wip
prompt: sdd/prompts/202605/rust_daemon_epic9_ace_ui_virtualization.md
---
# Plan - Rust Daemon Epic 9 Incremental ACE and UI Data Virtualization

## Context

Epic 9 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` adapts ACE to daemon-backed indexed reads without
rewriting the Textual UI or making Ratatui a prerequisite.

Current useful substrate in this checkout:

- Local daemon read plumbing exists under `src/sase/daemon/`, including typed read models, paged request helpers,
  capability-gated fallback, and client facades.
- ACE already has partial daemon-backed providers:
  - `src/sase/ace/tui/data_providers.py` for Agents snapshots and agent delta application.
  - `src/sase/ace/tui/actions/changespec/_provider.py` for ChangeSpec fallback reads.
  - `src/sase/ace/tui/actions/agents/_notification_provider.py` for notification snapshots/counts.
- ACE already has important hot-path work that Epic 9 should preserve:
  - j/k highlight-only paths for Agents and ChangeSpecs.
  - async loader scheduling/coalescing and navigation gates.
  - notification snapshot caching for agent unread reconciliation.
  - TUI trace spans in `src/sase/ace/tui/util/trace.py`.
  - perf harnesses such as `tests/perf/bench_tui_trace.py` and daemon rollout policy tests.

The main gap is that ACE still treats most data as full in-memory snapshots. Current daemon adapters often drain every
page immediately and then reuse the legacy full-list apply/render pipeline. Epic 9 should introduce a stable ACE data
provider and viewport model first, then migrate each surface incrementally while retaining direct Python fallback.

## Goals

- Keep ACE functional when the daemon is unavailable, disabled, incompatible, or returning projection errors.
- Move ACE read paths toward pages, cursors, snapshot ids, deltas, and lazy details.
- Keep navigation responsive: j/k key-to-paint should update highlights without list rebuilds or daemon calls.
- Ensure daemon-backed no-change refresh does not broad-reload Agents, ChangeSpecs, Notifications, artifacts, or
  archive/search surfaces.
- Keep Textual as the production shell for this epic; Ratatui remains an explicit later checkpoint only after backend
  contracts and ACE providers are stable.
- Add perf gates that are concrete enough for future agents to fail fast on regressions.

## Non-Goals

- Do not rewrite ACE in Rust or Ratatui in this epic.
- Do not make daemon projections authoritative for writes; write-through behavior belongs to earlier Epic 6/7 work.
- Do not remove direct Python loaders or no-daemon recovery paths.
- Do not require every ACE tab to become fully virtualized before the first daemon-backed tab ships.
- Do not introduce runtime-specific behavior for Claude/Gemini/Codex/Qwen/OpenCode; agent runtime capability remains
  uniform.
- Do not reimplement shared query/projection behavior in Python when it belongs in `../sase-core`.

## Cross-Phase Design

Use one ACE provider vocabulary across Agents, ChangeSpecs, Notifications, artifacts, archive, and search:

- `AceDataProvider`: provider identity, surface name, `prefers_daemon`, `capabilities`, and fallback metadata.
- `AceSnapshot`: surface, schema version, snapshot id, generation id, total/count/facet metadata, first page, and source
  info.
- `AcePage`: cursor, requested range or query, rows, next cursor, estimated total, bounded/truncated metadata.
- `AceDeltaBatch`: snapshot id, sequence, surface, row upserts/deletes/inserts, count/facet patches, invalidation
  reason, and resync hint.
- `AceRowHandle`: stable daemon handle plus local fallback identity for direct loaders.
- `AceDetailRequest`: row handle plus selection generation; detail/artifact loads must be cancellable and ignored if the
  selection generation has moved on.

Provider responsibilities:

- Daemon providers may request only the first viewport plus prefetch windows, not the full world.
- Direct providers can wrap current Python loaders and expose a snapshot-shaped API, even if internally they still load
  full lists.
- Fallback must preserve current behavior and must expose reason fields for tests and trace output.
- Unknown delta operations or expired cursors must degrade to targeted resync when possible, full snapshot reload only
  when necessary.

UI responsibilities:

- Highlight movement is local and never calls the daemon.
- List-shape changes are explicit: query, filter, fold, grouping, page arrival, delta batch, or fallback resync.
- Detail/artifact panes load after debounce/idle and carry selection generation guards.
- Background reads run off the Textual UI thread via existing `asyncio.to_thread`, `run_worker`, or a narrow async
  wrapper around the local daemon client.

Rollout flags:

- Reuse existing daemon read policy (`SASE_NO_DAEMON`, `daemon.reads.*`, surface groups) and keep ACE-specific gates
  separate where needed.
- Add or preserve surface toggles such as `ace_agents`, `ace_changespecs`, `ace_notifications`, `ace_artifacts`, and
  `ace_archive_search` so phases can land independently.

## Phase 9A - Shared ACE Provider and Viewport Foundation

Purpose: introduce the common provider/viewport contract and make existing providers conform without changing visible
ACE behavior.

Primary ownership:

- `src/sase/ace/tui/data_providers.py` or a new `src/sase/ace/tui/data/` package.
- Existing provider entry points for Agents, ChangeSpecs, and Notifications.
- Focused provider tests under `tests/ace/tui/` and daemon read facade tests.

Deliverables:

- Define provider-neutral dataclasses/protocols for snapshots, pages, row handles, delta batches, fallback metadata,
  count/facet patches, and detail requests.
- Wrap current direct loaders as direct providers:
  - Agents loader from the current `load_tiered_agents` path.
  - ChangeSpec loader from `find_all_changespecs_cached`.
  - Notification loader from `read_notification_snapshot`.
- Adapt existing daemon providers to return the shared snapshot shape while still allowing them to internally drain all
  pages for compatibility in this phase.
- Add selection generation helpers and cancellation/ignore policy for lazy detail requests, but do not yet route
  production detail panes through it.
- Add trace fields that identify provider source, snapshot id, page count, fallback reason, and whether a full reload
  was used.
- Document the provider contract in code comments or a short SDD note so later phases share the same API.

Acceptance gates:

- Existing ACE behavior and visual snapshots remain unchanged.
- Unit tests prove direct and daemon provider snapshots expose the same stable row-handle identity for the same logical
  row.
- Provider fallback reasons are visible in tests and trace records.
- No Textual widget code depends directly on daemon client wire dictionaries.

Suggested phase prompt:

> Implement Phase 9A from `sase_plan_rust_daemon_epic9_ace_ui_virtualization.md`: add the shared ACE provider,
> snapshot/page/delta, row-handle, fallback, and selection-generation foundation, then adapt existing Agents,
> ChangeSpec, and Notification providers without changing visible ACE behavior.

## Phase 9B - Agents Tab Paged Snapshots, Deltas, and Lazy Detail

Purpose: migrate the Agents tab from full daemon snapshot draining toward viewport pages and daemon deltas while keeping
the current direct loader fallback.

Primary ownership:

- `src/sase/ace/tui/data_providers.py` or the new provider package.
- `src/sase/ace/tui/actions/agents/_loading*.py`, `_display*.py`, `_panel*.py`.
- `src/sase/ace/tui/widgets/agent_list.py` and related row patch helpers only where needed.
- Tests under `tests/ace/tui/`, `tests/test_daemon_read_facade.py`, and perf harness extensions.

Deliverables:

- Add an Agents viewport model that requests visible rows plus a bounded prefetch window from `agent_active`,
  `agent_recent`, `agent_archive`, or `agent_search`.
- Preserve current grouped/tagged/panel rendering by materializing only the current viewport plus required group/banner
  metadata; direct fallback may still materialize the full list.
- Apply daemon agent delta batches using stable row handles:
  - insert/upsert/delete rows.
  - count/facet patches for headers and panels.
  - invalidate/resync when a delta cannot be applied safely.
- Route detail/artifact-heavy agent side-panel loads through selection generation guards and debounce/idle scheduling.
- Keep j/k navigation local: no daemon call on highlight movement, no broad list rebuild on selection-only changes.
- Keep existing manual unread, marks, tags, grouping, fold, revive, kill/dismiss, and workspace-status behavior intact.
- Add a targeted resync path for expired cursors/snapshots that preserves selection by row handle.

Acceptance gates:

- Agents tab works with daemon reads enabled and disabled.
- j/k burst tests still prove at most one unchanged tree rebuild per burst.
- Deltas patch rows/counts when possible and fall back to resync only on explicit invalidation or unknown operations.
- No-change auto-refresh on daemon-backed Agents does not call the legacy full loader.
- Trace output distinguishes highlight-only, page fetch, delta apply, targeted resync, and full fallback reload spans.

Suggested phase prompt:

> Implement Phase 9B from `sase_plan_rust_daemon_epic9_ace_ui_virtualization.md`: migrate the Agents tab onto paged ACE
> provider snapshots, daemon delta application, lazy detail/artifact loads guarded by selection generation, and
> no-change refresh avoidance while preserving direct fallback.

## Phase 9C - ChangeSpecs Tab Paged Queries and Lazy Detail

Purpose: migrate ChangeSpecs list/search/detail reads to query handles and lazy detail while preserving existing
grouping, hide toggles, and j/k behavior.

Primary ownership:

- `src/sase/ace/tui/actions/changespec/`.
- `src/sase/ace/tui/widgets/changespec_list.py` and row patch helpers only where needed.
- `src/sase/daemon/changespec_reads.py` and Python client facade code if ACE needs small read-shape additions.
- `../sase-core` only if the daemon contract lacks required query/detail metadata.

Deliverables:

- Add ChangeSpecs provider snapshots using daemon `changespec_list`, `changespec_search`, and `changespec_detail`
  surfaces with query/status/page parameters.
- Introduce query/session handles that keep list pages tied to a snapshot id and active query string.
- Keep current direct Python filter path as fallback; daemon-backed search should avoid building a full Python
  `ChangeSpec` corpus for ordinary list/search pages.
- Lazy-load selected ChangeSpec detail after debounce/idle with selection generation guards.
- Preserve current ancestry/children/sibling panel behavior:
  - use daemon summary metadata when available.
  - fall back to current local graph-index building where the daemon cannot yet provide relationship pages.
- Apply ChangeSpec delta batches for status/name/parent/source updates where possible; invalidate the active query
  session when a delta may reorder the current result set.
- Keep j/k highlight-only path unchanged for selection movement.

Acceptance gates:

- ChangeSpecs tab works with daemon reads enabled and disabled.
- Query edits and hide toggles do not block the UI thread on daemon-backed surfaces.
- Detail debounce still emits one final detail paint after a long j/k burst.
- Existing ChangeSpec visual snapshots and navigation tests pass.
- No-change auto-refresh on daemon-backed ChangeSpecs does not call `find_all_changespecs_cached`.

Suggested phase prompt:

> Implement Phase 9C from `sase_plan_rust_daemon_epic9_ace_ui_virtualization.md`: migrate the ChangeSpecs tab to paged
> daemon list/search/detail providers, query-session handles, lazy detail loading, and delta-aware refresh while
> preserving direct fallback and current navigation behavior.

## Phase 9D - Notifications, Artifacts, Archive, and Search Surfaces

Purpose: extend the provider/viewport model to remaining read-heavy ACE surfaces that currently piggyback on full
notification snapshots, artifact scans, or archive/history scans.

Primary ownership:

- Notification provider/action code under `src/sase/ace/tui/actions/agents/`.
- Notification modal code under `src/sase/ace/tui/modals/`.
- Agent artifact/detail panel code under `src/sase/ace/tui/actions/agents/` and widgets.
- Archive/search providers under `src/sase/ace/archive.py`, agent archive CLI/read facades, and ACE search actions.

Deliverables:

- Split notification reads into:
  - count-only provider for the persistent indicator.
  - unread modal page provider.
  - pending-action/detail provider for selected modal rows.
- Apply notification delta/count patches without reparsing full JSONL snapshots.
- Keep completion-to-agent unread reconciliation working from cached notification pages and count deltas.
- Add artifact association/detail page providers keyed by selected row handle, with cancellation on selection change.
- Add archive/search page providers for agents and artifacts so archive views do not scan the full history on every
  query/navigation action.
- Preserve notification actions, pending HITL behavior, plan/question modals, attachment rendering, and direct fallback.
- Add bounded payload handling for large artifacts and long notification bodies.

Acceptance gates:

- Notification indicator updates can run count-only through daemon reads.
- Opening the notification modal does not force a full notification-store load when daemon pages are available.
- Agent detail/artifact panes ignore stale loads after selection changes.
- Archive/search views request pages and bounded details rather than scanning all history on daemon-backed paths.
- Existing notification modal/action tests pass in daemon and no-daemon modes.

Suggested phase prompt:

> Implement Phase 9D from `sase_plan_rust_daemon_epic9_ace_ui_virtualization.md`: migrate notification
> count/list/detail, artifact detail/association, and archive/search ACE surfaces to paged provider reads with deltas,
> bounded payloads, lazy details, and direct fallback.

## Phase 9E - Refresh Loop Integration and Broad Reload Removal

Purpose: make the ACE refresh loop daemon-aware so clean daemon-backed tabs consume deltas/pages instead of scheduling
legacy broad reloads.

Primary ownership:

- `src/sase/ace/tui/actions/event_handlers.py`.
- `src/sase/ace/tui/actions/startup.py`.
- Existing watcher/dirty flag integration and daemon subscription client code.
- Tests under `tests/ace/tui/test_event_handlers_dirty_flags.py` and new daemon-refresh tests.

Deliverables:

- Add a daemon-backed refresh coordinator per surface:
  - consumes delta stream/subscription events when available.
  - uses dirty flags only as fallback/resync triggers.
  - maps file watcher events to targeted surface invalidation where possible.
- Replace no-change auto-refresh broad reloads for daemon-backed tabs with:
  - count/delta polling if subscriptions are unavailable.
  - snapshot freshness check.
  - no-op when snapshot id and last sequence have not changed.
- Keep the existing inotify watcher as fallback for direct/no-daemon mode and missed daemon events.
- Add startup behavior that renders ACE shell quickly, then hydrates initial daemon pages in background.
- Add explicit stale-projection/corrupt-projection fallback handling that switches the affected surface to direct loader
  without taking down the whole TUI.
- Add trace events for subscription connect/disconnect, delta batch apply, no-op refresh, targeted resync, and fallback
  mode switch.

Acceptance gates:

- With daemon-backed surfaces clean, `_on_auto_refresh` performs no broad Agents/ChangeSpecs/Notifications reload.
- When daemon subscription is unavailable, polling fallback still keeps ACE current.
- When daemon projection errors occur, only affected surfaces fall back to direct loaders with visible fallback reason
  in traces/tests.
- Existing watcher dirty-flag tests still pass for direct mode.

Suggested phase prompt:

> Implement Phase 9E from `sase_plan_rust_daemon_epic9_ace_ui_virtualization.md`: make ACE refresh coordination
> daemon-aware, consume deltas/no-op freshness checks for clean surfaces, retain inotify/direct fallback, and remove
> broad reloads from daemon-backed no-change auto-refresh.

## Phase 9F - Perf Gates, Rollout Policy, and Ratatui Checkpoint

Purpose: lock the migration behind measurable gates and record the optional future Rust TUI decision point.

Primary ownership:

- `tests/perf/bench_tui_trace.py`, `tests/perf/daemon_read_rollout.py`, and related baselines.
- TUI trace/perf utilities under `src/sase/ace/tui/util/`.
- Config/read rollout policy under `src/sase/daemon/read_config.py` and default config if needed.
- SDD notes for the Ratatui checkpoint.

Deliverables:

- Add Epic 9 perf targets for:
  - ACE shell first useful paint.
  - first indexed snapshot paint per daemon-backed tab.
  - j/k key-to-paint p95 for Agents and ChangeSpecs.
  - no-change auto-refresh p95 and broad-loader-call count.
  - query edit p95 on large ChangeSpec and agent-history fixtures.
  - lazy detail stale-load cancellation count.
- Extend trace summarization to assert forbidden spans for daemon-backed no-change refresh, such as direct full loaders.
- Add test fixtures/fakes for daemon pages, cursor expiry, snapshot expiry, delta batches, and projection errors.
- Define rollout policy:
  - all direct loaders remain available.
  - ACE surfaces remain opt-in until perf/parity gates pass.
  - defaults can flip one surface at a time only after CI gates and real-history soak pass.
- Add a short Ratatui checkpoint note:
  - required backend contracts before considering replacement.
  - Textual provider API compatibility requirements.
  - explicit non-blocking criteria for the daemon benefits.

Acceptance gates:

- Perf tests can fail a phase for j/k regressions, broad reloads, or first indexed snapshot regressions.
- Rollout policy prevents `ace_*` daemon surfaces from being enabled by default without explicit gate coverage.
- The plan records Ratatui as optional future shell work, not part of Epic 9 completion.
- All default tests pass, and slow perf gates are runnable locally with documented commands.

Suggested phase prompt:

> Implement Phase 9F from `sase_plan_rust_daemon_epic9_ace_ui_virtualization.md`: add Epic 9 TUI trace/perf gates,
> daemon page/delta/error fixtures, rollout policy checks, and the Ratatui decision checkpoint documentation.

## Dependencies and Sequencing

1. Phase 9A can begin once Epic 5 has at least the local daemon client/fallback machinery available, which this checkout
   already appears to have.
2. Phase 9B should wait for daemon `agent_active`, `agent_recent`, `agent_archive`, `agent_search`, and `agent_detail`
   read contracts to be stable enough for pages and row handles.
3. Phase 9C should wait for ChangeSpec list/search/detail daemon read contracts, including stable handles and enough
   relationship metadata to avoid full Python graph work on common detail paints.
4. Phase 9D should wait for notification count/list/detail and artifact association/detail read surfaces.
5. Phase 9E should wait for at least one surface from 9B/9C/9D to support deltas or freshness checks.
6. Phase 9F can start early for fixtures and target definitions, but enforcement gates should land after at least one
   daemon-backed ACE surface exists.

Each phase is intended for a distinct agent instance. Later agents should keep their write scope to that phase, avoid
unrelated refactors, and preserve the direct fallback path unless the phase explicitly says otherwise.

## Verification Strategy

For implementation phases that edit code in this repo:

- Run `just install` first in the current ephemeral workspace.
- Run focused tests for the touched surface.
- Run `just check` before completion unless the only changes are bead files.
- Run slow perf harnesses only when the phase touches perf gates or hot navigation behavior:
  - `pytest -s -m slow tests/perf/bench_tui_trace.py`
  - relevant daemon rollout perf tests under `tests/perf/`

For phases that touch `../sase-core`, also run the focused Rust package tests and any Python binding/contract tests that
exercise the changed wire models.
