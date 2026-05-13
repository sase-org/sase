---
create_time: 2026-05-13 12:51:48
status: done
prompt: sdd/prompts/202605/waiting_to_running_transition.md
---
# Fix WAITING -> STARTING Agent State Regression

## Problem

Agents displayed in the `sase ace` Agents tab can move from `WAITING` to `STARTING` and then `RUNNING`. That transition
is misleading: `STARTING` is only appropriate before an agent has entered a pre-run wait. Once a row has been `WAITING`,
completion of the wait should move it directly to `RUNNING`.

The current implementation creates this gap because active rows loaded from RUNNING-field claims and `running.json`
markers start as `STARTING`. Metadata enrichment promotes them to `RUNNING` only after `agent_meta.json` has
`run_started_at`, while `waiting.json` forces `WAITING`. In the runner, `waiting.json` is removed before
`record_run_started_at()` persists `run_started_at`, leaving a refresh window where the row has no waiting marker and no
run-start marker, so the loader reports `STARTING`.

## Goals

- Prevent `WAITING -> STARTING` in the Agents tab.
- Preserve `STARTING` for genuinely pre-execution agents that have not yet waited and do not have `run_started_at`.
- Keep filesystem and snapshot/wire loader behavior identical.
- Keep the `sase agents` listing status contract aligned where it uses the same active artifact markers.
- Add focused regression coverage for the race window.

## Plan

1. Introduce a durable "wait completed" signal in `agent_meta.json`.
   - When wait handling finishes successfully, persist a timestamp such as `wait_completed_at` before deleting
     `waiting.json`.
   - This marker means the agent has crossed the wait barrier even if `run_started_at` has not yet been written.
   - Preserve existing kill behavior: if the agent is killed while waiting, do not mark wait completion as successful.

2. Teach active status resolution to treat completed waits as `RUNNING`.
   - In TUI metadata enrichment, if an active row is still `STARTING` and metadata contains `wait_completed_at`, promote
     it to `RUNNING`.
   - Mirror the same logic in the snapshot/wire enrichment path so index-backed and source-scan refreshes agree.
   - Update the CLI/listing active-status helper to return `RUNNING` when `wait_completed_at` exists and `waiting.json`
     is absent.

3. Extend wire metadata support if needed.
   - Inspect the Rust core scan wire type for `AgentMetaWire`; if it does not expose arbitrary/new metadata fields or
     `wait_completed_at`, add the field in `../sase-core` and update Python bindings/consumers accordingly.
   - Respect the Rust core backend boundary: if artifact scan parsing owns this metadata, update it there rather than
     re-parsing JSON in the Python TUI.

4. Add focused tests.
   - Runner/wait test: verify successful wait completion writes `wait_completed_at` before the marker cleanup path
     completes.
   - TUI loader/enrichment test: metadata with `wait_completed_at`, no `waiting.json`, and no `run_started_at` yields
     `RUNNING`, not `STARTING`.
   - Snapshot/wire test: same state through `AgentMetaWire` yields `RUNNING`.
   - Listing test: `_active_status_for_record()` returns `RUNNING` for the same post-wait/pre-run-start race state.

5. Verify.
   - Run the targeted tests for wait handling, TUI metadata enrichment/loading, running-agent snapshot/listing, and any
     Rust core tests touched.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.

## Risks And Constraints

- `STARTING` remains useful for brand-new agents and should not be removed globally.
- The fix should not depend on remembering previous UI state in memory; the correct display state must be
  reconstructable after restarting `sase ace`.
- The marker must be written before `waiting.json` is removed, otherwise the same filesystem race remains.
- If the artifact index caches `agent_meta.json`, both source scan and index-backed records must expose the new field.
