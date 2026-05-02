---
create_time: 2026-04-07 16:59:02
status: wip
prompt: sdd/prompts/202604/fix_revive_agent.md
---

# Fix: Revived agents not appearing in side panel

## Problem

When a user revives a dismissed agent via R keymap on the Agents tab, the notification "Revived agent for X" appears but
the agent does not appear in the side panel.

## Root Cause

The issue stems from `agent_meta.json` not being cleaned up during dismissal or updated during revive.

`delete_agent_artifacts()` only removes `done.json`, `workflow_state.json`, and `prompt_step_*.json` — it does NOT
delete `agent_meta.json`. So when an agent is revived:

1. `_restore_agent_artifacts()` recreates `done.json`/`workflow_state.json`
2. `_restore_agent_meta()` sees `agent_meta.json` already exists → returns early without updating it
3. `_load_agents()` runs → `enrich_agent_from_meta()` reads the stale `agent_meta.json`
4. If that file contains `hidden: true` (set for axe-spawned agents like fix-hook, crs, mentor), the auto-dismiss code
   at `_loading.py:241-252` immediately re-dismisses the agent
5. Agent never appears in the side panel

This affects all agents that had `hidden: true` in their `agent_meta.json` — axe-spawned agents that the user manually
dismissed before auto-dismiss could trigger, or hidden FAILED agents that the user dismissed.

## Fix

Update `_restore_agent_meta` in `src/sase/ace/tui/actions/agents/_revive.py` to remove the `hidden` key from an existing
`agent_meta.json` when the file already exists. The user explicitly chose to revive this agent, so auto-dismiss should
not re-trigger.

- If `agent_meta.json` exists: read it, remove the `hidden` key, write it back
- If `agent_meta.json` does not exist: write it as before (no change)
