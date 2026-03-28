---
create_time: 2026-03-27 19:03:08
status: done
---

# Plan: Improve TUI Resume Keymap VCS Tag References

## Problem

The `r` (resume) keymap on the Agents tab prepends VCS workflow tags verbatim (e.g., `#gh:sase`). Two recent
improvements to the Telegram Resume button (sase-telegram commits `43b6d08` and `f961d4b`) made the VCS tag smarter:

1. **Branch name substitution**: When the agent has a specific branch/CL name, the VCS tag ref is swapped to that branch
   name (e.g., `#gh:sase` → `#gh:sase_foobar_1`).
2. **`@<name>` for PR agents**: When the agent's prompt contains `#pr`, the VCS tag ref becomes `@<name>` (e.g.,
   `#gh:sase` → `#gh:@foo`), which resolves to the agent's branch at runtime.

The TUI `action_resume_agent()` and `action_wait_for_agent()` methods still use the raw VCS tag. They should apply the
same `replace_ref_in_vcs_tag` logic.

## Analysis

### Current TUI VCS tag handling (in `_interaction.py`)

All three code paths (running-agent resume, done-agent resume, wait-for) follow the same pattern:

```python
from sase.xprompt import extract_vcs_workflow_tag

raw_content = agent.get_raw_xprompt_content()
if raw_content:
    vcs_tag = extract_vcs_workflow_tag(raw_content)
    if vcs_tag:
        prefix = f"{vcs_tag}{prefix}"
```

### What needs to change

After extracting the `vcs_tag`, apply `replace_ref_in_vcs_tag` based on:

1. **If `not agent.is_project_agent`** (i.e., `cl_name` is an actual branch name, not just the project name): use
   `replace_ref_in_vcs_tag(vcs_tag, agent.cl_name)`.
2. **Else if prompt has `#pr`**: use `replace_ref_in_vcs_tag(vcs_tag, f"@{name}")`.
3. **Else**: keep original `vcs_tag` unchanged.

### Key functions already available

- `sase.xprompt.replace_ref_in_vcs_tag(tag, new_ref)` — added in commit `b545bb53`
- `sase.xprompt.workflow_validator_extract.extract_xprompt_calls(content)` — for detecting `#pr`
- `agent.is_project_agent` property — `True` when `cl_name == project_name` (i.e., no specific branch)
- `agent.get_raw_xprompt_content()` — returns the raw prompt text

## Implementation

### Step 1: Add a helper to resolve the VCS tag with smart ref replacement

**File**: `src/sase/ace/tui/actions/agents/_interaction.py`

Add a private helper function that encapsulates the VCS tag resolution logic shared by all three callers:

```python
def _resolve_vcs_tag(agent: Agent, name: str) -> str | None:
    """Resolve a VCS workflow tag for the given agent, applying smart ref replacement.

    Returns the tag string (with trailing space) or None if no VCS tag found.
    """
    from sase.xprompt import extract_vcs_workflow_tag, replace_ref_in_vcs_tag

    raw_content = agent.get_raw_xprompt_content()
    if not raw_content:
        return None

    vcs_tag = extract_vcs_workflow_tag(raw_content)
    if not vcs_tag:
        return None

    # Use actual branch name if agent has one (not just the project name)
    if not agent.is_project_agent:
        return replace_ref_in_vcs_tag(vcs_tag, agent.cl_name)

    # Use @<name> if prompt contains #pr (will resolve to agent's branch)
    from sase.xprompt.workflow_validator_extract import extract_xprompt_calls

    if any(call.name == "pr" for call in extract_xprompt_calls(raw_content)):
        return replace_ref_in_vcs_tag(vcs_tag, f"@{name}")

    return vcs_tag
```

### Step 2: Update the three call sites to use the helper

Replace the duplicated VCS tag extraction blocks in:

1. **Running-agent resume** (lines ~343-349)
2. **Done-agent resume** (lines ~369-375)
3. **Wait-for-agent** (lines ~401-407)

Each becomes:

```python
vcs_tag = _resolve_vcs_tag(agent, name)
if vcs_tag:
    prefix = f"{vcs_tag}{prefix}"
```

### Step 3: Add tests

Add tests in `tests/test_ace_tui/` (or wherever the interaction action tests live) covering:

- Resume with `cl_name` != project name → VCS tag uses branch name
- Resume with `#pr` in prompt → VCS tag uses `@<name>`
- Resume without either → VCS tag unchanged
- Wait-for with the same three cases
- Running-agent resume with the same three cases
