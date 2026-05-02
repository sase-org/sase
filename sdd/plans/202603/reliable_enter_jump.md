---
create_time: 2026-03-31 13:31:24
status: done
prompt: sdd/prompts/202603/reliable_enter_jump.md
---

# Plan: Make `<enter>` on Agents Tab Reliably Jump to ChangeSpec

## Problem

The `<enter>` keymap on the Agents tab frequently "does nothing" even when a ChangeSpec IS associated with the selected
agent/workflow. There are 4 distinct failure modes.

## Failure Modes

### FM1: Workflow child steps have wrong cl_name (MOST COMMON)

`_workflow_loaders.py:445` sets `cl_name=step_name` for child steps (e.g., "run_agent", "make_changes"). When a user
expands a workflow and selects a child step, `<enter>` tries to navigate to ChangeSpec "run_agent" which doesn't exist.
The real ChangeSpec name is on the parent workflow entry (loaded from `workflow_state.json`'s `context.cl_name`).

### FM2: Project agents silently return with no feedback (COMMON)

`_core.py:194-199`: When `is_project_agent` is True but `get_meta_changespec_name()` returns None (no step_output or no
meta fields), the function just `return`s with zero feedback. The user sees nothing happen.

### FM3: cl_name = "unknown" navigates to nonexistent ChangeSpec

`_artifact_loaders.py:213` and `_workflow_loaders.py:202` both fall back to `"unknown"` when cl_name is missing.
Navigation searches for ChangeSpec "unknown" then shows a confusing warning.

### FM4: Footer "go to CL" visibility desynced from actual jumpability

`keybinding_footer.py:487-498` shows the binding for non-project agents unconditionally (including when
`cl_name="unknown"` or when the agent is a workflow child with step_name as cl_name). For project agents, it checks
`meta_new_cl`/`meta_new_pr` but not `meta_changespec` — missing the new canonical path that `get_meta_changespec_name()`
checks first.

## Changes

### 1. Resolve effective cl_name for navigation (`_core.py`)

Add a helper `_resolve_agent_cl_name(agent)` in `_core.py` that returns the correct ChangeSpec name for ANY agent type:

- **Workflow child steps** (`agent.is_workflow_child`): Look up parent in `self._agents_with_children` by matching
  `agent.parent_timestamp == parent.raw_suffix` (same pattern as `_is_child_of` in `_revive.py:15-25`). Use parent's
  `cl_name`. If parent not found (filtered out), fall back to reading `workflow_state.json` from the child's artifacts
  dir to extract `context.cl_name`.
- **Project agents**: Delegate to existing `get_meta_changespec_name()`.
- **All others**: Use `agent.cl_name` directly.
- Return `None` when the resolved name is `"unknown"` or empty.

Rewrite `action_jump_to_agent_changespec()` to use this helper, adding a notification ("No ChangeSpec for this agent")
when it returns None, instead of silently returning.

### 2. Sync footer visibility (`keybinding_footer.py`)

Replace the unconditional `not agent.is_project_agent` check with a call to the same resolution logic (or an equivalent
`can_jump_to_changespec(agent)` predicate) so the footer only shows "go to CL" when pressing enter would actually do
something:

- Non-project, non-child agents: show if `cl_name != "unknown"`
- Workflow children: show if parent's cl_name can be resolved and isn't "unknown"
- Project agents: show if `get_meta_changespec_name()` returns a value

Since the footer widget doesn't have access to `self._agents_with_children`, expose a lightweight predicate method on
the app (or pass the resolution result through the agent model) that the footer can call.

### 3. Tests (`tests/ace/tui/test_jump_to_changespec.py`)

New test file covering:

- **FM1**: Workflow child step resolves to parent's cl_name; falls back to workflow_state.json when parent not in list
- **FM2**: Project agent without meta shows notification
- **FM3**: Agent with cl_name="unknown" shows notification
- **FM4**: Footer hides "go to CL" for agents that can't jump

Follow the `_make_agent(**overrides)` helper pattern from `tests/ace/tui/widgets/test_agent_display.py`. Use a `FakeApp`
class (pattern from `tests/ace/tui/test_reload_and_reposition.py`) with mock `_agents_with_children`, `changespecs`,
`notify()`, etc.
