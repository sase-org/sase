---
create_time: 2026-05-16 09:47:13
status: wip
prompt: sdd/prompts/202605/fast_agents_tab_disk_load.md
---
# Fast Agents Tab Disk Loading Plan

## Goal

Make ordinary `sase ace` Agents-tab refreshes O(visible agent rows) instead of O(all historical artifact directories).
The target outcome is that `agents.load_from_disk` is normally a small SQLite-backed query plus lightweight hydration,
with historical scans reserved for explicit repair, archive, revive, and diagnostic paths.

The plan follows the direction in `sdd/research/202605/deep_ace_tui_perf_fix.md`: treat the Agents tab as an
active/visible inbox, rely on the persistent artifact index, stop scanning the full artifact tree during normal
interaction, avoid normal search forcing full-history loads, and lazy-load expensive detail-only data.

## Current Findings

- `src/sase/ace/tui/models/agent_loader.py` already has a Tier 1 path through `~/.sase/agent_artifact_index.sqlite` via
  `query_agent_artifact_index`.
- The current Tier 1 query is still `active + recent completed limit 200`; it is not a true
  `active + completed but not dismissed` visible inbox.
- If the index is missing, the TUI falls back to a bounded source scan. The research file calls out why this can still
  be expensive: historical directory discovery can happen before record limiting.
- `_load_agents` and `_load_agents_async` pass `full_history=full_history or bool(_agent_search_query)`, so any normal
  Agents-tab search can promote recurring refreshes into full-history source scans.
- `load_agents_from_disk_with_state` populates tags, attempt history, and retry state for every loaded agent. Attempt
  history is cached, but still needs filesystem listing/stat signatures per loaded artifact directory.
- The Rust core boundary applies: index schema/query semantics belong in `../sase-core/crates/sase_core`, with Python
  wire/adapters and TUI wiring in this repo.

## Phase 1 - Measurement And Contract Guardrails

Owner: one agent instance.

Add instrumentation and tests that make the slow path visible before changing behavior.

Deliverables:

- Expand `AgentLoadState` and `agents.load_from_disk` trace fields with: `tier`, `artifact_source`,
  `used_artifact_index`, `index_error`, `full_history`, `agent_search_active`, `snapshot_records`, loaded row counts,
  and Rust snapshot stats when available (`artifact_dirs_visited`, `marker_files_parsed`, `prompt_step_markers_parsed`,
  etc.).
- Add tests proving a normal `_agent_search_query` does not silently force the loader contract in future phases.
- Add focused tests around missing-index and index-error behavior so later phases can intentionally change them without
  ambiguity.
- Add a small local benchmark or perf fixture for: index query path, bounded source fallback, and full-history source
  scan. This can live under existing agent-loader or ACE perf tests and should not depend on the user’s real `~/.sase`.

Verification:

- Targeted pytest for agent loader wiring and trace-state tests.
- `just install` first if needed in this workspace; after changes in this repo, run `just check`.

## Phase 2 - Visibility-Aware Rust Index Query

Owner: one agent instance, primarily `../sase-core` plus Python wire updates.

Make the index able to answer the TUI’s real question: which artifact-backed agents are visible now?

Deliverables:

- Extend `AgentArtifactIndexQueryWire` in Rust and Python with a visibility mode for normal TUI inbox queries. The query
  should return: active/incomplete rows, waiting/attention rows, and completed rows that are not dismissed.
- Add a dismissal visibility projection to the index. Prefer a normalized sidecar table keyed by agent identity/raw
  suffix over only adding a `dismissed` column to `agent_artifacts`; this keeps artifact facts separate from user/UI
  dismissal state while still allowing a single indexed SQL query.
- Add Rust APIs and Python facade bindings for updating dismissal visibility in bulk from `dismissed_agents.json` and
  for marking individual suffixes/identities dismissed or revived.
- Preserve current hidden-row semantics and the safety rule that RUNNING rows sharing an identity/suffix with a
  dismissed completed row remain visible.
- Add migration/schema-version handling and tests in `sase-core` for: active rows are visible, dismissed completed rows
  are excluded, old non-dismissed completed rows are included, hidden rows stay excluded unless requested, and running
  aliases are not hidden by completed dismissal.
- Update Python wire conversion tests for the new query fields/schema.

Verification:

- Rust unit tests and parity tests in `../sase-core`.
- Python wire/facade tests in this repo.

Research differences:

- The research note suggests adding `dismissed`/`dismissed_at` directly to `agent_artifacts`. This plan uses a
  normalized dismissal sidecar table unless implementation constraints make direct columns simpler. That is a deliberate
  difference, because dismissal state is not an artifact marker and is already stored independently in
  `dismissed_agents.json`/dismissed bundles.

## Phase 3 - TUI Loader Uses The Inbox Query By Default

Owner: one agent instance, Python/TUI integration.

Wire the visibility-aware index into ordinary ACE refreshes and remove historical scans from normal interaction.

Deliverables:

- Change `_query_artifact_index_for_loader` to use the new inbox query instead of `include_recent_completed=True` with a
  fixed recent limit.
- Stop normal Agents-tab search from forcing `full_history=True`. Normal search should filter the current inbox/cached
  working set. Explicit archive/revive flows should opt into full-history.
- Change missing-index behavior for interactive `sase ace`: return the last known in-memory list or an empty/loading
  state immediately and schedule a background rebuild/repair. Do not perform source artifact scans on ordinary refresh
  when the index is absent.
- Keep full-history source scans only for explicit paths: revive/archive search, manual repair/reconcile, and
  doctor/debug workflows.
- Update `AgentLoadState` semantics so incomplete index/rebuild states are visible to the TUI without requiring repeated
  source scans.
- Ensure selected-row preservation and group/fold finalization continue to work when the loader returns a stale or empty
  snapshot during rebuild.

Verification:

- Existing agent loader self-heal/finalization tests.
- New tests proving: missing index does not call `_scan_artifacts_for_loader` from normal async load, search does not
  force full history, explicit full-history still scans, and stale cached agents are preserved during incomplete loads.

Research differences:

- The research note says to show empty/cached/loading when the index is missing. This plan prefers "cached if available,
  otherwise loading/empty" because ACE already has preservation logic for incomplete loads and that gives the least
  disruptive UX.

## Phase 4 - Keep The Index Fresh Incrementally

Owner: one agent instance, cross-cutting lifecycle updates.

Make the fast path reliable by updating the index when agent lifecycle files and dismissal state change.

Deliverables:

- Add a small index-maintenance adapter in Python that calls the Rust facade for upsert/delete/dismiss/revive updates.
  It should be safe to call best-effort and should never block the Textual event loop.
- On launch/running/waiting/done marker writes, upsert the affected artifact directory.
- On dismiss/kill cleanup, update dismissal visibility and delete/upsert rows as appropriate when artifacts are removed.
- On revive, clear dismissal visibility for the revived suffix/identity and upsert any restored artifact row.
- On startup, synchronize the dismissal projection from `dismissed_agents.json` before the first inbox query when cheap;
  otherwise queue it before/with the rebuild worker and mark the load state incomplete.
- Coalesce repeated updates from active agents so Claude/Gemini/Codex/etc. hooks do not create write storms.
- Treat all runtimes uniformly; do not add provider-specific branches.

Verification:

- Unit tests for index adapter calls in launch, done, dismiss, kill, revive, and cleanup paths.
- Integration-style tests with a temporary projects root and index asserting the TUI inbox query changes after each
  lifecycle event.

Research differences:

- The research note mentions daemon/watcher/lifecycle hooks as the ideal architecture. This plan starts with
  lifecycle-owned updates plus background repair because those are easier to test and fit the current code. A daemon or
  filesystem watcher can be added later if lifecycle coverage proves incomplete.

## Phase 5 - Lazy Detail Data And Search Split

Owner: one agent instance, TUI model/detail-panel work.

Remove remaining per-refresh reads that do not affect the visible list.

Deliverables:

- Stop loading `attempt_history` for every agent in the default list load. Load it for the selected detail panel,
  expanded attempts/workflow views, or explicit actions that need it.
- Keep retry state eager only for currently active/running rows if needed for list status; otherwise make it
  selected-row lazy as well.
- Make the content search cache explicitly operate in two modes: inbox search for normal Agents-tab filtering and
  archive search for explicit historical/dismissed search.
- Ensure the visible list still has all fields required for grouping, sorting, unread/completion indicators,
  kill/dismiss commands, and tool/artifact panel entry points.

Verification:

- Agent display, grouping, runtime-row, panel index, and selected-detail tests.
- Add tests asserting list load does not stat/list attempt directories for unselected rows.

## Phase 6 - End-To-End Perf Validation And Cleanup

Owner: one agent instance.

Validate the improvement against realistic large-history fixtures and remove obsolete paths.

Deliverables:

- Add or update a reproducible large-history fixture/benchmark that simulates many dismissed completed artifacts plus a
  small visible inbox.
- Capture before/after `agents.load_from_disk` and key-to-paint numbers with `SASE_TUI_TRACE=1 SASE_TUI_PERF=1`.
- Assert normal refresh does not call source scanning when the index is present or rebuilding.
- Document the operational behavior: how the index is built, repaired, verified, and when full-history scans are
  expected.
- Remove or quarantine obsolete bounded-source fallback tests once the new missing-index behavior is established.

Target thresholds:

- Normal `agents.load_from_disk` p95 under 50 ms.
- Normal `agents.load_from_disk` max under 150 ms, excluding explicit repair or archive/revive paths.
- Agents-tab `j`/`k` key-to-paint p95 under 33 ms with active agents.

Verification:

- Targeted perf benchmark.
- Relevant pytest suites.
- `just check` in this repo, and the appropriate Rust tests/checks in `../sase-core` for phases that touch core.

## Coordination Notes

- Phase ordering matters. Phase 2 should land before Phase 3 so the TUI has a correct inbox query to call. Phase 4
  should land before relying on the index as permanently authoritative.
- Keep fallback/recovery behavior explicit. Source scans are still required for rebuild, repair, verification, revive,
  and archive search; they just should not happen during ordinary Agents-tab refreshes.
- Avoid modifying memory files. This plan intentionally touches only source, tests, docs/plan artifacts, and the sibling
  Rust core where required.
