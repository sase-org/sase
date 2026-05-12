# TUI Agent Launch Failures Should Always Create Rows

## Question

The target behavior is: once a user submits a non-empty prompt in `sase ace` to run an agent, the Agents tab should get
a new row for that attempt. If the attempt fails before a live agent exists, the row should be terminal `FAILED` and
selection should show useful context: the submitted prompt, the failure summary/traceback when available, and any launch
context that helps the user understand what happened.

That target is not met today. The current launch path only creates an Agents-tab row after one of the existing row
sources exists:

- a project-file RUNNING claim,
- a home-mode `running.json` (see `src/sase/agent/running.py` and `_running_loaders.py`),
- an artifact `done.json`,
- an artifact `workflow_state.json`,
- or a ChangeSpec HOOKS/MENTORS/COMMENTS suffix.

Pre-spawn failures often produce only a toast and a log entry. There is one partial exception — multi-model fan-out
failures write a notification report (see [Prior art](#prior-art-record_fanout_launch_failure)) — but that surface is
the **notification inbox**, not the Agents tab, and it covers only one of several failure classes.

The TUI is currently the only launch surface in this repo. There is no `src/sase/cli/` launch path, no mobile/remote
launch entrypoint, and no scheduled/cron launcher today. All changes recommended below are therefore scoped to the TUI
launch lifecycle and the shared `src/sase/agent/` + `src/sase/core/` launch internals.

## Current Launch Path

The TUI submit path is:

1. `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py` forwards non-empty prompts into
   `_finish_agent_launch()`.
2. `src/sase/ace/tui/actions/agent_workflow/_launch_start.py:82-95` reserves a timestamp, unmounts the prompt bar, and
   schedules `_run_agent_launch_body_async()`.
3. `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` resolves VCS refs, history, workflows, fan-out, repeat, and
   final single-agent spawn.
4. Single-agent spawn goes through `execute_launch_plan()` in `src/sase/agent/launch_executor.py:136-196`, then
   `spawn_agent_subprocess()` in `src/sase/agent/launch_spawn.py:73-284`.
5. `spawn_agent_subprocess()` creates the child process and only then claims the workspace in its claim callback
   (`src/sase/agent/launch_spawn.py:181-228`). That claim is what makes non-home running agents appear immediately.
6. Once the child starts, `src/sase/axe/run_agent_runner_setup.py:42-83` writes initial `workflow_state.json`, and
   `src/sase/axe/run_agent_runner.py:316-347` writes a failed `done.json` if runner execution raises.

## What the Agents-Tab Loader Actually Needs

The Agents tab already knows how to display terminal failures. The key surfaces and the exact fields each one consumes
are below; this defines the minimum schema for any "failed launch attempt" artifact.

`src/sase/ace/tui/models/_loaders/_done_loaders.py:104-157` builds an `Agent` from `done.json`. For a `FAILED` row it
reads:

- `outcome` — must be `"failed"` (`"noop"` is skipped; anything else becomes `DONE`).
- `cl_name`, `project_file`, `workspace_num`, `workspace_dir`, `output_path`.
- `error`, `traceback` → `error_message`, `error_traceback` on the `Agent` model.
- Optional: `model`, `llm_provider`, `vcs_provider`, `name`, `hidden`, `approve`, `step_output`,
  `retried_as_timestamp`, `retry_chain_root_timestamp`, `retry_error_category`.

The artifact directory **name** must be a 14-digit `YYYYmmddHHMMSS` timestamp; the loader parses it with
`parse_timestamp_14_digit()` to get `start_time`.

`src/sase/ace/tui/models/_loaders/_workflow_loaders.py:115-124` maps a `workflow_state.json` with `status: "failed"`
into `FAILED`. `_workflow_loaders.py:199-208` pulls workflow-level or step-level error text for the detail panel.

`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` and `_agent_display_parts.py` already render raw prompt, error
text, traceback, and output paths when the Agent model has them. They read `raw_xprompt.md` from the artifact directory
to show the submitted prompt.

So the missing piece is **persistence before live process creation**, not list rendering. A correctly-shaped
`<artifact_dir>/done.json` plus `<artifact_dir>/raw_xprompt.md` is sufficient to render a useful FAILED row.

### Agents-list refresh is debounced, not watched

`src/sase/ace/tui/actions/agents/_loading.py:462-497` defines `request_agents_refresh(source, debounce_ms=150,
latest_only=True)`. It coalesces a burst of refresh requests into a single 150 ms-delayed
`_schedule_agents_async_refresh()`. There is **no filesystem watcher**; the only triggers are explicit caller invocation,
tab-switch, and periodic refresh. Any helper that writes a failed-attempt artifact MUST call
`request_agents_refresh("launch")` (or schedule it on the UI thread via `call_later`) or the row will not appear until
the next manual refresh.

## Prior Art: `_record_fanout_launch_failure`

`src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py:132-227` already records prompt fan-out failures, but it
writes a **notification**, not an Agents-tab row:

- `_write_fanout_failure_report()` writes a plain-text report to
  `~/.sase/notifications/fanout_failures/prompt_fanout_failure_<timestamp>.txt`.
- `append_notification()` adds a `Notification` with `action="ViewErrorReport"` so the user can read it from the
  notification inbox.

This solves the "lost context" half of the problem for one failure class. It does not solve "row on the Agents tab",
and it does not produce a row per planned slot. It is the right shape conceptually (single function, accepts
`PromptContext`, structured fields) and should be the starting point that the new helper either subsumes or augments.

## Gaps Found

### Pre-spawn validation creates no row

`_launch_body.py:142-162` validates multi-prompt name requests with `validate_launch_name_requests(multi.segments)`. On
`RuntimeError` it calls `add_or_update_prompt(..., cancelled=True)` and shows a toast, but writes no artifact.

`_launch_body.py:257-275` does the same for single-agent name validation.

`launch_executor.py:157-160` re-validates names inside `execute_launch_plan()` for every fan-out plan. Any exception
here happens before timestamps and requests are materialized for all slots, so callers cannot show per-slot rows unless
the executor (or a new failure callback) persists synthetic failed attempts.

### Worker-level exceptions create no row

`_launch_body.py:39-45` catches any exception escaping the launch worker and only notifies `"Agent launch failed (see
log)"`.

`_launch_body.py:491-498` catches single-agent low-level spawn failures and only notifies.

These failures include VCS resolution surprises, xprompt processing errors, Rust binding errors during launch
preparation, and workspace allocation failures that occur before a claim or child runner exists.

### Silent VCS resolution swallow

`_launch_body.py:122-127` catches any `Exception` from `resolve_agent_refs_in_prompt()` and `pass`-es ("Agent not
found — runner will resolve later"). For genuinely-missing agents this is fine because the runner will eventually emit
a `done.json`. But the same `except: pass` would swallow programming errors (binding crash, ImportError) that prevent
any runner from spawning. Worth tightening to a narrow exception class once the failed-attempt helper exists, so that
unexpected exceptions become rows.

### Subprocess preparation and claim failures create no row

`spawn_agent_subprocess()` derives an output path and prepares a Rust-backed launch request
(`src/sase/agent/launch_spawn.py:123-168`), then creates the child and claims/transfers the workspace
(`src/sase/agent/launch_spawn.py:181-258`).

If `prepare_agent_launch()`, `spawn_prepared_agent_process()`, `claim_workspace()`, or `transfer_workspace_claim()`
raises, the caller gets an exception before:

- a workspace RUNNING claim exists,
- the child writes `workflow_state.json`,
- the child writes `raw_xprompt.md`,
- or the child writes `done.json`.

`launch_executor.py:199-270` retries workspace claim races, but after retries are exhausted it raises
`WorkspaceClaimError`; the TUI catches it as a toast-only launch failure.

### Multi-prompt, prompt fan-out, and repeat have uneven failure recording

`_launch_multi_prompt.py:69-89` catches failures and only shows `"Multi-prompt launch failed (see log)"`.

`_launch_repeat.py:177-190` catches name-collision and generic repeat failures and only shows a toast.

`_launch_multi_model.py:108-127` is better: it writes a notification/report via `_record_fanout_launch_failure()` (see
[Prior art](#prior-art-record_fanout_launch_failure)). But the notification is not an Agents-tab row and it does not
preserve a row per slot.

`src/sase/agent/multi_prompt_launcher.py:55-65` defines `_MultiPromptPartialLaunchError` for already-spawned children,
but there is no terminal failed artifact for the segment or slot that failed before spawn. Already-spawned segments
appear as rows via the normal path; failed segments disappear.

### Workflow execution is closer, but start/claim failures still have gaps

Workflow subprocess launch creates `artifacts_dir` before `Popen`, and `src/sase/workflow/run_workflow_runner.py:112-114`
writes initial `workflow_state.json` early. `src/sase/workflow/workflow_runner.py:461-470` writes failed workflow state
for validation failures inside `execute_workflow()`.

The gap is in `_workflow_exec.py:303-347`: if `Popen` fails, or if `claim_workspace()` fails after `Popen`, the TUI only
notifies. `artifacts_dir` is already created, so this is the cheapest fix in the codebase — write a failed
`workflow_state.json` directly in those except branches.

## Recommended Design

Add a single durable "launch attempt failed" artifact writer and use it everywhere an attempted TUI launch can fail
before an ordinary row source exists.

### Artifact shape

Create an artifact directory whose name is a 14-digit timestamp (required by the loader's `parse_timestamp_14_digit()`):

```
<artifacts_root>/<workflow>/<YYYYmmddHHMMSS>/
    raw_xprompt.md      # the submitted user prompt verbatim
    done.json           # outcome=failed plus loader-required fields
    agent_meta.json     # minimal launch metadata (optional but recommended)
```

Use `src/sase/artifacts.py:45` `create_artifacts_directory(workflow_name, project_name=None, timestamp=None)` to derive
the directory. It already enforces the `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/` layout.

Use `src/sase/axe/run_agent_phases.py:599` `build_done_marker(...)` to build the `done.json` payload. Required fields
for the loader to produce a FAILED row:

- `outcome: "failed"`,
- `cl_name`, `project_file`,
- `workspace_num`, `workspace_dir` (use `None`/sentinel if not yet allocated — the loader tolerates missing values for
  most fields except `outcome` and `cl_name`),
- `output_path` if derivable from the artifact directory,
- `error` (one-line summary like `f"{type(exc).__name__}: {exc}"`),
- `traceback` (use `traceback.format_exc()` from the except branch),
- a new `launch_phase` field such as `"validation" | "spawn" | "claim" | "prepare" | "worker"` so the detail panel and
  later analytics can distinguish failure classes.

Mirror this shape through the Rust core boundary later. `src/sase/core/agent_launch_wire.py` is still Phase 1 (its top
comment notes "no production launch path consumes these records yet"), so this is the right moment to bake a
`FailedLaunchAttemptWire` (or equivalent on `AgentLaunchPreparedWire`) into the wire types before any consumer locks the
schema. The corresponding Rust core in `../sase-core/crates/sase_core/` does not currently model "failed launch
attempt"; it only has generic error variants. Aligning the wire and Rust types up front avoids a later cross-repo
change.

### Helper signature

A pragmatic first step is a Python helper that can be called from both TUI catch branches and the executor. It needs
the fields below (drawn from `src/sase/ace/tui/actions/agent_workflow/_types.py` `PromptContext` and
`src/sase/agent/launch_executor.py:35-50` `LaunchSpawnRequest`):

`PromptContext`: `project_name`, `cl_name`, `project_file`, `workspace_dir`, `workspace_num`, `workflow_name`,
`timestamp`, `history_sort_key`, `display_name`, `update_target`, `is_home_mode`.

`LaunchSpawnRequest`: adds `prompt`, `vcs_ref`, `deferred_workspace`, `local_xprompts_file`, `extra_env`,
`transfer_from_pid`.

Either type carries enough to write a failed-attempt artifact. Accept whichever the caller has.

Where this helper should live:

- The artifact schema and path derivation are backend/domain behavior shared by every launch surface (current TUI,
  future CLI/mobile/remote), so the long-term home should be in the launch/core boundary, not only in Textual UI code.
- A pragmatic first step is a helper near `src/sase/agent/launch_executor.py` or `src/sase/agent/launch_spawn.py`,
  backed by `create_artifacts_directory()` and `build_done_marker()`.
- If this becomes part of the normalized launch contract, mirror it through `src/sase/core/agent_launch_wire.py` and
  `src/sase/core/agent_launch_facade.py` so Rust-owned launch planning can return enough information to persist failed
  slots deterministically.

## Concrete Updates Needed

1. **Add `record_failed_launch_attempt(...)`** that accepts `PromptContext` or `LaunchSpawnRequest` fields, prompt,
   timestamp, phase, exception, and optional traceback. It should:
   - call `create_artifacts_directory()` with the reserved timestamp,
   - write `raw_xprompt.md` with the prompt body,
   - write `done.json` via `build_done_marker()` with `outcome="failed"` plus `error`, `traceback`, `launch_phase`,
   - write minimal `agent_meta.json` (mirror the keys produced by `src/sase/axe/run_agent_phases.py:35-155`
     `extract_directives_and_write_meta()`: `name`, `model`, `llm_provider`, `vcs_provider`, plus what is known at
     pre-spawn time),
   - call `request_agents_refresh("launch")` on the UI thread via `call_later`.
2. **Call the helper in `_launch_body.py`** for:
   - multi-prompt validation failure at lines 142-162,
   - single validation failure at lines 257-275,
   - generic worker escape at lines 39-45,
   - single low-level spawn exception at lines 491-498.
3. **Call it from fan-out launch surfaces**:
   - `_launch_multi_prompt.py:69-89`,
   - `_launch_multi_model.py:108-127` — keep the notification, add a row (or rows) alongside it,
   - `_launch_repeat.py:177-190`.
4. **Extend `execute_launch_plan()` or add an optional `on_slot_failure` callback** so fan-out callers can persist one
   failed row for the slot that could not be spawned. This is cleaner than asking every caller to reconstruct slot
   timestamps, workflow names, and spawn requests after `execute_launch_plan()` raises.
5. **In `_workflow_exec.py:303-347`, write failed `workflow_state.json`** for `Popen` failure and claim failure. The
   `artifacts_dir` is already created, so this can reuse `_write_failed_workflow_state()` (or the equivalent helper
   inside `workflow_runner.py:461-470`) directly. This is the cheapest gap to close.
6. **Tighten `_launch_body.py:122-127`** once the helper exists: narrow the `except Exception` to the specific
   "agent ref unresolved" exception so programming errors become failed rows rather than silently passing.
7. **Decide the fan-out contract** (see [open design choice](#open-design-choice)) before extending
   `execute_launch_plan()`.

## Suggested Test Coverage

There are no existing tests asserting that a failed artifact directory renders as a `FAILED` row through the loader.
The closest pattern is `tests/test_agent_loader_dedup_pid.py`, which mocks `load_done_agents_from_snapshot` rather than
writing artifacts on disk. New tests should construct real artifacts in a tmp `SASE_HOME` and call `load_all_agents()`
end-to-end, so the contract verified is "user sees a row" not "we wrote a file":

- Single prompt `%name` collision from the TUI launch body writes `done.json` + `raw_xprompt.md` and loads as `FAILED`
  via `load_done_agents_from_snapshot()` / `load_all_agents()`.
- `execute_launch_plan()` workspace exhaustion in the TUI single path writes one failed `ace-run` row with the original
  prompt and `WorkspaceClaimError` text in `error`.
- `prepare_agent_launch()` or `spawn_prepared_agent_process()` raising is recorded as a failed row with
  `launch_phase="prepare"` / `"spawn"`.
- Multi-prompt validation failure records at least one parent failed row, or one failed row per segment if that is the
  chosen contract.
- Partial multi-prompt failure records rows for already-spawned agents through the normal path **and** a failed row for
  the failed segment.
- Repeat launch `NameCollisionError` records a failed row with the repeat prompt and collision text.
- Workflow `Popen` and `claim_workspace()` failures produce a failed `workflow_state.json` row.
- `request_agents_refresh("launch")` is invoked (assert via spy) so the row reaches the UI within the 150 ms debounce
  window rather than waiting for a manual refresh.

## Open Design Choice

For fan-out failures, decide whether the contract is "one failed parent attempt row" or "one row per planned slot." The
user-facing ideal says every attempt to run an agent gets a row. For `%m`, `%alt`, `%r`, and multi-prompt, the system has
already expanded one user submission into multiple agent attempts, so per-slot failed rows are more consistent and make
partial failures easier to understand. The implementation is easier if `execute_launch_plan()` owns slot failure
recording because that is where slot timestamps, workflow names, launch contexts, and spawn requests come together. The
existing `_record_fanout_launch_failure()` should then either be removed (replaced by per-slot rows) or kept as a parent
summary that complements the per-slot rows.

## Bottom Line

The loader/detail UI mostly already supports the desired failed-row experience. The required work is to move "attempt
recording" earlier in the launch lifecycle and make it unconditional for failures after the user submits a non-empty
prompt. The highest-leverage code to update is `src/sase/agent/launch_executor.py` plus the TUI catch/validation
branches in `src/sase/ace/tui/actions/agent_workflow/`. The single cheapest concrete win — likely under a day of
work — is closing the `_workflow_exec.py:303-347` gap, where `artifacts_dir` is already on disk before the failure and
only a `_write_failed_workflow_state()` call is missing.
