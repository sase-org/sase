# STOP Output Variable For Repeat Directive Loops

Status: Research
Date: 2026-06-11

## Question

How should SASE support a new `STOP` output variable, set through
`sase var set STOP=...`, that breaks `%repeat` / `%r` directive loops?

## Short Answer

Implement `STOP` as a reserved output-variable convention that only affects
repeat-generated wait chains. Do not make `sase var set` directly mutate other
agents. Instead:

- keep `sase var set STOP=1` as a normal atomic write to the producing
  agent's `agent_meta.json["output_variables"]`;
- add repeat-chain metadata to repeat slots, especially the concrete previous
  repeat slot name;
- teach `wait_checks` to write a `ready.json` payload with `repeat_stop: true`
  when the repeat predecessor completed successfully and has a truthy
  `output_variables.STOP`;
- teach the waiting agent runner to read that ready payload, mark itself as
  intentionally skipped by repeat STOP, copy `STOP` into its own output
  variables, write a successful terminal marker, suppress normal completion
  notification, and exit before claiming a real deferred workspace or invoking
  the LLM provider.

This drains already-spawned future repeat slots instead of leaving them
permanently parked in `WAITING`.

## Current Architecture

### Output Variables

`sase var set` already stores arbitrary string output variables under
`agent_meta.json["output_variables"]`. The parser splits on the first `=`, and
the key regex accepts `STOP` because uppercase identifiers are valid
`[A-Za-z_][A-Za-z0-9_]*` keys
(`src/sase/core/agent_output_variables.py:19`,
`src/sase/core/agent_output_variables.py:23`). Writes merge atomically under a
per-agent-meta lock and refresh the artifact index
(`src/sase/core/agent_output_variables.py:44`).

The CLI handler does not special-case variable names. It requires
`SASE_AGENT=1` and `SASE_ARTIFACTS_DIR`, then delegates to the shared storage
helper (`src/sase/main/var_handler.py:28`). This is a good property to keep:
`STOP` should be a convention interpreted by repeat orchestration, not by the
var-writing command itself.

Waited agents can already read producer variables after the wait barrier. The
runner builds an `agents` Jinja namespace from explicit upstream records and
from `%wait` names (`src/sase/agent/output_variable_context.py:80`). For normal
wait dependencies, it resolves the waited agent and reads the producer's
`output_variables` (`src/sase/agent/output_variable_context.py:105`).

Generated skill docs are sourced from
`src/sase/xprompts/skills/sase_var.md`, not the installed skill file. Any user
contract change should update that source skill and the docs.

### Repeat Directive

The repeat launcher is shared by the TUI and CLI daemon launch path
(`src/sase/agent/repeat_launcher.py:1`). It expands one `%repeat:N` prompt into
N concrete agent specs. Iteration 1 gets `%n:<name>`, and each later iteration
gets both `%n:<name>` and an injected `%wait:<previous-name>`
(`src/sase/agent/repeat_launcher.py:142`). The docstring is explicit that the
chain is coordinated at the agent level, not by a parent loop
(`src/sase/agent/repeat_launcher.py:98`).

Both launch surfaces spawn all repeat slots up front:

- TUI repeat launch builds specs, creates a fake fan-out plan, and injects
  `SASE_REPEAT_NAME`, `SASE_REPEAT_ITERATION`, and `SASE_REPEAT_TOTAL`
  (`src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py:105`,
  `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py:129`).
- CLI/cwd repeat launch does the same recursive spawn for `sase run -d` style
  dispatch (`src/sase/agent/launch_cwd.py:308`,
  `src/sase/agent/launch_cwd.py:347`).

The Rust core fan-out planner only marks repeat slots after the first as
`wait_for_previous`; it does not know about concrete names or runtime output
variables (`../sase-core/crates/sase_core/src/agent_launch/mod.rs:1068`).
That means the STOP behavior can be implemented in the Python repeat/wait
runtime without changing the Rust parser contract.

### Wait Barrier

The runner writes `waiting.json`, then polls for `ready.json`
(`src/sase/axe/run_agent_wait.py:75`, `src/sase/axe/run_agent_wait.py:98`).
After the wait returns, the main runner resolves wait chats, claims a real
workspace for deferred `%wait` agents, prepares it, and only then builds the
output-variable context and calls the provider execution loop
(`src/sase/axe/run_agent_runner.py:306`,
`src/sase/axe/run_agent_runner.py:320`,
`src/sase/axe/run_agent_runner.py:358`).

This is the correct interception point for repeat STOP. A stopped future slot
can exit before claiming a real workspace and before provider invocation.

`wait_checks` currently scans all `agent_meta.json` files into a dependency
index, then scans `waiting.json` markers. When every dependency is resolved,
it writes `ready.json` with only `{"resolved_deps": waiting_for}`
(`src/sase/scripts/sase_chop_wait_checks.py:50`,
`src/sase/scripts/sase_chop_wait_checks.py:348`,
`src/sase/scripts/sase_chop_wait_checks.py:361`). The index currently records
status and timestamp, not artifact path or output variables.

### Workflow YAML `repeat:`

YAML workflow `repeat:` loops are a different mechanism. They run inside one
`WorkflowExecutor` process and already have a first-class `until:` condition
checked after every iteration
(`src/sase/xprompt/workflow_executor_loops.py:319`). A user can already stop
those loops by writing an `until:` condition against step output or context.
The new `STOP` convention is mainly needed for `%repeat/%r`, because those
future iterations are already separate parked agents.

## Constraints

- Do not leave future repeat slots waiting forever. Once a predecessor sets
  STOP, already-spawned slots must reach a terminal state.
- Do not make ordinary `%wait` consumers skip just because their producer has
  an output variable named `STOP`. The special behavior should be scoped to
  repeat-generated waits.
- Preserve existing `%wait` success semantics. Failed, killed, malformed, or
  missing dependencies must not be treated as STOP.
- Do not require a parent launcher process to stay alive. Repeat fan-out is
  intentionally launch-time only.
- Avoid having `wait_checks` write terminal markers for another live agent
  process. The waiting agent should finalize itself so workspace release,
  artifact indexing, and runner cleanup remain owner-local.
- Cover both TUI repeat launch and CLI/cwd repeat launch.

## Semantics

Recommended user contract:

```bash
sase var set STOP=1
```

When a repeat iteration completes successfully with truthy `STOP`, the next
repeat slot and every later slot should skip the LLM run and finish as an
intentional repeat-stop continuation.

Truthiness should be conservative:

- truthy: any non-empty value except `0`, `false`, `no`, and `off`
  case-insensitively;
- falsey: missing key, empty string, `0`, `false`, `no`, `off`.

This lets agents write `STOP=false` or `STOP=0` without accidentally stopping
the chain, while the documented path remains simple: `STOP=1`.

## Implementation Options

### Option A: Block Future `ready.json`

`wait_checks` could see producer STOP and simply not write `ready.json` for
the next repeat slot.

Rejected. This "breaks" the loop by creating permanent waiting agents. It
also makes the TUI show stale active work and requires manual cleanup.

### Option B: Kill Future Repeat Processes

`wait_checks` or the producer could find downstream repeat slots and kill
their processes.

Rejected. It is cross-process mutation, interacts poorly with workspace
claims, and would display the slots as killed or failed rather than
intentionally skipped. It also requires discovering the whole future chain.

### Option C: Write `done.json` Directly From `wait_checks`

`wait_checks` could mark downstream waiting agents complete when it sees
producer STOP.

Rejected for MVP. It would duplicate runner finalization, race with the live
waiting process, and still need a signal to make the waiting process stop
polling.

### Option D: `ready.json` Stop Payload Plus Runner Self-Finalization

`wait_checks` keeps owning dependency resolution. When a repeat predecessor
has truthy STOP, it writes `ready.json` with a stop payload. The waiting runner
reads that payload, finalizes itself as a skipped repeat slot, propagates STOP,
and exits.

Recommended. It preserves the current owner boundaries:

- `sase var set` only writes current-agent metadata;
- `wait_checks` only resolves wait barriers;
- the waiting runner owns its own marker lifecycle and process exit.

## Proposed Design

### Repeat Metadata

Extend `RepeatAgentSpec` with `previous_name: str | None`. For iteration 1 it
is `None`; for iteration `k > 1` it is `names[k - 2]`.

Add a new env var, for example:

```text
SASE_REPEAT_PREVIOUS_NAME=<previous repeat slot name>
```

Set it in both repeat launch surfaces:

- TUI `_slot_env` beside `SASE_REPEAT_NAME`, `SASE_REPEAT_ITERATION`, and
  `SASE_REPEAT_TOTAL`;
- CLI/cwd `_spawn_repeat_slot` beside the same variables.

This avoids brittle parsing of repeat names. It also distinguishes the
repeat-injected predecessor wait from user-authored waits that are preserved
inside every repeat slot.

Optionally persist repeat metadata into `agent_meta.json` during directive
extraction:

```json
{
  "repeat_name": "ww.2",
  "repeat_iteration": 2,
  "repeat_total": 5,
  "repeat_previous_name": "ww.1"
}
```

The critical field for STOP is the `waiting.json` value, but agent meta helps
debugging and TUI display.

### Waiting Marker

When `wait_for_dependencies()` writes `waiting.json`, include repeat metadata
when present:

```json
{
  "waiting_for": ["other", "ww.1"],
  "cl_name": "sase",
  "timestamp": "260611_120000",
  "repeat_name": "ww.2",
  "repeat_iteration": 2,
  "repeat_total": 5,
  "repeat_previous_name": "ww.1"
}
```

`repeat_previous_name` scopes STOP to the predecessor created by `%repeat`.
If `other` has `STOP=1` but `ww.1` does not, the repeat slot should run after
both dependencies resolve.

### Wait Checks

Extend the dependency index so the resolved candidate can expose:

- timestamp;
- resolved/done status;
- artifact directory;
- output variables, or at least truthy STOP state and STOP value.

Keep `is_resolved(name)` for existing callers, but add a richer lookup such as
`resolved_candidate(name)`.

For each waiting marker:

1. Validate `waiting_for` as today.
2. Resolve all dependencies exactly as today.
3. If all are done, inspect `repeat_previous_name`.
4. If `repeat_previous_name` names one of the resolved dependencies and that
   dependency has truthy `output_variables.STOP`, write:

   ```json
   {
     "resolved_deps": ["other", "ww.1"],
     "repeat_stop": true,
     "repeat_stop_source": "ww.1",
     "repeat_stop_value": "1"
   }
   ```

5. Otherwise write the current normal payload.

This keeps normal wait behavior unchanged and avoids STOP from unrelated
waited agents.

### Runner Wait Result

Change `wait_for_dependencies()` from a `None` side-effect function to a
backward-compatible return value:

```python
@dataclass(frozen=True)
class WaitResult:
    repeat_stop: bool = False
    repeat_stop_source: str | None = None
    repeat_stop_value: str | None = None
```

Callers that ignore the return value keep working. Existing tests should only
need updates where they assert behavior around `ready.json`.

Before deleting `ready.json`, read it and return the stop fields. For duration
and absolute-time-only waits, return the default `WaitResult()`.

### Repeat-Stop Finalization

In `run_agent_runner.main()`, assign:

```python
wait_result = wait_for_dependencies(...)
```

If `wait_result.repeat_stop` is true:

1. Set current output variables to propagate STOP:

   ```python
   set_agent_output_variables(
       artifacts_dir,
       {"STOP": wait_result.repeat_stop_value or "1"},
   )
   ```

   Optional extra keys such as `STOP_SOURCE` or `STOP_REASON` are useful but
   should be documented as metadata, not required for the loop break.

2. Merge debug fields into `agent_meta.json`, for example
   `repeat_stop_source`, `repeat_stopped_at`, and maybe
   `repeat_stop_value`.

3. Write a `done.json` for the current slot without calling the provider.
   Use outcome `"completed"` for the MVP so downstream `%wait` dependencies
   continue to resolve under current wait semantics. Include a `step_output`
   payload such as:

   ```json
   {
     "repeat_stop": true,
     "repeat_stop_source": "ww.1"
   }
   ```

4. Set `success = True`, `exec_outcome = "repeat_stopped"`, and
   `suppress_completion_notification = True`.

5. Skip wait chats, workspace claim, output-variable Jinja rendering, and
   `run_execution_loop()`.

The outcome field in `done.json` should remain `"completed"` initially because
`wait_checks` currently resolves only `done.json["outcome"] == "completed"`.
A new outcome such as `"repeat_stopped"` would require updating wait
resolution and wire docs. It can be added later if the UI needs a distinct
display status.

### Cascading Behavior

Because every skipped repeat slot copies `STOP` to its own output variables,
the stop condition cascades:

1. Iteration `k` completes and writes `STOP=1`.
2. `wait_checks` wakes iteration `k+1` with `repeat_stop: true`.
3. Iteration `k+1` writes its own `STOP=1`, writes a successful terminal
   marker, and exits.
4. `wait_checks` then wakes iteration `k+2`, and so on.

This may take one `wait_checks` cycle per remaining slot. That is acceptable
for an MVP and keeps ownership simple. A later optimization could let
`wait_checks` propagate virtual repeat-stop readiness through a waiting chain
in one scan, but that is more complex and not necessary for correctness.

## Tests To Add

- `tests/test_repeat_launcher.py`: `RepeatAgentSpec.previous_name` is set for
  slots after the first and absent for slot 1.
- `tests/test_agent_launch_repeat.py`: TUI repeat env includes
  `SASE_REPEAT_PREVIOUS_NAME` for iterations after the first.
- CLI/cwd repeat test: `_spawn_repeat_slot` passes the same env.
- `tests/test_axe_chop_wait_checks.py`: a completed repeat predecessor with
  `output_variables.STOP = "1"` causes `ready.json` to include
  `repeat_stop: true`.
- `tests/test_axe_chop_wait_checks.py`: `STOP=0` or `STOP=false` resolves
  normally without `repeat_stop`.
- `tests/test_axe_chop_wait_checks.py`: a user-authored waited dependency with
  STOP does not stop the repeat slot unless it is the marker's
  `repeat_previous_name`.
- `tests/test_run_agent_wait.py`: `wait_for_dependencies()` reads stop fields
  from `ready.json`, returns `WaitResult`, and still cleans up markers.
- Runner test near `tests/test_axe_run_agent_runner_deferred_workspace.py`:
  repeat STOP exits before deferred workspace claim and before
  `run_execution_loop()`.
- Runner test: skipped slot writes `output_variables.STOP`, `done.json`, and
  suppresses completion notification.
- Docs tests or snapshots if command docs are validated.

## Documentation Updates

Update:

- `docs/xprompt.md` repeat section;
- `docs/xprompt.md` cross-agent output variables section;
- `docs/configuration.md` `sase var` section;
- `src/sase/xprompts/skills/sase_var.md`;
- generated skill deployment flow if implementing in the live skill set
  (`sase init-skills --force`, then deploy as appropriate).

Suggested user-facing wording:

```text
Inside a %repeat/%r iteration, an agent can stop the remaining repeat slots
by running `sase var set STOP=1` before it completes. STOP only affects the
repeat-generated predecessor wait; ordinary agents that wait on this producer
can still read `agents["name"].STOP` like any other output variable.
```

## Recommended Solution

Implement Option D. Add repeat predecessor metadata (`previous_name` plus
`SASE_REPEAT_PREVIOUS_NAME`), persist that metadata into `waiting.json`, extend
`wait_checks` to detect truthy `STOP` only on the repeat predecessor and write
a `ready.json` stop payload, then have the waiting runner self-finalize as a
successful skipped repeat slot that propagates `STOP` and exits before
workspace claim or provider execution. Keep `done.json["outcome"]` as
`"completed"` for the MVP, suppress notifications for skipped slots, and
document `sase var set STOP=1` as the supported loop-break contract.
