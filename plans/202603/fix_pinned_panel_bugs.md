---
create_time: 2026-03-30 15:07:57
status: done
---

# Fix Pinned Agents Panel Bugs

## Problem

Two independent code reviews of PR #56 (pinned agents panel) identified 5 bugs, all stemming from the same root cause:
pinned agents are removed from `self._agents` but many code paths still assume `self._agents` is the only agent list.

## Issues

1. **Wrong-agent bug** — ~15 action methods (`kill`, `diff`, `reword`, `edit`, `resume`, `wait`, `approve`,
   `toggle_layout`, `open_tmux`, `cycle_panel_mode`, etc.) read `self._agents[self.current_idx]` without checking
   `_pinned_panel_focused`. When focused on the pinned panel, the user acts on the wrong agent from the main list.

2. **No abstraction for "get current agent"** — Every action handler independently resolves the agent. PR #57's
   `_get_active_panel_agent()` pattern is the correct fix: one helper, every call site uses it.

3. **Notification navigation misses pinned agents** — `find_agent_for_notification()` and `navigate_to_agent_tab()` in
   `_notification_navigation.py` only search `_agents`. Clicking a notification for a pinned agent fails silently.

4. **Tab bar done count excludes pinned agents** — `done_visible` (line ~420 in `_core.py`) only counts from
   `self._agents`, but pinned agents have already been removed from that list. The tab shows a misleadingly low count.

5. **Notification status overrides miss pinned agents** — `_apply_agent_notification_statuses()` in `_notifications.py`
   (line ~110) iterates only `self._agents`, so PLANNING/QUESTION overrides don't apply to pinned agents.

## Design

### `_get_active_panel_agent()` Helper

Add to `AgentCoreMixin` in `_core.py`:

```python
def _get_active_panel_agent(self) -> Agent | None:
    if self._pinned_panel_focused and self._pinned_agent_objects:
        from ...widgets import PinnedAgentList
        pinned_list = self.query_one("#pinned-agent-list", PinnedAgentList)
        return pinned_list.get_selected_agent()
    if self._agents and 0 <= self.current_idx < len(self._agents):
        return self._agents[self.current_idx]
    return None
```

All action methods switch from the `self._agents[self.current_idx]` pattern to `self._get_active_panel_agent()`, with
early return on `None`.

### Combined Agent Lists for Global Operations

For operations that need to search all agents (notifications, counts), use
`[*self._agents, *self._pinned_agent_objects]`.

## Implementation Plan

### Phase 1: Add `_get_active_panel_agent()` helper

**Modify: `_core.py`** — Add the helper method. Also update:

- `action_jump_to_agent_changespec()` (line ~580) to use the helper
- `_apply_agent_detail_update()` already handles this correctly (leave as-is)

### Phase 2: Migrate all action call sites in `_interaction.py`

Replace `self._agents[self.current_idx]` with `self._get_active_panel_agent()` and `if agent is None: return` in:

- `action_kill_agent()` (line 83)
- `_refresh_agent_file()` (line 211)
- `_wait_agent()` (line 232)
- `_open_agent_chat()` (line 356)
- `action_resume_agent()` (line 456)
- `action_wait_for_agent()` (line 506)
- `_cycle_panel_mode()` (line 566)
- `_open_agent_tmux_window()` (line 604)
- `action_toggle_approve()` (line 657)
- `action_edit_panel()` (line 416) — doesn't directly get agent, but has bounds check on `_agents`

### Phase 3: Migrate folding call sites

**Modify: `_folding.py`** — `_expand_fold()` and `_collapse_fold()` use `self._agents[self.current_idx]`. These
operations only make sense for workflow parents in the main list. When `_pinned_panel_focused`, no-op (folding doesn't
apply to pinned agents, which are already completed).

### Phase 4: Fix notification navigation

**Modify: `_notification_navigation.py`**:

- `find_agent_for_notification()`: search `[*app._agents, *app._pinned_agent_objects]`
- `navigate_to_agent_tab()`: search both lists; if found in pinned list, set `_pinned_panel_focused = True` and select
  the agent in the pinned panel

### Phase 5: Fix notification status overrides

**Modify: `_notifications.py`**:

- `_apply_agent_notification_statuses()`: iterate `[*self._agents, *self._pinned_agent_objects]` instead of just
  `self._agents`

### Phase 6: Fix tab bar done count

**Modify: `_core.py`**:

- `done_visible` calculation: include pinned agents that are in `DISMISSABLE_STATUSES` (which they all are, since only
  dismissable pinned agents enter the pinned panel)

### Phase 7: Verify and test

Run `just check` to ensure lint/type/test pass. Run `sase ace --agent --keys tab` to verify the TUI renders correctly.

## Files Changed

| File                                         | Change                                          |
| -------------------------------------------- | ----------------------------------------------- |
| `actions/agents/_core.py`                    | Add `_get_active_panel_agent()`, fix done count |
| `actions/agents/_interaction.py`             | Migrate ~10 call sites to use helper            |
| `actions/agents/_folding.py`                 | No-op when pinned panel focused                 |
| `actions/agents/_notification_navigation.py` | Search both agent lists                         |
| `actions/agents/_notifications.py`           | Iterate combined list for overrides             |
