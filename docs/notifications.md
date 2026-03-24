# Notifications

## Overview

Sase includes a notification system that surfaces important events from background processes (axe, workflows, mentors)
to the user through the ACE TUI. Notifications are stored as JSONL and persisted to
`~/.sase/notifications/notifications.jsonl`.

## Viewing Notifications

Press `N` on any tab in ACE to open the notifications modal. Notifications display relative timestamps (e.g., "2m ago",
"1h ago") and can be marked as read or dismissed.

### Modal Keybindings

| Key                 | Action                                              |
| ------------------- | --------------------------------------------------- |
| `j` / `k`           | Navigate between notifications                      |
| `Enter`             | Select notification (jump to CL, approve plan, etc) |
| `x`                 | Dismiss notification (with confirmation for plans)  |
| `e`                 | Open attached file in `$EDITOR`                     |
| `Ctrl+N` / `Ctrl+P` | Cycle through attached files                        |
| `Ctrl+D` / `Ctrl+U` | Scroll file content down / up                       |
| `R`                 | Mark all notifications as read                      |
| `Esc` / `q`         | Close modal                                         |

Plan and question notifications require confirmation (`y` / `n`) before dismissal to prevent accidental loss of pending
approvals.

## Notification Types

The following events generate notifications:

| Sender       | Event                                                                |
| ------------ | -------------------------------------------------------------------- |
| `plan`       | A plan file is ready for user review and approval                    |
| `question`   | An agent is asking the user a question (via Claude Code hook)        |
| `hitl`       | A workflow HITL step is waiting for user input                       |
| `sync`       | A sync operation completed for a ChangeSpec                          |
| `axe`        | Hourly error digest summarizing recent axe errors                    |
| (agent name) | Agent retry after a recoverable error (includes countdown and model) |
| (agent name) | Agent model fallback after exhausting retries                        |
| (workflow)   | Workflow completion (success or failure)                             |

## Notification Fields

Each notification contains:

| Field         | Type         | Description                                                   |
| ------------- | ------------ | ------------------------------------------------------------- |
| `id`          | string       | UUID4 unique identifier                                       |
| `timestamp`   | string       | ISO-8601 creation timestamp                                   |
| `sender`      | string       | Source identifier (e.g., "plan", "sync", "axe")               |
| `notes`       | list[string] | Human-readable message lines                                  |
| `files`       | list[string] | Associated file paths (e.g., plan files, error digest files)  |
| `action`      | string       | Action type: `HITL`, `JumpToChangeSpec`, `PlanApproval`, etc. |
| `action_data` | dict         | Action-specific data (e.g., response directory, CL name)      |
| `read`        | bool         | Whether the notification has been read                        |
| `dismissed`   | bool         | Whether the notification has been dismissed                   |

## CLI

The `sase notify` command creates a notification from the command line:

```bash
echo '{"sender": "test", "notes": ["Hello"]}' | sase notify
sase notify -s my_sender < notification.json
```

See [`docs/configuration.md`](configuration.md#sase-notify) for the full CLI reference.

## Storage

Notifications are stored in JSONL format at `~/.sase/notifications/notifications.jsonl`. File locking (via `fcntl`) is
used for concurrent read/write safety, since multiple axe processes and the TUI may access the file simultaneously.

Source: `src/sase/notifications/`
