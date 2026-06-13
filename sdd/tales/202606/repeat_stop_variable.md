---
create_time: 2026-06-13 16:04:11
status: done
prompt: sdd/prompts/202606/repeat_stop_variable.md
---
# Plan: STOP Output Variable for `%repeat`

## Goal

Add first-class support for a reserved `STOP` output variable, set by an agent with `sase var set STOP=1` through the
`/sase_var` workflow, that prevents later `%repeat` / `%r` fan-out slots from running when the current repeat iteration
determines no further work is needed.

The key architectural point is that `%repeat` is launch-time fan-out, not a runtime loop. Future slots already exist and
are parked behind injected `%wait:<previous-slot>` dependencies. Stopping the repeat therefore means a downstream slot
must wake, notice that its repeat predecessor set `STOP`, finalize itself as a successful skipped repeat slot, and exit
before claiming a real workspace or invoking a provider.

## Semantics

- `STOP` is an exact, case-sensitive output-variable name. Agents set it with the existing command:

  ```bash
  sase var set STOP=1
  ```

- `sase var set` should remain generic. It already accepts `STOP`; the new behavior lives in repeat orchestration, not
  in the variable-writing command.
- Truthiness is conservative: `""`, `"0"`, `"false"`, `"no"`, and `"off"` are false, case-insensitively. Any other
  string value is true.
- `STOP` affects only repeat-chain continuation. Ordinary `%wait` consumers, multi-agent `---` segments, `%alt`
  fan-outs, and manually named agents still treat `STOP` as a normal output variable under `agents[...]`.
- A stopped downstream slot is a successful terminal result:
  - exit status 0;
  - `done.json` has `outcome: "completed"`;
  - `done.json` also records `repeat_stopped: true` and `stopped_by: <predecessor-name>`;
  - the slot propagates `STOP` into its own output variables before writing `done.json`;
  - completion notification is suppressed;
  - no deferred workspace is claimed and no provider execution happens.

Keeping the outcome as `"completed"` is intentional: the existing wait-check chop already resolves completed producers,
so STOP cascades through the already-spawned repeat chain without changing generic `%wait` semantics.

## Design

Use the runner-side post-wake design from `sdd/research/202606/repeat_stop_variable_consolidated.md`.

Do not change the Rust fan-out planner, the `%repeat` parser contract, the `waiting.json` or `ready.json` schema, or the
wait-check chop. The repeat launcher will pass one additional piece of launch metadata, and the Python runner will make
the STOP decision after its wait barrier returns.

### 1. Thread Repeat Predecessor Metadata

- Add `REPEAT_PREV_NAME_ENV = "SASE_REPEAT_PREV_NAME"` in `src/sase/agent/repeat_launcher.py`.
- Add `prev_name: str | None` to `RepeatAgentSpec`.
- Populate `prev_name` as `None` for slot 1 and `names[k - 2]` for slots 2..N. This must use the already-resolved names,
  not string surgery on `<base>.<k>`, because repeat names can come from resume- or wait-derived allocation paths such
  as `foo.f2` or `foo.w3`.
- Inject `SASE_REPEAT_PREV_NAME` alongside the existing repeat env vars in both launch surfaces:
  - TUI repeat launch: `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py`;
  - CLI/cwd repeat launch: `src/sase/agent/launch_cwd.py`.
- Optionally persist repeat metadata into `agent_meta.json` in `run_agent_directives.py` for debugging: `repeat_name`,
  `repeat_iteration`, `repeat_total`, and `repeat_prev_name`. This is not required for STOP behavior, so keep it small
  and only add it if it fits the existing metadata style.

### 2. Add a Focused STOP Helper

- Add a small module such as `src/sase/axe/run_agent_repeat_stop.py`.
- Define constants and helpers:
  - `STOP_OUTPUT_VARIABLE = "STOP"`;
  - `is_stop_value(value: str) -> bool`;
  - a `RepeatStopDecision` dataclass with `producer_name` and `stop_value`;
  - `detect_repeat_stop() -> RepeatStopDecision | None`.
- `detect_repeat_stop()` should:
  - read `SASE_REPEAT_PREV_NAME`;
  - return `None` when it is unset;
  - resolve that producer the same way waited-agent output-variable context does;
  - read the predecessor's `output_variables`;
  - return a decision only when `STOP` is present and truthy.
- Avoid duplicating name-resolution logic. Export a narrow helper from `src/sase/agent/output_variable_context.py` that
  reuses its existing `_resolve_waited_agent()` and `read_agent_output_variables()` path, then call that from the STOP
  helper.

### 3. Integrate with the Agent Runner

In `src/sase/axe/run_agent_runner.py`, check for repeat STOP immediately after `wait_for_dependencies()` returns and
before these existing steps:

- resolving wait chats;
- claiming a deferred workspace;
- refreshing sibling repos for a claimed workspace;
- building Jinja output-variable namespaces;
- calling `run_execution_loop()`.

When a STOP decision exists:

- call `set_agent_output_variables(artifacts_dir, {"STOP": decision.stop_value})` first;
- build and write a completed `done.json` marker for the current artifacts directory, adding `repeat_stopped: true` and
  `stopped_by: decision.producer_name`;
- set local runner state so final cleanup, metrics, workspace release, and output-log completion marker still run as a
  normal successful agent completion;
- set `suppress_completion_notification = True`;
- log a clear message such as `Repeat chain stopped by <name> (STOP=<value>); skipping execution`;
- skip the normal execution path without raising an exception or calling `sys.exit()` from inside the inner runner body.

The write order matters: output variables first, then `done.json`. The next downstream waiter can only wake after this
slot has a completed `done.json`, so writing `STOP` first guarantees cascade correctness.

### 4. Documentation and Skill Source

Update user-facing guidance in the same change set:

- `docs/xprompt.md`
  - repeat directive section: explain that a repeat iteration can stop later slots by setting `STOP`;
  - cross-agent output variables section: note that `STOP` is reserved only for repeat-chain continuation.
- `docs/configuration.md`
  - `sase var` section: document `STOP` usage, truthiness, and scope.
- `src/sase/xprompts/skills/sase_var.md`
  - document when to set `STOP=1`, and explicitly say it only affects later `%repeat` / `%r` slots.

Because provider skill files are generated from source, regenerate deployed skill files after editing the source with:

```bash
sase skills init --force
```

If the local chezmoi flow reports unrelated drift, keep the implementation scoped to the generated `sase_var` targets
and do not hand-edit generated `SKILL.md` files.

## Tests

Add focused coverage at each integration boundary:

- `tests/test_repeat_launcher.py`
  - `RepeatAgentSpec.prev_name` is `None` for slot 1 and the exact predecessor name for later slots;
  - resume-derived and wait-derived repeat names use the resolved predecessor names.
- `tests/test_agent_launch_repeat.py`
  - TUI repeat launch injects `SASE_REPEAT_PREV_NAME` only for later slots.
- A CLI/cwd launch test near existing `launch_agents_from_cwd` coverage
  - repeat launch injects the new env var in the daemon/cwd path.
- New `tests/test_run_agent_repeat_stop.py`
  - truthiness table;
  - no-op when `SASE_REPEAT_PREV_NAME` is unset;
  - no-op when the predecessor cannot be resolved or has no truthy `STOP`;
  - predecessor `STOP=1` returns a stop decision with the producer name and value.
- `tests/test_axe_run_agent_runner_deferred_workspace.py`
  - repeat STOP after wait exits before deferred workspace claim and before `run_execution_loop()`;
  - `set_agent_output_variables()` is called before the done marker write;
  - the runner exits successfully and suppresses completion notification.
- `tests/test_axe_chop_wait_checks.py`
  - a completed marker with `repeat_stopped: true` still resolves a downstream wait, proving the cascade remains generic
    completed-outcome behavior.
- `tests/main/test_init_skills_sources.py`
  - update the `sase_var` expected phrases so generated skill rendering covers the new STOP guidance.

## Validation

Run the focused tests first:

```bash
just install
.venv/bin/python -m pytest \
  tests/test_repeat_launcher.py \
  tests/test_agent_launch_repeat.py \
  tests/test_axe_run_agent_runner_deferred_workspace.py \
  tests/test_axe_chop_wait_checks.py \
  tests/test_run_agent_repeat_stop.py \
  tests/main/test_init_skills_sources.py
```

Then run the repository gate:

```bash
just check
```

## Deferred Follow-Up

TUI display polish can be a separate follow-up. V1 stopped slots will show as `DONE` because their outcome is
`completed`, with `repeat_stopped: true` available in `done.json` and propagated `STOP` visible in output variables.

If we want a distinct display label such as `DONE (STOPPED)`, update both done-loader paths and the Rust-backed done
record wire in `../sase-core` per the Rust core boundary instructions. That work is not required for the control-flow
behavior and should not block v1.

## Risks and Mitigations

- Cascade latency is one wait-check cycle per stopped downstream slot. This is acceptable for v1 because it avoids new
  marker schemas and keeps wait semantics generic.
- User-supplied extra `%wait` dependencies are still honored. A repeat slot checks STOP after its wait barrier returns,
  and only the repeat predecessor's `STOP` can stop it.
- A failed or killed predecessor does not trigger STOP. Existing `%wait` behavior remains unchanged.
- The STOP convention should be documented clearly so agents know to set it before completing the iteration.
