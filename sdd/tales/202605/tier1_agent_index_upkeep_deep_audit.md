---
create_time: 2026-05-21 18:08:47
status: done
prompt: sdd/prompts/202605/tier1_agent_index_upkeep_deep_audit.md
---
# Tier 1 Agent Index Upkeep Deep Audit Plan

## Goal

Keep the Tier 1 Agents-tab artifact index current for every loader-visible marker lifecycle, and make future regressions
harder to introduce. Tier 1 depends on the persistent SQLite agent artifact index for fast visible-inbox loads, so any
direct mutation of indexed marker files must either update/delete the matching row or be intentionally documented as
non-projected.

## Current Understanding

Indexed marker files are:

- `agent_meta.json`
- `done.json`
- `running.json`
- `waiting.json`
- `pending_question.json`
- `workflow_state.json`
- `plan_path.json`
- `prompt_step_*.json`

The prior `sdd/epics/202605/tier1_agent_index_upkeep.md` work is mostly landed:

- Runner helpers update after `agent_meta.json`, `done.json`, `waiting.json`, `pending_question.json`,
  `workflow_state.json`, `plan_path.json`, and prompt-step marker writes.
- TUI rename, approve, wait edits, plan approval, mobile plan approval, revive, dismissal, kill persistence, name
  migration, and stale home-running cleanup have lifecycle hooks.
- Rust core now tracks `pending_question.json`, stores marker signatures, and query-time self-heals stale rows before
  visible/status filtering.
- `tests/test_agent_artifact_marker_write_audit.py` inventories direct marker mutation contexts.

The audit still has two gaps:

- The marker-write audit allowlist records that a function was "reviewed", but it does not assert that reviewed
  write/delete sites actually call an index lifecycle helper or are explicitly exempt. A reviewed context can drift into
  a stale-index bug without the test failing.
- `src/sase/agent/names/_wipe.py::_release_artifact_workspace` deletes `running.json` before `_remove_artifact_dirs()`
  deletes the artifact directory. Successful directory deletion removes the row later, but if the directory delete
  fails, the artifact remains with a stale indexed `running.json` projection.

## Implementation Plan

1. Add a lifecycle update for name-wipe `running.json` cleanup.
   - In `src/sase/agent/names/_wipe.py`, call `update_agent_artifact_index_for_marker_mutation(path)` after
     `running.json` is successfully unlinked in `_release_artifact_workspace`.
   - Keep the existing later `delete_agent_artifact_index_artifacts(removed_artifacts)` call for successfully removed
     artifact directories.
   - Preserve best-effort behavior: index update failures must not affect forced name reuse.

2. Strengthen the marker mutation audit.
   - Extend `tests/test_agent_artifact_marker_write_audit.py` so each reviewed mutation context carries either:
     - direct lifecycle coverage (`update_agent_artifact_index_for_marker_mutation`,
       `upsert_agent_artifact_index_artifacts`, `delete_agent_artifact_index_artifacts`,
       `sync_dismissed_agent_artifact_index`),
     - indirect lifecycle coverage through a known caller/helper, or
     - an explicit exemption reason for non-projected or caller-batched writes.
   - Keep `sase_chop_wait_checks.py` exempt because it writes `ready.json`, which is not Tier 1 indexed; it only reads
     `waiting.json`/`agent_meta.json`.
   - Keep revive artifact restoration exempt at the helper level because callers batch one
     `upsert_agent_artifact_index_artifacts()` after restoring all files.
   - Keep auto-name migration exempt at the helper level because `run_historical_auto_name_migration()` collects changed
     indexed marker files and upserts their artifact dirs after the rewrite pass.
   - Keep generic helper wrappers (`write_agent_meta`, `write_done_marker`, `setup_artifacts_directory`, etc.) as
     covered when they already call lifecycle hooks internally.

3. Add focused tests for the uncovered cleanup edge.
   - Add or update `tests/test_agent_name_wipe.py` to assert `_release_artifact_workspace()` refreshes the artifact
     index after deleting a home-mode `running.json`.
   - If `_release_artifact_workspace()` is private but testable, call it directly with a temporary artifact dir and
     monkeypatch the lifecycle function.
   - Verify forced name reuse still deletes rows for directories removed by `_remove_artifact_dirs()`.

4. Re-run the mutation inventory.
   - Use the AST audit test plus targeted `rg` scans for the indexed marker filenames.
   - Confirm every current direct mutation either updates/deletes/upserts the Tier 1 index or has an explicit audit
     exemption.

5. Verification.
   - Run `just install` before repo checks, per workspace guidance.
   - Run targeted tests:
     - `pytest -q tests/test_agent_artifact_marker_write_audit.py`
     - `pytest -q tests/test_agent_name_wipe.py`
   - Run `just check` after file changes.

## Acceptance Criteria

- Deleting `running.json` during forced name reuse refreshes the artifact index even if artifact directory deletion does
  not complete.
- The direct marker mutation audit fails if a new indexed marker mutation appears without direct lifecycle coverage,
  known indirect coverage, or a documented exemption.
- Existing reviewed contexts remain covered without broadening runtime behavior for non-indexed files such as
  `ready.json`, `.sase_plan_pending`, and `.sase_questions_pending`.
- Targeted tests and `just check` pass.
