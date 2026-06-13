---
create_time: 2026-06-13 13:35:34
status: done
prompt: sdd/prompts/202606/ace_run_layout_review_fixes.md
---
# Plan: Fix Gaps in the Sharded `ace-run` Artifact Layout Implementation

## Context

The prior agent implemented `sdd/tales/202606/ace_run_layout.md` across `sase` (commit `6cfa3b171`) and `sase-core`
(commit `8908ce3`): a core layout contract, scanner/index support, a Python facade
(`src/sase/core/agent_artifact_paths.py`), a migration CLI
(`sase agents artifacts layout {migrate,rollback,status,verify}`), and conversion of the hot TUI/launch/lookup
callsites.

I reviewed both commits in depth (Rust core, the Python facade, the migration CLI, and a codebase-wide sweep for
un-migrated path handling). The core layout contract, the scanner parity, the index schema-v4 migration, and the
**revive legacy-preservation fix are correct**. However, the change **already flipped new writes to the sharded
layout**: `create_artifacts_directory()` now calls `canonical_agent_artifact_path()`, so **every new `ace-run` agent is
written to `ace-run/YYYYMM/DD/<timestamp>/` today** — even before any machine migration is run.

That makes a set of **missed reader conversions into live bugs**, not latent ones. The prior agent completed Phase 4
(new sharded writes) but left several Phase 2/3 reader sites still assuming the flat `ace-run/<timestamp>/` layout.
Those readers now misbehave for every newly-created agent. This plan fixes those, hardens the destructive migration
path, and removes dead surface — all verified, high-confidence changes.

## Goals

- Make every **live** code path that parses, iterates, or attributes an `ace-run` artifact directory correct under both
  the legacy flat layout and the new sharded layout.
- Make the directory-moving migration command crash-safe and resumable (it moves ~15k dirs / ~1.3 GB).
- Remove dead/misleading CLI and import surface introduced by the change.
- Add regression tests so the sharded layout is exercised at each fixed site.

## Non-Goals

- No change to the canonical layout, the Rust contract, the index schema, or the migration manifest format. These are
  correct.
- No machine migration is run as part of this work (that remains an operator action).
- The performance optimization of wiring the new index columns into name/workflow predicates is **explicitly deferred**
  (see "Deferred" below) — it is an optimization, not a correctness fix, and is larger in scope.

## In-Scope Fixes

### 1. Un-migrated readers that misparse sharded paths (correctness — highest priority)

Each of these is on a live path and currently returns wrong results for sharded (i.e. all new) agents. The fix in every
case is to route path → `(project, workflow, timestamp)` through the existing `parse_agent_artifact_path()` facade (or
iterate via `iter_agent_artifact_dirs()`), keeping the old flat logic only as the unparseable-path fallback.

- **`src/sase/agents/cli_show.py:41`** — `project = artifacts_dir.parent.parent.parent.name` reports `Project: ace-run`
  for any sharded agent in `sase agents show`. Derive the project via `parse_agent_artifact_path()`.
- **`src/sase/agents/cli_tag.py:64`** — same `.parent.parent.parent` arithmetic in the running-agent `cl_name` fallback
  yields `cl_name="ace-run"`. Same fix.
- **`src/sase/agent/names/_registry_scan.py`** — `collect_artifact_entries()` walks `workflow_dir.iterdir()` and treats
  month-shard dirs (`202606`) as artifact dirs; since they have no `agent_meta.json`/`done.json` they are skipped, so
  **the durable name registry never indexes sharded agents**. `source_signature_paths()` only lists workflow + month
  dirs, so a new agent under an existing month does not change the signature → the registry is considered fresh and is
  **never rebuilt**. Fix `collect_artifact_entries()` to enumerate real timestamp dirs via
  `iter_agent_artifact_dirs(project, workflow_name)` (which handles both layouts per workflow); fix
  `source_signature_paths()` to also include the day-shard dirs for sharded workflows so the `{count, max_mtime_ns}`
  signature changes when a new agent appears (this is both correct and cheaper than the old per-timestamp listing).
- **`src/sase/agent/names/_registry_entries.py:65-68`** — `owner_from_artifact_name()` computes
  `workflow_dir = artifact_dir.parent` and `project_dir` from `.parent.parent`, yielding `workflow_dir="13"`,
  `project=None` for sharded paths. Derive via `parse_agent_artifact_path()`.
- **`src/sase/agent/names/_migration.py:180`** — `_artifact_dirs()` repeats the same 3-level flat walk and misses all
  sharded agents during registry migration/backfill. Reuse the same per-workflow `iter_agent_artifact_dirs()` traversal.
- **`src/sase/core/agent_artifact_types.py:108`** — `artifact_association_from_dir()` overwrites the correct
  `raw_timestamp` (`artifacts_dir.name`) with `parts[index+4]`, which is the month shard `"202606"` under sharding.
  Derive `(project, workflow, raw_timestamp)` via `parse_agent_artifact_path()`, falling back to the current positional
  parse for non-standard paths. This feeds `agent_artifact_facade`/`_helpers`/`_explicit` (explicit artifact
  association, e.g. the `sase artifact` flow).
- **`src/sase/logs/collectors.py:160`** — `collect_artifacts()` 3-level walk treats `202606` as a timestamp dir;
  `_ts_from_artifacts_dir("202606")` returns `None`, so all sharded agents are excluded from `sase logs pack`. Iterate
  via `iter_agent_artifact_dirs()` per workflow.

> Verified **not** broken (no change): `running.py` kill-path and `_launch_delta` output fallback both call
> `parse_agent_artifact_path()` first; `_record_helpers.` `_project_workflow_from_artifact_dir()` reads `parts[2]` which
> is the workflow name under both layouts.

### 2. Migration command crash-safety (data-safety)

`src/sase/agents/cli_artifacts_layout.py::_handle_migrate` builds the manifest in memory and only persists it via
`_finish_payload` **after** the move loop. The loop also does a bare `os.rename` with no per-entry guard. So a single
failure mid-run (permission error, or the final `rebuild_agent_artifact_index`) raises before the manifest is written,
leaving moved directories on disk with **no manifest to drive `rollback`**. For a destructive 15k-dir operation this is
the most important robustness gap.

Fix:

- When `-m/--manifest` is supplied, **persist the manifest with `planned` entries before the move loop starts**, so a
  crash leaves a complete rollback record (the per-entry alias rows are already written incrementally, and `rollback`
  already tolerates partial state by checking `new_path.exists()` / `not old_path.exists()`).
- Wrap each entry's move in a try/except: on failure mark the entry `failed` with the reason and continue, instead of
  aborting the whole migration. Re-persist the manifest at the end with final statuses.
- Keep behavior identical on the happy path and for dry-run.

### 3. Remove dead `--force` option (CLI hygiene)

`parser_agents.py` defines `-f/--force` for `migrate`, but `cli_artifacts_layout.py` never reads it — a documented flag
that does nothing, which violates the "excellent, honest help" CLI rule. Either remove it, or give it real meaning by
having `_skip_reason`/the preflight honor it. **Recommendation: remove it** — the plan never specified concrete override
semantics, and a half-implemented `--force` on a destructive command is worse than none. (If the user prefers, wire it
to override the non-`running.json` skip reasons instead.)

### 4. Dead-import cleanup (hygiene)

Remove now-unused `sase_projects_dir` imports in `src/sase/ace/tui/modals/_runners_data.py` and
`src/sase/axe/chop_agents.py` (left behind when their manual path construction was replaced by the layout helpers; not
caught because ruff `F401` is globally ignored here).

### 5. Revive writer/indexer resolution symmetry (narrow correctness)

In the revive flow the writer resolves the artifact dir (`_revive_artifacts.py` uses `resolve_agent_artifact_path` +
`.exists()` guard — correct), but `revived_artifact_dir()` (`_revive_helpers.py`) and the child `parent_artifacts_dir`
(`_revive_execution.py`) pass the **unresolved** recorded path to the indexer / child marker write. When a bundle was
migrated to the sharded path while persisted state still holds the legacy string, the index update is skipped (recovered
later by a full scan) and a child marker can be written to the legacy dir while the parent state is at the sharded dir.
Resolve the path in those two spots to keep writer and indexer consistent. Low-risk; include only if it stays small.

## Validation

- **Rust**: no changes expected; if any helper signature is touched, run `SASE_CORE_DIR=<sibling> just rust-check`. (The
  sibling core checkout for this workspace is `sase-core_10`.)
- **Python tests** (add/extend, all under a temp `SASE_HOME`):
  - mixed legacy+sharded fixtures for `collect_artifact_entries`/`source_signature_paths` (registry sees sharded agents;
    signature changes when a sharded agent is added),
  - `owner_from_artifact_name`, `artifact_association_from_dir`, and `collect_artifacts(logs)` return correct
    project/workflow/timestamp for sharded dirs,
  - `cli_show`/`cli_tag` report the real project/cl_name for a sharded agent,
  - migration: a forced mid-loop failure still leaves a persisted manifest that `rollback` can consume; per-entry
    failure is recorded and does not abort the run.
- **Full gate**: `SASE_CORE_DIR=/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_10 just check`
  (run `just install` first — ephemeral workspace). Rebuild the editable `sase_core_rs` extension if any Rust changed.
- **Manual smoke**: create a new agent (lands in a shard), then `sase agents show <name>`, `sase agents tag`,
  `sase agents artifacts layout status -j`, and `sase logs pack` for the day, confirming correct
  project/workflow/timestamp attribution.

## Deferred (recommend separate follow-up, not this change)

- **Index-backed name/workflow predicates.** Schema v4 added `workflow_name` and `agent_family` columns (and indexes),
  but no Python helper queries them — `is_workflow_complete`, `_iter_family_members`, `get_most_recent_agent_name`, and
  the `_auto` active/live maps still do full filesystem walks. The schema-migration cost was paid but the perf benefit
  is unrealized. Wiring a narrow index query API (Rust binding + Python callers + fallback) is the plan's intended Phase
  3 optimization but is a sizeable, separate effort.
- **Streaming/newest-first bounded source scan.** `collect_workflow_artifact_candidates` still materializes all
  candidates into a `BTreeMap` before applying bounds; the plan's "avoid collecting all candidates" goal is unmet.
  Matches pre-existing behavior; index is the primary path.
- **`reader._artifact_cache_scope` staleness tradeoff.** For sharded paths the cache scope is the `ace-run` workflow dir
  (`parents[2]`), whose mtime rarely changes, so a held selection's newly-created same-day retry may not refresh the
  tools panel until the index/watcher catches it. This was a deliberate cache-stability choice; flagging for a conscious
  decision rather than flipping blind.
- **CLI colored/table output.** `status`/`verify` print raw `json.dumps` even in non-JSON mode; a Rich table would match
  the "prefer beautiful, colored output" rule.

## Recommendation

Do In-Scope items 1–4 (correctness + data-safety + hygiene) as one focused change with tests; include item 5 if it stays
small. These are all verified, low-risk, high-confidence. The deferred items are real but are optimizations/UX or
deliberate tradeoffs that deserve their own decision and should not block fixing the live correctness regressions.
