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

`src/sase/ace/tui/actions/agents/_loading_helpers.py::load_agents_from_disk()` currently:

1. Calls `load_all_agents()`.
2. Loads tags, attempt history, and retry state for each visible agent.
3. Uses `dismissed_agents.json` to identify dismissed agents found in the normal loader.
4. Calls `snapshot_cache.dismissed_bundles()`, which loads every dismissed bundle on a cold process.
5. Returns `(all_agents, dismissed_from_loader)` so the TUI can both hide dismissed rows and support revive/self-healing.

`src/sase/ace/tui/models/agent_loader.py::load_all_agents()` currently:

1. Reads project files and ChangeSpecs.
2. Calls the Rust `scan_agent_artifacts()` facade across `~/.sase/projects`.
3. Builds Python `Agent` objects from done markers, running markers, workflow states, prompt-step markers, and
   ChangeSpec HOOKS/MENTORS/COMMENTS fields.
4. Runs liveness filtering, dedupe, status overrides, follow-up linkage, retry-chain linkage, and sorting.

`src/sase/ace/dismissed_agents.py::load_dismissed_bundles()` supports loading only selected suffixes, but startup calls
it with no suffix filter. `AgentRunLogModal` also loads all dismissed bundles and then filters by CL.

## Functionality To Preserve

Any solution must preserve:

- Fast hiding of dismissed agents on startup.
- Revive of dismissed parent agents and their children.
- Same-session revive of recently dismissed agents.
- Agent run log by ChangeSpec, including dismissed rows.
- Workflow child display and nested step metadata.
- Search/group/filter behavior across visible agents.
- Agent-name collision avoidance using historical artifacts and bundles.
- Self-healing for dismissed identities whose bundles still exist.
- Safe behavior when an agent is currently running and its eventual `done.json` has not appeared yet.

The on-disk artifact tree should remain the source of truth. Indexes and caches should be rebuildable and disposable.

## Options

### Option A: Do Not Hydrate Dismissed Bundles During Startup

Keep reading `dismissed_agents.json` at startup because it is compact and needed to filter visible rows. Stop loading
every dismissed bundle in `load_agents_from_disk()`.

Instead:

- Populate `_dismissed_agent_objects` only from dismissed rows already encountered in `load_all_agents()`.
- Lazy-load dismissed bundles when the user opens revive UI or the run-log modal.
- Add a small "dismissed archive not loaded yet" state so revive can show a spinner while it loads bundles off-thread.
- For `AgentRunLogModal`, derive the CL's dismissed suffixes first and call `load_dismissed_bundles(suffixes=...)` where
  possible instead of loading all bundles.

Expected effect: remove about 1.6 to 1.8 seconds from cold-process agent loading on this machine. Functionality is
preserved because the full bundle data still exists and is loaded when the user asks for revive/history.

Risk: existing self-healing depends on having all bundles during every load. That should move to a background maintenance
task or run only when the dismissed archive is opened. Startup should not pay for archive repair.

### Option B: Add a Persistent Dismissed Bundle Summary Index

Create `~/.sase/dismissed_bundles/index.sqlite` or `index.jsonl` with one row per bundle:

- `raw_suffix`
- `bundle_path`
- `agent_type`
- `cl_name`
- `agent_name`
- `status`
- `start_time` / `finished_at`
- `is_workflow_child`
- `parent_timestamp`
- `step_index`
- `model`
- `llm_provider`
- optional metadata keys needed for `meta_new_cl` / `meta_new_pr` matching

`save_dismissed_bundle()` appends or updates one row. `remove_bundle_by_identity()` removes rows. A rebuild command
walks the existing bundle tree and recreates the index.

Startup then never needs full bundle hydration. Revive and run-log screens can query the summary index to build option
lists instantly, and hydrate only the selected bundle for preview/revive details.

Prefer SQLite if we expect CL/date/status queries and multi-process writers. JSONL is simpler, but compaction and
deletion get awkward once there are thousands of rows.

### Option C: Add a Persistent Agent Artifact Summary Index

The Rust artifact scanner is already the right source for correctness, but it still walks 8k directories and returns a
large Python wire object on every cold TUI process. Add a rebuildable index for artifact summaries under
`~/.sase/agent_artifact_index.sqlite`.

Suggested table key:

- `artifact_dir` primary key
- marker signatures for `agent_meta.json`, `done.json`, `running.json`, `waiting.json`, `workflow_state.json`,
  `plan_path.json`, and prompt-step marker aggregate signature
- summary fields required by the Agents list
- optional blob JSON for less common marker fields

Update paths:

- Launch writes initial `agent_meta.json` and inserts an index row.
- Done-marker writing updates the row.
- Dismiss/kill/revive updates rows or marks them hidden/dismissed.
- Artifact watcher records changed artifact dirs and updates only those rows.
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

Add scan options such as:

- `max_records`
- `newest_first`
- `not_before_timestamp`
- `include_done_markers`
- `include_workflow_state`
- `include_prompt_step_markers`
- `include_waiting`
- `only_projects`

The current Rust scanner sorts deterministic ascending by `(project, workflow, timestamp)` after walking everything.
That is good for parity tests, but not ideal for "give me the newest visible rows fast." A bounded mode could scan
timestamp directories newest-first and stop after active plus recent rows are found.

This is less complete than a persistent index because running agents can be old and workflow trees are scattered across
projects. It is still useful as an incremental improvement and as the fallback path when the persistent index is absent.

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

## Recommendation

Implement in this order:

1. **Stop loading all dismissed bundles during startup.** Keep `dismissed_agents.json` for filtering. Load full bundles
   only when revive/history needs them. This is the fastest high-confidence win and should save roughly half the current
   cold `load_agents_from_disk()` time on this machine.
2. **Optimize run-log and revive paths with targeted bundle loading.** Use `load_dismissed_bundles(suffixes=...)` where
   a suffix set is known. Move full archive loading off the UI thread.
3. **Add a dismissed bundle summary index.** This preserves fast revive/history even when the bundle archive grows past
   10k files.
4. **Add a persistent artifact summary index in Rust core.** Query active/recent rows from the index on startup, then
   reconcile in the background. Treat the artifact tree as source of truth and make the index rebuildable.
5. **Add bounded Rust scan options as the fallback path.** Useful when the index is missing, stale, or disabled.
6. **Consider archive compaction only after indexes are reliable.** Compaction should reduce storage and inode pressure,
   not be required for acceptable startup.

## Why Not Just Cap History?

A hard startup cap like "load only the newest 500 agents" is tempting, but it changes behavior in subtle ways:

- Old running/waiting agents could disappear.
- Revive and run-log screens would become incomplete.
- Search results would depend on age instead of source truth.
- Agent-name collision handling could regress.

Caps are acceptable only as part of a tiered loader where the UI clearly knows it has a partial initial result and can
query the full index/archive on demand.

## Test Strategy

Add tests around behavior, not just timing:

- Startup loader does not call `load_dismissed_bundles()` on the first agents refresh.
- Dismissed identities still hide matching visible agents using only `dismissed_agents.json`.
- Revive modal loads dismissed bundles off-thread and can revive parent plus child bundles.
- Run-log modal can show dismissed agents for one CL without scanning every bundle file when suffixes are known.
- Missing or corrupt summary indexes trigger rebuild or fallback scan without losing artifacts.
- New index update paths handle launch, done, dismiss, kill, revive, retry-spawn, and workflow child markers.
- Multi-process writes are safe under file locking or SQLite transactions.

Add perf sentinels:

- Cold `load_agents_from_disk()` with synthetic 10k dismissed bundles should not scale with bundle count unless revive is
  opened.
- Warm startup with an artifact summary index should be bounded by active/recent row count, not total historical
  artifact count.
- Rebuild benchmarks should remain separate from startup benchmarks because rebuild is maintenance work.

## Open Questions

- Should dismissed bundle summaries live in the same SQLite DB as artifact summaries, or in a separate archive DB?
- Which exact fields are needed to render revive/run-log option lists without hydrating full `Agent` objects?
- Should artifact summary rows store normalized `Agent` projections, or raw marker projections plus a small Rust query
  layer?
- How much of `load_all_agents()` status override logic should move into Rust core once an artifact index exists?
- Should the TUI expose a manual "full history still loading" indicator, or is background completion plus search-on-demand
  enough?

