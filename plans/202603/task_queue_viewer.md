---
create_time: 2026-03-31 18:48:40
status: done
---

# Task Queue Viewer

## Problem

The TUI shows a `⚙ N` counter in the top-right when background tasks (sync, mail, accept) are running. Once tasks
complete, the counter goes back to 0 and there is **no way to see what happened** — whether tasks succeeded or failed,
what their output was, or even what tasks ran. Users must rely on transient toast notifications that disappear quickly.

## Design

### Interaction Model

**Keybinding**: `leader + t` (`,t`) — "leader, tasks". This fits the existing leader-mode pattern (`,i` for activity
dashboard, `,r` for runners, etc.). The `t` key is available in leader mode.

**Alternative access**: Clicking the `⚙ N` indicator could also open the modal in the future, but Textual click events
on Static widgets are fiddly. We'll start with the keybinding and can add click support later.

### Modal Design: `TaskQueueModal`

A two-panel modal (matching the NotificationModal layout pattern) that shows all tasks — running, completed, and failed:

```
┌─────────────── Task Queue ────────────────────────────────────────────────────┐
│                                                                               │
│  TASKS                                    │  OUTPUT                           │
│  ┌──────────────────────────────────────┐  │                                  │
│  │ ● sync my-feature          2s ago    │  │  Syncing my-feature...           │
│  │ ✓ mail login-fix           1m ago    │  │  Uploaded to Gerrit              │
│  │ ✗ accept broken-thing     3m ago     │  │  Rebased onto main              │
│  │ ✓ sync old-change        12m ago     │  │  Updated 3 files                │
│  │                                      │  │                                  │
│  │                                      │  │                                  │
│  └──────────────────────────────────────┘  │                                  │
│                                                                               │
│  j/k: navigate  d: dismiss  D: dismiss all done  Ctrl+D/U: scroll  q: close  │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Left panel** — task list (OptionList):

- Each row shows: status icon, task type, CL name, relative time
- Status icons: `●` running (green), `✓` success (cyan), `✗` error (red)
- Sorted newest-first (already the `get_all()` order)
- j/k navigation via `OptionListNavigationMixin`

**Right panel** — output viewer (scrollable Static):

- Shows the captured stdout/stderr output of the selected task
- For running tasks: shows "Task is running..." placeholder
- For errors: shows the error message prominently, then any captured output below
- ANSI-aware rendering via `Text.from_ansi()` (matching the AXE dashboard pattern)
- `Ctrl+D`/`Ctrl+U` to scroll

**Actions**:

- `d` — dismiss (remove) selected completed task from the queue
- `D` — dismiss all completed tasks (clear history)
- `q`/`Esc` — close modal
- `Enter` — close and return to main view (no-op action, just convenience)

### Data: Task Retention

Currently, completed tasks stay in the `TaskQueue._tasks` dict indefinitely (they're never cleaned up). This is actually
perfect for the viewer — we want a history. We'll add a light pruning mechanism:

- Auto-prune tasks older than 1 hour when the modal opens (keeps the list manageable)
- The `d`/`D` keys give manual control
- No persistence across TUI sessions (tasks are in-memory only, which is fine)

### Integration Points

1. **`task_queue.py`** — add `remove_completed()` method and `prune_old(max_age_seconds)` method
2. **New file: `modals/task_queue_modal.py`** — the modal implementation
3. **`modals/__init__.py`** — export `TaskQueueModal`
4. **`styles.tcss`** — modal styling (following NotificationModal/ActivityModal pattern)
5. **`keymaps/types.py`** — add `task_queue` key to `LeaderModeKeymaps`
6. **`default_config.yml`** — add `task_queue: "t"` to leader_mode keys
7. **`actions/agent_workflow/_leader_mode.py`** — handle the new leader key
8. **`actions/task_actions.py`** — add `_show_task_queue_modal()` method
9. **`modals/help_modal/bindings.py`** — add `,t` to leader mode section in help

## Phases

### Phase 1: Core Modal

- Add `remove_completed()` and `prune_old()` to `TaskQueue`
- Create `TaskQueueModal` with two-panel layout
- Wire up styling in `styles.tcss`
- Register the modal in `modals/__init__.py`

### Phase 2: Keybinding + Wiring

- Add `task_queue` to `LeaderModeKeymaps` defaults and `default_config.yml`
- Handle `,t` in `_handle_leader_key()`
- Add `_show_task_queue_modal()` to `TaskActionsMixin`
- Update help modal bindings
- Update leader mode footer bindings

### Phase 3: Polish

- Verify with `just check`
- Test with `sase ace --agent` if applicable
