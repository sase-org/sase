---
create_time: 2026-06-25 18:47:16
status: done
prompt: sdd/prompts/202606/wait_plan_agents_1.md
---
# Plan: `%wait` Support for Submitted Plan Agents

## Context

The current `%wait` runtime is driven by artifact metadata, not by the TUI's final display rows. `WaitDependencyIndex`
in `src/sase/core/wait_dependency_resolution.py` indexes exact names, workflow names, and plan-chain family names, and
treats a dependency as satisfied only when the newest matching candidate is resolved and has a successful `done.json`
outcome. For handoff artifacts without `done.json`, it has a narrow completed-workflow-state fallback.

Plan proposals do not naturally produce a final `done.json` while waiting for review. When an agent runs
`sase plan propose`, the runner handles `.sase_plan_pending`, records `plan_submitted_at` and `plan_path` in
`agent_meta.json`, writes `plan_path.json`, saves a synthetic planner chat, and then blocks in the plan approval flow.
The TUI derives the visible `PLAN` status from that metadata. It also may synthesize a planner child row named with the
canonical plan-chain suffix, such as `<family>--plan`, even when the backing artifact still has the base
`agent_meta.name`.

Cross-agent Jinja variables already have the right shape: `agents` is the single reserved namespace, keyed by agent name
or stable template key, and populated by `src/sase/agent/output_variable_context.py` from prior multi-prompt upstream
records and explicit `%wait` names. The new `plan_file` variable should extend that namespaced context rather than
adding a top-level Jinja variable.

## Goals

1. Allow `%wait` to target planner phase rows, including canonical names like `<base>--plan` and
   legacy/display-compatible forms where the existing `plan_chain` helpers recognize them.
2. Treat the submitted-plan `PLAN` state as done for that planner-row dependency.
3. Preserve existing semantics for waits on the root family/workflow name: a submitted planner row alone must not make
   the whole plan chain look complete.
4. Expose the proposed plan path as `plan_file` in the existing `agents[...]` namespace, available to later agents in
   the same multi-agent prompt/xprompt and to explicit `%wait` consumers.

## Design

Add a small shared plan-wait resolver around artifact metadata rather than depending on TUI-only status code. The
resolver should identify a submitted planner artifact by:

- plan-chain role suffix canonicalized to `PLAN_CHAIN_PLAN_SUFFIX`;
- a submitted-plan marker, using the same meaning as the TUI's `PLAN` status (`plan_submitted_at` present and not
  superseded by feedback/approval/rejection metadata);
- a usable plan path from `plan_path.json`, `agent_meta.plan_path`, or the existing `selected_plan_path` helper if that
  is the best local fit.

In `WaitDependencyIndex.add`, keep two concepts separate:

- the ordinary artifact candidate used for workflow/family completion;
- exact/alias named candidates used for a concrete row dependency.

For submitted planner artifacts, add a named wait candidate for the stored `agent_meta.name` only when that name itself
is the planner row, and add derived planner-row aliases with `agent_family_phase_name(base, PLAN_CHAIN_PLAN_SUFFIX)`
when the artifact represents a base/root planner phase. Mark only these named planner-row candidates as resolved/done.
Do not let this synthetic done state feed the workflow/family aggregate that decides whether `%wait:<base>` is
satisfied.

In `src/sase/agent/output_variable_context.py`, extend variable loading so it can synthesize `{"plan_file": "<path>"}`
from a resolved submitted-plan artifact. Keep existing `output_variables` behavior and merge order:

- upstream records from earlier segments remain first, using their existing stable `agent_key`;
- explicit `%wait` names can add or override the namespace for the exact wait target;
- if a wait target is a planner-row alias that resolves to the same artifact as an upstream base record, populate the
  alias key too so `{{ agents["base--plan"].plan_file }}` works;
- never inject `plan_file` at top level.

Avoid changing `#fork`/resume semantics. Submitted planner rows have no normal `done.json` response path, so plan-aware
resolution for Jinja context should be separate from `resolve_resume_agent_name`.

## Implementation Steps

1. Add focused helpers for submitted-plan detection and plan-path extraction. Prefer a non-TUI module such as
   `sase.core.wait_dependency_resolution` or a small shared core helper to avoid importing TUI enrichment code from
   runtime wait paths.
2. Update `WaitDependencyIndex` to index submitted planner-row aliases as named resolved candidates while leaving
   workflow/family candidates unchanged for whole-chain completion.
3. Add a plan-aware artifact lookup for output-variable context. It should resolve exact wait names and derived
   planner-row aliases to the backing artifact directory and its Jinja key, then merge `plan_file` with any stored
   `output_variables`.
4. Update multi-prompt/upstream handling only if needed after tests prove a previous named planner segment does not
   receive `plan_file` through existing upstream records. The expected key should follow existing rules:
   `agents["planner"].plan_file` for a previous segment named `planner`, and `agents["planner--plan"].plan_file` for an
   explicit wait on the planner row.
5. Refresh docs in `docs/xprompt.md` near the `%wait` and cross-agent variable sections to explain planner-row waits and
   the namespaced `plan_file` variable.

## Tests

Add/adjust focused tests rather than broad end-to-end fixtures:

- `tests/test_axe_chop_wait_checks.py`: a submitted planner artifact with `role_suffix="--plan"`, `plan_submitted_at`,
  and `plan_path.json` resolves `%wait:<base--plan>` / equivalent legacy alias; `%wait:<base>` remains unresolved until
  the existing family completion conditions are met.
- `tests/test_run_agent_wait.py` or the shared resolver tests: immediate dependency checks also treat the planner-row
  alias as already satisfied.
- `tests/test_agent_output_variable_context.py`: plan path is exposed as `agents["planner--plan"].plan_file` for
  explicit waits, and as the existing upstream key for subsequent named multi-prompt segments.
- Existing `sase var set` variables still merge under the same namespace and are not lost when `plan_file` is
  synthesized.
- Documentation examples render with the namespaced form and no top-level `plan_file`.

Run the focused tests first:

```bash
pytest tests/test_axe_chop_wait_checks.py tests/test_agent_output_variable_context.py tests/test_run_agent_wait.py
```

Then run any broader affected launch/multi-prompt tests if the upstream-record path changes:

```bash
pytest tests/test_multi_prompt_launcher_launch_env.py tests/test_cd_multi_prompt_launch_resolution.py
```
