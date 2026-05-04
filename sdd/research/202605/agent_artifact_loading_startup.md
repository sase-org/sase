# `sase ace` Startup: Reducing Agent Artifact Loading Cost

## Context

The current `sase ace` startup problem is scale-sensitive: machines with years of Sase agent history pay much more
startup cost than fresh machines. The earlier profile in
`sdd/research/202605/ace_startup_profile_20260502.md` identified the main wall-clock bucket as the post-first-paint
agent load, especially full artifact scans plus dismissed bundle hydration.

This note looks specifically at ways to reduce that cost without sacrificing functionality. The key constraint is that
old agent history is still useful: users can revive dismissed agents, inspect run logs, search and group agents, see
workflow children, and recover metadata from historical artifacts. The fix should avoid making those workflows worse.

## Current Findings

On this workstation at research time:

| Corpus | Count / size |
| --- | ---: |
| `~/.sase/projects` artifact timestamp directories | 8,157 |
| marker JSON files under `~/.sase/projects` | 17,724 |
| `~/.sase/dismissed_bundles/**/*.json` | 8,947 |
| `~/.sase/projects` size | 411 MB |
| `~/.sase/dismissed_bundles` size | 41 MB |
| `~/.sase/dismissed_agents.json` size | 560 KB |

Targeted warm-cache probes in this workspace:

| Operation | Time | Notes |
| --- | ---: | --- |
| `load_dismissed_agents()` | 0.031s | Reads the compact dismissed identity index. |
| `_scan_artifacts_for_loader()` | 1.153s | Rust tree walk plus Python wire hydration for the TUI scan options. |
| `load_all_agents()` | 1.422s | Artifact scan, ChangeSpec sources, Python `Agent` hydration, dedupe, status overrides, sort. |
| `load_dismissed_bundles()` uncached | 1.690s | Reads and hydrates all 8,947 dismissed bundle JSON files. |
| `load_agents_from_disk()` | 3.001s | Combines visible agents, tags/retry/attempt metadata, and all dismissed bundles. |
| `AgentSnapshotCache.dismissed_bundles()` warm | 0.037s | Still walks/stats every bundle path, but skips JSON parse when signatures match. |

The biggest avoidable startup cost is not the compact dismissed index. It is hydrating every dismissed bundle into an
`Agent` object even though the initial Agents tab only needs active and non-dismissed visible rows. Full dismissed
objects are needed for revive and some history views, but not for first usable startup.

## Current Loading Shape

`src/sase/ace/tui/actions/agents/_loading_helpers.py::load_agents_from_disk()` (entry at line 75) currently:

1. Calls `load_all_agents()` (line 104).
2. Loads tags, attempt history, and retry state for each visible agent (lines 108–134) via `AgentSnapshotCache`.
3. Builds a `dismissed_suffixes` set from `dismissed_agents.json` (lines 139–141).
4. Identifies `dismissed_from_loader` — agents the scanner already returned that match a dismissed identity (lines
   147–155).
5. Calls `snapshot_cache.dismissed_bundles()` with **no suffix filter** (line 167), supplements the loader rows with
   bundle-only ones, and dedupes by suffix (lines 163–177).
6. Returns `(all_agents, dismissed_from_loader)` so the TUI can hide dismissed rows, drive revive, and self-heal.

`src/sase/ace/tui/models/agent_loader.py::load_all_agents()` currently:

1. Reads project files and ChangeSpecs.
2. Calls the Rust `scan_agent_artifacts()` facade (`src/sase/core/agent_scan_facade.py:50`) across `~/.sase/projects`.
3. Builds Python `Agent` objects from done markers, running markers, workflow states, prompt-step markers, and
   ChangeSpec HOOKS/MENTORS/COMMENTS fields.
4. Runs liveness filtering, dedupe, status overrides, follow-up linkage, retry-chain linkage, and sorting.

`src/sase/ace/dismissed_agents.py::load_dismissed_bundles()` (line 209) supports loading only selected raw suffixes,
but startup calls it with no suffix filter. `AgentRunLogModal._load_agents_for_cl()`
(`src/sase/ace/tui/modals/agent_run_log_modal.py:75`) also loads all bundles and then filters in-memory by CL — even
though it has already computed the dismissed suffixes for that CL a few lines above.

### On-disk layout details that matter

- **Dismissed bundles are sharded by `YYYYMM`** under `~/.sase/dismissed_bundles/`, with legacy pre-shard files still
  supported at the root (`dismissed_agents.py:23–47`). An index design must enumerate shards, not assume a flat layout.
- **Workflow children use `{raw_suffix}__c{step_index}.json`** to avoid colliding with the parent bundle of the same
  raw suffix (`dismissed_agents.py:196–206`). Suffix-filtered loads must look up both the parent (`{suffix}.json`) and
  any `{suffix}__c*.json` siblings (`load_dismissed_bundles` lines 232–249).
- **`dismissed_agents.json` carries only three fields per identity**: `agent_type`, `cl_name`, `raw_suffix`
  (`dismissed_agents.py:84–118`). It is enough to filter visible rows but not enough to render revive option lists,
  status counts, parent/child links, or run-log entries — which is why the codebase falls back to full bundle
  hydration today.

## Existing Building Blocks

A solution should reuse these primitives rather than introduce parallel ones:

- **`AgentSnapshotCache`** (`src/sase/ace/tui/actions/agents/_snapshot_cache.py:38–170`) — process-local, mtime-keyed
  cache of attempt history, retry state, and dismissed bundles. Caches a single dismissed-bundle list keyed by a tuple
  of every bundle file's `(st_mtime_ns, st_size)`. Global singleton at line 165, in-memory only.
- **`_MTimeJsonCache`** (`src/sase/ace/tui/models/_loaders/_json_cache.py`) — LRU-bounded (4096) cache keyed by
  `(path, mtime_ns, size)`, thread-safe. Already used by `_load_bundle_file()` (`dismissed_agents.py:263–277`) so warm
  re-reads are cheap; the cold cost is still the OS stat + open + read for every bundle.
- **`get_loader_executor()`** (referenced from `dismissed_agents.py:256–259`) — a shared thread pool that fans out
  bundle JSON reads. Bundle loading is already parallelized; the remaining cost is largely syscall + JSON parse, not
  serial Python.
- **`ArtifactWatcher`** (`src/sase/ace/tui/util/fs_watcher.py:84–241`) — Linux inotify watcher with 50ms event
  coalescing. Today it only signals "something changed → refresh"; the same fd stream could feed an incremental index.
  Falls back silently if inotify is unavailable.
- **Rust write helpers already exist**: `try_save_dismissed_agents_index`, `try_save_dismissed_bundle`, and
  `delete_agent_artifacts` (called from `dismissed_agents.py:139–146`, `177–183`). A persistent index can hook the
  same write paths so the index update happens at the source of truth, not in a separate sync job.
- **Rust `scan_agent_artifacts()` options struct** (`AgentArtifactScanOptionsWire`,
  `src/sase/core/agent_scan_wire.py:95–119`) already has `include_prompt_step_markers`,
  `include_raw_prompt_snippets`, `max_prompt_snippet_bytes`, and `only_workflow_dirs`. Bounded options (Option D
  below) can extend this struct rather than introduce a new entry point.

## Why MTime-Only Caching Doesn't Help Cold Startup

`AgentSnapshotCache` is a module-level singleton (`_GLOBAL_CACHE`, `_snapshot_cache.py:165`). Each `sase ace`
invocation is a new Python process, so the cache is empty on every cold launch. The warm 0.037s number above is
intra-session (e.g. a manual refresh), not the user-visible cost.

The cache is also keyed by file `(st_mtime_ns, st_size)` aggregated across the bundle set. Even on a warm in-process
refresh, it must `os.stat()` every bundle file to validate the cache key (`_snapshot_cache.py:70–83`). With nearly
9k files across YYYYMM shards, the stat fan-out alone takes tens of ms and grows with archive size. A persistent
index avoids both the cold-start parse cost and the stat sweep.

## Functionality To Preserve

Any solution must preserve:

- Fast hiding of dismissed agents on startup.
- Revive of dismissed parent agents and their children, including the `__c{step_index}` child sibling lookup.
- Same-session revive of recently dismissed agents.
- Agent run log by ChangeSpec, including dismissed rows, with stable ordering.
- Workflow child display, parent/child linkage via shared `raw_suffix`, and nested step metadata
  (`step_index`, `step_name`).
- Retry-chain linkage edges: `retry_of_timestamp` (backward), `retried_as_timestamp` (forward),
  `retry_chain_root_timestamp` (root), `retry_attempt` (depth) — see `AgentMetaWire` and `DoneMarkerWire` in
  `src/sase/core/agent_scan_wire.py:217–257`. An index must store both directions or recompute them on read.
- Search/group/filter behavior across visible agents.
- Agent-name collision avoidance using historical artifacts and bundles.
- Self-healing for dismissed identities whose bundles still exist (`has_dismissed_bundle()`,
  `dismissed_agents.py:69–81`) and whose artifact dirs need cleanup
  (`src/sase/ace/tui/actions/agents/_loading_compute.py:35–72`).
- Safe behavior when an agent is currently running and its eventual `done.json` has not appeared yet.
- Legacy pre-shard bundle files at `~/.sase/dismissed_bundles/*.json` and the one-time migration helpers
  (`_maybe_migrate_bundles`, `_maybe_fix_child_collisions`) called at the top of `load_dismissed_bundles()`.

The on-disk artifact tree should remain the source of truth. Indexes and caches should be rebuildable and disposable.

## Options

### Option A: Do Not Hydrate Dismissed Bundles During Startup

Keep reading `dismissed_agents.json` at startup because it is compact and needed to filter visible rows. Stop loading
every dismissed bundle in `load_agents_from_disk()`.

Concrete code touch list:

- Drop the unconditional `snapshot_cache.dismissed_bundles()` call at `_loading_helpers.py:167`. Populate
  `_dismissed_agent_objects` only from rows already encountered in `load_all_agents()`.
- Move self-healing of orphaned dismissed identities (`_loading_compute.py:35–72`) off the startup path. Either run it
  on a debounced background timer or trigger it when the dismissed archive is opened. Today
  `compute_loader_cleanup()` calls `has_dismissed_bundle()` per orphan, which is `O(N)` in bundle count for the worst
  case.
- Add a "dismissed archive not loaded yet" sentinel so revive UI and run-log modal can show a brief loading state.
- For `AgentRunLogModal._load_agents_for_cl()` (`agent_run_log_modal.py:65–93`), derive the CL's dismissed suffixes
  first and call `load_dismissed_bundles(suffixes=...)` — the suffix-filter fast path already exists at
  `dismissed_agents.py:227–249`.

Expected effect: remove about 1.6 to 1.8 seconds from cold-process agent loading on this machine. Functionality is
preserved because the full bundle data still exists and is loaded when the user asks for revive/history.

Risk: existing self-healing depends on having all bundles during every load. That should move to a background
maintenance task or run only when the dismissed archive is opened. Startup should not pay for archive repair.

### Option B: Add a Persistent Dismissed Bundle Summary Index

Create `~/.sase/dismissed_bundles/index.sqlite` (or `index.jsonl`) with one row per bundle:

- `raw_suffix`
- `bundle_path` (or shard month + filename)
- `agent_type`
- `cl_name`
- `agent_name`
- `status`
- `start_time` / `finished_at`
- `is_workflow_child`
- `parent_timestamp`
- `step_index`
- `step_name`
- `model`
- `llm_provider`
- retry-chain edges (`retry_of_timestamp`, `retried_as_timestamp`, `retry_chain_root_timestamp`)
- optional metadata keys needed for `meta_new_cl` / `meta_new_pr` matching

Hook the existing write paths: `save_dismissed_bundle()` (`dismissed_agents.py:161–193`) appends/updates one row;
identity changes through `save_dismissed_agents()` (line 121) keep the index in sync; a `remove_bundle_by_identity()`
helper deletes rows. Add `sase agents archive rebuild-index` to walk the bundle tree from scratch.

Startup then never needs full bundle hydration. Revive and run-log screens query the summary index to build option
lists instantly, hydrating only the selected bundle for preview/revive details.

Prefer SQLite over JSONL: row-level updates and deletes, secondary indexes on `cl_name`/`status`/`raw_suffix`, and
stable behavior with multiple writers via `BEGIN IMMEDIATE` transactions. JSONL forces full-file rewrites on every
removal and offers no cheap query by CL.

### Option C: Add a Persistent Agent Artifact Summary Index

The Rust artifact scanner is already the right source for correctness, but it still walks 8k directories and returns a
large Python wire object on every cold TUI process. Add a rebuildable index for artifact summaries under
`~/.sase/agent_artifact_index.sqlite`.

Suggested table key:

- `artifact_dir` primary key
- marker signatures for `agent_meta.json`, `done.json`, `running.json`, `waiting.json`, `workflow_state.json`,
  `plan_path.json`, and prompt-step marker aggregate signature
- summary fields required by the Agents list (status, agent_type, cl_name, agent_name, started_at, finished_at,
  parent_timestamp, step_index, retry edges)
- optional blob JSON for less common marker fields

Update paths:

- Launch writes initial `agent_meta.json` and inserts an index row.
- Done-marker writing updates the row.
- Dismiss/kill/revive updates rows or marks them hidden/dismissed.
- `ArtifactWatcher` (`fs_watcher.py:84–241`) records changed artifact dirs and updates only those rows; today its
  inotify mask already covers `IN_CLOSE_WRITE | IN_CREATE | IN_DELETE` (lines 44–51), which is exactly what an
  incremental indexer needs.
- A `sase agents index rebuild` command fully scans and repairs the index.

The TUI startup query becomes:

1. Read compact dismissed identity index.
2. Query active/incomplete agents and the recent visible completed window from SQLite.
3. Render immediately.
4. Kick a background reconciliation scan to repair missing/stale rows and backfill the full list.

This preserves functionality because the full artifact tree remains canonical. The index is only a fast materialized
view.

This belongs in `../sase-core` or behind the Rust core boundary if the query/update semantics become shared by the TUI,
CLI, editor integrations, and a future web UI.

### Option D: Make the Rust Scanner Support Bounded Startup Scans

Extend `AgentArtifactScanOptionsWire` (`agent_scan_wire.py:95–119`) with:

- `max_records`
- `newest_first`
- `not_before_timestamp`
- `include_done_markers`
- `include_workflow_state`
- `include_prompt_step_markers` (already exists — keep)
- `include_waiting`
- `only_projects: tuple[str, ...]` (mirrors existing `only_workflow_dirs`)

The current Rust scanner sorts deterministic ascending by `(project, workflow, timestamp)` after walking everything.
That is good for parity tests, but not ideal for "give me the newest visible rows fast." A bounded mode could scan
timestamp directories newest-first and stop after active plus recent rows are found.

This is less complete than a persistent index because running agents can be old and workflow trees are scattered across
projects. It is still useful as an incremental improvement and as the fallback path when the persistent index is absent
or rebuilding.

### Option E: Split Startup Into Explicit Loading Tiers

Make the product contract explicit:

- Tier 0: first paint and ChangeSpec list.
- Tier 1: active agents plus recent visible completed agents.
- Tier 2: full visible agent history.
- Tier 3: dismissed archive for revive/history.

The UI should show partial-but-honest state: counts can indicate "loading" or "recent" until the full background load
finishes. Search and run-log actions that require older data can trigger the relevant tier. This keeps functionality
while making initial interactivity independent of archive size.

### Option F: Retention and Archive Compaction

Do not solve startup by deleting old artifacts by default. That sacrifices functionality.

A safe retention feature can still help long-term:

- Keep full artifacts for recent N months.
- Compact older dismissed bundles into monthly archive files plus a summary index.
- Keep full source artifacts unless the user explicitly opts into pruning.
- Provide `sase agents archive verify` and `sase agents archive rebuild-index`.

This is a storage-management feature, not the primary startup fix. It should come after lazy loading or persistent
indexes, because users with large history should not have to delete history to get fast startup.

## Concurrency & Multi-Process Safety

`sase` is multi-process by design: axe agents may be writing artifacts and saving dismissed bundles while an `ace` TUI
is open. Any new index must be safe under that pattern.

Current state:

- `save_dismissed_agents()` (`dismissed_agents.py:121–158`) tries the Rust write helper first
  (`try_save_dismissed_agents_index`); on failure or absence it falls back to a plain `open(..., "w") + json.dump()`
  with **no `fcntl.flock` and no temp-file-rename** (lines 148–158). Concurrent writes from two processes can
  interleave or truncate.
- `save_dismissed_bundle()` (lines 161–193) writes one file per bundle, so collisions between processes typically
  affect distinct files. Same-bundle races are still possible (e.g. two dismiss-same-agent paths) and are handled by
  last-writer-wins.
- ACE process invariants (one ACE per user/host) make the read-side easier, but they do not extend to background axe
  writers.

Implications for an index design:

- Prefer SQLite with WAL mode for the persistent index — it gives well-defined multi-writer semantics and
  crash-resistant transactions.
- Index update hooks should be embedded in the Rust write helpers (the same place that already serializes
  `dismissed_agents.json`), so a single transaction covers the file write and the index row.
- The reconciliation rebuild path must tolerate finding rows for artifact dirs that were deleted between steps, and
  finding new artifact dirs that have no row yet.

## Failure Isolation & Schema Drift

- Today, a single corrupt bundle returns `None` from `_load_bundle_file()` (`dismissed_agents.py:263–277`) and is
  silently dropped. An index must preserve that property: a row that fails to parse on read should not poison the
  whole startup query.
- `_maybe_migrate_bundles()` and `_maybe_fix_child_collisions()` run inside `load_dismissed_bundles()` (lines 219–220)
  and mutate the on-disk layout. If startup stops calling `load_dismissed_bundles()`, those migrations need a new
  trigger (e.g. first archive-open, an idempotent boot-time check, or a maintenance command).
- Index schema migrations should be additive and tagged with a version row; the rebuild command is the safety net for
  schema-incompatible changes.

## Recommendation

Implement in this order:

1. **Stop loading all dismissed bundles during startup.** Keep `dismissed_agents.json` for filtering. Load full bundles
   only when revive/history needs them. Move self-healing off the startup path. This is the fastest high-confidence
   win and should save roughly half the current cold `load_agents_from_disk()` time on this machine.
2. **Optimize run-log and revive paths with targeted bundle loading.** Use `load_dismissed_bundles(suffixes=...)`
   wherever a suffix set is known (e.g. `AgentRunLogModal._load_agents_for_cl()`). Move full archive loading off the UI
   thread.
3. **Add a dismissed bundle summary index.** This preserves fast revive/history even when the bundle archive grows
   past 10k files. Hook into the existing Rust write helpers so concurrent writers stay consistent.
4. **Add a persistent artifact summary index in Rust core.** Query active/recent rows from the index on startup, then
   reconcile in the background using `ArtifactWatcher` events. Treat the artifact tree as source of truth and make the
   index rebuildable.
5. **Add bounded Rust scan options as the fallback path.** Useful when the index is missing, stale, or disabled, and
   for the reconciliation rebuild step.
6. **Consider archive compaction only after indexes are reliable.** Compaction should reduce storage and inode
   pressure, not be required for acceptable startup.

## Why Not Just Cap History?

A hard startup cap like "load only the newest 500 agents" is tempting, but it changes behavior in subtle ways:

- Old running/waiting agents could disappear.
- Revive and run-log screens would become incomplete.
- Search results would depend on age instead of source truth.
- Agent-name collision handling could regress.
- Retry chains rooted at older timestamps could lose their head row, breaking parent/child rendering.

Caps are acceptable only as part of a tiered loader where the UI clearly knows it has a partial initial result and can
query the full index/archive on demand.

## Test Strategy

Add tests around behavior, not just timing:

- Startup loader does not call `load_dismissed_bundles()` on the first agents refresh.
- Dismissed identities still hide matching visible agents using only `dismissed_agents.json`.
- Revive modal loads dismissed bundles off-thread and can revive parent plus child bundles, including the
  `{suffix}__c{idx}.json` sibling case.
- Run-log modal can show dismissed agents for one CL without scanning every bundle file when suffixes are known.
- Self-healing of orphan identities is invariant whether it runs on startup or on archive open; same artifact-cleanup
  outcome either way.
- Missing or corrupt summary indexes trigger rebuild or fallback scan without losing artifacts.
- A single corrupt bundle row in the index does not break the rest of the startup query.
- Index update paths handle launch, done, dismiss, kill, revive, retry-spawn, workflow child markers, and the
  `__c{idx}` child filename.
- Two `sase` processes saving dismissed bundles concurrently both end up reflected in the index; neither corrupts
  `dismissed_agents.json`.
- Legacy unsharded bundles at `~/.sase/dismissed_bundles/*.json` are visible to both the index rebuild and any
  fallback scan.
- Inotify-driven incremental updates correctly translate `IN_CREATE` / `IN_CLOSE_WRITE` / `IN_DELETE` on artifact
  files into index row writes/deletes.

Add perf sentinels:

- Cold `load_agents_from_disk()` with synthetic 10k dismissed bundles should not scale with bundle count unless revive
  is opened.
- Warm startup with an artifact summary index should be bounded by active/recent row count, not total historical
  artifact count.
- `os.stat()` count during a warm `AgentSnapshotCache.dismissed_bundles()` should not grow with archive size after
  the index is in place.
- Rebuild benchmarks should remain separate from startup benchmarks because rebuild is maintenance work.

## Open Questions

- Should dismissed bundle summaries live in the same SQLite DB as artifact summaries, or in a separate archive DB?
  (Same DB simplifies cross-joins for run-log; separate DB matches the on-disk split between
  `~/.sase/projects` and `~/.sase/dismissed_bundles`.)
- Which exact fields are needed to render revive/run-log option lists without hydrating full `Agent` objects? An
  audit of `AgentRunLogModal` and the revive modal renderers would pin this down.
- Should artifact summary rows store normalized `Agent` projections, or raw marker projections plus a small Rust query
  layer?
- How much of `load_all_agents()` status override logic should move into Rust core once an artifact index exists?
- Should the TUI expose a manual "full history still loading" indicator, or is background completion plus
  search-on-demand enough?
- How should the index handle agents whose `done.json` is written by an axe process while the ACE TUI is mid-query?
  (Snapshot isolation via SQLite WAL is likely sufficient, but warrants a documented invariant.)
- Where should `_maybe_migrate_bundles()` and `_maybe_fix_child_collisions()` move once startup no longer calls
  `load_dismissed_bundles()`? Candidates: an idempotent `sase agents archive verify` step on first archive open, or a
  one-shot boot-time maintenance task gated by a per-version sentinel file.
- Is there a case for keeping the in-process `AgentSnapshotCache` after the persistent index lands, or does the index
  fully subsume it for the dismissed-bundle key?
