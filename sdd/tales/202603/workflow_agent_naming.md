---
create_time: 2026-03-26 14:28:45
status: done
prompt: sdd/prompts/202603/workflow_agent_naming.md
---

# Plan: Workflow Agent Naming (`<name>.<N>`)

## Problem

When an agent creates a plan, asks questions, or receives user feedback, the execution loop in `run_execution_loop()`
spawns multiple child agents under the same workflow. Currently, all child agents inherit the parent's `name` field
verbatim (e.g., all are named `"a"`). This makes it impossible to distinguish individual agent steps within a workflow.

## Desired Behavior

- The **workflow** (the overall execution loop run) gets the original name (e.g., `"a"`).
- Each **child agent** within the workflow gets the name `<name>.<N>` (e.g., `"a.1"`, `"a.2"`, `"a.3"`).
- `N` starts at 1 and increments by 1 for each subsequent agent step.
- **Single-agent workflows** (no plan/question/feedback): the workflow and agent MUST have the same name (just `"a"`).

## Current Flow (for context)

In `run_execution_loop()` (`src/sase/axe/run_agent_exec.py`):

1. Initial agent runs with name `"a"` in `agent_meta.json`.
2. Agent gets killed (invoked `sase plan` or `sase questions`).
3. Initial agent's meta gets `role_suffix` updated (e.g., `.plan`).
4. Plan approval / question flow happens.
5. `create_followup_artifacts()` creates new artifacts dir with `parent_timestamp` linking to initial agent. Inherits
   `name: "a"` from parent meta.
6. Follow-up agent runs (`.code`, `.epic`, `.2`, `.3`, `.q` suffixes).
7. `done.json` is written to `current_artifacts_dir` with `ctx.agent_name` (always the original name).

Key files:

- `src/sase/axe/run_agent_exec.py` — execution loop, creates follow-ups
- `src/sase/axe/run_agent_helpers.py` — `create_followup_artifacts()`, `update_meta_suffix()`
- `src/sase/axe/run_agent_phases.py` — `extract_directives_and_write_meta()`, `build_done_marker()`
- `src/sase/agent/names.py` — `claim_agent_name()`, `find_named_agent()`, `_get_active_agent_names()`
- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py` — TUI reads `name` from meta/done
- `src/sase/ace/tui/widgets/agent_list.py` — TUI displays `@name`

## Design

### Core concept: lazy promotion to multi-agent workflow

The initial agent starts as `"a"`. Only when the **first follow-up agent is created** do we know this is a multi-agent
workflow. At that point:

1. **Retroactively rename** the initial agent from `"a"` to `"a.1"` (update its `agent_meta.json`).
2. Give the follow-up agent the name `"a.2"`.
3. Subsequent follow-ups get `"a.3"`, `"a.4"`, etc.

The workflow-level name `"a"` is NOT stored in any individual agent's `name` field — it's the **base name** derived by
stripping the `.<N>` suffix. The `_get_active_agent_names()` function already skips child agents (those with
`parent_timestamp`), so the workflow name reservation comes from the initial agent (which has no `parent_timestamp`).

### Tracking the agent step counter

Add `_agent_step` counter to `run_execution_loop()`:

- Starts at `1` (the initial agent is step 1).
- Increments each time `create_followup_artifacts()` is called.
- When `_agent_step` goes from 1 to 2, retroactively rename the initial agent to `<name>.1`.

### Naming follow-up agents

Modify `create_followup_artifacts()` to accept an optional `agent_name_override` parameter. The caller in
`run_execution_loop()` computes `f"{base_name}.{step}"` and passes it.

### Done marker

The `done.json` is written at the end of `run_execution_loop()` to `current_artifacts_dir` (which is the last follow-up
agent's dir for multi-agent workflows). Currently it uses `ctx.agent_name` (the original name). Change this to use the
correct per-agent name.

For the initial agent's artifacts dir (when it was retroactively renamed to `"a.1"`), the initial agent's artifacts dir
gets its own `done.json` via the plan/question handoff — actually, looking at the code, the initial agent does NOT get a
separate done.json. The done.json is only written for the FINAL artifacts dir. But the initial agent's `agent_meta.json`
was already renamed to `"a.1"`.

Wait — actually the done marker is written to `current_artifacts_dir`, which is the LAST follow-up's dir. And the
initial agent's dir doesn't get a done.json at all (it was killed). So we need to handle this:

- `current_artifacts_dir` done.json should use the final agent's name (`"a.N"`)
- The initial agent's dir doesn't need a done.json (it was killed for plan/questions)

### Name resolution (`find_named_agent`)

`find_named_agent("a")` should still work — it should resolve to the workflow (the most recent completed agent in the
workflow). Two options:

1. Search for exact match first, then try as base name (strip `.<N>` from candidates).
2. Keep the workflow name stored somewhere (e.g., a `workflow_name` field in agent_meta.json for child agents).

**Option 2 is cleaner**: add a `workflow_name` field to child agent meta. This way `find_named_agent("a")` can match on
`workflow_name` for child agents, and `find_named_agent("a.2")` matches on `name`.

### `_get_active_agent_names`

Currently skips agents with `parent_timestamp`. This means child agent names (`"a.1"`, `"a.2"`) won't be reserved
independently. The initial agent (no `parent_timestamp`, name `"a.1"` after rename) will still be counted. We need to
ensure the base name `"a"` is what gets reserved, not `"a.1"`.

**Solution**: In `_get_active_agent_names()`, when collecting names, if the name matches `<base>.<N>` pattern and the
agent has no `parent_timestamp`, extract `<base>` as the reserved name. Alternatively, store `workflow_name` on the
initial agent too (after promotion to multi-agent).

Actually, simpler: the initial agent's meta can keep both `name: "a.1"` and `workflow_name: "a"`. The
`_get_active_agent_names()` function reads `workflow_name` (if present) instead of `name` for reservation purposes.

### TUI display

The TUI reads `agent.agent_name` from `agent_meta.json`. No changes needed to the TUI display code — it will naturally
show `@a.1`, `@a.2`, etc. for child agents. The parent grouping still works via `parent_timestamp`.

## Implementation Plan

### Phase 1: Add `workflow_name` field support

**File: `src/sase/axe/run_agent_helpers.py`**

1. Modify `create_followup_artifacts()`:
   - Add `agent_name_override: str | None = None` parameter.
   - If provided, use it as the `name` field instead of inheriting from `base_meta`.
   - Add `workflow_name` field to followup meta, set to the original base name.

**File: `src/sase/axe/run_agent_exec.py`**

2. Add `_agent_step = 1` counter to `run_execution_loop()`.

3. Before each `create_followup_artifacts()` call, increment `_agent_step` and compute the child name:

   ```python
   _agent_step += 1
   child_name = f"{ctx.agent_name}.{_agent_step}" if ctx.agent_name else None
   ```

4. On the first follow-up creation (when `_agent_step` goes from 1 to 2), retroactively update the initial agent's
   `agent_meta.json`:
   - Set `name` to `f"{ctx.agent_name}.1"`
   - Set `workflow_name` to `ctx.agent_name`

   Create a helper function `_promote_to_workflow(artifacts_dir, base_name)` for this.

5. Pass `agent_name_override=child_name` to each `create_followup_artifacts()` call.

6. Update the done.json writing at the end of `run_execution_loop()`:
   - If `_agent_step > 1`, the done marker name should be the last child name (`f"{ctx.agent_name}.{_agent_step}"`).
   - If `_agent_step == 1`, use `ctx.agent_name` as before (single-agent case).

### Phase 2: Update name resolution

**File: `src/sase/agent/names.py`**

7. Update `_get_active_agent_names()`:
   - When reading agent meta, prefer `workflow_name` over `name` if present (so the base name `"a"` is reserved, not
     `"a.1"`).

8. Update `find_named_agent()`:
   - After exact `name` match fails, try matching against `workflow_name` field.
   - When matching by `workflow_name`, prefer the most recent child agent (highest `.<N>` suffix, or most recent
     timestamp).

9. Update `claim_agent_name()`:
   - When claiming a name, also strip it from agents whose `workflow_name` matches (in addition to `name` match).

### Phase 3: Update done.json name handling

**File: `src/sase/axe/run_agent_phases.py`**

10. No structural changes needed to `build_done_marker()` — it already accepts `agent_name`. The caller just needs to
    pass the correct name.

### Phase 4: Tests

11. Add tests for:
    - `create_followup_artifacts()` with `agent_name_override`
    - `_promote_to_workflow()` helper (retroactive rename)
    - `_get_active_agent_names()` with `workflow_name` field
    - `find_named_agent()` resolving both `"a"` and `"a.1"`
    - End-to-end naming: single-agent stays as `"a"`, multi-agent gets `"a.1"`, `"a.2"`
    - `claim_agent_name()` strips workflow_name matches

## Risks & Edge Cases

- **Race condition on retroactive rename**: The TUI polls agent_meta.json. Renaming `"a"` → `"a.1"` mid-flight could
  cause a brief flicker. This is acceptable since the TUI already handles meta changes.
- **Killed agents without follow-ups**: If an agent is killed by the user (not for plan/questions), `_agent_step` stays
  at 1, so the single-agent naming is preserved.
- **Questions flow appends `.q` suffix**: The question flow doesn't create new artifacts via
  `create_followup_artifacts()` — it updates the current meta's suffix in-place. But the follow-up AFTER questions DOES
  create new artifacts. We need to make sure `.q` handling doesn't increment the step counter (only new artifact
  creation does).
  - Looking at the code: questions update `current_role_suffix` and `update_meta_suffix()` in-place, then call
    `create_followup_artifacts()` to create the post-question agent. So the step counter increments correctly when the
    new artifacts are created.
- **Feedback rounds**: Feedback creates follow-up artifacts with suffix `.2`, `.3`, etc. Each of these should get a new
  `_agent_step` number. Note: these `.2`, `.3` suffixes are `role_suffix` values (different from the `.<N>` in the agent
  name). Agent name might be `"a.3"` while role_suffix is `.2` — the numbers won't necessarily match, which is fine
  since they track different things.
