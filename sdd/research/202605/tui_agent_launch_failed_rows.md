# TUI Agent Launch Failures Should Always Create Rows

## Question

The target behavior is: once a user submits a non-empty prompt in `sase ace` to run an agent, the Agents tab should get
a new row for that attempt. If the attempt fails before a live agent exists, the row should be terminal `FAILED` and
selection should show useful context: the submitted prompt, the failure summary/traceback when available, and any launch
context that helps the user understand what happened.

That target is not met today. The current launch path only creates an Agents-tab row after one of the existing row
sources exists:

- a project-file RUNNING claim,
- a home-mode `running.json`,
- an artifact `done.json`,
- an artifact `workflow_state.json`,
- or a ChangeSpec HOOKS/MENTORS/COMMENTS suffix.

Pre-spawn failures often only produce a toast and a log entry.

## Current Launch Path

The TUI submit path is:

1. `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py` forwards non-empty prompts into
   `_finish_agent_launch()`.
2. `src/sase/ace/tui/actions/agent_workflow/_launch_start.py:82-95` reserves a timestamp, unmounts the prompt bar, and
   schedules `_run_agent_launch_body_async()`.
3. `src/sase/ace/tui/actions/agent_workflow/_launch_body.py:47-498` resolves VCS refs, history, workflows, fan-out,
   repeat, and final single-agent spawn.
4. Single-agent spawn goes through `execute_launch_plan()` in
   `src/sase/agent/launch_executor.py:136-196`, then `spawn_agent_subprocess()` in
   `src/sase/agent/launch_spawn.py:73-284`.
5. `spawn_agent_subprocess()` creates the child process and only then claims the workspace in its claim callback
   (`src/sase/agent/launch_spawn.py:181-228`). That claim is what makes non-home running agents appear immediately.
6. Once the child starts, `src/sase/axe/run_agent_runner_setup.py:42-83` writes initial `workflow_state.json`, and
   `src/sase/axe/run_agent_runner.py:316-347` writes failed `done.json` if runner execution raises.

The Agents tab already knows how to display terminal failures:

- `src/sase/ace/tui/models/_loaders/_done_loaders.py:104-157` maps `done.json` with `outcome: "failed"` into a
  `FAILED` row with `error`, `traceback`, `output_path`, metadata, and prompt markers.
- `src/sase/ace/tui/models/_loaders/_workflow_loaders.py:115-124` maps failed `workflow_state.json` into `FAILED`.
- `src/sase/ace/tui/models/_loaders/_workflow_loaders.py:199-208` pulls workflow-level or step-level error text for
  the detail panel.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` and `_agent_display_parts.py` already render raw prompt,
  error text, traceback, and output paths when the Agent model has them.

So the missing piece is mostly persistence before live process creation, not list rendering.

## Gaps Found

### Pre-spawn validation creates no row

`_launch_body.py:142-162` validates multi-prompt name requests. On error it saves prompt history as cancelled and shows
a toast, but writes no artifact.

`_launch_body.py:257-275` does the same for single-agent name validation.

`launch_executor.py:157-160` validates names again for every fan-out plan. Any exception here happens before timestamps
and requests are materialized for all slots, so callers cannot show per-slot rows unless they catch and persist a
synthetic failed attempt.

### Worker-level exceptions create no row

`_launch_body.py:39-45` catches any exception escaping the launch worker and only notifies `"Agent launch failed (see
log)"`.

`_launch_body.py:491-498` catches single-agent low-level spawn failures and only notifies.

These failures include VCS resolution surprises, xprompt processing errors, Rust binding errors during launch
preparation, and workspace allocation failures that occur before a claim or child runner exists.

### Subprocess preparation and claim failures create no row

`spawn_agent_subprocess()` derives an output path and prepares a Rust-backed launch request
(`src/sase/agent/launch_spawn.py:123-168`), then creates the child and claims/transfers the workspace
(`src/sase/agent/launch_spawn.py:181-258`).

If `prepare_agent_launch()`, `spawn_prepared_agent_process()`, `claim_workspace()`, or `transfer_workspace_claim()`
raises, the caller may get an exception before:

- a workspace RUNNING claim exists,
- the child writes `workflow_state.json`,
- the child writes `raw_xprompt.md`,
- or the child writes `done.json`.

`launch_executor.py:199-270` retries workspace claim races, but after retries are exhausted it raises
`WorkspaceClaimError`; the TUI catches it as a toast-only launch failure.

### Multi-prompt, prompt fan-out, and repeat have uneven failure recording

`_launch_multi_prompt.py:69-89` catches failures and only shows `"Multi-prompt launch failed (see log)"`.

`_launch_repeat.py:177-190` catches name-collision and generic repeat failures and only shows a toast.

`_launch_multi_model.py:108-127` is better: it writes a notification/report via `_record_fanout_launch_failure()`, but
that still is not an Agents-tab row. It also does not preserve a row per slot.

`multi_prompt_launcher.py:55-65` has `_MultiPromptPartialLaunchError` for already-spawned children, but there is no
terminal failed artifact for the segment or slot that failed before spawn.

### Workflow execution is closer, but start/claim failures still have gaps

Workflow subprocess launch creates `artifacts_dir` before `Popen`, and `run_workflow_runner.py:112-114` writes initial
`workflow_state.json` early. `workflow_runner.py:461-470` also writes failed workflow state for validation failures
inside `execute_workflow()`.

The gap is in `_workflow_exec.py:303-347`: if `Popen` fails, or if `claim_workspace()` fails after `Popen`, the TUI only
notifies. It has already created `artifacts_dir`, so this is a relatively easy place to write failed
`workflow_state.json` before returning.

## Recommended Design

Add a single durable "launch attempt failed" artifact writer and use it everywhere an attempted TUI launch can fail
before an ordinary row source exists.

The writer should create an `ace-run/<YYYYmmddHHMMSS>/` artifact directory containing at least:

- `raw_xprompt.md` with the submitted user prompt,
- `done.json` with `outcome: "failed"`, `cl_name`, `project_file`, `timestamp`, `artifacts_timestamp`, `workspace_num`
  when known, `workspace_dir` when known, `output_path` if derivable, `error`, and `traceback`,
- `agent_meta.json` with launch metadata available before spawn: `workspace_dir`, `changespec_name`/`cl_name`,
  optional model/provider if already known, and a new failure category such as `launch_phase`.

This shape reuses the existing `done.json` loader and prompt panel. It also avoids inventing a new Agents-tab source.

Where this helper should live:

- The artifact schema and path derivation are backend/domain behavior shared by TUI, mobile, CLI launchers, and future
  launch surfaces, so the long-term home should be in the launch/core boundary, not only in Textual UI code.
- A pragmatic first step could be a Python helper near `src/sase/agent/launch_executor.py` or
  `src/sase/agent/launch_spawn.py`, backed by existing `create_artifacts_directory()` and `build_done_marker()`.
- If this becomes part of the normalized launch contract, mirror it through `src/sase/core/agent_launch_wire.py` and
  `src/sase/core/agent_launch_facade.py` so Rust-owned launch planning can return enough information to persist failed
  slots deterministically.

## Concrete Updates Needed

1. Add a helper, roughly `record_failed_launch_attempt(...)`, that accepts `PromptContext` or `LaunchSpawnRequest`
   fields, prompt, timestamp, phase, exception, and optional traceback. It should write `raw_xprompt.md`, `done.json`,
   and minimal `agent_meta.json`.
2. Call that helper in `_launch_body.py` for:
   - multi-prompt validation failure at lines 142-162,
   - single validation failure at lines 257-275,
   - generic worker escape at lines 39-45,
   - single low-level spawn exception at lines 491-498.
3. Call it from fan-out launch surfaces:
   - `_launch_multi_prompt.py:69-89`,
   - `_launch_multi_model.py:108-127` in addition to the existing notification,
   - `_launch_repeat.py:177-190`.
4. Extend `execute_launch_plan()` or add an optional failure callback so fan-out callers can persist one failed row for
   the slot that could not be spawned. This is cleaner than requiring every caller to reconstruct slot timestamps and
   contexts after `execute_launch_plan()` raises.
5. In `_workflow_exec.py`, write failed `workflow_state.json` for `Popen` failure and claim failure. This can use the
   existing `_write_failed_workflow_state()` shape from `workflow_runner.py` or a small shared helper.
6. Ensure the helper schedules `request_agents_refresh("launch")` or `_schedule_agents_async_refresh()` after writing
   the failed artifact, otherwise the row may not appear until a later filesystem refresh.
7. Add tests that assert a row-loadable artifact exists for each failure class, not just that a toast/notification is
   emitted.

## Suggested Test Coverage

Focused unit tests should be enough before any visual tests:

- Single prompt `%name` collision from the TUI launch body writes `done.json`, `raw_xprompt.md`, and loads as `FAILED`
  via `load_done_agents_from_snapshot()` / `load_all_agents()`.
- `execute_launch_plan()` workspace exhaustion in the TUI single path writes one failed `ace-run` row with the original
  prompt and `WorkspaceClaimError` text.
- `prepare_agent_launch()` or `spawn_prepared_agent_process()` raising is recorded as a failed row.
- Multi-prompt validation failure records at least one parent failed row, or one failed row per segment if that is the
  chosen contract.
- Partial multi-prompt failure records rows for already-spawned agents through the normal path and a failed row for the
  failed segment.
- Repeat launch `NameCollisionError` records a failed row with the repeat prompt and collision text.
- Workflow `Popen` and `claim_workspace()` failures produce a failed `workflow_state.json` row.

The acceptance test should load agents through the normal loader rather than inspecting files only, because the user
standard is "a row appears on the Agents tab."

## Open Design Choice

For fan-out failures, decide whether the contract is "one failed parent attempt row" or "one row per planned slot." The
user-facing ideal says every attempt to run an agent gets a row. For `%m`, `%alt`, `%r`, and multi-prompt, the system has
already expanded one user submission into multiple agent attempts, so per-slot failed rows are more consistent and make
partial failures easier to understand. The implementation is easier if `execute_launch_plan()` owns slot failure
recording because it is where slot timestamps, workflow names, launch contexts, and spawn requests come together.

## Bottom Line

The loader/detail UI mostly already supports the desired failed-row experience. The required work is to move "attempt
recording" earlier in the launch lifecycle and make it unconditional for failures after the user submits a non-empty
prompt. The highest-leverage code to update is `src/sase/agent/launch_executor.py` plus the TUI catch/validation
branches in `src/sase/ace/tui/actions/agent_workflow/`.
