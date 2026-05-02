---
create_time: 2026-04-24 18:36:56
status: done
prompt: sdd/prompts/202604/pylimit_split_for_loop_resilience.md
---
# Fix `sase_pylimit_split` chop spawning fewer agents than expected per run

## Problem

The `sase_pylimit_split` chop (defined in chezmoi at `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`)
should spawn one agent per file that needs splitting. In practice, when multiple files violate the pylimit thresholds on
a single run, only one (or fewer than expected) agent gets launched — the remaining files are abandoned and have to wait
for the next 60-minute cycle.

The chop's underlying workflow (`xprompts/pylimit_split.yml`) is correct in shape: a `find_files` bash step produces a
JSON list of offenders, then a `split_files` step uses `for: { file_path: "{{ find_files.files }}" }` to fan out one
agent per file. The bug is in how the executor's for-loop reacts to per-iteration failure.

## Prior context

A previous fix (`.sase/home/.sase/plans/fix_pylimit_split.md`) collapsed an earlier 4-step layout into the current
2-step `for:` form to "eliminate the inter-step failure surface." The reasoning was that step 3 (`split_src_files`)
succeeded at the agent level (commit landed) but failed during post-processing, which marked the step as failed and
caused step 4 (`split_tests_files`) to be skipped.

That fix only moved the failure surface — it did not eliminate it. The same kind of post-iteration failure now happens
_between iterations of the single `for:` loop_ instead of between two top-level steps.

## Hypothesis (root cause)

`src/sase/xprompt/workflow_executor_loops.py:153-231` (`_execute_for_step`) treats _any_ failure of a single iteration
as fatal to the whole loop:

- The `try/finally` around `_execute_prompt_step` only restores `self.context`; it does **not** catch exceptions. A
  raise inside `_execute_prompt_step` (e.g. an embedded `#gh:sase` post-step failing, `capture_vcs_diff()` raising,
  marker-save raising) propagates out of the loop, abandoning subsequent iterations.
- A clean `return False` from `_execute_prompt_step` (e.g. HITL `reject`) also aborts the loop at line 213-215.

So if iteration 1's agent commits successfully but its trailing post-processing trips, iteration 2 never runs even
though it is fully independent work on a different file.

This is a clean fit for the observed symptom ("should run N, runs 1"). It is also consistent with the prior bug: the
same failure pattern moved one level down.

## Plan

### Phase 1 — Confirm the hypothesis from real chop run data (no code changes yet)

Before touching code, confirm the failure mode from persisted state. Inspect a recent run where the user expected
multiple agents but observed one.

1. **Locate recent chop activity.**
   - `~/.sase/axe/lumberjacks/run_every/chop_timestamps.json` — most recent `sase_pylimit_split` invocation timestamp.
   - `~/.sase/axe/lumberjacks/run_every/logs/output.log` — search for `sase_pylimit_split` lines around that timestamp;
     note PIDs and any error lines.

2. **Find the workflow state for that run.**
   - The chop launches an agent via `launch_agent_from_cwd()`, so the workflow state lives under the project's artifacts
     dir, e.g. `~/.sase/projects/<project>/artifacts/run/<timestamp>/workflow_state.json` or
     `~/.sase/logs/pack/*/artifacts/*/workflow_state.json`. Glob for `workflow_state.json` files modified shortly after
     the chop timestamp.

3. **Inspect `workflow_state.json`** for the run. Confirm:
   - `find_files` step's `output.files` contains **multiple** entries (otherwise the upstream gate/scanner is the real
     bug, not the for-loop).
   - `agents_launched` (top-level counter) is `1` (or `< len(files)`), not `len(files)`.
   - `split_files` step `status` is `failed`, with an `error` and `traceback` field populated. Read the traceback to
     identify exactly which line in `_execute_prompt_step` raised, and on which iteration.
   - Look for a sibling `prompt_step_split_files.json` marker that may capture the failure context as well.

4. **Decide branch based on findings:**
   - If `find_files.output.files` had only one entry → bug is upstream (`pylimit_files-260227` scanner or the bash
     one-liner). Stop and pivot the plan to the scanner. **Out of scope of the rest of this plan.**
   - If `agents_launched == len(files)` but the user _perceives_ fewer (e.g. only one PR shows up) → bug is in how
     downstream commits/PRs are produced or surfaced (not the executor). Pivot accordingly.
   - If `agents_launched < len(files)` and `split_files.status == failed` with a traceback → hypothesis confirmed,
     proceed to Phase 2.

Write findings inline at the top of this plan file under a "Diagnostic results" heading before starting Phase 2.

### Phase 2 — Make `for:` loops resilient to per-iteration failure (executor fix)

Assuming Phase 1 confirms the hypothesis, fix `_execute_for_step` so a single iteration's failure does not abandon the
rest of the loop. The semantic we want for "fan out one agent per file" is: each iteration is independent work; one
failing should be reported but the rest must still run.

**Design choice — fail-fast vs continue-on-error default:**

| Option                                                                                         | Description                                                                                               | Tradeoffs                                                                                                                                                |
| ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A. Add `on_error: stop \| continue` field on for-loop steps; default `stop` (current behavior) | Opt-in resilience. Minimal blast radius for other workflows.                                              | User has to explicitly opt in. The `pylimit_split.yml` author won't have known to opt in. Doesn't help anyone who just writes the obvious thing.         |
| B. Default `for:` loops to continue-on-error; opt-out via `on_error: stop`                     | Aligns with the natural fan-out semantic.                                                                 | Behavior change for any existing workflow that depended on early-abort.                                                                                  |
| C. Continue-on-error only for `for: + agent:` (not bash/python iterations); opt-out via flag   | Targeted: agent fan-out is where this fits naturally; deterministic bash/python loops keep stop-on-error. | Slight asymmetry between iteration kinds, but it matches user mental model: agent steps are independent units of work, script steps are pipeline stages. |

**Recommended: Option C.** It matches what the chop author wrote and what `for:` over an agent step is for.
Deterministic loops (bash/python) keep their existing fail-fast behavior because those are pipeline stages where a
partial result is usually worse than no result.

Add `on_error: stop | continue` for explicit opt-out (so a future workflow that wants strict agent fan-out can ask for
it), but make the default for agent-step for-loops be `continue`.

**Implementation sketch (do not write code yet — sketch only):**

- `src/sase/xprompt/workflow_models.py`: add `on_error: Literal["stop", "continue"] | None = None` to `WorkflowStep`,
  parsed from the YAML alongside `for:`. Document it.
- `src/sase/xprompt/workflow_executor_loops.py:_execute_for_step`:
  - Wrap the per-iteration body in `try/except Exception as exc:` (in addition to the existing `finally`).
  - Track `iteration_failures: list[tuple[int, BaseException | str]]`.
  - Determine effective behavior:
    `effective_on_error = step.on_error or ("continue" if step.is_agent_step() else "stop")`.
  - On exception OR `success is False`:
    - If `stop`: log, return `False` (current behavior).
    - If `continue`: append to `iteration_failures`, log a clear `[for-loop iteration N/M failed]` message via the
      output handler so it is visible in the TUI/log, **continue to next iteration**.
  - After the loop: if any failures occurred under `continue` mode, attach them to `step_state.error` /
    `step_state.iteration_errors` (new field on `StepState`) but mark the overall step `completed` if at least one
    iteration succeeded (or `completed_with_errors` if we want a third status — keep it simple, prefer two-state).
  - Ensure `_agents_launched` increments per _attempt_ (already does, since it lives inside `_execute_prompt_step`
    before the call site that may raise).
- `src/sase/xprompt/workflow_executor.py`: surface `iteration_errors` (if non-empty) into the persisted
  `workflow_state.json` so future diagnostics are easy.

**Logging:** at minimum, on each iteration boundary, log iteration index, iteration variable values, and outcome.
Currently `output_handler.on_step_iteration` is called only at _start_ — also call an `on_step_iteration_complete` (or
reuse the existing one) with the outcome so the TUI/log shows `1/3 ✓ 2/3 ✗ (error: ...) 3/3 ✓`. This was the exact
information missing in the prior debug pass.

### Phase 3 — Test coverage

There are no existing tests for `for: + agent:` mid-iteration failure (verified during exploration). Add:

- `tests/test_workflow_executor_loops.py::test_for_agent_step_continues_on_iteration_failure`
  - 3-item list, second iteration's agent invocation raises.
  - Assert: 3 attempts (`_agents_launched == 3`), iterations 1 and 3 succeed, iteration 2 captured in
    `step_state.iteration_errors`, overall step status reflects partial success, subsequent workflow steps still run.
- `tests/test_workflow_executor_loops.py::test_for_agent_step_on_error_stop_aborts`
  - Same 3-item list with `on_error: stop`. Assert legacy fail-fast behavior.
- `tests/test_workflow_executor_loops.py::test_for_bash_step_default_stops_on_failure`
  - Document the deliberate asymmetry between agent and bash for-loops.

Use existing test scaffolding and mocked `invoke_agent` (the file already has loop-iteration tests for bash/python
steps; mirror that style).

### Phase 4 — Verify on a real chop run

1. `just check` in `/home/bryan/projects/github/sase-org/sase_101` (the user's workspace; from `workspaces.md`, run
   `just install` first if the workspace hasn't been touched recently).
2. Manually craft a fixture where `find_files` outputs ≥ 2 paths and force a controlled failure on the first iteration's
   agent (e.g. via a debugging sentinel) — confirm second iteration still runs.
3. Wait for (or trigger) one real `sase_pylimit_split` run where ≥ 2 files are over limit, and confirm
   `agents_launched == len(files)` in the persisted state.

### Out of scope / explicit non-actions

- The chop definition in chezmoi (`sase_athena.yml`) is correct as written and does **not** need to change. No
  `chezmoi apply` step is needed.
- `xprompts/pylimit_split.yml` does **not** need to change either — the new default for agent for-loops covers it. Only
  edit it if Phase 1 reveals an additional issue that requires it (e.g. dedup, scoping per-file artifacts).
- This fix targets the executor's general for-loop semantics and therefore benefits other agent-fan-out workflows too.
  We are not adding any pylimit-specific code path.

## Files expected to change (final)

- `src/sase/xprompt/workflow_executor_loops.py` — exception-resilient iteration in `_execute_for_step`, iteration
  outcome logging.
- `src/sase/xprompt/workflow_models.py` — `on_error` field on `WorkflowStep`; possibly `iteration_errors` on
  `StepState`.
- `src/sase/xprompt/workflow_executor.py` — persist `iteration_errors` into `workflow_state.json`.
- `src/sase/xprompt/workflow_output.py` — iteration-complete event for TUI/log surface (only if we add the new event).
- `tests/test_workflow_executor_loops.py` — three new tests above.

No changes to chezmoi, no changes to the `pylimit_split.yml` xprompt, no changes to plugin repos.
