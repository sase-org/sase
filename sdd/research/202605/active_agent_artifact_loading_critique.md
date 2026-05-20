# Active Agent Artifact Loading Critique

Date: 2026-05-20

## Question

The Agents tab can become inefficient when it loads years of agent artifact history. One proposed mitigation is to store
active agent artifacts in a separate directory, scan only that active directory for normal Agents-tab loads, and move an
agent's artifacts out of that active directory when the user dismisses it.

This note critiques that plan against the current implementation and recommends a high-level path.

## Short Answer

The plan is feasible, but physically moving canonical artifact directories is not the best first implementation. The
advisable version is to make "active artifacts" a maintained materialized view, not a new source-of-truth directory.

SASE already has most of the right machinery:

- the TUI loader has a Tier 1 path that queries `~/.sase/agent_artifact_index.sqlite` before falling back to source
  scans (`src/sase/ace/tui/models/agent_loader.py:121`);
- Rust core has rebuild, upsert, delete, and query APIs for that index
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:73`);
- dismissal already runs asynchronously and removes loader-visible marker files instead of deleting whole artifact
  trees (`src/sase/ace/tui/actions/agents/_killing_utils.py:12`);
- revive already restores marker files into the canonical artifact location
  (`src/sase/ace/tui/actions/agents/_revive_artifacts.py:24`).

The high-level solution should be: keep canonical artifacts where they are, maintain an active/recent artifact index
incrementally, and make dismissal remove or mark rows inactive in that index. If a filesystem-visible "active"
directory is still wanted, implement it as symlinks or small pointer files generated from the index, not by moving the
canonical artifact trees.

## Current Scale

On this workstation at research time:

| Corpus | Count / size |
| --- | ---: |
| `~/.sase/projects` artifact timestamp directories | 13,508 |
| JSON marker files under `~/.sase/projects` | 50,113 |
| `done.json` markers on disk | 1,643 |
| `workflow_state.json` markers on disk | 1,816 |
| `running.json` markers on disk | 81 |
| `waiting.json` markers on disk | 0 |
| `~/.sase/dismissed_bundles/**/*.json` | 22,469 |
| `~/.sase/projects` size | 831 MB |
| `~/.sase/dismissed_bundles` size | 187 MB |
| `~/.sase/agent_artifact_index.sqlite` size | 76 MB |

This validates the underlying concern. Any normal TUI refresh that scales with all historical timestamp directories will
get worse with years of daily use. The target should be `O(active + recent completed)` for normal Agents-tab loads, with
explicit full-history operations paying the archival cost.

Growth check: an earlier research note (`sdd/research/202605/agent_artifact_loading_startup.md`) recorded 8,157
timestamp directories and 17,724 marker files on the same workstation. Both counts have grown ~65% since then, so
"years of daily use" is not a hypothetical scaling regime — it is the regime the loader is already entering.

### Empirical Index State

The persistent artifact index already exists on this workstation. Direct SQLite inspection of
`~/.sase/agent_artifact_index.sqlite` (schema_version = 1):

| Metric | Value |
| --- | ---: |
| `agent_artifacts` rows | 11,845 |
| Source timestamp directories | 13,508 |
| Rows matching the index's "active" predicate | 10,208 |
| Rows with `has_done_marker = 0` | 10,299 |
| Rows with `hidden = 1` | 2,261 |
| `dismissed_agents` rows | 24,272 |
| `running.json` markers on disk | 81 |
| `waiting.json` markers on disk | 0 |

Two facts jump out:

1. The index has ~1,600 fewer rows than there are source timestamp directories. Something writes artifact directories
   without notifying the index. Rebuild is the only path that re-syncs them.
2. The index reports ~10,200 "active" rows, but only ~80 `running.json` files exist on disk and no `waiting.json`
   files exist. The active row count is roughly two orders of magnitude larger than the real active set.

The reason is structural, not a one-off corruption: dismissal removes `done.json` and `workflow_state.json` but the
index row is not deleted or marked, so the active-predicate (`has_done_marker = 0 OR workflow_status NOT IN
terminal`) flips a previously-completed dismissed row back to active. This is exactly the failure mode the previous
draft mentioned as a hypothetical and that is in fact already happening on disk.

## Current Loading Model

`src/sase/ace/tui/models/agent_loader.py` already uses a tiered design:

- Tier 1 queries `default_agent_artifact_index_path()` when the index exists.
- The Tier 1 query includes active rows and a bounded recent-completed window of 200 rows.
- If the index is missing or bad, Tier 1 falls back to a bounded source scan.
- Tier 2 forces a full source scan for deliberate full-history needs.

Relevant code:

- `_TIER1_RECENT_COMPLETED_LIMIT = 200` and bounded fallback options are defined at
  `src/sase/ace/tui/models/agent_loader.py:67`.
- `_query_artifact_index_for_loader()` builds an `AgentArtifactIndexQueryWire` with active plus recent completed rows at
  `src/sase/ace/tui/models/agent_loader.py:121`.
- `_artifact_snapshot_for_tui_load()` makes full history an explicit Tier 2 path at
  `src/sase/ace/tui/models/agent_loader.py:171`.

Rust core's index is also already shaped like the desired active set:

- `agent_artifacts` has one row per artifact directory and stores denormalized status, marker-presence, hidden,
  timestamp, model/provider, parent/step, retry, and marker-signature fields
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:241`).
- `query_agent_artifact_index()` can combine active, recent completed, and full-history slices
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:160`).
- The active predicate is currently marker/status based: no `done.json`, or workflow status not terminal
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:442`).

## Production Wiring Status

The Rust APIs for the artifact index are complete, but only one of them is wired into production Python today.

| API | Defined at | Production callers |
| --- | --- | --- |
| `rebuild_agent_artifact_index` | `src/sase/core/agent_scan_facade.py:91` | `sase agents index rebuild` (`src/sase/agents/cli_index.py:42`) |
| `verify_agent_artifact_index` | `src/sase/core/agent_scan_facade.py:154` | `sase agents index verify` (`src/sase/agents/cli_index.py:62`) |
| `query_agent_artifact_index` | `src/sase/core/agent_scan_facade.py:135` | TUI Tier 1 (`src/sase/ace/tui/models/agent_loader.py:142`) |
| `upsert_agent_artifact_index_row` | `src/sase/core/agent_scan_facade.py:106` | none outside tests |
| `delete_agent_artifact_index_row` | `src/sase/core/agent_scan_facade.py:125` | none outside tests |

The asymmetry is the core implementation gap. The TUI reads from the index, but the index is only written by a manual
rebuild command. Every agent lifecycle event today — launch, marker writes, dismissal, revive, external kill — leaves
the index either out of date (missing rows for new artifact dirs) or actively wrong (stale rows whose markers were
removed by dismissal).

That is why this workstation shows 1,663 unindexed directories plus 10,208 "active" index rows where the real active
set is at most ~80. A rebuild would re-sync the row count but would not reclassify dismissed rows as inactive, because
the active predicate is purely marker-derived. Rebuild on its own is therefore not a fix for the active set being
wrong; the predicate or the rebuild input needs to know about dismissal too.

### The `hidden` Column Today

The index already has a `hidden INTEGER` column and the active predicate already filters `hidden = 0`
(`../sase-core/crates/sase_core/src/agent_scan/index.rs:448`). However, `hidden` is currently derived only from marker
fields at index time:

- `agent_meta.json#hidden`
- `done.json#hidden`
- `workflow_state.json#hidden`
- `workflow_state.json#is_anonymous`

(`../sase-core/crates/sase_core/src/agent_scan/index.rs:554`)

Dismissal does not write any of these fields. It deletes `workflow_state.json`, `done.json`, and `prompt_step_*.json`
but leaves `agent_meta.json` in place (`src/sase/ace/tui/actions/agents/_killing_utils.py:35`). So `hidden` cannot be
the dismissal switch as currently fed. Either dismissal needs a marker write that flips one of those fields, or the
index needs a dismissal-aware column/join.

A complementary signal already exists on disk in `~/.sase/dismissed_agents.json`, and the artifact index DB even
carries a `dismissed_agents` table (24,272 rows on this workstation, populated by
`agent_cleanup/execution.rs::save_dismissed_agents_index`). The active query in
`../sase-core/crates/sase_core/src/agent_scan/index.rs:442` does not join on that table today. Joining on
`(agent_type, cl_name, raw_suffix)` would push dismissed-vs-visible decisions into a single indexed query and make
"phantom active" rows go away without changing the artifact tree.

## Dismissal Today

Dismissal is already close to the desired lifecycle hook:

1. The TUI optimistically removes rows in memory.
2. The worker saves dismissed bundles for revive.
3. The worker releases workflow workspaces where needed.
4. The worker removes loader-visible marker files from artifact directories.
5. The worker dismisses matching notifications.
6. The worker saves the compact dismissed identity index.

The side-effect path lives in `src/sase/ace/tui/actions/agents/_dismiss_persistence.py:18` and
`src/sase/ace/tui/actions/agents/_dismiss_persistence.py:94`.

The important detail is that dismissal does not currently move or delete the artifact directory. It deletes marker files
that cause rediscovery: `workflow_state.json`, `done.json`, and `prompt_step_*.json`
(`src/sase/ace/tui/actions/agents/_killing_utils.py:35`). Notably it leaves `agent_meta.json` in place, so the artifact
directory is still parseable and the index can still produce a record for it on rebuild. Rust's cleanup execution has
the same semantic shape.

This keeps dismissal relatively cheap and gives it a simple failure model. A failed marker cleanup is recoverable because
the dismissed identity index can still hide the row. But it is also the reason the index drifts: removing `done.json`
flips `has_done_marker` from 1 to 0 the next time the row is reparsed, which makes the active predicate match.

## Critique Of Physical Moves

A physical active directory can work, but it would force a storage migration into many contracts that currently assume
canonical artifact paths:

- The scanner walks `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>` and validates that exact relative
  layout (`../sase-core/crates/sase_core/src/agent_scan/scanner.rs:219`).
- The candidate enumeration walks every timestamp directory before marker parsing
  (`../sase-core/crates/sase_core/src/agent_scan/scanner.rs:107`).
- Revive reconstructs marker files in the original canonical project/artifacts layout
  (`src/sase/ace/tui/actions/agents/_revive_artifacts.py:50`).
- Dismissed bundles, notifications, explicit artifacts, retry metadata, wait/resume lookup, name lookup, and run logs
  can contain raw suffixes or artifact paths that assume stable locations.

The largest product risk is not that `rename(2)` is impossible. It is that artifact paths are part of the runtime API.
Moving directories would add a second lifecycle transition at the most failure-prone moment: done -> dismissed -> archived
or revived.

It also complicates the "save chats and artifacts for all time" goal. Moving a directory preserves more marker files
than today's marker deletion, but it also makes embedded absolute paths stale unless every reader tolerates old paths or
the move layer rewrites metadata. A long-lived archive needs stable references more than it needs a physically separate
active tree.

## Index Nuance

The current index must be handled carefully. It cannot simply rebuild from source and treat "no done marker" as active.
This is no longer a theoretical concern: see the "Empirical Index State" section above for the actual count of phantom
active rows on this workstation.

The Rust scanner enumerates all supported timestamp directories, then parses whatever marker files exist
(`../sase-core/crates/sase_core/src/agent_scan/scanner.rs:51`). If a dismissed artifact directory still exists but its
`done.json` or `workflow_state.json` was removed, a naive rebuilt index can classify the row as active-like because the
active predicate includes `has_done_marker = 0`.

That means dismissal/index integration should choose one explicit invariant. Each option has a concrete edit point:

1. **Delete the row during dismissal.** Call `delete_agent_artifact_index_row()` in the worker side of dismissal
   (`src/sase/ace/tui/actions/agents/_dismiss_persistence.py`) and `_kill_persistence.py`. Pair with a rebuild rule that
   does not re-insert rows whose `(agent_type, cl_name, raw_suffix)` is in `dismissed_agents` /
   `~/.sase/dismissed_agents.json`. Without that pair, the next rebuild reintroduces the row as active.
2. **Join on `dismissed_agents` in the active query.** Change `active_where()`
   (`../sase-core/crates/sase_core/src/agent_scan/index.rs:442`) to filter out rows whose identity exists in the
   `dismissed_agents` table. This is the smallest patch: no new column, no new write path. It still requires writes
   into `dismissed_agents` to happen during dismissal — which exists today via `save_dismissed_agents_index`, but is
   not invoked from every dismissal call site.
3. **Add a durable `dismissed_at` column on `agent_artifacts`.** Repurposes the existing `hidden` filter or adds a new
   column. Schema change is cheap (`meta.schema_version` already exists) and gives O(1) tombstone semantics. The
   dismissal worker writes both `dismissed_at` on the row and the existing dismissed identity records.
4. **Mark dismissal explicitly on disk.** Have the dismissal worker write a `dismissed.json` marker in the artifact
   directory (instead of deleting `done.json`/`workflow_state.json`), and have the scanner set `hidden = 1` when it
   sees the marker. This keeps "source of truth = artifact tree" and makes rebuild deterministic, but it changes the
   on-disk contract for revive and other readers.

Recommended pick: combine option 2 (active query joins `dismissed_agents`) with option 1 (delete row on dismiss) so
the index is consistent both before and after a rebuild. Option 3 is a sensible follow-up if a single denormalized
column is preferred for SQL simplicity. Option 4 is the most invasive and not needed if options 1+2 land.

Deleting the index row during dismissal is good enough only if a later rebuild will not reintroduce the row as active.

## Recommended Implementation

### 1. Keep canonical artifacts in place

Do not move `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>` as the primary optimization. Keep the
artifact tree as the source of truth and keep dismissed bundles as the revive/archive representation.

### 2. Promote the artifact index to the active materialized view

Use the existing Rust APIs exposed by `src/sase/core/agent_scan_facade.py:91`:

- `rebuild_agent_artifact_index()`
- `upsert_agent_artifact_index_row()`
- `delete_agent_artifact_index_row()`
- `query_agent_artifact_index()`
- `verify_agent_artifact_index()`

Add a small Python/Rust lifecycle wrapper with project defaults so callers do not hand-roll index paths:

- `record_artifact_changed(artifact_dir)`
- `record_artifact_dismissed(artifact_dir, identity)`
- `record_artifact_revived(artifact_dir)`
- `rebuild_artifact_index_if_missing()`

Because this behavior is shared backend semantics for TUI, CLI, mobile, and future web surfaces, the durable visibility
rules belong in `../sase-core` behind the Rust core boundary.

### 3. Wire index updates at lifecycle mutation points

Update the index when:

- an artifact directory is created and `workflow_state.json` or initial metadata is written
  (`src/sase/axe/run_agent_runner_setup.py::setup_artifacts_directory`);
- `agent_meta.json`, `running.json`, `waiting.json`, `pending_question.json`, `workflow_state.json`,
  `prompt_step_*.json`, `plan_path.json`, or `done.json` changes;
- an agent is dismissed and marker files are removed
  (`src/sase/ace/tui/actions/agents/_dismiss_persistence.py`, `_kill_persistence.py`);
- a workflow parent dismissal affects child prompt-step rows;
- a dismissed agent is revived and marker files are restored
  (`src/sase/ace/tui/actions/agents/_revive_artifacts.py`);
- CLI/mobile/external kill paths dismiss agents outside the live TUI;
- index rebuild or verification runs.

The right place to hook most of these is the same Rust write layer that already exists for marker writes and dismissal,
not Python try/except sprinkles. Push the upsert/delete down into `agent_cleanup/execution.rs` and the marker-writer
crates so any frontend (TUI, CLI, mobile, web, axe) that mutates artifacts implicitly maintains the index. The Python
side then only needs explicit hooks for the few writes that are still Python-side (e.g. revive marker restoration in
`_revive_artifacts.py`).

Dismissal should remain optimistic in memory. The worker transaction should save bundles and the dismissed index, update
artifact visibility in the SQLite index, and then remove loader markers. If index update fails, schedule a bounded
refresh/rebuild rather than blocking the UI.

### 3b. One-time reconciliation

A backfill step is required for machines that already have a populated but inconsistent index (this workstation is one
example: 1,663 unindexed source directories plus 10,208 phantom-active rows). Options:

- Ship a `sase agents index gc` subcommand that joins on `dismissed_agents` and either deletes or sets `hidden = 1`
  for matched rows, then rebuilds the row set for unindexed directories.
- Or fold this into the existing `sase agents index rebuild` command and document that the post-fix rebuild produces a
  smaller, dismissal-aware index.
- Or auto-run a one-shot reconciliation on first launch after the upgrade, gated by a sentinel file like
  `~/.sase/agent_artifact_index_v2_reconciled`.

The reconciliation step is a one-shot, not a hot-path concern, so it can pay full-history cost without impacting the
Agents-tab interactivity.

### 4. Make normal Agents-tab loads trust Tier 1

The existing query shape is the right product contract:

```text
include_active = true
include_recent_completed = true
recent_completed_limit = 200
include_full_history = false
include_hidden = false
```

When the index is missing, use the current bounded fallback and schedule an async rebuild. Full source scans should be
reserved for explicit full-history operations such as archive/revive/search diagnostics or `sase agents index verify`.

### 5. Optional active directory as a cache

If a filesystem-visible active set remains useful, make it rebuildable and non-authoritative:

```text
~/.sase/active_agent_artifacts/<project>/<workflow>/<timestamp>.json
```

Each file should be a pointer to the canonical artifact directory, or a symlink if portability concerns are acceptable.
The TUI should not require this directory for correctness. Dismissal removes the pointer; revive recreates it; rebuild
can regenerate it from the index.

## Edge Cases

- Done but not dismissed agents are active for the TUI and must stay visible until dismissal or auto-dismissal.
- Running-state liveness still needs PID checks; an index row is not proof a process is alive. The TUI's
  `_filter_dead_pids()` step in `agent_loader.py:345` runs after the snapshot is built and should stay outside the
  index.
- Workflow parents and children share timestamps, and parent dismissal must update child/prompt-step visibility.
- Home-mode agents use `running.json`; completion and cleanup must update the same materialized row.
- Revive should upsert rows after restoring marker files.
- Search and full-history views should explicitly opt into archival cost (Tier 2 in
  `_artifact_snapshot_for_tui_load()`).
- Index corruption must remain recoverable with `sase agents index rebuild` and `sase agents index verify`.
- Any design must tolerate external dismissals from CLI/mobile/notification paths, not just TUI keybindings.
- Multi-process safety: axe agents may write `done.json` and `agent_meta.json` while ACE has the index open. SQLite
  WAL mode and `BEGIN IMMEDIATE` transactions on writes are the assumed safety model.
- A single corrupt artifact row must not break the active query. Today `_query_artifact_index_for_loader()` already
  falls back to a bounded source scan on query failure (`agent_loader.py:148`); per-row robustness should be added in
  the Rust read path.
- Pre-shard legacy bundles (`~/.sase/dismissed_bundles/*.json`) need to be enumerable by the same join. The dismissed
  bundle index at `~/.sase/dismissed_bundles/index.sqlite` already covers this.

## Test Strategy

Add focused behavioral tests rather than relying on end-to-end TUI runs (existing TUI tests are slow and have proven
brittle for performance-sensitive code paths):

- `_query_artifact_index_for_loader()` returns active+recent rows when the index is present, with no source-scan fan-out
  observed (assert via spy on `scan_agent_artifacts`).
- Launch path writes or upserts a row visible to the active query.
- `done.json` write upserts and flips the row out of the active set.
- Dismissal removes the row (or sets dismissed marker), and a subsequent rebuild does not reintroduce it as active
  because the rebuild input filters on `dismissed_agents`.
- Revive upserts the row again.
- Workflow parent dismissal updates child/prompt-step rows.
- Missing index falls back to bounded source scan and schedules rebuild.
- External CLI/mobile dismissal paths update both `dismissed_agents.json` and the index.

Add perf sentinels in `tests/ace/tui/perf/`:

- Cold `_load_agents_from_all_sources()` with a 50k-row index and 100k phantom-historical timestamp directories must
  stay bounded by active + 200 recent.
- Index rebuild benchmark is a separate suite, not a startup sentinel.

## Open Questions

- Should `dismissed_agents` move out of `agent_artifact_index.sqlite` and stay only in
  `~/.sase/dismissed_bundles/index.sqlite`, or is co-location a deliberate denormalization for the active-query join?
- For the active predicate, prefer a join on `dismissed_agents` (no schema change) or a denormalized `dismissed_at`
  column on `agent_artifacts` (one extra write per dismissal but simpler SQL)?
- Where exactly should the upsert/delete hooks live: in the Rust write helpers (`agent_cleanup/execution.rs`,
  marker-writer crates) so they fire for any frontend, or in Python at the explicit lifecycle sites
  (`_dismiss_persistence.py`, `_revive_artifacts.py`, `setup_artifacts_directory`)? Pushing into Rust covers axe and
  external clients but is a larger refactor.
- How aggressively should the Tier 1 fallback (bounded source scan) be relied on? At current scale (~13k directories)
  the fallback is ~1 second; at 10x growth, the fallback alone becomes the slow path.
- Should `sase agents index gc` be a separate subcommand, or part of `rebuild`?

## Verdict

The plan is directionally right: normal Agents-tab loading should enumerate only active and bounded recent artifacts.
The safer implementation is not to relocate canonical artifact directories, but to finish and harden the existing
artifact-index lifecycle. Concretely, on this workstation today: the index already exists, the TUI already queries it,
but ~99% of "active" rows are phantom-dismissed and the upsert/delete APIs are not wired into the dismissal or launch
paths. Adding (a) a `dismissed_agents` join (or `dismissed_at` column) to the active query, (b) upsert/delete hooks at
lifecycle mutation points, and (c) a one-time `sase agents index gc` reconciliation will give the desired
"O(active + recent)" Agents-tab load without changing the canonical artifact tree, the dismissed-bundle revive model,
or the long-term archival goal.

