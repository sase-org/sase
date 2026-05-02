---
create_time: 2026-03-31 09:38:39
status: done
prompt: sdd/prompts/202603/pinned_dismiss_behavior.md
---

# Plan: Pinned Agent Dismiss Behavior

## Problem

When an agent/workflow is in the "Pinned" panel on the Agents tab:

1. The red `✘` icon is shown redundantly — the pinned panel already groups these entries, so the icon just adds noise.
2. Pressing `x` (dismiss) immediately dismisses the agent, even though the user likely wants to unpin first and review
   before dismissing. There's no intermediate step.

## Goal

- **Remove the `✘` icon** for entries rendered in the pinned panel.
- **Make `x` unpin instead of dismiss** when the selected agent is pinned. After unpinning, the entry moves to the main
  list panel and remains focused, so a second `x` press dismisses it.

## Design

### Phase 1: Remove `✘` icon in pinned panel

**File:** `src/sase/ace/tui/widgets/agent_list.py` (~line 272-275)

Currently the done icon is rendered for all dismissible agents regardless of panel. The icon style is already dimmed for
pinned agents, but we want to skip it entirely when `self._panel == "pinned"`.

Change: wrap the done-icon block in a `self._panel != "pinned"` guard.

### Phase 2: `x` unpins instead of dismissing for pinned agents

**File:** `src/sase/ace/tui/actions/agents/_interaction.py` (action_kill_agent, ~line 66-109)

Currently `action_kill_agent` checks `agent.status in DISMISSABLE_STATUSES` and immediately calls `_dismiss_done_agent`.
We need to intercept this for pinned agents.

Change: Before the dismiss branch (line 85-87), check if the agent is pinned. If so, call a new helper
`_unpin_and_focus(agent)` that:

1. Calls `toggle_pinned_agent` to unpin.
2. Saves pinned state.
3. Rebuilds panel indices.
4. Switches focus to the main panel.
5. Finds the agent's new position in the main panel and sets `current_idx` so it stays selected.
6. Refreshes display.
7. Notifies "Unpinned <name>".

This reuses the same logic from `action_pin_agent` (lines 125-150) but is unidirectional (always unpins) and always
follows the agent to the main panel.

### Phase 3: Footer hint update

**File:** `src/sase/ace/tui/widgets/keybinding_footer.py` (~line 439-442)

Currently for DONE/FAILED agents, the footer shows `x dismiss` regardless of pin state. We need to show `x unpin` when
the agent is pinned.

Change: In the `agent.status in ("DONE", "FAILED")` branch, use `"unpin"` as the label when `is_pinned` is True,
otherwise `"dismiss"`.

## Test plan

- Use `sase ace --agent` to verify the `✘` icon no longer appears for entries in the pinned panel.
- Verify the `✘` icon still appears for dismissible entries in the main panel.
- Verify that pressing `x` on a pinned agent unpins it and keeps it focused in the main list.
- Verify that pressing `x` again on the now-unpinned agent dismisses it normally.
- Run `just check` to validate lint, type checks, and tests pass.
