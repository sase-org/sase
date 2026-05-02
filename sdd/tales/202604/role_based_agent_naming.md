---
create_time: 2026-04-14 22:41:48
status: done
prompt: sdd/prompts/202604/role_based_agent_naming.md
---

# Plan: Role-Based Agent Naming (`<name>.plan` / `<name>.code`)

## Problem

When a named agent (e.g., `foo`) enters the plan-and-code workflow, child agents get numeric suffixes: `foo.1`
(planner), `foo.2` (coder), `foo.3` (epic), etc. These numbers carry no semantic meaning — you can't tell from the name
what role an agent plays. The `role_suffix` field (`.plan`, `.code`, `.epic`) already tracks this internally, but the
visible agent name doesn't reflect it.

## Desired Behavior

- The **initial planner** agent is renamed to `<name>.plan` (not `<name>.1`) when a follow-up is created.
- The **coder** follow-up is named `<name>.code` (not `<name>.2`).
- The **epic** follow-up is named `<name>.epic` (not `<name>.2`).
- **Intermediate agents** (feedback rounds, post-questions continuations) keep numeric suffixes `<name>.<N>` — these are
  transient steps that don't have stable, unique role names.
- The **`#resume:`** prefix correctly references `<name>.plan` when the coder resumes the planner's conversation.
- Single-agent workflows (no plan/question/feedback) are unchanged — just `<name>`.

## Trace of a Typical Workflow

### Simple: plan → code

| Step | Current naming | New naming |
| ---- | -------------- | ---------- |
| Plan | `foo.1`        | `foo.plan` |
| Code | `foo.2`        | `foo.code` |

Coder's `#resume:` prefix: `#resume:foo.plan` (was `#resume:foo.1`)

### With feedback: plan → feedback → code

| Step          | Current naming | New naming |
| ------------- | -------------- | ---------- |
| Plan          | `foo.1`        | `foo.plan` |
| Feedback (r2) | `foo.2`        | `foo.2`    |
| Code          | `foo.3`        | `foo.code` |

Coder's `#resume:` prefix: `#resume:foo.2` (references the most recent planner, which is the feedback agent)

### With questions: plan → questions → code

| Step                | Current naming | New naming |
| ------------------- | -------------- | ---------- |
| Plan                | `foo.1`        | `foo.plan` |
| Post-question agent | `foo.2`        | `foo.2`    |
| Code                | `foo.3`        | `foo.code` |

### Epic: plan → epic

| Step | Current naming | New naming |
| ---- | -------------- | ---------- |
| Plan | `foo.1`        | `foo.plan` |
| Epic | `foo.2`        | `foo.epic` |

## Design

### Core rule

Only **three roles** get descriptive name suffixes: `.plan`, `.code`, `.epic`. Everything else keeps numeric `.<N>`
naming (using `agent_step`). This avoids collisions from compound suffixes (`.plan.q`, `.2.q`) while giving the most
important roles readable names.

### Changes

**1. `promote_to_workflow()` in `run_agent_helpers.py`** — rename to `<base>.plan` instead of `<base>.1`

The initial agent in a workflow is always a planner. When the first follow-up is created and the single-agent run is
promoted to a multi-agent workflow, the initial agent's name should become `foo.plan`.

**2. `agent_name_override` in `run_agent_exec_plan.py`** — use role suffix for primary roles

Four call sites compute `agent_name_override=f"{ctx.agent_name}.{state.agent_step}"`. Change the coder and epic sites to
use the role suffix directly:

- **Feedback round** (line 249): Keep `foo.{state.agent_step}` — feedback rounds are numbered, not role-named.
- **Epic** (line 345): Change to `foo.epic`.
- **Coder** (line 382): Change to `foo.code`.
- **Questions followup** (line 478): Keep `foo.{state.agent_step}` — questions are transient.

Concretely, for coder/epic call sites:

```python
agent_name_override=f"{ctx.agent_name}{state.current_role_suffix}"
```

This works because `current_role_suffix` is set to `.code` or `.epic` right before these call sites.

**3. `#resume:` prefix in `run_agent_exec_plan.py`** — reference planner by role name

Currently (line 403): `planner_name = f"{ctx.agent_name}.{state.agent_step - 1}"`

Change to: when the previous agent was the initial (promoted) planner (`agent_step == 2`), use `foo.plan`; otherwise
keep `foo.{agent_step - 1}` (the previous intermediate agent).

```python
if state.agent_step == 2:
    planner_name = f"{ctx.agent_name}.plan"
else:
    planner_name = f"{ctx.agent_name}.{state.agent_step - 1}"
```

**4. `_done_agent_name` in `run_agent_exec.py`** — use role suffix for primary roles

Currently (line 121-123):

```python
_done_agent_name = (
    f"{ctx.agent_name}.{state.agent_step}"
    if state.agent_step > 1 and ctx.agent_name
    else ctx.agent_name
)
```

Change to: use role suffix when the final agent has a primary role, otherwise keep numeric.

```python
if state.agent_step > 1 and ctx.agent_name:
    if state.current_role_suffix in (".code", ".epic"):
        _done_agent_name = f"{ctx.agent_name}{state.current_role_suffix}"
    else:
        _done_agent_name = f"{ctx.agent_name}.{state.agent_step}"
else:
    _done_agent_name = ctx.agent_name
```

**5. No changes needed in:**

- `find_named_agent()` — resolves by exact `name` or `workflow_name` match; works with any suffix format
- `_get_active_agent_names()` — reads `workflow_name` (the base name) for reservation; unaffected
- `claim_agent_name()` / `_strip_name_from_json()` — matches on `name` or `workflow_name`; unaffected
- TUI display code — reads `agent.agent_name` from meta; naturally shows `@foo.plan`, `@foo.code`, etc.
- `get_phase_label()` — maps `role_suffix` to display labels; role_suffix is unchanged

### Test updates

- `test_promote_to_workflow`: expect `a.plan` instead of `a.1`
- `test_create_followup_with_name_override`: update example from `a.2` to `a.code`
- `test_coder_prompt_includes_resume_prefix`: expect `#resume:test_agent.plan` instead of `#resume:test_agent.1`

## Edge Cases

- **Feedback after questions**: Questions create a numeric followup (e.g., `foo.2`), which re-plans. If feedback is
  given, the next followup is `foo.3` (numeric). If approved, the coder is `foo.code`. The `#resume:` references
  `foo.{step-1}` (numeric) correctly.
- **Multiple question rounds**: Each creates a new numeric followup (`foo.2`, `foo.3`, etc.) via `agent_step`. No
  collisions.
- **Agent killed before plan**: `agent_step` stays at 1, no promotion happens. Single-agent naming preserved.
- **Plan committed without coder**: Final agent is the planner. `_done_agent_name` falls through to `foo.{agent_step}`
  since `current_role_suffix` is not `.code`/`.epic`.

## Files Changed

| File                                    | Change                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------- |
| `src/sase/axe/run_agent_helpers.py`     | `promote_to_workflow`: `.1` → `.plan`                                           |
| `src/sase/axe/run_agent_exec_plan.py`   | Coder/epic `agent_name_override` uses role suffix; `#resume` references `.plan` |
| `src/sase/axe/run_agent_exec.py`        | `_done_agent_name` uses role suffix for primary roles                           |
| `tests/test_axe_run_agent_helpers.py`   | Update expected names                                                           |
| `tests/test_axe_run_agent_exec_plan.py` | Update expected resume prefix                                                   |
