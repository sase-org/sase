---
create_time: 2026-04-02 14:03:52
status: done
prompt: sdd/prompts/202604/resume_plan_done.md
---

# Plan: Fix resume keymap ('r') for PLAN DONE agents

## Problem

When pressing 'r' on a PLAN DONE agent in the agents tab, the user gets "Agent not finished yet" error.

**Root cause** in `src/sase/ace/tui/actions/agents/_interaction.py:431-478`:

1. Line 444: `agent.status not in DISMISSABLE_STATUSES` → False (PLAN DONE IS in DISMISSABLE_STATUSES), so the
   running-agent path is skipped
2. Line 459: `agent.status != "DONE"` → True (status is "PLAN DONE", not "DONE"), so the error is triggered

## Desired Behavior

When resuming a PLAN DONE agent, use the **coder agent's name** (the `.code` follow-up) as the input argument for the
`#resume` xprompt. The coder agent did the actual implementation work, so its conversation is the one worth resuming.

## Implementation

**File:** `src/sase/ace/tui/actions/agents/_interaction.py`

In `action_resume_agent()`, add a new branch after the running-agent check (line 457) and before the
`agent.status != "DONE"` check (line 459) that handles PLAN DONE:

1. Check if `agent.status == "PLAN DONE"`
2. Find the coder follow-up agent: search `agent.followup_agents` for one with `role_suffix == ".code"`
3. Use the coder agent's `agent_name` to populate the `#resume:{coder_name}` prefix
4. Fall through to the existing error if no coder agent is found

```python
if agent.status == "PLAN DONE":
    # Find the coder follow-up agent to resume its conversation
    coder = next(
        (f for f in agent.followup_agents if f.role_suffix == ".code"),
        None,
    )
    if coder and coder.agent_name:
        name = coder.agent_name
        prefix = f"#resume:{name} "
        vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"
        self._show_prompt_input_bar_for_home(
            initial_text=prefix,
            display_name=f"resume({name})",
            history_sort_key=agent.cl_name or "resume",
        )
        return
```

This goes right before the existing `if agent.status != "DONE":` check.

## Testing

Run `just install && just check` to verify lint/type/test pass.
