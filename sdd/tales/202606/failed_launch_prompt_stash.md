---
create_time: 2026-06-19 09:14:48
status: done
prompt: sdd/prompts/202606/failed_launch_prompt_stash.md
---

# Failed Launch Prompt Stash Plan

## Goal

Any failed SASE agent launch that still has access to the submitted prompt must preserve that prompt in the existing
prompt-input-widget stash store, so a long prompt is recoverable with `gp` / `gP` after the prompt bar has already been
unmounted.

The immediate regression is a project-alias conflict during launch canonicalization. In ACE, that exception can escape
the launch body before the normal failed-history branches run, so the user only sees the long error and the submitted
prompt is gone.

## Current Behavior

- The prompt stash is a per-user Rust-backed JSONL store at `~/.sase/prompt_stash.jsonl`, exposed through
  `sase.core.prompt_stash_facade`.
- Manual stash is centralized in `PromptBarStashMixin._persist_stashed_panes()`. It writes one `PromptStashEntryWire`
  per stash action, with `text`, optional `frontmatter`, `project`, `source`, and `pane_index`.
- Launch failures usually call `sase.history.prompt.record_failed_launch_prompt(text)`, but that only updates prompt
  history. It does not append to the prompt stash.
- Several launch paths already call `record_failed_launch_prompt(...)` on explicit failure: single-agent
  validation/spawn failures, multi-prompt failures, prompt fan-out failures, repeat failures, CWD launch
  validation/spawn failures, and planned bead-work launch failures.
- Some important failures do not currently reach that helper: project-alias canonicalization failures in
  `AgentLaunchBodyMixin._run_agent_launch_body_async()`, early CWD canonicalization failures, bulk-launch top-level
  failures, and some workflow-launch start/claim failures.
- TUI launch work runs through tracked background tasks. Unexpected worker exceptions become payloadless failed task
  completions, so the completion handler cannot stash the prompt unless the launch task records the submitted prompt as
  metadata up front.

## Design

Add one reusable failed-launch stash adapter and wire it at the existing failed-launch boundaries.

1. Create a best-effort helper for failed-launch stash writes.
   - Add a small module near the launch/history boundary, for example `sase.agent.failed_launch_prompt_stash`.
   - Provide `stash_failed_launch_prompt(prompt: str, *, project: str | None = None, source: str = "failed_launch")`.
   - Skip blank prompts.
   - Never raise. Any stash-store failure should be logged at warning/debug level and must not replace the original
     launch error.
   - Write through `append_prompt_stash(prompt_stash_path(), PromptStashEntryWire(...))` so the existing Rust-backed
     store remains the only persistence mechanism.
   - Preserve xprompt/frontmatter semantics by extracting a leading YAML frontmatter block into the entry `frontmatter`
     field and storing only the prompt body in `text`. Keep multi-prompt bodies joined with the canonical `\n---\n`
     separator so restore expands them as normal bundle rows.
   - Use `source="failed_launch"` and `pane_index=0`. Do not change the prompt-stash wire schema or Rust store.

2. Make `record_failed_launch_prompt(...)` stash as well as write history.
   - Extend `sase.history.prompt_store.record_failed_launch_prompt` to call the new helper after the history mutation.
   - Add optional keyword metadata, most likely `project: str | None = None`, while preserving the current positional
     call shape.
   - Existing callers automatically get stash preservation with minimal churn.
   - Update high-context launch callers opportunistically to pass `project=...` when already available, but do not make
     project metadata required for recovery.

3. Cover failures that currently bypass failed-history recording.
   - In `AgentLaunchBodyMixin._run_agent_launch_body_async()`, call `record_failed_launch_prompt(prompt, project=...)`
     inside the broad exception handler before logging/notifying. This directly fixes the project-alias-conflict case.
   - In `launch_agents_from_cwd_impl()`, protect the early alias-canonicalization step so an alias-map conflict records
     and stashes the original submitted query before re-raising.
   - In `launch_planned_bead_work_agents()`, protect normalization/canonicalization so planned bead-work prompt segments
     are stashed if alias resolution or pre-launch validation fails before the existing catch blocks.
   - In `BulkLaunchMixin._run_bulk_launch()`, stash the shared submitted prompt once when the bulk launch has any failed
     slot, and also in the top-level exception branch.
   - For workflow launch start/claim failures that originate from a prompt bar submission, thread an optional
     `submitted_prompt` through `_try_execute_workflow()`, `_execute_workflow_in_thread()`, and
     `_launch_workflow_subprocess()` so those failures can call the same helper with the original `#workflow(...)`
     prompt.

4. Preserve payloadless tracked launch failures when the prompt is known.
   - Extend `LaunchTaskOutcome` or `LaunchTaskMixin._submit_launch_task()` with optional submitted-prompt metadata.
   - Pass that metadata from fan-out launch task submissions (`multi_prompt`, `fanout`, `repeat`, and `bulk`) because
     their workers can fail before returning a `LaunchTaskOutcome`.
   - In `_on_launch_task_complete()`, if the launch task failed with no payload and has submitted-prompt metadata, call
     the failed-launch prompt recorder/stasher off the Textual event loop before showing the existing failure
     notification.
   - Keep the generic task queue unchanged; this is launch-specific metadata, not a new task-queue contract.

5. Refresh ACE's prompt-stash badge after failed launches without blocking the event loop.
   - Add a small async/scheduled badge refresh helper that reads `_read_prompt_stash_count()` via `asyncio.to_thread()`
     and then applies `_apply_prompt_stash_count()` on the UI thread.
   - Trigger it after launch-task completions whose outcome is an error or warning, and after payloadless launch-task
     failures that stash a prompt.
   - Keep manual stash behavior unchanged. Avoid synchronous stash reads in launch completion handlers.

## Tests

Add focused regression coverage before broadening to the full suite.

1. Unit-test the failed-launch stash helper.
   - Stashes a long prompt into `prompt_stash.jsonl` with `source="failed_launch"`.
   - Extracts leading xprompt/frontmatter into `frontmatter` and stores the body as `text`.
   - Preserves multi-prompt bodies as one bundle row.
   - Skips blank prompts.
   - Swallows missing Rust binding / append failures.

2. Extend prompt-history tests.
   - `record_failed_launch_prompt("...")` still force-cancels prompt history.
   - The same call also appends exactly one failed-launch stash entry.
   - Existing short prompt behavior such as `#gh:foo` remains preserved.

3. Extend ACE launch-failure tests.
   - A project-alias conflict raised from `canonicalize_project_aliases_in_prompt()` in the launch body records failed
     history and appends a failed-launch stash row containing the original long prompt.
   - Single-agent spawn failure, multi-prompt failure, prompt fan-out failure, repeat failure, and bulk partial failure
     each leave a restorable stash row.
   - Keep-bar single-pane failure stashes only the submitted pane text, not other panes still mounted in the prompt
     stack.
   - Payloadless launch-task failure with submitted-prompt metadata stashes the prompt and refreshes the badge.

4. Extend non-TUI launch tests.
   - `launch_agents_from_cwd()` stashes the original query when early alias canonicalization raises.
   - Planned bead-work launch stashes the normalized joined prompt when pre-launch canonicalization/validation fails.
   - Mobile launch can rely on `launch_agents_from_cwd()` for stash preservation; no mobile-specific persistence path
     should be added.

## Verification

After implementation:

1. Run `just install` first in this ephemeral workspace.
2. Run focused tests:
   - `pytest tests/history/test_prompt_cancelled.py`
   - `pytest tests/ace/tui/test_agent_launch_dispatch.py tests/ace/tui/test_launch_failure_logging.py`
   - `pytest tests/ace/tui/test_launch_multi_prompt.py tests/ace/tui/test_launch_multi_model.py tests/ace/tui/test_launch_repeat_bulk.py`
   - `pytest tests/ace/tui/actions/test_prompt_stash_handler.py tests/ace/tui/actions/test_prompt_stash_restore.py`
   - Relevant CWD/bead launch tests for alias/canonicalization failure coverage.
3. Run formatting on touched files.
4. Run `just check`.
5. Run `git diff --check`.

## Non-Goals

- No prompt-stash Rust wire schema migration.
- No new keymaps, prompt-stash modal redesign, or help-popup changes.
- No attempt to deduplicate old already-stashed rows.
- No change to successful-launch prompt history behavior.
- No user-facing retry automation; the recovery path is the existing prompt stash restore/load flow.

## Risks And Mitigations

- Duplicate stash rows are possible if the same prompt is recorded by nested failure handlers. Prefer wiring the new
  behavior through `record_failed_launch_prompt(...)` and adding missing record calls only where no existing call can
  run. If duplicates appear in tests, introduce a narrowly scoped per-launch attempt guard rather than a global
  cross-session dedupe.
- Project metadata will be best-effort. Losing the `project` chip is acceptable; losing the prompt text is not.
- Stash writes add disk I/O on failure paths. These paths already run in worker threads in ACE; any badge refresh must
  remain off the event loop.
- The stash append depends on the Rust binding. The helper must degrade exactly like manual stash error handling:
  preserve the original launch error and never crash while trying to preserve the prompt.
