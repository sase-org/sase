---
create_time: 2026-03-28 17:21:04
status: done
prompt: sdd/prompts/202603/resume_coder_vcs_tag.md
---

# Plan: Fix resume VCS tag for coder agents

## Problem

When pressing `r` (resume) on a coder agent in the Agents tab, the prompt is missing the `#gh:sase ` VCS tag prefix.
This happens because coder agents (follow-ups to planner agents) don't have their own `raw_xprompt.md` file — only the
parent planner does.

## Root Cause

`_resolve_vcs_tag()` in `_interaction.py` calls `agent.get_raw_xprompt_content()`, which looks for `raw_xprompt.md` in
the agent's artifacts directory. But `create_followup_artifacts()` in `run_agent_helpers.py` never writes a
`raw_xprompt.md` for follow-up agents — it only creates `agent_meta.json`. So `get_raw_xprompt_content()` returns `None`
and the VCS tag is lost.

## Fix

Modify `_resolve_vcs_tag()` to fall back to the parent agent's `raw_xprompt.md` when the current agent doesn't have one.
The coder agent has `parent_timestamp` linking to its parent. The `_agents` list (available in the calling context)
contains the parent with a matching `raw_suffix`.

### Changes

**`src/sase/ace/tui/actions/agents/_interaction.py`**:

1. Add an `agents` parameter to `_resolve_vcs_tag()` so it can look up the parent.
2. When `agent.get_raw_xprompt_content()` returns `None` and `agent.parent_timestamp` is set, find the parent agent in
   `agents` by matching `raw_suffix == parent_timestamp`, then use the parent's `raw_xprompt_content`.
3. Update the three call sites in `action_resume_agent()` and `action_wait_for_agent()` to pass `self._agents`.

This is a small, focused change — the parent lookup is just a linear scan of the already-loaded agents list, and the
`raw_suffix`/`parent_timestamp` relationship is already established by `_apply_status_overrides`.
