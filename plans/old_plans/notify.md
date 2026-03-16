---
bead_id: sase-wjw
---

# Notification System Overhaul

## Context

The current notification system in `sase ace` is tightly coupled to agent identity tracking. Pressing `N` shows a simple
list of completed agents. Notifications are tracked via `viewed_agents.json` and `dismissed_agents.json` sets. HITL is
handled separately via file-based polling on the Agents tab.

This overhaul introduces a unified, file-based notification store with a `sase notify` CLI, a rich TUI notification
popup with file browsing, and three action types (HITL, JumpToChangeSpec, Tmux). It replaces the agent-completion
notifications, audible bells, tab badge, and agents-tab HITL.

## Final Notification Schema

```json
{
  "sender": "string (required)",
  "notes": ["array of strings"],
  "files": ["array of file paths to display"],
  "action": "HITL | JumpToChangeSpec | Tmux | null",
  "action_data": {
    "changespec_name": "string (for JumpToChangeSpec)",
    "project_file": "string (for JumpToChangeSpec)",
    "workspace_dir": "string (for Tmux)",
    "artifacts_dir": "string (for HITL)",
    "workflow_name": "string (for HITL)"
  }
}
```

---

## Phase 1: Notification Data Model, Storage Layer, and CLI

**Goal**: Build the foundation — data model, JSONL store, and `sase notify` CLI.

### Data Model (`src/sase/notifications/models.py`)

```python
@dataclass
class Notification:
    id: str                           # UUID
    timestamp: str                    # ISO-8601
    sender: str                       # "crs", "fix-hook", "sync", "axe", "user-agent", etc.
    notes: list[str]                  # Human-readable lines
    files: list[str]                  # File paths to display to user
    action: str | None                # "HITL", "JumpToChangeSpec", "Tmux", or None
    action_data: dict[str, str]       # Action-specific data
    read: bool = False
    dismissed: bool = False
```

### Storage (`src/sase/notifications/store.py`)

- JSONL file at `~/.sase/notifications/notifications.jsonl`
- `append_notification(n: Notification) -> None` — append one line, use `fcntl.flock()` for concurrency
- `load_notifications(include_dismissed: bool = False) -> list[Notification]` — read all, filter dismissed
- `mark_read(notification_id: str) -> None`
- `mark_dismissed(notification_id: str) -> None`
- `mark_all_read() -> None`

### CLI (`sase notify` subcommand)

- Add `notify` subparser in `src/sase/main/parser.py` (alphabetically between `init-git` and `restore`)
- Accepts JSON on stdin:
  `echo '{"sender":"crs","notes":["Done"],"action":"JumpToChangeSpec","action_data":{"changespec_name":"foo"}}' | sase notify`
- Also accepts `--sender` flag with JSON body as positional arg for simpler usage
- Handler in `src/sase/main/notify_handler.py` parses, validates, creates `Notification`, calls `append_notification()`
- Add handler dispatch in `src/sase/main/entry.py`

### Files to Create

- `src/sase/notifications/__init__.py`
- `src/sase/notifications/models.py`
- `src/sase/notifications/store.py`
- `src/sase/main/notify_handler.py`
- `tests/test_notification_store.py`

### Files to Modify

- `src/sase/main/parser.py` — add `notify` subparser
- `src/sase/main/entry.py` — add `notify` command dispatch

### Verification

- `echo '{"sender":"test","notes":["hello"],"files":[],"action":null}' | sase notify`
- `python -c "from sase.notifications.store import load_notifications; print(load_notifications())"`
- `just test -k test_notification`

---

## Phase 2: New TUI Notification Modal and Polling

**Goal**: Replace the current `NotificationModal` with a rich modal that reads from the notification store. Wire polling
and tab badge to notification count.

### New Notification Modal (`src/sase/ace/tui/modals/notification_modal.py`)

Rewrite to accept `list[Notification]` instead of `list[Agent]`. Layout:

```
┌─ Notifications ──────────────────────────────────────┐
│                                                      │
│  * [crs] CRS completed for my_feature    2m ago      │
│    > Addressed 3 reviewer comments                   │
│    [CL] 2 files                                      │
│                                                      │
│    [sync] Merge resolved for other_cl    15m ago      │
│    > All conflicts resolved by AI agent              │
│    [tmux] 0 files                                    │
│                                                      │
│  * [axe] Hourly error digest             1h ago      │
│    > 3 errors in the last hour                       │
│    [tmux] 5 files                                    │
│                                                      │
├──────────────────────────────────────────────────────┤
│ Enter: action  d: dismiss  f: files  R: read all     │
│ j/k: navigate  q/Esc: close                         │
└──────────────────────────────────────────────────────┘
```

- `*` = unread indicator
- `[CL]`/`[tmux]`/`[HITL]` = action type badge
- `f` key opens a file browser sub-view for the selected notification's files
- `d` dismisses the selected notification
- `R` marks all as read
- `Enter` triggers the action (or does nothing if action is null)
- Uses existing `OptionListNavigationMixin` for j/k navigation

### File Browser Sub-View

When user presses `f` on a notification with files:

- Show a secondary OptionList of file paths
- Selecting a file shows its contents in a scrollable panel (reuse syntax highlighting from `_EXTENSION_TO_LEXER`
  pattern)
- `q`/`Esc` returns to the notification list

### Polling Changes (`_notifications.py`)

- Replace `_poll_agent_completions()` internals to poll `load_notifications()` for unread count
- Keep `_ring_tmux_bell()` but trigger it when unread count increases between polls
- Update `_pending_attention_count` from notification unread count
- Tab badge continues to work via `TabBar.set_attention_count()`

### Files to Modify

- `src/sase/ace/tui/modals/notification_modal.py` — full rewrite
- `src/sase/ace/tui/actions/agents/_notifications.py` — replace polling internals
- `src/sase/ace/tui/app.py` — update `action_show_notifications` callback, update init
- `src/sase/ace/tui/modals/__init__.py` — update imports

### Files to Create

- `src/sase/ace/tui/modals/notification_file_browser.py` — file content viewer modal/sub-view

### Verification

- `echo '{"sender":"test","notes":["Test notification"],"files":["/tmp/test.txt"],"action":null}' | sase notify`
- Press `N` in TUI — new notification should appear
- Press `f` — file browser should open showing file contents
- Tab badge should show unread count
- Tmux bell should ring on new notification arrival

---

## Phase 3: Implement Notification Actions

**Goal**: Implement all three action types that fire when user presses Enter on a notification.

### JumpToChangeSpec Action

- Parse `action_data.changespec_name` and `action_data.project_file`
- Dismiss the modal
- Switch `app.current_tab` to `"changespecs"`
- Find the ChangeSpec by name in `app.changespecs`, set `app.current_idx`
- Toast notification if not found

### Tmux Action

- Parse `action_data.workspace_dir`
- Dismiss the modal
- Open tmux window in the workspace directory
- Reuse the pattern from `BaseActionsMixin.action_open_tmux()` (`app.suspend()` + subprocess)

### HITL Action

- Parse `action_data.artifacts_dir` and `action_data.workflow_name`
- Dismiss the modal
- Read `hitl_request.json` from artifacts_dir
- Construct `WorkflowHITLInput`, show `WorkflowHITLModal`
- On dismiss callback, write `hitl_response.json` back
- Reuse logic from `AgentWorkflowHITLMixin._answer_workflow_hitl`

### Files to Create

- `src/sase/ace/tui/actions/agents/_notification_actions.py` — `handle_jump_to_changespec()`, `handle_tmux()`,
  `handle_hitl()`

### Files to Modify

- `src/sase/ace/tui/actions/agents/_notifications.py` — wire modal callback to dispatch actions
- `src/sase/ace/tui/actions/agents/__init__.py` — export new module if needed

### Verification

- Send a JumpToChangeSpec notification, press Enter → should navigate to CL
- Send a Tmux notification, press Enter → should open tmux window
- Send a HITL notification, press Enter → should show HITL modal

---

## Phase 4: Wire Up Notification Senders

**Goal**: Add notification sending to all the sources described in requirements.

### Sender Helper Functions (`src/sase/notifications/senders.py`)

- `notify_workflow_complete(sender, cl_name, project_file, success, notes, action, action_data)`
- `notify_sync_result(status, cl_name, workspace_dir, project_file)`
- `notify_axe_error_digest(errors, workspace_dirs)`
- `notify_hitl_request(step_name, workflow_name, artifacts_dir)`

### CRS Workflow (`src/sase/axe_crs_runner.py`)

- In `finally` block after finalization, call `notify_workflow_complete()` with:
  - sender="crs", action="JumpToChangeSpec", action_data with changespec_name

### Fix-Hook Workflow (`src/sase/axe_fix_hook_runner.py`)

- Same pattern: sender="fix-hook", action="JumpToChangeSpec"

### User-Initiated Agents/Workflows

Three separate code paths need notification calls:

- **`src/sase/axe_run_agent_runner.py`** — TUI-launched agents. Add `notify_workflow_complete()` in the `finally` block
  (~line 303). sender="user-agent", action=Tmux if workspace dir known, else None.
- **`src/sase/axe_run_workflow_runner.py`** — Standalone workflows launched from TUI. Add `notify_workflow_complete()`
  in the `finally` block (~line 185). sender="user-workflow", action=Tmux if workspace dir known, else None.
- **`src/sase/main/_query.py:run_query()`** — CLI `sase run` foreground execution. This is a separate code path from the
  TUI runners. Add notification after run completes. sender="user-agent", action=None.

Only for non-axe-spawned agents (user-initiated via `sase run` or TUI keymaps).

### Sync Workflow (`src/sase/ace/tui/actions/sync.py:action_sync()`)

- In `action_sync()`, after parsing the workflow result JSON (~lines 129-140), check status:
  - `status == "success"` (clean, no merge) → NO notification
  - `status == "resolved"` or `status == "unresolved"` or `status == "error"` → send notification
- sender="sync", action="Tmux", action_data with workspace_dir

### Axe Hourly Error Digest (`src/sase/axe/core.py`)

- Leverage existing error collection infrastructure:
  - `src/sase/axe/state.py:append_error()` — already persists errors to `~/.sase/axe/recent_errors.json`
  - `src/sase/axe/state.py:read_errors()` — reads collected errors
  - `src/sase/axe/core.py:_handle_job_error()` — already calls `append_error()` on every job failure
- Add hourly scheduled job that calls `read_errors()`, filters by timestamp (last hour)
- If errors exist, call `notify_axe_error_digest()` with summary and workspace dirs
- Clear/mark digested errors after sending (no new error collection mechanism needed)

### HITL Workflow Steps (`src/sase/xprompt/workflow_hitl.py`)

- In `TUIHITLHandler.prompt()`, after writing `hitl_request.json`, call `notify_hitl_request()`
- sender="hitl", action="HITL", action_data with artifacts_dir and workflow_name

### Files to Create

- `src/sase/notifications/senders.py`

### Files to Modify

- `src/sase/axe_crs_runner.py`
- `src/sase/axe_fix_hook_runner.py`
- `src/sase/xprompt/workflow_hitl.py`
- `src/sase/axe/core.py`
- `src/sase/ace/tui/actions/sync.py`
- `src/sase/axe_run_agent_runner.py`
- `src/sase/axe_run_workflow_runner.py`
- `src/sase/main/_query.py`

### Verification

- Run `#crs` on a CL → notification should appear with JumpToChangeSpec action
- Run `#sync` with conflicts → notification should appear with Tmux action
- Run `#sync` without conflicts → NO notification
- Wait for axe error cycle → digest notification should appear
- Run workflow with `hitl: true` step → HITL notification should appear

---

## Phase 5: Deprecation Cleanup

**Goal**: Remove the old notification system that is now superseded.

### Remove

- `src/sase/ace/tui/viewed_agents.py` — no longer needed
- `src/sase/ace/tui/dismissed_agents.py` — no longer needed
- Old agent-identity tracking state: `_tracked_running_agents`, `_viewed_agents`, `_dismissed_agents`
- Old `_poll_agent_completions()` agent-identity logic (replaced in Phase 2)
- HITL polling from agents tab (`_answer_workflow_hitl` scanning for `hitl_request.json`)
- Old `NotificationModal` code that accepted `list[Agent]`
- Initialization of old state in `app.py` (`load_viewed_agents`, `load_dismissed_agents`)

### Preserve

- `_load_agents()` and agent display on Agents tab (still needed for viewing running agents)
- `WorkflowHITLModal` (still used, but invoked from notification action handler)
- Agent list, agent detail widgets (unchanged)

### Files to Modify

- `src/sase/ace/tui/app.py` — remove old init, clean up imports
- `src/sase/ace/tui/actions/agents/_notifications.py` — remove old agent tracking code
- `src/sase/ace/tui/actions/agents/_workflow_hitl.py` — remove HITL file polling
- `src/sase/ace/tui/actions/agents/_core.py` — clean up mixin chain

### Files to Delete

- `src/sase/ace/tui/viewed_agents.py`
- `src/sase/ace/tui/dismissed_agents.py`

### Verification

- `just check` passes
- `N` keymap still works with new notification store
- Agents tab still displays running/completed agents correctly
- No references to `viewed_agents.json` or `dismissed_agents.json` remain
- HITL only triggers through notification system
