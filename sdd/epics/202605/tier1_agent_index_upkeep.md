---
create_time: 2026-05-21 16:25:39
status: done
prompt: sdd/prompts/202605/tier1_agent_index_upkeep.md
bead_id: sase-3u
tier: epic
---
# Keep the Tier 1 Agent Index Current Across Marker Lifecycles

## Inputs Reviewed

- `~/.sase/plans/202605/tier1_agent_index_lifecycle.md`
- `~/.sase/plans/202605/tier1_index_upsert_gaps.md`
- Tier 1 memory files under `memory/short/`
- Current Python marker writers under `src/sase/`
- Current Rust index implementation under `../sase-core/crates/sase_core/src/agent_scan/`

## Problem

The ACE Tier 1 Agents-tab load relies on the SQLite artifact index, but several code paths still mutate loader-visible
artifact state without refreshing or deleting the matching index row. The old plans correctly identified many runner and
workflow gaps, but the current codebase has more entrypoints than those plans covered: inline `sase run`, TUI
auto-approve/rename/wait edits, home-mode `running.json` cleanup, stale marker cleanup during loading, historical name
migrations, and name-wipe deletion.

The index must stay current for every mutation of files projected into `AgentArtifactRecordWire`:

- `agent_meta.json`
- `done.json`
- `running.json`
- `waiting.json`
- `pending_question.json`
- `workflow_state.json`
- `plan_path.json`
- `prompt_step_*.json`

Artifact directory deletion must delete the row. Files such as `ready.json`, `.sase_plan_pending`,
`.sase_questions_pending`, `embedded_workflows.json`, and explicit artifact JSONL indexes are not currently projected
into the Tier 1 agent index, so they do not need direct Tier 1 index upserts unless they are paired with a tracked
marker mutation.

## Existing Coverage To Preserve

These paths already refresh or delete the index and should not be regressed:

- `src/sase/axe/run_agent_runner_setup.py`
  - initial `workflow_state.json`
  - runner `agent_meta.json`
  - home-mode `running.json`
- `src/sase/axe/run_agent_markers.py`
  - runner `agent_meta.json`
  - `stopped_at`
- `src/sase/axe/run_agent_exec_markers.py`
  - `done.json`
- `src/sase/axe/runner_utils.py`
  - review-runner `agent_meta.json`
  - review-runner `done.json`
- `src/sase/axe/run_agent_runner_finalize.py`
  - failed `done.json`
- `src/sase/ace/tui/actions/agents/_dismiss_persistence.py`
- `src/sase/ace/tui/actions/agents/_kill_persistence.py`
- `src/sase/ace/tui/actions/agents/_revive.py`

## Additional Gaps Found In This Audit

Runner/helper gaps:

- `src/sase/axe/run_agent_helpers.py`
  - `append_meta_list_field`
  - `update_meta_field`
  - `update_meta_suffix`
  - `promote_to_workflow`
  - `normalize_handoff_interruption_state`
  - `update_step_marker_chat_path`
  - `create_followup_artifacts`
  - `handle_questions_flow` writes and deletes `pending_question.json`
- `src/sase/axe/run_agent_exec_plan_artifacts.py`
  - `write_plan_path_artifact`
- `src/sase/axe/run_agent_exec_markers.py`
  - `update_workflow_pdf_status`
  - `clear_workflow_pdf_activity`
- `src/sase/axe/run_agent_wait.py`
  - all `waiting.json` writes and deletes
- `src/sase/axe/run_agent_retry_spawn.py`
  - `mark_parent_retried`
- `src/sase/axe/run_agent_runner.py`
  - final home-mode `running.json` cleanup

Workflow and inline-run gaps:

- `src/sase/axe/run_workflow_runner.py`
  - `_write_workflow_state`
- `src/sase/xprompt/workflow_executor.py`
  - `_save_state`
  - `_save_prompt_step_marker`
- `src/sase/xprompt/workflow_runner.py`
  - `_persist_failed_state`
- `src/sase/main/query_handler/_query.py`
  - inline `agent_meta.json`
  - inline initial `workflow_state.json`
  - inline `done.json`

TUI, mobile, and external action gaps:

- `src/sase/ace/tui/actions/rename.py`
  - manual agent rename writes `agent_meta.json`
- `src/sase/ace/tui/actions/agents/_approve.py`
  - auto-approve toggle writes `agent_meta.json`
- `src/sase/ace/tui/actions/agents/_notification_plan_persistence.py`
  - plan approval writes `agent_meta.json`
- `src/sase/integrations/_mobile_notification_side_effects.py`
  - mobile plan approval writes `agent_meta.json`
- `src/sase/ace/tui/actions/agents/_wait_resume.py`
  - wait dependency edit writes `waiting.json`
- `src/sase/agent/running.py`
  - named kill deletes home-mode `running.json`
- `src/sase/ace/tui/models/_loaders/_running_loaders.py`
  - stale home-mode `running.json` cleanup deletes markers while loading

Cleanup and migration gaps:

- `src/sase/ace/tui/actions/agents/_killing_utils.py`
  - `delete_agent_artifacts` can be called from loader self-heal without a paired index delete
- `src/sase/ace/tui/actions/agents/_loading_compute.py`
  - uses `delete_agent_artifacts` for dismissed loader-sourced artifacts
- `src/sase/agent/names/_migration.py`
  - historical auto-name migration rewrites `agent_meta.json`, `done.json`, and `waiting.json`
- `src/sase/agent/names/_wipe.py`
  - forced name reuse removes artifact directories and home `running.json`

Backend self-heal gaps:

- `../sase-core/crates/sase_core/src/agent_scan/index.rs`
  - `pending_question.json` is parsed by the scanner but absent from `MARKER_FILES`, the stored signatures, and the
    SQLite schema, so query-time self-heal cannot detect question-marker drift.
  - `select_records` applies `hidden = 0` and status predicates before signature refresh. Rows whose stale indexed
    fields exclude them from the SQL candidate set cannot self-heal until a full rebuild.

## Phase 1: Rust Index Safety Net

Goal: make query-time self-heal reliable for the marker set and for stale visibility/status predicates.

Ownership:

- `../sase-core/crates/sase_core/src/agent_scan/index.rs`
- Rust tests in the same module or nearby agent-scan test modules

Implementation:

- Add `pending_question.json` to the marker signature model.
- Add a `pending_question_sig` column, bump `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION`, and migrate existing indexes with
  `ALTER TABLE` when needed.
- Include `pending_question_sig` in SELECT, INSERT, UPSERT, and signature comparison paths.
- Refactor indexed query selection so signature refresh can happen before applying visibility and active/completed
  predicates that depend on stale indexed columns. The implementation can either broaden SQL candidate sets and apply
  the final predicate in Rust, or introduce a two-pass repair for stale hidden/status rows. The important behavior is
  covered by tests, not by a specific query shape.
- Preserve the dismissed-agent visibility semantics.
- Keep normal Tier 1 visible-inbox refresh bounded; benchmark or inspect query plans if the candidate set is broadened.

Tests:

- Hidden-to-visible mutation on disk appears in a visible query without a full rebuild.
- Waiting-to-running mutation caused by deleting `waiting.json` is reflected without a full rebuild.
- `pending_question.json` creation and deletion are reflected without an explicit upsert.
- `done.json` creation on disk is reflected in recent completed results.
- Existing hidden anonymous workflow tests still pass.

Verification:

- From `../sase-core`: `cargo test -p sase_core agent_scan::index`
- If package names differ locally, run the equivalent `cargo test` subset for `agent_scan`.

## Phase 2: Runner-Owned Marker Lifecycle Hooks

Goal: every generic runner helper that mutates tracked markers refreshes the artifact row immediately after the
successful filesystem mutation.

Ownership:

- `src/sase/axe/run_agent_helpers.py`
- `src/sase/axe/run_agent_exec_plan_artifacts.py`
- `src/sase/axe/run_agent_exec_markers.py`
- `src/sase/axe/run_agent_wait.py`
- `src/sase/axe/run_agent_retry_spawn.py`
- `src/sase/axe/run_agent_runner.py`
- Focused tests under existing runner test files

Implementation:

- Call `update_agent_artifact_index_for_marker_mutation(artifacts_dir)` after successful writes/deletes in the files
  listed above.
- For helpers that can rewrite multiple files in one call, such as `normalize_handoff_interruption_state` and
  `update_step_marker_chat_path`, coalesce to one index update per artifact dir after at least one tracked marker
  changed.
- For `handle_questions_flow`, update after `pending_question.json` is written and again after it is removed.
- For `run_agent_wait`, update after each `waiting.json` write and after each successful `waiting.json` removal. Do not
  add an update for `ready.json` alone because it is not index-projected.
- For home-mode runner cleanup, update after `running.json` is successfully unlinked in the finalizer.
- Keep all index updates best-effort. Index update failures must not change runner outcomes.

Tests:

- Mock `sase.core.agent_artifact_index_lifecycle.update_agent_artifact_index_for_marker_mutation` or the imported symbol
  and assert it fires for each helper-level mutation.
- Existing `tests/test_run_agent_wait.py`, `tests/test_axe_run_agent_helpers.py`,
  `tests/test_axe_run_agent_retry_spawn.py`, and runner setup/finalize tests are good homes for these checks.

Verification:

- `just install` if the workspace has not been installed recently.
- Targeted pytest for the edited runner tests.

## Phase 3: Workflow And Inline `sase run` Visibility

Goal: workflows and inline runs are indexed from their first visible marker write through completion/failure.

Ownership:

- `src/sase/axe/run_workflow_runner.py`
- `src/sase/xprompt/workflow_executor.py`
- `src/sase/xprompt/workflow_runner.py`
- `src/sase/main/query_handler/_query.py`
- Workflow and query-run tests

Implementation:

- In `run_workflow_runner._write_workflow_state`, refresh after writing `workflow_state.json`. This covers initial
  workflow visibility and failure rewrites before `WorkflowExecutor` takes over.
- In `WorkflowExecutor._save_state`, refresh after writing `workflow_state.json`.
- In `WorkflowExecutor._save_prompt_step_marker`, refresh after writing any `prompt_step_*.json`.
- In `xprompt.workflow_runner._persist_failed_state`, refresh after writing `workflow_state.json`.
- In `main/query_handler/_query.py`, refresh after inline `agent_meta.json`, initial `workflow_state.json`, and final
  `done.json` writes.
- Avoid swallowing the original workflow/query exception because of an index failure; use the existing lifecycle
  helper's best-effort behavior.

Tests:

- A workflow row is visible from the first `_write_workflow_state` without requiring a child agent runner.
- Prompt-step marker writes update Tier 1 child rows.
- Inline `sase run` artifacts are visible and transition to done without a full rebuild.
- Failure-state workflow writes are visible in Tier 1.

Verification:

- Targeted workflow executor and workflow runner pytest files.
- Include at least one Tier 1 loader integration assertion through `load_tiered_agents(full_history=False)`.

## Phase 4: User-Driven And External Entry Points

Goal: marker edits initiated by the TUI, mobile bridge, CLI helpers, and stale-running cleanup update the index just
like runner-owned edits.

Ownership:

- `src/sase/ace/tui/actions/rename.py`
- `src/sase/ace/tui/actions/agents/_approve.py`
- `src/sase/ace/tui/actions/agents/_notification_plan_persistence.py`
- `src/sase/integrations/_mobile_notification_side_effects.py`
- `src/sase/ace/tui/actions/agents/_wait_resume.py`
- `src/sase/agent/running.py`
- `src/sase/ace/tui/models/_loaders/_running_loaders.py`
- Targeted TUI/mobile/agent-running tests

Implementation:

- After manual rename writes `agent_meta.json`, refresh the index.
- After auto-approve toggle writes `agent_meta.json`, refresh the index while preserving worker-thread error reporting.
- After TUI and mobile plan approval writes `agent_meta.json`, refresh the index.
- After wait dependency edits write `waiting.json`, refresh the index. `ready.json` writes remain out of scope because
  they are not index-projected.
- After named kill or stale-running cleanup deletes home-mode `running.json`, refresh the index for that artifact dir.
- Keep UI state updates optimistic where they already are; index refresh is a side effect, not a UI-blocking operation.

Tests:

- TUI rename persists through a Tier 1 reload.
- Auto-approve toggle and plan approval metadata persist through a Tier 1 reload.
- Mobile approval updates Tier 1-visible plan metadata.
- Wait dependency edits update Tier 1-visible waiting fields.
- Home-mode stale `running.json` deletion no longer leaves a stale Tier 1 running row.

Verification:

- Targeted tests for `test_agent_toggle_approve`, notification plan persistence, mobile notification side effects, wait
  resume, and running loader cleanup.

## Phase 5: Cleanup, Migration, And Regression Guardrails

Goal: deletion/migration paths do not leave stale rows, and future direct marker writers are easier to catch.

Ownership:

- `src/sase/ace/tui/actions/agents/_killing_utils.py`
- `src/sase/ace/tui/actions/agents/_loading_compute.py`
- `src/sase/agent/names/_migration.py`
- `src/sase/agent/names/_wipe.py`
- Cross-cutting regression tests

Implementation:

- Centralize index deletion for artifact marker cleanup. The safest direction is for `delete_agent_artifacts` to delete
  the artifact index row itself, then simplify or leave existing caller-side deletes as idempotent duplicates.
- Ensure loader self-heal cleanup in `_loading_compute.py` cannot delete loader-visible marker files without also
  removing the row.
- In `wipe_agent_name_for_reuse`, delete index rows for artifact dirs removed by `_remove_artifact_dirs`.
- In the historical auto-name migration, collect artifact directories whose tracked marker files changed and upsert
  those rows after the rewrite pass. If dismissed bundle payloads change, also sync the dismissed projection.
- Add a regression test or audit helper that inventories direct writes/deletes of tracked marker names and fails on
  unreviewed new sites. Keep an explicit allowlist for read-only uses and non-projected files.

Tests:

- Loader cleanup of dismissed artifacts deletes the Tier 1 row.
- Forced name reuse removes index rows for deleted artifact dirs.
- Historical name migration upserts changed artifact rows.
- The audit/allowlist test catches a synthetic new direct writer or at least verifies all current direct writers are
  intentionally covered.

Verification:

- Targeted cleanup and migration tests.
- Run the direct-writer audit command manually:
  `rg -n "agent_meta\\.json|done\\.json|running\\.json|waiting\\.json|pending_question\\.json|workflow_state\\.json|plan_path\\.json|prompt_step_" src/sase -g '*.py'`
- Final full verification after all phases land:
  - `just install`
  - `just check`
  - Rust `cargo test` subset from Phase 1

## Final Acceptance Criteria

- Every tracked marker write/delete found in this audit either calls the lifecycle helper directly, goes through a
  helper that does, or is documented as read-only/non-projected.
- Artifact directory deletion paths delete the matching index row.
- `pending_question.json` is part of the Rust index signature model.
- Query-time self-heal can recover stale hidden/status rows that would otherwise be filtered before refresh.
- Tier 1 visible-inbox loads reflect plan/question/wait/workflow/inline-run/home-running transitions without a manual
  full rebuild.
- `just check` passes in this repo, and the relevant `sase-core` tests pass in the sibling repo.
