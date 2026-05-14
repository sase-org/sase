---
create_time: 2026-05-14
status: done
legend_bead_id: sase-3e
bead_id: sase-3e.5
tier: epic
epic_number: 5
source: sdd/legends/202605/rust_daemon_indexed_projections_1.md
---

# Epic 5 Plan - Daemon-Backed Read APIs for CLI, Editor, and ACE

## Source

This plan implements Epic 5, "Daemon-Backed Read APIs for CLI, Editor, and ACE", from
`sdd/legends/202605/rust_daemon_indexed_projections_1.md`.

Epic 5 purpose: move hot read paths to paged daemon queries while keeping current Python behavior as fallback.

## Current State

- `../sase-core/crates/sase_core/src/projections/` contains event-backed SQLite projections for ChangeSpecs,
  notifications, agents/artifacts/archive/dismissals, beads, workflows, catalogs, and file history.
- `../sase-core/crates/sase_gateway` owns daemon lifecycle, host-local storage, local framed JSON RPC, projection
  service, indexing service, rebuild/verify/diff diagnostics, and local heartbeat/event scaffolding.
- Epic 4 shadow indexing is diagnostic-only. `sase daemon rebuild|verify|diff` can prove projection parity, but
  production CLI, ACE, editor, mobile, and bead reads still use existing source-store loaders.
- The local daemon wire contract already has health, capabilities, batch, list, events, indexing diagnostics, fallback,
  bounded payload metadata, snapshot IDs, cursors, and collection names. The production `list` handler is still mocked
  and must be replaced with real projection queries.
- Python already has a low-level synchronous local daemon client in `src/sase/daemon/client.py` and direct Rust facades
  under `src/sase/core/`. There is no typed daemon read facade yet.
- Existing hot read paths include:
  - `sase agents status/show` via `sase.agent.running` and agent artifact loaders.
  - `sase notify list/show` via notification catalog/store loaders.
  - `sase changespec search/current` and ACE ChangeSpecs via `find_all_changespecs_cached` plus query corpus filtering.
  - `sase editor helper-bridge` and mobile helper aliases via catalog, xprompt, snippet, file-history, and bead helpers.
  - `sase bead list/show/ready/blocked/stats` via fast-path Rust bindings and local store selection.
  - ACE Agents and ChangeSpecs tabs via broad disk scans plus in-memory filtering; notification counts and modals still
    read notification snapshots directly.

## Goals

- Add real local daemon read APIs backed by projections, shaped around bounded pages, cursors, snapshot IDs, stable
  handles, facets/counts, details, search filters, and delta subscriptions.
- Route selected latency-sensitive CLI/editor reads through the daemon with explicit `--no-daemon` and automatic
  fallback on unavailable daemon, incompatible client, corrupt/degraded projections, expired cursors, or unsupported
  capabilities.
- Keep output byte-compatible where commands promise stable text/JSON; record intentional differences in tests.
- Add ACE data-provider adapters that can load indexed snapshots, apply row/count deltas, lazily fetch details and
  artifacts, and avoid broad filesystem I/O during navigation or no-change refreshes.
- Preserve current direct source-store behavior for daemon-disabled, recovery, unsupported surface, and parity-failure
  cases.
- Prove performance and parity on representative large fixtures before enabling a surface by default.

## Non-Goals

- Do not move mutations to daemon write APIs. Epic 6 owns writes.
- Do not make SQLite projections the source of truth.
- Do not remove `.sase`, `.gp`, notification JSONL, bead JSONL/config/cache, agent artifact markers, xprompt files,
  memory files, or file-history source stores.
- Do not reroute every CLI command in one phase. Each surface should be independently gated and reversible.
- Do not block ACE startup or navigation on synchronous daemon calls.
- Do not introduce runtime-specific behavior for Claude, Gemini, Codex, Qwen, opencode, or other agent runtimes.

## Architecture

- Put projection query semantics and reusable wire records in `../sase-core/crates/sase_core`.
- Put RPC dispatch, capabilities, cursor validation, snapshot lifetime, bounded payload handling, delta publication, and
  projection-service reads in `../sase-core/crates/sase_gateway`.
- Put Python transport wrappers, typed read facades, output conversion, command-routing gates, and ACE data providers in
  this repo.
- Use a typed read contract rather than overloading one generic JSON summary shape for all production surfaces. A
  generic list envelope is acceptable, but each collection needs typed filter/detail/count records and contract
  snapshots.
- Use stable handles for identity:
  - ChangeSpecs: projection handle such as `changespec:<project_id>:<name>`.
  - Agents: project id plus agent/artifact identity.
  - Notifications: notification id.
  - Beads: project id plus bead id.
  - Catalog/file history: catalog id or normalized project/path key.
- Use opaque cursors in daemon RPC even when the current projection helper uses offsets internally. Cursor payloads
  should include collection, query/filter hash, snapshot id or snapshot generation, offset/keyset state, and expiry.
- Keep direct fallback local to each facade so CLI and ACE call sites do not duplicate exception handling.
- Delta streams should carry row upsert/delete/invalidate, count/facet patches, and resync-required events. ACE must
  treat resync as a bounded snapshot reload, not a full source-store scan unless daemon fallback is active.

## Phase 5A - Read Contract and Projection Query Foundation

Owner: one agent.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/`
- `../sase-core/crates/sase_core/src/wire.rs` or a focused projection read wire module
- `../sase-core/crates/sase_gateway/src/wire.rs`
- `../sase-core/crates/sase_gateway/src/local_transport.rs`
- `../sase-core/crates/sase_gateway/src/contract.rs`
- `../sase-core/crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json`

Deliverables:

- Define typed local read requests/responses for:
  - ChangeSpec list/search/detail.
  - Agent active/recent/archive/search/detail/children/artifacts.
  - Notification list/detail/counts/pending actions.
  - Bead list/show/ready/blocked/stats.
  - Xprompt catalog, editor catalog, snippet/catalog-adjacent helper data, and file-history reads.
- Add reusable page/cursor/snapshot/filter records and typed daemon errors for cursor expired, snapshot expired,
  projection degraded, unsupported capability, and payload too large.
- Replace mocked `LocalDaemonCollectionWire::Mocked`-only list behavior with projection-backed dispatch for at least one
  low-risk collection and explicit unsupported errors for collections not implemented yet.
- Add projection query helper gaps needed for the contract, especially notification paging/search/detail/counts and
  agent search/detail shapes that are currently only partially exposed.
- Add contract snapshot tests for the new local daemon read shapes.
- Publish capabilities per completed surface, for example `changespecs.read`, `notifications.read`, `agents.read`,
  `beads.read`, `catalogs.read`, and `daemon.deltas`.

Acceptance gates:

- `cargo test -p sase_core projections` and `cargo test -p sase_gateway local_daemon` pass.
- The local daemon contract snapshot changes only for intentional read API additions.
- Every read response is bounded by page limit and max payload metadata.
- Unsupported surfaces fail with typed fallback metadata instead of returning empty success.

## Phase 5B - Python Daemon Read Facades and Fallback Harness

Owner: one agent after Phase 5A.

Primary write scope:

- `src/sase/daemon/client.py`
- new `src/sase/daemon/read_facade.py` or `src/sase/daemon/read_models.py`
- focused adapters under `src/sase/core/`
- tests under `tests/`

Deliverables:

- Add Python client methods for every Phase 5A read endpoint, including paged iteration helpers and bounded detail
  calls.
- Add typed Python response dataclasses or rehydration helpers that preserve existing model shapes where practical.
- Add a shared routing/fallback helper:
  - honors `--no-daemon` and `SASE_NO_DAEMON`;
  - checks daemon capabilities before routing;
  - converts daemon unavailable/degraded/cursor/snapshot errors into direct loader fallback;
  - can expose fallback reason in debug JSON without changing normal output.
- Add golden tests that compare daemon-backed facades against existing direct loaders using Epic 1/4 fixtures.
- Add a small fake daemon transport for Python tests so CLI routing can be tested without launching the Rust daemon.

Acceptance gates:

- `just test` passes for the new Python facade tests.
- Daemon disabled, missing socket, unsupported capability, projection degraded, and cursor-expired cases all fall back
  to direct loaders.
- Facades do not import Textual or heavyweight ACE modules on pure CLI/editor paths.

## Phase 5C - Notification CLI Reads

Owner: one agent after Phases 5A and 5B.

Primary write scope:

- `src/sase/notifications/cli_list.py`
- `src/sase/notifications/cli_show.py`
- `src/sase/notifications/catalog.py`
- notification-specific daemon facade/conversion files
- tests under `tests/`

Deliverables:

- Route `sase notify list` and `sase notify show` through daemon projections when `notifications.read` is available.
- Add parser support for `--no-daemon` on read subcommands without changing notification create/write behavior.
- Preserve existing filters: limit, query, sender, unread, and include dismissed.
- Add daemon-backed counts/pending-action reads for notification indicator use, but keep mark-read/dismiss writes direct
  until Epic 6.
- Add byte-compatible JSON/text output tests comparing daemon and direct paths.

Acceptance gates:

- CLI output is byte-compatible or intentional differences are documented in tests.
- Invalid notification JSONL soft-error behavior matches the direct loader fallback.
- Notification list/show does not read the JSONL file when daemon routing succeeds.

## Phase 5D - Agent CLI Reads

Owner: one agent after Phases 5A and 5B.

Primary write scope:

- `src/sase/agents/cli_status.py`
- `src/sase/agents/cli_show.py`
- `src/sase/agent/running.py` only for conversion seams needed by CLI compatibility
- agent-specific daemon facade/conversion files
- tests under `tests/`

Deliverables:

- Route `sase agents status` through daemon projections for active agents and `--all` recent agents.
- Add `--no-daemon` for read subcommands.
- Preserve JSON schema from `_agent_to_json` and existing pretty-table semantics.
- Route `sase agents show` through daemon detail/artifact reads when the requested agent can be resolved by stable name
  or handle; fall back to current detail rendering otherwise.
- Preserve current project filtering, prompt truncation, provider/model fields, approve status, workspace number,
  duration, and artifact directory behavior.

Acceptance gates:

- Status/show JSON output stays compatible with direct loaders.
- Completed, failed, waiting, hidden/dismissed, archived, workflow, and parent/child cases are covered.
- Successful daemon status does not scan `~/.sase/projects` directly.

## Phase 5E - ChangeSpec CLI Reads

Owner: one agent after Phases 5A and 5B.

Primary write scope:

- `src/sase/main/changespec_handler.py`
- `src/sase/main/search_handler.py`
- ChangeSpec-specific daemon facade/conversion files
- query/display compatibility tests under `tests/`

Deliverables:

- Route `sase changespec search` through daemon ChangeSpec search/list/detail projections when available.
- Route `sase changespec current` through a daemon list/search/detail path after the current workspace branch/change URL
  context has been resolved locally.
- Add `--no-daemon` for read subcommands.
- Preserve rich, markdown, plain, and JSON output behavior by rehydrating existing `ChangeSpec` display models or by
  proving a byte-compatible renderer over daemon detail records.
- Keep current query parsing semantics. If a query feature cannot be represented by the daemon FTS/search API yet,
  fallback to current `find_all_changespecs_cached` plus query-corpus evaluation.

Acceptance gates:

- Search/current outputs match direct loaders on active/archive/project-scoped fixtures.
- Queries that target terminal/submitted/reverted statuses keep current hide/filter behavior.
- Successful daemon search/current avoids broad project spec hydration.

## Phase 5F - Editor Helper, Catalog, File-History, and Bead Read Routing

Owner: one agent after Phases 5A and 5B. This phase may be split into two agents if bead routing conflicts with editor
helper work; keep catalog/editor files and bead files as separate write scopes if parallelized.

Primary write scope:

- `src/sase/integrations/editor_helpers.py`
- `src/sase/integrations/_editor_helper_snippets.py`
- `src/sase/integrations/mobile_helpers.py` or focused helper modules
- `src/sase/main/bead_fast_path.py`
- `src/sase/bead/cli_*.py`
- bead/catalog daemon facade/conversion files
- tests under `tests/`

Deliverables:

- Route editor helper catalog/file-history reads through daemon catalog projections when capability and projection
  parity are available.
- Keep explicit resync-required diagnostics for non-watchable catalog/plugin/generated inputs.
- Route `sase bead list/show/ready/blocked/stats` through daemon projections only when the selected project/store
  context exactly matches the daemon projection project. Preserve VC/non-VC store selection rules.
- Add `--no-daemon` or environment fallback for daemon-routed bead reads without affecting bead writes.
- Preserve existing bead fast-path behavior for writes and unsupported read options.

Acceptance gates:

- Editor helper bridge JSON remains stable.
- Bead read output remains compatible for VC-backed and non-VC stores.
- Daemon bead reads never choose a different project store than the current direct fast path would choose.

## Phase 5G - ACE Data Provider Abstraction and Agents Tab

Owner: one agent after Phases 5A, 5B, and 5D.

Primary write scope:

- new or updated ACE data-provider modules under `src/sase/ace/tui/`
- `src/sase/ace/tui/actions/agents/`
- `src/sase/ace/tui/models/`
- ACE tests and repro fixtures under `tests/`

Deliverables:

- Add an ACE data-provider abstraction with direct-loader and daemon-backed implementations.
- Add daemon-backed initial snapshots for the Agents tab:
  - active rows;
  - recent rows;
  - parent/child rows;
  - archive/dismissed metadata required by current UX;
  - lazy detail/artifact loads for selected rows.
- Apply daemon row/count deltas from local event streams where available.
- Treat resync-required, cursor-expired, or snapshot-expired events as bounded daemon snapshot reloads.
- Preserve current selection, grouping, folding, unread projection, tag behavior, and revive/cleanup affordances.
- Keep all daemon calls off the Textual UI thread.

Acceptance gates:

- ACE Agents tab remains functional with daemon disabled.
- With daemon routing enabled, startup/no-change refresh does not perform broad agent artifact scans.
- Existing Agents tab unit/repro/visual tests pass, with additional tests for daemon snapshot and delta application.

## Phase 5H - ACE ChangeSpecs and Notifications Providers

Owner: one agent after Phases 5A, 5B, 5C, and 5E.

Primary write scope:

- `src/sase/ace/tui/actions/changespec/`
- `src/sase/ace/tui/actions/agents/_notifications.py`
- `src/sase/ace/tui/modals/notification_modal*.py`
- ChangeSpec/notification ACE provider files
- ACE tests and repro fixtures under `tests/`

Deliverables:

- Add daemon-backed ChangeSpecs snapshots, search/filter pages, and lazy detail loads.
- Add daemon-backed notification counts, modal list/detail reads, pending-action reads, and count patches.
- Apply row/count deltas for ChangeSpecs and Notifications.
- Preserve selection restore, query behavior, hide-submitted/reverted semantics, notification toasts, unread indicators,
  and modal action behavior.
- Keep notification writes direct until Epic 6; after direct writes, refresh via daemon delta or bounded snapshot
  reload.

Acceptance gates:

- ACE ChangeSpecs and notification views work with daemon enabled and disabled.
- No-change refresh for daemon-backed tabs does not call broad `find_all_changespecs_cached` or notification JSONL
  snapshot reads.
- TUI perf traces show reduced broad load spans for daemon-backed tabs.

## Phase 5I - Rollout, Perf Gates, and Default Enablement

Owner: one integration agent after all earlier phases.

Primary write scope:

- feature flag/config defaults
- docs/runbook updates
- CI/perf tests
- cross-surface integration tests
- minimal fixes in previously touched facades/providers

Deliverables:

- Add or finalize config flags for:
  - daemon disabled;
  - read-through daemon enabled per surface;
  - fallback diagnostics;
  - force direct loaders.
- Add command-level and ACE perf gates aligned with `docs/perf_runbook.md`:
  - warm CLI reads;
  - ACE first indexed snapshot;
  - no-change refresh;
  - large ChangeSpec search;
  - large agent history status/list.
- Add end-to-end tests that run daemon rebuild, verify, daemon-routed CLI reads, and fallback reads against large
  fixtures.
- Document rollout and recovery:
  - when to run `sase daemon rebuild|verify|diff`;
  - how `--no-daemon` and `SASE_NO_DAEMON` behave;
  - what fallback reasons mean.
- Enable daemon read routing by default only for surfaces that meet parity and perf gates. Leave weaker surfaces behind
  explicit opt-in flags.

Acceptance gates:

- `just install` followed by `just check` passes in this repo.
- Rust core/gateway tests pass in `../sase-core`.
- Warm daemon reads meet the Epic 5 p95 targets on large synthetic fixtures.
- Every default-enabled surface has direct fallback, parity tests, and recovery documentation.

## Suggested Phase Dependency Graph

1. Phase 5A must land first.
2. Phase 5B depends on 5A and should land before user-facing Python routing.
3. Phases 5C, 5D, 5E, and 5F can proceed independently after 5B if each agent owns a separate surface.
4. Phase 5G depends on agent CLI/facade work from 5D.
5. Phase 5H depends on notification and ChangeSpec facade work from 5C and 5E.
6. Phase 5I integrates and decides default enablement after all migrated surfaces report parity and perf.

## Testing Strategy

- Rust unit tests for every projection query helper and cursor/snapshot handler.
- Local daemon contract snapshot tests for request/response schemas and typed errors.
- Python fake-transport tests for daemon success, unsupported capability, unavailable daemon, degraded projection,
  cursor expiry, snapshot expiry, and direct fallback.
- Golden output tests comparing daemon-backed and direct CLI output.
- ACE provider tests for snapshot load, delta upsert/delete/invalidate, resync-required, selection restore, and lazy
  detail fetch.
- End-to-end daemon tests that rebuild shadow projections, verify parity, then run daemon-routed reads.
- Perf tests using large fixtures: at least 100k agents, 5k ChangeSpecs, large notification stores, and representative
  bead/catalog stores.

## Rollback and Safety

- Every routed command must support `--no-daemon` or `SASE_NO_DAEMON`.
- Daemon read failures must fall back to direct source-store readers unless the user explicitly requested daemon-only
  diagnostics.
- Surface enablement should be capability-gated. A new daemon binary without a surface capability must not change CLI or
  ACE behavior.
- Projection mismatch should keep the surface on direct loaders until `sase daemon verify --surface <surface>` is clean
  or the user opts in to read-through diagnostics.
- Writes remain direct in this epic, so rollback never requires converting daemon events back into source files.
