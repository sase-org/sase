---
create_time: 2026-05-12 18:26:51
status: wip
prompt: sdd/prompts/202605/agent_launch_failed_rows.md
bead_id: sase-39
tier: epic
---
# Plan: Agent Launch Failures Always Produce Agent Rows

## Goal

After a user submits a non-empty prompt from `sase ace`, every attempted agent/workflow launch should produce a visible
Agents-tab row. If the launch fails before a subprocess or runner can write its normal markers, SASE should persist a
terminal `FAILED` row with the submitted prompt, useful error context, and enough launch metadata for the detail panel
to explain what happened.

This plan intentionally splits the work into independently assignable phases. Each phase should be executed by a
separate agent instance and should leave the repo in a passing state.

## Research Baseline

Use `sdd/research/202605/tui_agent_launch_failed_rows.md` as the primary context. The key finding is that rendering is
mostly already supported: a timestamped artifact directory containing `done.json` plus `raw_xprompt.md` can load as a
`FAILED` row through `load_all_agents()`, and failed `workflow_state.json` can load as a failed workflow row. The
missing piece is durable attempt recording before ordinary row sources exist.

Relevant code entry points:

- TUI submit/body: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py`,
  `src/sase/ace/tui/actions/agent_workflow/_launch_start.py`, `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`
- Fan-out surfaces: `_launch_multi_prompt.py`, `_launch_multi_model.py`, `_launch_repeat.py`
- Shared launch executor/spawn: `src/sase/agent/launch_executor.py`, `src/sase/agent/launch_spawn.py`
- Multi-prompt shared launcher: `src/sase/agent/multi_prompt_launcher.py`
- Workflow subprocess launch: `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py`
- Existing marker helpers/loaders: `src/sase/artifacts.py`, `src/sase/axe/run_agent_phases.py`,
  `src/sase/ace/tui/models/_loaders/_done_loaders.py`, `src/sase/ace/tui/models/_loaders/_workflow_loaders.py`,
  `src/sase/xprompt/workflow_runner.py`

## Design Principles

1. Record the attempt at the first point where the system knows enough to make a meaningful row.
2. Prefer one shared failed-attempt writer over one-off JSON snippets in TUI catch blocks.
3. For fan-out launches, prefer one failed row per planned slot whenever a slot exists. A parent summary notification
   may remain as a complement, but it should not be the only durable user-facing record.
4. Do not require a live workspace claim or child PID for a failed row.
5. Keep refresh explicit. The Agents tab is debounced, not filesystem-watched, so TUI integrations must call
   `request_agents_refresh("launch")` via `call_later` from worker threads.
6. Treat all runtimes uniformly. The fix should not branch on Claude/Gemini/Codex/Qwen/OpenCode behavior.

## Phase 1: Failed Launch Artifact Foundation

Owner: first implementation agent.

Add a small shared backend helper for durable failed agent launch attempts, without wiring it into every launch path
yet.

Scope:

- Add a module such as `src/sase/agent/launch_failures.py`.
- Define a compact input type, for example `FailedLaunchAttempt`, that can be built from known launch fields.
- Provide constructors/adapters for:
  - `PromptContext`-like fields from TUI validation/catch branches.
  - `LaunchExecutionContext` + fan-out slot data, when a full `LaunchSpawnRequest` does not exist yet.
  - `LaunchSpawnRequest`, when the executor has already resolved timestamp/workspace/workflow.
- Write:
  - `<artifacts>/raw_xprompt.md` with the exact user/slot prompt.
  - `<artifacts>/done.json` with `outcome="failed"`, `error`, `traceback`, `project_file`, `cl_name`, workspace fields,
    timestamp fields, and `output_path` when known or derivable.
  - `<artifacts>/agent_meta.json` with known launch metadata such as `name`, `model`, `llm_provider`, `vcs_provider`,
    `launch_phase`, `launch_kind`, `slot_index`, `display_name`, and any VCS ref.
- Use existing helpers where practical:
  - `create_artifacts_directory()`
  - `convert_timestamp_to_artifacts_format()`
  - `build_done_marker()`
- Make the writer idempotent enough that multiple nearby failure handlers do not corrupt an existing terminal marker. If
  the target artifact directory already has a live/richer marker, avoid overwriting it.

Tests:

- Add helper-level tests in a focused new test file.
- Add at least one loader-level contract test that writes a real failed artifact under a temp `SASE_HOME`/home fixture
  and proves `load_all_agents()` or the lower-level done loader returns a `FAILED` row with prompt/error fields.
- Assert timestamp directory names remain 14-digit `YYYYmmddHHMMSS` after passing launcher timestamps like
  `YYmmdd_HHMMSS`.

Verification:

- `just install`
- Targeted pytest for the new tests
- `just check`

Deliverable:

- Shared failed-attempt writer plus tests. No broad TUI behavior changes are required in this phase.

## Phase 2: Single-Prompt Launch Guarantee

Owner: second implementation agent.

Wire the Phase 1 helper into the normal single-agent TUI path so validation, launch-preparation, spawn, claim, and
worker escape failures create failed rows.

Scope:

- Update `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`.
- Record failed rows for:
  - single `%name`/launch-name validation failures,
  - exceptions escaping `_run_agent_launch_body_async()`,
  - low-level spawn failures around the single `execute_launch_plan()` call.
- Extend `src/sase/agent/launch_executor.py` with an optional slot-failure callback if needed. The callback should be
  invoked with the best available context for:
  - validation failure before `LaunchSpawnRequest` exists,
  - workspace preclaim/allocation exhaustion,
  - spawn callback failures, including `prepare_agent_launch()`, `spawn_prepared_agent_process()`, and claim transfer
    failures surfaced through `spawn_agent_subprocess()`.
- Ensure the TUI calls `request_agents_refresh("launch")` after writing a failed marker.
- Keep the existing toast behavior; the row is additive, not a replacement.

Tests:

- Single validation failure records a `FAILED` row and `raw_xprompt.md`.
- A mocked spawn/prepare failure records a `FAILED` row with exception summary and traceback.
- A mocked workspace claim exhaustion records a `FAILED` row.
- Refresh is requested from the TUI path after recording.

Verification:

- `just install`
- Targeted tests for launch body/executor failure paths
- `just check`

Deliverable:

- A submitted single prompt should never vanish as a toast-only failure once `_prompt_context` exists.

## Phase 3: Fan-Out and Multi-Prompt Guarantees

Owner: third implementation agent.

Apply the same failed-row contract to all prompt expansion paths that produce multiple child launch attempts.

Scope:

- Update:
  - `src/sase/ace/tui/actions/agent_workflow/_launch_multi_prompt.py`
  - `src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py`
  - `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py`
  - `src/sase/agent/multi_prompt_launcher.py`
  - `src/sase/agent/launch_executor.py` if Phase 2 left only single-path support.
- Preserve `_record_fanout_launch_failure()` notifications for now, but add Agents-tab rows alongside them.
- Prefer per-slot failed rows once a fan-out plan/slot exists:
  - `%m` / `%alt`: one row per planned model/alt slot that fails before spawn.
  - `%r`: one row per repeat slot that fails before spawn; `NameCollisionError` should become a failed row with the
    original repeat prompt and collision text.
  - multi-prompt: spawned segments continue to appear normally; the failed segment/slot gets a failed row.
- If failure occurs before slots can be materialized, record a single parent failed row with `launch_kind` and
  `slot_count` metadata.
- Ensure worker-thread paths request an Agents-tab refresh through `call_later`.

Tests:

- Multi-prompt validation failure records at least a parent failed row, or per-segment rows if slots are available.
- Partial multi-prompt failure records normal rows for already-spawned children and one failed row for the failed slot.
- Prompt fan-out exception records failed row(s) and still records/refreshes the existing notification.
- Repeat `NameCollisionError` records a failed row.
- Executor slot-failure callback receives enough context to write deterministic timestamps and workflow names.

Verification:

- `just install`
- Targeted fan-out/multi-prompt/repeat tests
- `just check`

Deliverable:

- Any user submission that expands into multiple agent attempts should have visible rows for successful and failed
  slots, with no slot disappearing silently before spawn.

## Phase 4: Workflow Launch Failure Rows

Owner: fourth implementation agent.

Close the workflow subprocess gaps where an artifact directory already exists but the TUI only shows a toast.

Scope:

- Update `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py`.
- For project-scoped workflow subprocesses:
  - on `subprocess.Popen` failure, write a failed `workflow_state.json` under the already-created `artifacts_dir`;
  - on `claim_workspace()` failure after `Popen`, terminate the process as today and write failed workflow state;
  - include workflow name, project/CL context, error text, start time, artifacts dir, and any step prompts available.
- Consider exposing/reusing a small public helper around
  `src/sase/xprompt/workflow_runner.py::_write_failed_workflow_state()` rather than importing a private function
  directly from TUI code.
- For home-thread workflow start failures, record failed workflow state when `artifacts_dir` exists before execution.
- Request Agents-tab refresh after writing failed workflow state.

Tests:

- Mocked `Popen` failure produces a failed workflow row through `load_workflow_states()`.
- Mocked `claim_workspace()` failure produces a failed workflow row and still terminates the child process.
- Home-mode workflow thread start failure writes failed state when possible.

Verification:

- `just install`
- Targeted workflow launch tests
- `just check`

Deliverable:

- Standalone workflow launch failures are visible as failed workflow rows instead of toast-only errors.

## Phase 5: Contract Hardening and Rust/Wire Alignment

Owner: fifth implementation agent.

Harden the launch-attempt contract now that the Python/TUI behavior works, and align the boundary types so future launch
surfaces do not reintroduce invisible failures.

Scope:

- Update `src/sase/core/agent_launch_wire.py` and `src/sase/core/agent_launch_facade.py` with a wire shape for failed
  launch attempts, such as `FailedLaunchAttemptWire`, if earlier phases did not already do this.
- If the corresponding behavior belongs in Rust core, update `../sase-core/crates/sase_core` plus Python bindings rather
  than duplicating backend rules in Python. Keep this focused on schema/contract support unless the Rust planner is
  already the natural owner of the logic.
- Tighten broad exception swallowing in `_launch_body.py` around `resolve_agent_refs_in_prompt()`:
  - keep expected unresolved-reference behavior;
  - turn unexpected resolver failures into failed rows rather than silent pass-throughs.
- Add regression tests around serialization/deserialization of the new wire records.
- Review loader/detail-panel display for `launch_phase`, `launch_kind`, and slot metadata. Add display support only if
  the existing error/prompt panels do not show enough context.
- Add a short entry to the research note or implementation docs summarizing the final contract and covered launch
  surfaces.

Tests:

- Wire round-trip tests for failed-attempt records.
- A regression test proving unexpected VCS resolver errors become failed rows.
- Loader/detail tests if metadata display changes.

Verification:

- `just install`
- Rust-side tests/checks if `../sase-core` changes
- `just check`

Deliverable:

- The invariant is encoded in shared launch contracts and protected against future TUI/CLI/mobile launch surfaces.

## Phase Acceptance Checklist

Every phase agent should finish with:

- No unrelated rewrites or formatting churn.
- New tests focused on the phase’s failure class.
- `just install` before repo checks.
- `just check` passing unless a blocker is explicitly documented.
- A final summary listing the newly guaranteed failure paths and any remaining phases.

## Final Acceptance Criteria

The full project is done when these scenarios all create visible failed rows with useful selected-row context:

- Single-prompt validation failure.
- Single-prompt launch preparation/spawn/claim failure.
- Unexpected launch worker exception after prompt submission.
- Multi-prompt validation failure.
- Multi-prompt partial failure.
- Prompt fan-out (`%m` / `%alt`) failure.
- Repeat (`%r`) name collision and generic launch failure.
- Workflow subprocess `Popen` failure.
- Workflow workspace-claim failure.
- Unexpected VCS reference resolver failure.

At completion, the Agents tab should no longer have a known TUI path where a submitted non-empty prompt can fail before
creating either a normal running row or a terminal failed row.
