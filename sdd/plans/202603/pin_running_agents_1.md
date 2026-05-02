---
create_time: 2026-03-31 08:57:50
status: done
prompt: sdd/prompts/202603/pin_running_agents_1.md
---

# Plan: Allow Pinning Running Agents

## Problem

The `P` (pin/unpin) keymap on the Agents tab only works on completed agents (status in DISMISSABLE_STATUSES: DONE,
FAILED, PLAN COMMITTED, PLAN DONE). Users want to mark running agents as "important" so that when they complete, they
automatically land in the Pinned panel instead of mixed in with other completed agents.

## Design

**Core idea**: Allow `P` to toggle the pinned flag on any agent regardless of status. Running pinned agents stay in the
main panel (with a 📌 icon) until they complete, at which point the existing refresh cycle (`_load_agents()` →
`_build_panel_indices()`) automatically moves them to the Pinned panel — no new completion-detection logic needed.

**Why this works**: `_build_panel_indices()` already gates pinned-panel placement on
`identity in pinned_agents AND status in DISMISSABLE_STATUSES`. A running agent with its identity in the pinned set will
stay in the main panel. When it completes and its status becomes DONE/FAILED/etc., the next refresh moves it to the
pinned panel automatically.

## Changes

### 1. `src/sase/ace/tui/actions/agents/_interaction.py` — Remove DISMISSABLE gate

Remove lines 121-125 (the `DISMISSABLE_STATUSES` check and its import). The `raw_suffix is None` guard on line 127 is
sufficient — it prevents pinning agents that can't be reliably identified.

Update the docstring from "Toggle pinned state on a completed agent" to "Toggle pinned state on an agent."

For the panel-follow logic (lines 142-146): when pinning a running agent, it stays in the main panel (since
`_build_panel_indices` won't move it yet), so we should only follow to the pinned panel if the agent is already
dismissable. Specifically, wrap the panel-switch in a condition: only switch to the pinned panel if the agent is
dismissable AND was just pinned.

### 2. `src/sase/ace/tui/widgets/agent_list.py` — Show pin icon on running agents

Lines 268-274: Remove the `agent.status in _DISMISSIBLE_STATUSES` condition from the pin icon check. The icon should
display for any pinned agent in the main panel, regardless of status. This gives the user visual confirmation that their
running agent is marked for pinning.

### 3. `src/sase/ace/tui/widgets/keybinding_footer.py` — Show pin/unpin in footer for running agents

Lines 453-461: The `else` branch handles RUNNING and other active statuses. Currently, pin/unpin only appears for PLAN
DONE and PLAN COMMITTED within this branch. Add pin/unpin for all active statuses (move it outside the
`PLAN DONE`/`PLAN COMMITTED` check, or add a parallel check for running statuses).

### 4. No changes needed

- **`_core.py` (`_build_panel_indices`)**: Already correct — running pinned agents stay in main, completed pinned agents
  move to pinned panel.
- **`pinned_agents.py`**: Identity-based persistence is status-agnostic, works as-is.
- **Help modal (`bindings.py`)**: Already says "Pin / unpin agent" — generic enough.
- **`default_config.yml`**: Keybinding unchanged.
