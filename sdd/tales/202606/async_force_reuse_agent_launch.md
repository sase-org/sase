---
create_time: 2026-06-13 10:49:57
status: done
prompt: sdd/prompts/202606/async_force_reuse_agent_launch.md
---
# Plan: Move forced agent-name reuse cleanup into the tracked launch task

## Goal

Keep the ACE TUI responsive when launching an agent with forced name reuse syntax such as `%name:!foo`. The existing
launch path already submits normal launch work to a tracked background task, but `_finish_agent_launch()` currently
performs the forced-reuse name wipe on the Textual event-loop thread before submitting that task. That wipe can scan
artifacts, remove directories/bundles, dismiss notifications, rebuild the name registry, and release workspaces, so it
belongs in the same tracked launch worker as the rest of the launch body.

## Current shape

- `src/sase/ace/tui/actions/agent_workflow/_launch_start.py` unmounts the prompt bar and submits
  `_run_agent_launch_body()` through `_submit_launch_task()`.
- Before that submission, it detects `%name:!<name>`, calls `wipe_names_for_forced_reuse()`, rewrites the prompt to
  `%name:<name>`, and records a failed prompt synchronously on wipe failure.
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` already runs in the tracked task worker and performs the
  blocking launch pipeline.
- `src/sase/agent/names/_wipe.py` confirms the wipe is heavy filesystem/process/index work and must not stay on the UI
  thread.
- Existing tests in `tests/ace/tui/test_agent_launch_non_blocking.py` assert the old synchronous forced-reuse behavior
  and should be updated to guard the new contract.

## Proposed change

1. Move forced-reuse preparation out of `_finish_agent_launch()`.
   - Keep only cheap prompt-context checks, launch timestamp reservation, prompt bar unmount, toast, and tracked task
     submission in `_finish_agent_launch()`.
   - Submit the original prompt text to the launch task so `%name:!` handling happens in the worker.

2. Add a small worker-side preparation step before the existing launch-body pipeline.
   - In `_run_agent_launch_body()`, detect `force_reuse_owner_names([prompt])` near the start, before
     `submitted_xprompt` is captured and before prompt history or launch validation.
   - If forced reuse is present, call `wipe_names_for_forced_reuse()` in the worker, then rewrite the prompt with
     `rewrite_force_reuse_name_directives()`.
   - Capture the original submitted prompt separately so wipe failures can record the prompt the user actually
     submitted, while successful launches persist the rewritten prompt in the same way the current TUI behavior does.

3. Preserve existing user-visible semantics.
   - `%name:!foo` should still be treated as explicit TUI confirmation, not as a non-TUI validation error.
   - The low-level validation should continue to see `%name:foo` after rewrite, so collision checks happen after the old
     owner has been wiped.
   - Wipe failure should produce the existing `"Agent name reuse failed (see log)"` error outcome and should not launch
     an agent.
   - Prompt bar unmount and launch task submission should still happen immediately, making the task visible in the task
     indicator and Task Queue modal while cleanup runs.

4. Keep UI mutations on the UI thread.
   - The worker should return a `LaunchTaskOutcome` for failure/success rather than calling UI methods directly.
   - Existing completion handling in `_on_launch_task_complete()` can apply notifications, refreshes, and launch result
     deltas.

5. Update focused tests.
   - Change `test_finish_agent_launch_force_reuse_wipes_and_schedules_rewritten_prompt` so `_finish_agent_launch()` only
     submits a task with the original forced-reuse prompt; assert `wipe_names_for_forced_reuse()` is not called until
     `task_callable()` runs, and assert the body receives the rewritten prompt.
   - Change `test_finish_agent_launch_force_reuse_wipe_failure_does_not_schedule` into a worker-task failure test:
     `_finish_agent_launch()` should still submit a task, and invoking the task should record the original `%name:!foo`
     prompt and return an error outcome.
   - Add or adjust an assertion that the forced-reuse wipe happens off the `_finish_agent_launch()` path to prevent
     future regressions.
   - Run the targeted TUI launch tests first, then the repo-required check command after file changes.

## Risks and mitigations

- **History prompt shape:** Current successful TUI forced-reuse launches appear to save the rewritten `%name:foo`
  prompt. The plan keeps that behavior by rewriting before `submitted_xprompt` is set.
- **Failure accounting:** Moving failure handling into the task means the task queue should show a failed launch record.
  That is desirable and consistent with other launch failures, but tests should assert the user still gets the existing
  error notification.
- **Context mutation:** `_run_agent_launch_body()` mutates `_prompt_context` during launch. The forced-reuse preparation
  should run before those mutations and should return early on wipe failure so no partial launch state advances.
- **Validation ordering:** Validation must stay after rewrite. Otherwise `%name:!foo` would still raise
  `AgentNameReuseConfirmationRequiredError` inside the worker.

## Verification

- `pytest tests/ace/tui/test_agent_launch_non_blocking.py`
- If source files are changed, run the repo-required `just check` after `just install` if the workspace environment
  needs installation.
