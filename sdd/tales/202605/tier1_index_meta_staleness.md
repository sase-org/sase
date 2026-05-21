---
create_time: 2026-05-21 14:14:17
status: done
prompt: sdd/prompts/202605/tier1_index_meta_staleness.md
---
# Fix: Tier 1 Fast Reload Doesn't Pick Up agent_meta.json Timestamp Updates

## Context

The Agents tab detail panel renders timestamp entries (START, RUN, PLAN, etc.) from `Agent` fields populated from
`agent_meta.json`:

- `agent.plan_times` ← `plan_submitted_at`
- `agent.feedback_times` ← `feedback_submitted_at`
- `agent.questions_times` ← `questions_submitted_at`
- `agent.retry_times` ← `retry_started_at`
- `agent.epic_time` ← `epic_started_at`
- `agent.run_start_time` ← `run_started_at`
- `agent.stop_time` ← `stopped_at`

The bug: when an agent transitions to a state that appends a new timestamp to `agent_meta.json` mid-run (e.g. PLAN
submitted), the detail panel does **not** update on auto-refresh. Only `,y` (full filesystem rescan) reveals the new
entry. The BAD/GOOD snapshots in the user's report show `PLAN` missing on auto-refresh and present after `,y`.

Note: a separate plan (`sase_plan_agent_timestamps_refresh.md`) addresses `code_time` loss during the Tier 1 merge —
that's a child-derived field problem. This plan covers a different, simpler problem one layer below: stale parent
timestamp data coming **out of the Rust artifact index**.

## Root Cause

The Tier 1 fast reload reads from a SQLite-backed Rust artifact index (`crates/sase_core/src/agent_scan/index.rs`). Each
agent's full `AgentArtifactRecordWire` — including the `AgentMetaWire` block with all timestamp fields — is stored as a
serialized `record_json` blob, written at the last **upsert** call. `query_agent_artifact_index()` simply deserializes
whatever is in `record_json`. It **does not** re-read `agent_meta.json` from disk, **does not** compare stored marker
signatures (`agent_meta_sig`) against the current file mtime, and **does not** trigger any rescan when signatures
differ.

Upsert is only called from explicit lifecycle points (`update_agent_artifact_index_for_marker_mutation` in
`src/sase/core/agent_artifact_index_lifecycle.py`):

- `run_agent_runner_setup` (initial setup)
- `runner_utils.write_agent_meta` (model/provider metadata)
- `runner_utils.write_done_marker` / `run_agent_exec_markers.write_done_marker_and_update_index` (completion)
- `run_agent_runner_finalize`

But the runtime status-transition path that writes timestamp lists to `agent_meta.json` uses `update_meta_field()` (e.g.
plan submission in `run_agent_exec_plan.py` writes `plan_submitted_at` via `_record_workflow_metadata`). That helper
writes the JSON file but does **not** call the index upsert. Consequently:

1. `agent_meta.json` on disk gets the new `plan_submitted_at` entry — file mtime bumps and `agent_meta_sig` would change
   if rescanned.
2. The index keeps the old `record_json` indefinitely.
3. Tier 1 query returns stale `AgentMetaWire`; `enrich_agent_from_meta_wire()` produces an `Agent` with empty
   `plan_times`.
4. `,y` triggers a full rebuild (`rebuild_agent_artifact_index` DELETEs + rescans), restoring the data.

This is a generic cache-invalidation gap, not a deserialization bug — every list-valued timestamp field (`plan_*`,
`feedback_*`, `questions_*`, `retry_*`) and any other `agent_meta.json` field appended mid-run is affected the same way.

## Design Decision: Where to Fix It

Three candidate fix locations were considered:

**A. Add upsert calls at every metadata write site.** Targeted, but requires touching every place that ever calls
`update_meta_field` and is easy to regress in the future when new state writes are added. Also pushes Rust-index
concerns into business logic that should stay metadata-only.

**B. Lazy stale-signature detection inside the Rust query path.** Reuse the existing `agent_meta_sig` /
`MarkerSignatures::from_artifact_dir()` infrastructure: on query, compare stored signatures to the current artifact dir;
for rows whose signatures differ, re-scan the dir and refresh `record_json` before returning. Self-healing, catches
**all** mid-run metadata updates uniformly (not just timestamps), and is bounded by the Tier 1 result-set size (~200
rows + active set).

**C. Background watcher thread.** Most complex, adds latency/lifecycle concerns, and is overkill given B already
amortizes cost across queries.

**Choose Option B as the primary fix.** The index already pays to store signatures for exactly this purpose; the
on-query revalidation completes what the signature mechanism was clearly designed to enable. Option A would be a
brittle, partial fix; Option C is unnecessary.

Per the `rust_core_backend_boundary.md` litmus test, this is core backend logic: any frontend (TUI, CLI, future web)
querying the index needs the same self-healing behavior. The fix belongs in `sase-core`, not in TUI/Python adapters.

## Implementation Plan

1. **Rust: add per-row stale detection inside `query_agent_artifact_index`.**
   - In `crates/sase_core/src/agent_scan/index.rs`, extend the query path so each result row is validated against the
     current on-disk marker signatures:
     - Recompute `MarkerSignatures::from_artifact_dir(artifact_dir)` for the row's artifact directory.
     - Compare to the per-file `*_sig` columns stored on the row.
     - If any tracked signature differs (or the file now exists where it didn't, or vice versa), rescan that single
       directory via the same code path the upsert uses, write the refreshed `record_json` + signatures back, and return
       the refreshed wire instead of the cached one.
   - Skip rescan when all signatures match.
   - Handle "dir missing" gracefully (return the cached row, leave a follow-up to mark it terminal — out of scope for
     this fix).
   - Keep the refresh inside a single SQLite transaction per stale row so concurrent queries see consistent data.

2. **Rust: avoid pathological repeated rescans.**
   - Add a small in-memory mtime/sig cache keyed by artifact_dir to dedupe rescans within one query call (the same row
     should not be rescanned twice if referenced through multiple lookup paths).
   - No persistent cache or TTL: the next call should still detect post-write signature changes immediately.

3. **Rust: unit tests for the self-healing query.**
   - Test: build index for an artifact dir, append a new entry to `plan_submitted_at` in `agent_meta.json`, query,
     assert the returned `AgentMetaWire.plan_submitted_at` reflects the new entry without an explicit upsert.
   - Test: same for `feedback_submitted_at`, `run_started_at`, and a marker-file mtime change (e.g. `running.json`
     replaced by `done.json`).
   - Test: matching signatures → no rescan (verify with a counter / spy or by leaving the file unchanged and observing
     no row write).

4. **Python: integration test in `sase_11`.**
   - Add a TUI-level test that drives the Tier 1 loader against an artifact dir whose `agent_meta.json` is mutated after
     the initial upsert. Assert the resulting `Agent.plan_times` contains the new timestamp without invoking a full
     rebuild.
   - Place near the existing Tier 1 loader tests under `tests/ace/tui/`.

5. **No Python-side workaround.**
   - Do **not** add upsert calls inside `update_meta_field` or its callers. The fix belongs in the index. Leaving those
     write paths untouched also confirms the Rust self-healing actually works in production.

6. **Verification.**
   - Update the Rust bindings if any wire signatures changed (none expected; this is internal index logic).
   - Run `cargo test` in `sase-core`.
   - Run `just check` in `sase_11`.
   - Manual TUI verification: start an agent, observe `PLAN` timestamp appears on the next auto-refresh tick without
     pressing `,y`.

## Out of Scope

- Reworking `update_meta_field` to push index updates (not needed once Option B lands; would also duplicate work).
- Fixing the related `code_time` post-merge regression — that's tracked in `sase_plan_agent_timestamps_refresh.md` and
  is in the Python merge layer, not the Rust index.
- Background index watchers or any scheduled rescan loop.
