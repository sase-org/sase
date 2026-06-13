---
create_time: 2026-06-13 12:28:33
status: done
prompt: sdd/prompts/202606/ace_run_layout.md
---
# Plan: Restructure `ace-run/` Artifact Storage and Search

## Summary

The previous TUI freeze plan fixed the hottest repeated scan by moving related-tool discovery to the artifact index and
by reusing discovered directories in the tools panel. That was the right immediate fix, but the underlying storage shape
is still a scaling hazard: on this machine, `~/.sase/projects/sase/artifacts/ace-run/` is a single flat directory with
15,168 timestamp children and about 1.3 GB of artifacts.

This plan restructures both the physical directory layout and the code paths that search/process `ace-run` artifacts:

- Make the canonical on-disk layout day-sharded: `artifacts/ace-run/YYYYMM/DD/<timestamp>/`.
- Centralize artifact path creation, parsing, resolution, and iteration in core APIs instead of reconstructing
  `ace-run/<timestamp>` in many Python call sites.
- Keep the artifact index as the normal query path, add narrow index queries for targeted agent-name/workflow lookups,
  and make source scans shard-aware and streaming.
- Migrate this machine with a dry-run/manifest/rollback flow, without deleting artifacts or leaving 15K top-level
  compatibility symlinks.

## Current Local Evidence

Observed on this machine during planning:

- `~/.sase/projects/sase/artifacts/ace-run/` has 15,168 direct child directories.
- The local `sase` project's flat `ace-run` distribution is:
  - `202603`: 2,703 dirs
  - `202604`: 3,859 dirs
  - `202605`: 6,747 dirs
  - `202606`: 1,860 dirs
- The largest observed day has 544 artifact dirs, so month-only sharding would still leave large leaf directories, while
  day sharding keeps normal per-directory fanout under roughly hundreds.
- The local `sase` project has 2,180 `done.json` files and 1,806 `tool_calls.jsonl` files under `ace-run`.
- The persistent artifact index exists, is schema version 3, passes `PRAGMA integrity_check`, and has 16,622 total rows.
  It currently has 15,153 `sase/ace-run` rows, slightly fewer than the 15,168 dirs on disk, so migration must include
  reconcile/verify rather than trusting the index as complete.

## Goals

- Keep `sase ace` responsive even when historical artifact count grows far past 15K.
- Make new `ace-run` writes land in a bounded, human-readable directory layout.
- Preserve existing agent semantics: project name, workflow dir name `ace-run`, timestamp leaf name, retry lineage,
  dismissed/revived behavior, notifications, tool-call display, and chat/history links.
- Support both legacy flat and new sharded layouts during a compatibility window.
- Make the migration of this machine inspectable, reversible, and safe around live agents.

## Non-Goals

- No artifact deletion or retention policy in the first migration. This plan reorganizes history; it does not decide
  what history can be removed.
- No top-level symlink fanout for old paths. Creating 15K `ace-run/<timestamp>` symlinks would preserve the exact
  performance cliff this plan removes.
- No TUI-visible behavior redesign beyond keeping the same rows/panels populated from the new layout.

## Proposed Physical Layout

Canonical v2 layout for `ace-run`:

```text
~/.sase/projects/<project>/artifacts/ace-run/
  202603/
    13/
      20260313211940/
      20260313212059/
    15/
      ...
  202604/
    ...
  202605/
    ...
  202606/
    13/
      20260613114457/
```

Rules:

- The timestamp directory basename remains the 14-digit timestamp. Existing `raw_suffix`, index `timestamp`, and display
  ordering semantics stay unchanged.
- `workflow_dir_name` remains `ace-run` in scanner/index wire records. The shard components are storage details, not a
  user-visible workflow name.
- Hidden implementation metadata can live under `ace-run/.layout/` or `~/.sase/artifact_layout_migrations/`, but normal
  humans browsing the directory should primarily see `YYYYMM/DD/<timestamp>`.
- Legacy flat dirs remain readable indefinitely: `artifacts/ace-run/<timestamp>/`.

## Core Design

### 1. Add a Core Artifact Layout Contract

Add a Rust-core layout module, exposed through a thin Python facade:

- Parse an artifact path into `(project_name, workflow_dir_name, timestamp, layout_version)`.
- Build the canonical path for `(project_name, workflow_dir_name, timestamp)`.
- Resolve a possibly stale legacy path to the current physical path.
- Iterate artifact candidates for a workflow in deterministic order, supporting both flat v1 and sharded v2 layouts.

This belongs in `sase-core` because CLI, TUI, mobile/server surfaces, and background agent launch all need the same
artifact path semantics.

Python should stop open-coding:

```text
sase_projects_dir() / project / "artifacts" / "ace-run" / timestamp
```

and call the shared resolver instead.

### 2. Make Scanner and Exact-Dir APIs Layout-Aware

Update `sase-core` scanner behavior:

- `scan_agent_artifacts()` walks supported workflow dirs through the layout iterator.
- `scan_agent_artifact_dirs()` and `scan_agent_artifact_dir()` accept both:
  - `projects/<project>/artifacts/ace-run/<timestamp>`
  - `projects/<project>/artifacts/ace-run/YYYYMM/DD/<timestamp>`
- Wire records still return the canonical physical `artifact_dir`, `workflow_dir_name = "ace-run"`, and
  `timestamp = <leaf basename>`.
- Source scans with `newest_first` should traverse newest shards first and avoid collecting all candidates before
  applying bounded options where possible.

### 3. Keep Index-First Processing, Add Targeted Queries

The normal TUI path should remain index-first. The physical layout should not become the query engine.

Add or extend index-backed queries for current direct-walk use cases:

- Related tool-call artifact dirs already use `query_related_agent_artifact_dirs`; update fallback lineage path building
  so it resolves timestamps through the layout helper rather than `current.parent / timestamp`.
- Agent name and workflow predicates in `sase.agent.names` should use narrow index queries when the index is present:
  active/live name maps, most-recent named agent, workflow-family membership, and workflow completion checks.
- Add denormalized index columns only where needed, likely `workflow_name` and `agent_family`, because some current
  targeted predicates read fields inside `agent_meta.json` that are not first-class SQL columns today.
- Keep a shard-aware filesystem fallback for missing/stale indexes, but make it newest-first and bounded for the
  hot/interactive cases.

### 4. Add Alias Compatibility Without Recreating Flat Fanout

When this machine is migrated, persisted strings may still refer to legacy paths. Examples include index rows, workflow
markers, prompt-step markers, notification payloads, dismissed bundles, logs, chat links, and copied terminal paths.

Compatibility strategy:

- Add an artifact alias table in the persistent index:
  `agent_artifact_aliases(alias_path TEXT PRIMARY KEY, artifact_dir TEXT NOT NULL)`.
- Normalize artifact paths at facade boundaries before exact-dir scan, index upsert/delete, related-dir lookup, and TUI
  artifact panel reads.
- During migration, update SASE-owned marker files that contain exact artifact-dir fields used by loaders, especially
  `workflow_state.json.artifacts_dir` and `prompt_step_*.json.artifacts_dir`.
- Do not rewrite arbitrary historical transcripts or user notes. The resolver/index alias path should make SASE code
  continue to understand old paths even when shell `cd old-flat-path` no longer works.

### 5. Update TUI Watcher and Delta Refresh

The current watcher is intentionally shallow. With `YYYYMM/DD/<timestamp>`, it must understand shard directories:

- On startup, watch project `artifacts/`, workflow dirs, and a bounded set of current/recent `ace-run` shard dirs, not
  every historical timestamp dir.
- When a new `YYYYMM`, `DD`, or timestamp dir appears, install watches for that newly-created subtree.
- Classify marker paths under both layouts back to the exact timestamp artifact directory so delta refresh still uses
  `scan_agent_artifact_dirs()` rather than falling back to broad loads.
- Keep heavy work off the Textual event loop and preserve the existing navigation/activity gates.

## Proposed CLI Surface

Add an operator-facing physical-layout command under `sase agents artifacts layout`:

```text
sase agents artifacts layout migrate
sase agents artifacts layout rollback
sase agents artifacts layout status
sase agents artifacts layout verify
```

Command options should follow existing CLI rules: sorted help, clear descriptions, and short aliases for every public
long option.

Recommended options:

- `-d|--dry-run`: print/write the manifest without moving anything.
- `-f|--force`: allow migration after preflight warnings that are explicitly safe to override.
- `-i|--index-path`: artifact index path, default `~/.sase/agent_artifact_index.sqlite`.
- `-j|--json`: machine-readable output.
- `-l|--limit`: migrate at most N artifact dirs in this invocation for staged rollout.
- `-m|--manifest`: manifest path for rollback/verify.
- `-P|--project`: limit to one project, useful for migrating `sase` first.
- `-p|--projects-root`: projects root, default `~/.sase/projects`.

`status` should report flat dirs, sharded dirs, active/live dirs, index row counts, alias rows, and whether migration is
recommended. `verify` should compare source dirs, alias rows, index rows, and sampled marker references.

## Machine Migration Procedure

The implementation should support this exact operational flow:

1. Deploy code that can read and write both layouts, but keep new writes on the legacy layout initially.
2. Run `sase agents artifacts layout status -j` and save the baseline.
3. Run `sase agents index verify -j` or an equivalent layout-aware verify. If the index is stale, run
   `sase agents index gc -j` before moving paths.
4. Dry-run the migration: `sase agents artifacts layout migrate -d -P sase -j`
5. Review the manifest:
   - old path
   - new path
   - timestamp
   - marker files that will be rewritten
   - skipped reason for active/conflicting/unreadable dirs
6. Stop or avoid active agents for the selected project, or have the migrator skip any dir with a live process,
   `running.json`, current `SASE_ARTIFACTS_DIR`, or recently-mutated marker files.
7. Run the real migration with a manifest: `sase agents artifacts layout migrate -P sase -m <manifest> -j`
8. For each artifact dir, create parent shard dirs, atomically rename the timestamp dir, record an alias row from old
   path to new path, and update owned marker fields.
9. Rebuild or transactionally update index rows so `artifact_dir` points at the new canonical path while aliases retain
   legacy lookup.
10. Run `sase agents artifacts layout verify -P sase -m <manifest> -j`.
11. Run `sase agents index status -j`; then launch `sase ace` and verify normal row loading, tools panel, name lookup,
    and delta refresh.
12. Only after this works for `sase`, repeat for other projects with smaller `ace-run` populations.

Rollback should use the manifest to move dirs back, restore rewritten marker fields where possible, and rebuild the
artifact index. Rollback is only expected to be used immediately after migration, before substantial new writes.

## Implementation Phases

### Phase 1: Layout Support Without Migration

- Add Rust layout parser/builder/iterator.
- Expose Python facade helpers.
- Update exact-dir scanner parsing for both v1 and v2.
- Add tests for legacy flat paths, sharded paths, malformed shard paths, duplicate timestamps, and filters.

### Phase 2: Centralize Python Path Construction

Replace direct `ace-run/<timestamp>` construction in:

- `sase.artifacts.create_artifacts_directory`
- launch planning helpers that predict future artifact dirs
- TUI `Agent.get_artifacts_dir()` resolution
- output-variable context
- multi-prompt naming wait
- revive and retry helpers
- agent-name lookup helpers
- any tests/fixtures that encode the physical path unnecessarily

Keep behavior compatible with existing flat dirs until migration is explicitly run.

### Phase 3: Search and Processing Cleanup

- Add targeted index queries or index columns for agent-name/workflow-family predicates.
- Replace Python direct walks over `projects/*/artifacts/ace-run/*` with index queries or the shared shard-aware
  iterator.
- Update tools-reader fallback lineage resolution to use timestamp-to-path resolution rather than sibling arithmetic.
- Make Rust scanner candidate traversal streaming/newest-first for bounded source fallbacks.
- Update TUI watcher classification for sharded paths.

### Phase 4: New Writes to V2

- Flip `create_artifacts_directory("ace-run", ...)` to produce `YYYYMM/DD/<timestamp>` for new runs.
- Keep non-`ace-run` workflow dirs unchanged unless a separate plan expands sharding to all high-volume workflow dirs.
- Verify live agent launch, plan submission, questions, retries, tool-call append/read, and finalization all work with
  the new path.

### Phase 5: Migrate This Machine

- Add the CLI migration/status/verify/rollback flow.
- Dry-run and then migrate `~/.sase/projects/sase/artifacts/ace-run`.
- Rebuild/verify the artifact index.
- Confirm the top-level `ace-run` directory now contains month shards plus hidden metadata, not 15K timestamp dirs.

### Phase 6: Follow-Up Retention

After sharding is stable, separately plan retention/archival policy:

- age-based compression or archival of old tool-call-heavy artifacts,
- dismissed-agent archive integration,
- optional cleanup of alias rows after a defined compatibility period.

This should not be mixed into the first physical migration.

## Affected Areas

- `sase-core/crates/sase_core/src/agent_scan/scanner.rs`
- `sase-core/crates/sase_core/src/agent_scan/index.rs`
- `sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/agent_scan_facade.py`
- `src/sase/core/paths.py` or a new `src/sase/core/agent_artifact_paths.py`
- `src/sase/artifacts.py`
- `src/sase/ace/tui/models/agent_artifacts.py`
- `src/sase/ace/tui/tools/reader.py`
- `src/sase/ace/tui/util/fs_watcher.py`
- `src/sase/ace/tui/actions/_event_refresh.py`
- `src/sase/agent/names/_lookup.py` and related name-map helpers
- launch/retry/revive helpers that synthesize future artifact paths
- `src/sase/main/parser_agents.py` and `src/sase/agents/cli_*` for the new CLI

## Validation Plan

- Rust unit tests:
  - parse/build legacy and sharded artifact paths,
  - scan mixed v1/v2 trees,
  - exact-dir scans accept both layouts,
  - index rebuild/query preserves `workflow_dir_name`, `timestamp`, and canonical `artifact_dir`,
  - alias normalization works for old paths.
- Python unit tests:
  - `create_artifacts_directory("ace-run")` writes v2 after the feature flip,
  - `Agent.get_artifacts_dir()` resolves explicit, legacy, and sharded paths,
  - direct path synthesis sites are gone or routed through the helper,
  - name lookup/workflow completion no longer walks flat `ace-run` directly,
  - tools fallback lineage resolves cross-day retry timestamps.
- TUI tests:
  - watcher maps sharded marker writes to exact artifact dirs,
  - delta refresh uses exact-dir loader rather than broad fallback,
  - tools panel reads related tool files for v1 and v2 agents.
- Migration tests:
  - dry-run writes a complete manifest and changes no dirs,
  - migrate moves dirs and records aliases,
  - verify detects missing moves, stale index rows, and bad marker rewrites,
  - rollback restores a small fixture tree.
- Manual validation on this machine:
  - `sase agents artifacts layout status -j`
  - `sase agents artifacts layout migrate -d -P sase -j`
  - real migration for `sase`
  - `sase agents artifacts layout verify -P sase -j`
  - `sase agents index status -j`
  - launch a new agent, submit a plan/question, use retry/follow-up flows, and open `sase ace` tools/prompt/detail
    panels.
- Performance validation:
  - top-level `ace-run` entries drop from 15K timestamp dirs to a handful of month dirs,
  - TUI startup/refresh profiles show no Python flat-dir scans over historical `ace-run`,
  - source fallback scans traverse bounded shard dirs for recent views,
  - `SASE_TUI_PERF=1 sase ace` remains within the existing p95 key-to-paint target.

## Risks and Mitigations

- Persisted absolute paths are the main compatibility risk. Mitigate with resolver normalization and index alias rows;
  avoid top-level symlink fanout.
- Moving active artifacts can break live agents. Mitigate by skipping live/current/recently-mutated dirs and
  recommending migration when no agents are running for the target project.
- Index rows can be stale before migration. Mitigate with preflight `gc`/verify and post-migration rebuild/verify.
- Watcher misses could cause broad refresh fallbacks. Mitigate with layout-aware watch installation and exact-dir
  classification tests.
- New index columns can require schema migration. Keep schema migration idempotent and covered by mixed old/new index
  tests.

## Recommendation

Proceed in the staged order above. The key design choice is to treat sharding as a core storage/layout contract, not as
a TUI-only workaround. The first implementation should stop after the machine migration verifies cleanly; retention and
artifact deletion should remain a separate, explicit decision.
