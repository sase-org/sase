---
create_time: 2026-05-04 12:57:15
bead_id: sase-20
tier: epic
status: done
prompt: sdd/prompts/202605/agent_artifact_startup_perf.md
---
# `sase ace` Agent Artifact Startup Performance Plan

## Background

The prior research in `sdd/research/202605/agent_artifact_loading_startup.md` shows that slow `sase ace` startup scales
with historical agent artifacts, especially dismissed bundles. On the measured workstation:

- `load_dismissed_agents()` is cheap at about 0.03s because it reads only the compact identity index.
- `load_all_agents()` costs about 1.4s because it scans and hydrates the artifact tree.
- Uncached `load_dismissed_bundles()` costs about 1.7s because it reads and hydrates thousands of bundle JSON files.
- `load_agents_from_disk()` costs about 3.0s because it combines visible agents, retry/attempt metadata, and every
  dismissed bundle.

The important product constraint is that old history must remain fully functional: dismissed agents must be revivable,
run logs must include dismissed rows, workflow parent/child links and retry chains must remain intact, and old artifacts
must continue to participate in name collision avoidance and search/history flows. The artifact tree and bundle files
remain the source of truth; any index introduced by this plan is a rebuildable cache/materialized view.

## Goals

- Make initial `sase ace` interactivity independent of dismissed-bundle archive size.
- Preserve revive, run-log, workflow child display, retry-chain linkage, search/group/filter behavior, and historical
  name collision avoidance.
- Make archive/history workflows fast enough that deferred loading does not simply move the same stall to the first
  revive or run-log action.
- Keep indexes crash-safe, multi-process safe, schema-versioned, and rebuildable.
- Respect the Rust core boundary: shared scanner/index semantics belong in `../sase-core`; Python TUI code should use
  thin adapters.

## Non-goals

- Deleting, pruning, or capping agent history as the primary fix.
- Replacing the existing `Agent` model or Textual UI structure.
- Solving unrelated startup costs such as config YAML parsing, prompt-panel Rich rendering, or parser/import startup.
- Making SQLite rows the source of truth.

## Product Contract

After this plan lands, startup has explicit loading tiers:

- **Tier 0:** first paint and ChangeSpec list.
- **Tier 1:** active agents and visible completed agents needed for the initial Agents tab.
- **Tier 2:** full visible history, loaded from the artifact index or a background reconciliation scan.
- **Tier 3:** dismissed archive summaries for revive/history, with full bundles hydrated only when selected or restored.

The UI may honestly indicate that archive/history data is loading, but it must not present incomplete data as complete.
Actions that need older or dismissed data should trigger the relevant tier and then continue with the same behavior
users have today.

## Invariants To Preserve

- `dismissed_agents.json` continues to hide dismissed visible rows immediately on startup.
- Same-session dismissal and revive continue to work without waiting for persistent index rebuilds.
- Revive can restore parent agents and workflow children, including `{raw_suffix}__c{step_index}.json` child bundles.
- The run-log modal can show active and dismissed agents for a ChangeSpec, including agents that created the CL/PR via
  `meta_new_cl` or `meta_new_pr`.
- Retry-chain fields keep both forward and backward edges: `retry_of_timestamp`, `retried_as_timestamp`,
  `retry_chain_root_timestamp`, and `retry_attempt`.
- Legacy top-level dismissed bundles and one-time bundle migrations remain supported.
- Corrupt or unreadable individual markers/bundles are skipped without poisoning the whole load.
- Running agents are never hidden or deleted just because they share a raw suffix with a dismissed completed marker.
- Index absence, staleness, or corruption falls back to source-of-truth scans and offers a rebuild path.

## Dependency Graph

```text
Phase 1: Baseline and tests
    └── Phase 2: Lazy dismissed archive startup
            ├── Phase 3: Dismissed bundle summary index
            │       └── Phase 5: Tiered startup integration
            └── Phase 4: Artifact summary index in Rust core
                    ├── Phase 5: Tiered startup integration
                    └── Phase 6: Bounded scanner fallback

Phase 7: Hardening, maintenance commands, and perf sentinels
    depends on Phases 2-6
```

Phases 3 and 4 can run in parallel after Phase 2 because they have different primary write scopes. Phase 6 can also run
in parallel with parts of Phase 5 if the option-wire changes are coordinated.

## Phase 1 - Baseline, Contracts, and Regression Fixtures

**Goal:** give later agents objective pass/fail checks before changing behavior.

### Scope

- Add focused tests around the current startup contract:
  - `load_agents_from_disk()` hides dismissed identities using only `dismissed_agents.json`.
  - dismissed loader rows exclude `RUNNING` agents that share a raw suffix.
  - revive grouping understands parent/child relationships and `__c{idx}` bundle filenames.
  - run-log CL matching includes active rows, dismissed rows, and `meta_new_cl` / `meta_new_pr` creators.
- Add synthetic fixture builders for:
  - 10k dismissed bundle files across `YYYYMM` shards plus legacy root files;
  - workflow parent + child bundle collisions;
  - retry-chain marker edges;
  - corrupt bundle files.
- Add lightweight perf sentinels that can be run in normal test mode without depending on a specific workstation:
  - startup loader test asserts it does not call `load_dismissed_bundles()` once Phase 2 lands;
  - targeted bundle load test asserts suffix filtering does not hydrate unrelated parent bundles.
- Record an optional manual benchmark recipe in `sdd/research/202605/` or `tests/perf/README.md` for measuring
  cold-process `load_agents_from_disk()`, run-log open, revive modal open, and index rebuild time.

### Files

- `tests/sase/ace/tui/actions/agents/`
- `tests/sase/ace/tui/modals/`
- `tests/sase/ace/dismissed_agents/` or equivalent existing test layout
- Optional docs under `sdd/research/202605/`

### Acceptance

- Tests fail against the known risky behaviors and pass against the current baseline where appropriate.
- Later phases can add stricter assertions without rewriting the fixture builders.
- No product behavior changes in this phase.

## Phase 2 - Remove Full Dismissed-Bundle Hydration From Startup

**Goal:** deliver the immediate startup win by making the initial Agents refresh use the compact dismissed identity
index only.

### Scope

- In `src/sase/ace/tui/actions/agents/_loading_helpers.py`, remove the unconditional
  `snapshot_cache.dismissed_bundles()` call from `load_agents_from_disk()`.
- Keep `_dismissed_agent_objects` populated with dismissed agents that were already returned by `load_all_agents()` and
  with same-session dismissals appended by existing dismissal paths.
- Introduce an archive-loading path for revive:
  - `R` on the Agents tab should load dismissed bundles on demand, off the UI thread.
  - The project/scope selector can open immediately, but the dismissed agent selection list should show a loading or
    disabled state until the archive data for that scope is ready.
  - Preserve same-session revives even before the archive load completes.
- Move self-healing of orphan dismissed identities off the startup path:
  - `compute_loader_cleanup()` should no longer call `has_dismissed_bundle()` for every missing suffix during startup.
  - Run equivalent repair during archive open or a debounced background maintenance task.
  - Keep stale loader-sourced artifact cleanup, but only for loader-sourced dismissed rows already known without full
    bundle hydration.
- Optimize `AgentRunLogModal._load_agents_for_cl()`:
  - derive candidate dismissed suffixes for the requested CL before loading bundles;
  - call `load_dismissed_bundles(suffixes=...)`;
  - if meta-created CL matching cannot be answered from identities alone, either load a targeted superset by suffix or
    defer the exact meta match to Phase 3's summary index.
- Make bundle migration/fixup no longer depend on startup calling `load_dismissed_bundles()`; trigger it on first
  archive open or via a tiny idempotent maintenance gate.

### Files

- `src/sase/ace/tui/actions/agents/_loading_helpers.py`
- `src/sase/ace/tui/actions/agents/_loading_compute.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/tui/modals/agent_run_log_modal.py`
- `src/sase/ace/dismissed_agents.py`
- Tests from Phase 1

### Acceptance

- Cold startup no longer hydrates every dismissed bundle.
- Hiding dismissed visible agents still works from `dismissed_agents.json`.
- Same-session revive still works.
- Revive of old dismissed agents still works after the on-demand archive load.
- Run-log for one CL does not scan every bundle file when suffixes are known.
- `just check` passes in `sase_100`.

## Phase 3 - Persistent Dismissed Bundle Summary Index

**Goal:** make revive/history queries fast at large archive sizes without hydrating every bundle.

### Scope

- Add a rebuildable SQLite index under `~/.sase/dismissed_bundles/index.sqlite` or a shared Sase index directory.
- Store one row per dismissed bundle file with the fields needed to render revive/run-log option lists:
  - raw suffix, bundle path or shard+filename, agent type, CL name, agent name, status, start/finish times;
  - project file, model/provider fields, workflow-child flag, parent timestamp, step index/name;
  - retry-chain fields and meta output keys needed for CL/PR matching.
- Add indexed query APIs:
  - by raw suffix set, including parent + `__c*` child siblings;
  - by CL name or project/scope;
  - by bundle identity for removal/revive;
  - latest/top-level rows for option lists.
- Hook write paths:
  - `save_dismissed_bundle()` inserts/updates one summary row;
  - `remove_bundle_by_identity()` deletes parent and child rows;
  - dismissed identity saves keep identity/index consistency where needed.
- Prefer implementing durable writes and row updates in `../sase-core` behind Python wrappers because bundle writes
  already cross the Rust cleanup boundary and multiple `sase` processes can write concurrently.
- Use WAL mode, schema version metadata, additive migrations, and `BEGIN IMMEDIATE` or equivalent write transactions.
- Add `sase agents archive rebuild-index` and `sase agents archive verify` commands.
- Treat corrupt bundle files as skipped rows with diagnostics; never break startup or archive open because one row is
  bad.

### Files

- `../sase-core/crates/sase_core/` and `../sase-core/crates/sase_core_py/`
- `src/sase/core/agent_cleanup_execution.py`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/main/` and relevant CLI command modules
- Revive/run-log callers from Phase 2
- Tests in both `sase-core` and `sase_100`

### Acceptance

- Rebuild creates correct rows for sharded and legacy bundle layouts.
- Save/remove/revive operations update both files and index rows.
- Revive and run-log option lists query summaries first and hydrate full bundles only for selected/restored agents or
  exact data that is not in the summary.
- Two concurrent dismissals both appear in the index and do not corrupt `dismissed_agents.json`.
- Deleting the index causes a rebuild or source-scan fallback without data loss.

## Phase 4 - Persistent Agent Artifact Summary Index in Rust Core

**Goal:** stop cold TUI startup from walking and hydrating the entire historical artifact tree.

### Scope

- Design a Rust-owned SQLite materialized view for `~/.sase/projects` artifact summaries.
- Store one row per artifact directory, keyed by artifact dir path, with marker file signatures and the fields needed
  for the initial Agents list:
  - project/workflow/timestamp/artifact dir paths;
  - status, agent type, CL name, agent name, model/provider, start/finish times;
  - running/waiting/done/workflow-state flags;
  - parent timestamp, step index/name, workflow child metadata;
  - retry-chain edges;
  - compact JSON blob for less common marker fields needed by existing loader conversions.
- Add Rust core APIs for:
  - full rebuild from source artifacts;
  - upsert one artifact dir from current marker files;
  - delete one artifact dir row;
  - query active/incomplete agents;
  - query recent completed visible agents;
  - query full visible history for background completion.
- Hook write/update sites where practical:
  - launch writes `agent_meta.json` and inserts a row;
  - done marker writes update the row;
  - kill/dismiss/delete removes or marks rows;
  - revive restoration recreates rows;
  - `ArtifactWatcher` events queue incremental upserts/deletes for directories changed while ACE is open.
- Keep the current `scan_agent_artifacts()` facade as the source-scan fallback and parity reference.
- Add `sase agents index rebuild` and diagnostics for stale/missing/corrupt index states.

### Files

- `../sase-core/crates/sase_core/src/agent_scan/` or a sibling index module
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/agent_scan_facade.py` or new Python adapter
- agent launch/done/dismiss/revive/delete call sites in `src/sase/`
- `src/sase/ace/tui/util/fs_watcher.py`
- Rust and Python tests

### Acceptance

- A fresh rebuild produces loader-equivalent summaries for representative artifacts.
- Startup can query active/recent rows without walking all historical timestamp dirs.
- Incremental updates handle `IN_CREATE`, `IN_CLOSE_WRITE`, and `IN_DELETE` on marker files.
- If an axe process writes `done.json` while ACE is querying, readers see a valid snapshot and the next refresh sees the
  completed row.
- The artifact tree remains canonical; deleting the index and rebuilding restores behavior.

## Phase 5 - Tiered Startup Integration

**Goal:** wire the dismissed and artifact indexes into the TUI so startup is fast while history remains complete.

### Scope

- Replace the startup `load_all_agents()` path with an index-backed tiered loader:
  - read `dismissed_agents.json`;
  - query active/incomplete rows and a recent visible completed window;
  - render immediately;
  - start background full-history reconciliation;
  - make search/history actions trigger full index queries when needed.
- Keep an explicit `AgentLoadState` or equivalent so the UI can distinguish partial initial data from complete history.
- Preserve existing grouping/filter/search semantics once Tier 2 completes.
- Teach revive and run-log flows to use dismissed summary index queries from Phase 3.
- On index miss/corruption, fall back to bounded/source scans and schedule rebuild without blocking first paint longer
  than today's behavior.
- Ensure name collision avoidance can query historical names from artifact and dismissed summary indexes without loading
  all full `Agent` objects.

### Files

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/actions/agents/_loading.py`
- `src/sase/ace/tui/actions/agents/_loading_helpers.py`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- `src/sase/ace/tui/actions/agents/_display.py`
- `src/sase/ace/tui/modals/agent_run_log_modal.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- Index adapters from Phases 3 and 4

### Acceptance

- Cold startup cost is bounded by active/recent rows, not total historical artifact or bundle count.
- Searching after full-history load returns the same results as the previous full scan path.
- Run-log and revive display complete dismissed history after their targeted loads complete.
- Startup UI state does not imply full history is loaded until it is.
- Existing tests for fold state, grouping, filtering, retry chains, and workflow children still pass.

## Phase 6 - Bounded Scanner Fallback

**Goal:** make fallback/rebuild paths faster and safer when indexes are absent or rebuilding.

### Scope

- Extend `AgentArtifactScanOptionsWire` in Python and Rust with bounded/query options such as:
  - `max_records`;
  - `newest_first`;
  - `not_before_timestamp`;
  - `include_done_markers`;
  - `include_workflow_state`;
  - `include_waiting`;
  - `only_projects`.
- Keep deterministic full-scan behavior as the default so existing parity tests remain stable.
- Implement newest-first bounded traversal in Rust for startup fallback and reconciliation seed queries.
- Update Python wire conversion and facade wrappers.
- Add tests that compare bounded results to filtered full-scan results on synthetic trees, including old running agents
  and workflow directories.

### Files

- `src/sase/core/agent_scan_wire.py`
- `src/sase/core/agent_scan_facade.py`
- `../sase-core/crates/sase_core/src/agent_scan/wire.rs`
- `../sase-core/crates/sase_core/src/agent_scan/scanner.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- Rust parity tests and Python facade tests

### Acceptance

- Default scan output remains parity-compatible.
- Bounded scans can return newest visible rows quickly without losing old running/waiting agents.
- Tiered startup has a reasonable fallback when the artifact index is missing or disabled.

## Phase 7 - Hardening, Maintenance, and Performance Sentinels

**Goal:** make the new architecture durable enough for long-lived machines and future schema changes.

### Scope

- Consolidate archive/index maintenance commands:
  - `sase agents archive verify`;
  - `sase agents archive rebuild-index`;
  - `sase agents index verify`;
  - `sase agents index rebuild`.
- Add startup-safe version gates and one-shot migration sentinels for:
  - legacy monolithic dismissed bundles;
  - pre-shard root bundle files;
  - child bundle collision fixes;
  - index schema upgrades.
- Add concurrency tests around multiple processes writing bundles and marker files.
- Add perf regression fixtures:
  - synthetic 10k dismissed bundles;
  - synthetic 10k artifact dirs;
  - mixed running/done/workflow/retry corpus.
- Document operational behavior:
  - indexes are disposable;
  - rebuild commands are safe;
  - history pruning/compaction is optional and not required for startup.
- Consider optional archive compaction only after index correctness is proven. Compaction should reduce storage/inode
  pressure, not preserve acceptable startup.

### Files

- CLI command modules under `src/sase/main/` and/or `src/sase/agent/`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/core/*index*` adapters
- `../sase-core` index modules
- `tests/perf/` or focused regression tests
- SDD documentation

### Acceptance

- Index verification and rebuild commands are idempotent.
- Perf sentinels prove startup does not scale with dismissed-bundle count after Phase 2/3, and does not scale with total
  artifact count after Phase 4/5.
- A single corrupt bundle or marker does not break startup, revive, run-log, or rebuild.
- `just check` passes in `sase_100`; relevant `cargo test` suites pass in `../sase-core`.

## Implementation Notes

- Avoid solving this by silently capping history. Caps are only acceptable as a clearly marked partial Tier 1 result
  backed by on-demand full-history queries.
- Keep lazy loading honest. A modal can show loading state, but it should not show an incomplete revive/run-log list as
  complete.
- Prefer SQLite over JSONL for persistent indexes because revive/delete/update operations need row-level updates,
  secondary indexes, and multi-process safety.
- Be careful with `dismissed_agents.json`: current Python fallback writes are not locked. If index work touches this
  path, move durability into the Rust helper rather than adding another ad hoc Python writer.
- Do not let `_maybe_migrate_bundles()` and `_maybe_fix_child_collisions()` disappear when startup stops calling
  `load_dismissed_bundles()`. They need an explicit archive maintenance trigger.
- Keep `AgentSnapshotCache` only for intra-session volatile file reads after persistent indexes land; it should not be
  the only protection against cold startup archive size.
