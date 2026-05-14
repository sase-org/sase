---
legend_bead_id: sase-3e
tier: epic
epic_number: 4
source: sdd/legends/202605/rust_daemon_indexed_projections_1.md
create_time: 2026-05-13 20:56:36
status: wip
prompt: sdd/prompts/202605/rust_daemon_epic4_shadow_indexers.md
---

# Epic 4 Plan - Shadow Indexers and File Watch Ownership

## Source

This plan implements Epic 4, "Shadow Indexers and File Watch Ownership", from
`sdd/legends/202605/rust_daemon_indexed_projections_1.md`.

Epic 4 purpose: make the Rust daemon observe existing SASE source files and maintain indexed projections without
changing CLI, ACE, editor, mobile, or workflow behavior. The daemon should index in shadow mode first, compare against
existing loaders, report differences, and recover from missed watcher events through reconciliation.

## Current State

- `../sase-core/crates/sase_core/src/projections/` already exists with event envelopes, SQLite/WAL migrations,
  projection tables, rebuild/replay, and domain appliers for ChangeSpecs, notifications, agents, beads, workflows, and
  catalogs.
- `../sase-core/crates/sase_gateway` already has daemon mode, host-local ownership, a projection service, local framed
  JSON RPC, heartbeat/event scaffolding, metrics, and a storage-reset rebuild path.
- The local daemon list/read API is still mostly mocked. Epic 5 owns production read migration, so Epic 4 should expose
  only diagnostics, shadow status, rebuild, and diff surfaces needed to prove indexing correctness.
- `ProjectionService::append_event` currently appends raw events only. Domain watcher writes must use projection-aware
  append paths or add a dispatch layer so event append and projection update remain in one transaction.
- Existing source-of-truth loaders remain available:
  - ChangeSpecs: Python facade around Rust parser via `src/sase/ace/changespec/parser.py` and `sase_core::parser`.
  - Notifications: Rust-backed JSONL store via `src/sase/notifications/store.py` and `sase_core::notifications`.
  - Agents/artifacts: Rust scanner and one-off artifact index via `src/sase/core/agent_scan_facade.py` and
    `sase_core::agent_scan`.
  - Beads: Rust-backed read/mutation facades via `src/sase/core/bead_read_facade.py`,
    `src/sase/core/bead_mutation_facade.py`, and `sase_core::bead`.
  - Xprompt/catalog helpers: `sase_core::xprompt_catalog` plus Python config/workflow loaders.

## Goals

- Add daemon-owned file watching and indexing services for existing SASE source files.
- Backfill projections from current source files and keep them current through debounced incremental updates.
- Keep indexing shadow-only: no production CLI/TUI/editor path should require daemon projections yet.
- Provide deterministic diff tooling that compares projected rows to existing loaders and reports missing, stale, extra,
  and corrupt rows with actionable source paths.
- Provide rebuild and verify commands for all sources, one project, or one surface.
- Recover from watcher loss, reordering, file rewrites, and bursty marker writes through periodic reconciliation.

## Non-Goals

- Do not route ACE, CLI, editor, mobile, or bead read commands to daemon projections. That is Epic 5.
- Do not make the daemon authoritative for writes.
- Do not remove `.sase`, legacy `.gp`, notification JSONL, pending-action files, bead JSONL/config/cache inputs,
  artifact marker files, xprompts, memory files, or file-history stores.
- Do not add runtime-specific assumptions about Claude/Gemini/Codex/Qwen/opencode behavior.
- Do not duplicate existing parser, notification, bead, xprompt, or agent-scan semantics when a Rust core helper already
  owns them.

## Architecture

- Put shared source discovery, indexing, event construction, fingerprints, and diff logic in
  `../sase-core/crates/sase_core` when it is backend/domain behavior.
- Put daemon runtime ownership of watchers, debounce queues, reconciliation scheduling, local RPC exposure, metrics, and
  lifecycle integration in `../sase-core/crates/sase_gateway`.
- Keep Python changes limited to thin comparison/CLI adapters where existing Python behavior is the current contract or
  where `sase daemon ...` needs to call the local daemon.
- Use the `notify` crate in `sase_gateway` for file watching. Keep watcher callbacks minimal: enqueue normalized source
  changes and let blocking workers perform parsing, scanning, SQLite writes, and diff generation.
- Represent every indexed source with a stable `SourceIdentity` containing domain, project id when known, source path,
  archive flag when relevant, stat fingerprint, content hash when needed, and last indexed event sequence.
- Use deterministic idempotency keys derived from domain, normalized path, content/stat fingerprint, and operation kind
  so duplicate watcher events do not create duplicate logical events.
- Publish local daemon delta events only for indexing state and diagnostics in this epic. User-facing data deltas for
  ACE lists remain Epic 5.

## Phase 4A - Indexer Runtime Foundation

Owner: one agent.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/`
- `../sase-core/crates/sase_gateway/src/`
- `../sase-core/crates/sase_gateway/Cargo.toml`
- focused Rust tests in `../sase-core`

Deliverables:

- Add shared indexing types in `sase_core`:
  - source identity and fingerprint records;
  - normalized source change operations: upsert, delete, rewrite, reconcile;
  - per-domain indexing report records;
  - shadow diff records with missing/stale/extra/corrupt categories and source paths.
- Add a projection-aware append dispatcher to `ProjectionService` so a domain event updates the matching projection in
  the same SQLite transaction. Avoid using raw `append_event` for watcher-generated domain events unless a
  rebuild/replay immediately applies them.
- Add a daemon indexing service shell:
  - lifecycle start/stop tied to daemon runtime;
  - bounded debounce queue;
  - bounded blocking worker boundary;
  - metrics for queued changes, dropped/coalesced changes, indexed sources, failed parses, and diff counts;
  - local event publication for indexing progress and resync-required diagnostics.
- Add `notify` as a daemon dependency and wrap it behind a small trait so tests can inject synthetic changes without
  relying on platform-specific watcher behavior.
- Add local daemon capabilities for shadow indexing diagnostics, but keep production list/read APIs unchanged.

Acceptance gates:

- `cargo test -p sase_gateway indexer` and `cargo test -p sase_core projections` pass.
- A synthetic source change can be enqueued, debounced, handled on a blocking worker, and reported through daemon health
  or diagnostics without starting a real filesystem watcher.
- Projection-aware event append proves event row, domain projection rows, and projection metadata update atomically.
- Daemon still starts without indexing enabled if watcher initialization fails, and reports degraded indexing status
  instead of breaking health/RPC.

## Phase 4B - ChangeSpec Source Discovery, Backfill, Watch, and Diff

Owner: one agent after Phase 4A.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/changespec.rs`
- new `sase_core` indexing/diff helpers for ChangeSpecs
- `../sase-core/crates/sase_gateway/src/` watcher integration
- optional thin Python diff adapter/tests in this repo

Deliverables:

- Discover active and archive project spec files under `~/.sase/projects/<project>/`, including canonical `.sase` and
  legacy `.gp` files.
- Backfill ChangeSpec projections by reading each source file once, using existing Rust parser behavior, and emitting
  source-file observed/reparsed or snapshot events with stable idempotency keys.
- Watch active/archive project spec files and their parent project directories for create, modify, rename, and delete
  events.
- Debounce file rewrites and reparse only the affected project file. Patch affected ChangeSpec rows through existing
  projection events; do not hydrate unrelated projects.
- Tombstone rows when a source file disappears or a spec is removed from a rewritten file.
- Add a shadow diff that compares projected summaries/details to the current parser output and reports source path,
  ChangeSpec name, handle, and mismatch reason.

Acceptance gates:

- Backfill and diff pass on representative `.sase` and legacy `.gp` fixtures, including archive files.
- Rewriting one project file updates only that project file's affected ChangeSpec rows.
- Deleting or renaming active/archive files removes or moves projected rows deterministically.
- Diff output is stable enough for snapshot tests and does not expose large raw file contents.

## Phase 4C - Notification and Pending Action Indexing

Owner: one agent after Phase 4A. This can run in parallel with Phase 4B if both agents keep their domain write scopes
separate.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/notifications.rs`
- `../sase-core/crates/sase_core/src/notifications/`
- `../sase-core/crates/sase_gateway/src/` watcher integration
- optional Python CLI/status adapter tests in this repo

Deliverables:

- Discover and watch `~/.sase/notifications/notifications.jsonl` and pending-action store files.
- Backfill notification projections from the current JSONL snapshot and pending-action store.
- Handle append-heavy changes cheaply when stat information indicates an append; fall back to full rewrite comparison
  when the file shrinks, inode changes, or JSONL ordering changes.
- Emit notification append, rewrite, state-update-equivalent, pending-action register/update/cleanup/store-rewrite
  events using existing Rust store wire records.
- Diff projected notification snapshots and pending-action rows against existing Rust-backed store loaders, including
  include-dismissed behavior and count facets.
- Ensure invalid JSONL lines remain soft errors consistent with current notification loading behavior.

Acceptance gates:

- Appending one notification does not require reparsing unrelated daemon surfaces.
- Rewriting notifications after mark-read/dismiss/mute/snooze converges to existing store output.
- Pending action stale/missing/extra rows are reported separately from notification row mismatches.
- Notification diff tests cover append, rewrite, invalid line, dismissed/read state, and pending-action cleanup.

## Phase 4D - Agent, Artifact, Archive, and Dismissal Indexing

Owner: one agent after Phase 4A. Prefer starting after either Phase 4B or 4C has established the shared diff report
format.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/agents.rs`
- `../sase-core/crates/sase_core/src/agent_scan/`
- `../sase-core/crates/sase_core/src/agent_archive/`
- `../sase-core/crates/sase_gateway/src/` watcher integration
- Python parity tests may be updated, but production ACE loaders stay direct

Deliverables:

- Discover and watch project artifact trees under `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/`.
- Watch marker files used by the existing scanner: `done.json`, `agent_meta.json`, `running.json`, `waiting.json`,
  `pending_question.json`, `workflow_state.json`, `prompt_step_*.json`, `plan_path.json`, and `raw_xprompt.md`.
- Reparse and update one affected artifact directory on marker writes, creates, deletes, or renames.
- Backfill agent projections using existing `sase_core::agent_scan` output and projection event constructors.
- Index archive bundles and dismissed identities using existing `agent_archive` behavior; keep the existing one-off
  `agent_artifact_index.sqlite` untouched unless needed only for comparison.
- Add a shadow diff against `scan_agent_artifacts` and archive/dismissed loaders, with mismatch reports keyed by
  artifact directory or archive bundle path.

Acceptance gates:

- Updating one marker file changes one projected agent/artifact row and does not rescan full history.
- Full backfill projection rows match current scanner output on existing agent scan parity fixtures.
- Archive bundle revive/purge and dismissed identity changes converge after reconciliation.
- Corrupt marker JSON is counted and reported consistently with current scanner stats.

## Phase 4E - Bead Indexing

Owner: one agent after Phase 4A. This can run in parallel with Phase 4D if migration/event changes are coordinated
through existing bead projection APIs.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/beads.rs`
- `../sase-core/crates/sase_core/src/bead/`
- `../sase-core/crates/sase_gateway/src/` watcher integration
- optional Python `sase daemon verify` adapter tests

Deliverables:

- Discover bead stores in VC-backed `sdd/beads/` and non-VC `.sase/sdd/beads/` layouts using the same project-context
  rules as the current bead fast path where practical.
- Watch bead JSONL/config files and any SQLite/cache inputs that current bead commands depend on.
- Backfill bead projections from existing bead read/storage APIs.
- Emit snapshot/rewrite events when JSONL or cache inputs change, and specific mutation events only when the source
  change can be classified without guessing.
- Diff projected bead list/show/ready/blocked/stats/dependency results against existing Rust-backed bead read helpers.
- Preserve current JSONL/SQLite sync behavior; this phase observes it, it does not replace it.

Acceptance gates:

- Bead projection diff matches existing bead read/storage parity fixtures.
- Dependency, ready-to-work, closed/reopened, removed, and plan hierarchy rows converge after source rewrites.
- VC and non-VC bead stores are discovered without changing the selected write store for normal `sase bead` commands.
- Corrupt or partially written bead inputs produce soft indexing errors and recover on the next valid write.

## Phase 4F - Workflow, Xprompt, Config, Memory, Artifact Index, and File-History Catalogs

Owner: one agent after Phase 4A and preferably after Phase 4D, because workflow catalog and agent artifact state
overlap.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/workflows.rs`
- `../sase-core/crates/sase_core/src/projections/catalogs.rs`
- `../sase-core/crates/sase_core/src/xprompt_catalog.rs`
- `../sase-core/crates/sase_gateway/src/` watcher integration
- thin Python comparison adapters only where existing catalog behavior is Python-owned

Deliverables:

- Discover and watch:
  - project, user, and packaged xprompt/workflow sources;
  - config files and plugin-provided xprompt catalog inputs;
  - memory catalogs and generated `.sase/memory/` files;
  - explicit artifact index files;
  - file-history stores used by editor/helper commands.
- Backfill catalog/workflow projections from existing loaders.
- Use snapshot replacement events for catalogs where source identity is naturally file-based and the full catalog is
  cheap enough to recompute for one changed source.
- Diff projected xprompt/config/memory/file-history rows against existing helper/catalog loaders with stable source-path
  mismatch reports.
- Keep generated skill/memory files read-only unless a later approved epic explicitly changes their generation pipeline.

Acceptance gates:

- Adding, modifying, or deleting one xprompt/workflow source updates catalog projection rows for that source.
- Config/plugin catalog changes trigger bounded catalog rebuilds and clear resync diagnostics when plugin inputs are not
  directly watchable.
- File-history projection diff can identify missing/stale/extra entries without routing editor helpers through the
  daemon.
- Workflow projection rows remain consistent with agent artifact workflow markers indexed in Phase 4D.

## Phase 4G - Rebuild, Verify, and Shadow Diff Commands

Owner: one agent after Phases 4B through 4F have at least their backfill and diff APIs.

Primary write scope:

- `../sase-core/crates/sase_gateway/src/local_transport.rs`
- `../sase-core/crates/sase_gateway/src/wire.rs`
- `../sase-core/crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json`
- `src/sase/integrations/daemon_lifecycle.py`
- `src/sase/main/parser_daemon.py`
- `src/sase/main/daemon_handler.py`
- tests in both repos

Deliverables:

- Extend local daemon RPC for:
  - `indexing.status`;
  - `indexing.rebuild` with all/project/surface selectors;
  - `indexing.verify` with all/project/surface selectors;
  - `indexing.diff` returning bounded shadow diff pages.
- Update `sase daemon rebuild` so it can request source backfill, not only storage-reset replay, while preserving the
  current reset-only path as an explicit recovery mode.
- Add `sase daemon doctor` and JSON output fields for watcher health, last reconciliation, last indexed seq per surface,
  queued changes, and diff summaries.
- Add Python client/adapters that call local RPC and fall back to clear "daemon unavailable" messages. Do not import
  Textual or heavy ACE modules.
- Regenerate local daemon contract snapshots only when wire shapes change intentionally.

Acceptance gates:

- `sase daemon rebuild --surface changespecs|notifications|agents|beads|catalogs|all` works against a live daemon.
- `sase daemon doctor --json` includes compact indexing health and diff summaries.
- Local RPC responses are page/bound limited and reject oversized diff payloads.
- Existing mobile gateway contract tests and daemon lifecycle tests still pass.

## Phase 4H - Reconciliation, Throttling, and Large-History Soak

Owner: one agent after Phases 4B through 4G.

Primary write scope:

- `../sase-core/crates/sase_gateway/src/` indexing service
- `../sase-core/crates/sase_core/src/projections/maintenance.rs`
- integration/soak fixtures in `../sase-core`
- focused Python smoke tests where daemon CLI behavior is involved

Deliverables:

- Add periodic reconciliation for all indexed surfaces:
  - scan known roots for source identities;
  - detect missed creates/deletes/renames;
  - requeue stale sources by fingerprint;
  - publish resync-required diagnostics when bounded reconciliation cannot prove convergence.
- Add throttling policies:
  - debounce bursts per source path;
  - cap concurrent blocking indexing tasks;
  - coalesce repeated writes while preserving final state;
  - avoid starving small updates behind full rebuilds.
- Add large-history fixtures or synthetic generators for ChangeSpecs, notifications, agents/artifacts, beads, and
  catalogs.
- Add soak tests that simulate watcher loss/reordering, file rewrite bursts, partial writes followed by valid writes,
  and daemon restart during queued indexing.
- Add performance assertions for steady-state updates: no full history hydration after initial backfill for ordinary
  file changes.

Acceptance gates:

- Shadow indexes converge on large representative histories after backfill, restart, and missed watcher events.
- Ordinary single-file changes are handled with bounded source reads and no full-history hydration.
- Reconciliation repairs watcher loss or reordering and reports any unrecoverable gaps with source paths and guidance.
- Daemon remains responsive to health/status RPCs during indexing bursts.

## Phase 4I - Final Integration and Documentation

Owner: one agent after Phase 4H.

Primary write scope:

- `sdd/` docs or tale notes as appropriate
- `../sase-core/crates/sase_gateway/README.md`
- small cleanup in touched Rust/Python modules only

Deliverables:

- Document shadow-indexing behavior, supported surfaces, source-of-truth policy, rebuild/verify commands, and fallback
  expectations.
- Add a concise operational playbook for:
  - daemon indexing degraded;
  - projection/source mismatch;
  - stale watcher roots;
  - corrupt projection database;
  - large rebuild in progress.
- Review all Epic 4 local daemon capabilities and ensure they are diagnostic-only, not hidden production read routing.
- Remove temporary test-only toggles or debug logs that are no longer needed.
- Produce an Epic 5 handoff note listing which indexed read surfaces are ready, which diff gaps remain, and which API
  shapes still need pagination/detail work.

Acceptance gates:

- A new agent can start from the docs and run rebuild/verify/doctor locally.
- All Epic 4 acceptance gates from the legend are covered by tests or documented manual verification.
- No user-visible behavior has changed except new `sase daemon` diagnostics and rebuild/verify commands.

## Dependency Summary

- Phase 4A is the foundation and must land first.
- Phases 4B and 4C can run in parallel after 4A.
- Phases 4D and 4E can run in parallel after 4A, but should reuse the diff/report conventions established by 4B or 4C if
  those are already merged.
- Phase 4F should start after 4A and preferably after 4D.
- Phase 4G depends on the domain backfill/diff APIs from 4B through 4F.
- Phase 4H depends on 4G and the domain watchers.
- Phase 4I is the final documentation and handoff pass.

## Verification Strategy

- Rust unit tests for source identity, fingerprinting, idempotency keys, projection-aware append, domain backfill, and
  diff algorithms.
- Rust daemon tests with synthetic watcher events through the watcher trait.
- Contract tests for any local daemon RPC changes.
- Existing parity tests for ChangeSpec parser, notification store, agent scan, bead read/storage, and query helpers.
- Python tests only for thin daemon CLI/client behavior and comparison adapters.
- Before each phase finishes, run the relevant `cargo test -p sase_core ...` and/or `cargo test -p sase_gateway ...`
  commands plus the Python tests touched by that phase. Agents working in this repo should run `just install` before
  repo-level checks, then `just check` when they make repo changes.
