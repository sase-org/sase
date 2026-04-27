# Notifications

## Overview

Sase includes a notification system that surfaces important events from background processes (axe, workflows, mentors)
to the user through the ACE TUI. Notifications are stored as JSONL and persisted to
`~/.sase/notifications/notifications.jsonl`.

## Viewing Notifications

Press `i` on any tab in ACE to open the notifications modal. Notifications display relative timestamps (e.g., "2m ago",
"1h ago") and can be marked as read or dismissed.

### Modal Keybindings

| Key                 | Action                                                      |
| ------------------- | ----------------------------------------------------------- |
| `j` / `k`           | Navigate between notifications                              |
| `Enter`             | Select notification (jump to CL, approve plan, etc)         |
| `x`                 | Dismiss notification (with confirmation for plans)          |
| `m`                 | Toggle mute on the highlighted notification                 |
| `s`                 | Snooze the highlighted notification (opens duration picker) |
| `e`                 | Open attached file in `$EDITOR`                             |
| `Ctrl+N` / `Ctrl+P` | Cycle through attached files                                |
| `Ctrl+D` / `Ctrl+U` | Scroll file content down / up                               |
| `R`                 | Mark all notifications as read                              |
| `Esc` / `q`         | Close modal                                                 |

Plan and question notifications require confirmation (`y` / `n`) before dismissal to prevent accidental loss of pending
approvals.

### Sectioned Layout

The modal renders notifications in three fixed-order sections, each with a colored header row and per-section count:

| Section      | Color | Contents                                                                                                                                |
| ------------ | ----- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **PRIORITY** | Red   | Plan approvals, user questions, mentor reviews, axe error digests, CRS workflow results, and agent error reports                        |
| **INBOX**    | Gold  | Everything else                                                                                                                         |
| **MUTED**    | Cyan  | Notifications the user has muted (or that are still snoozed). Mute dominates priority — a muted plan appears under MUTED, not PRIORITY. |

Empty sections are not rendered. Section header rows are non-selectable; `j` / `k` skip over them automatically.

### Mute and Snooze

Press `m` on a notification to toggle its muted state. Muted notifications are dimmed in the list, prefixed with `~`,
and moved to the **MUTED** section. They are still delivered to the JSONL store and remain visible in the modal — only
the bell indicator and toast pipeline ignore them.

Press `s` to snooze a notification for `15m`, `1h`, `4h`, or until tomorrow morning. Snoozed notifications are
implicitly muted (so they fall into the MUTED section) and display a `⏰ <remaining>` badge counting down to the snooze
expiry. Toggling mute off cancels any pending snooze. The snooze expiry is persisted, so the notification re-emerges
from MUTED on its own once the timer runs out.

### Top-Bar Indicator

The notification indicator in the TUI top bar takes its color from the highest-priority unread bucket present:

- **Orange** — at least one unread PRIORITY notification (plan approval, user question, mentor review, axe error, …)
- **Gold** — only regular INBOX notifications are unread
- **Cyan** — only MUTED (or snoozed) notifications are unread
- **Hidden** — no unread notifications at all

Silent notifications never contribute to the indicator (see [Silent Notifications](#silent-notifications) below).

## Notification Types

The following events generate notifications:

| Sender             | Event                                                         |
| ------------------ | ------------------------------------------------------------- |
| `plan`             | A plan file is ready for user review and approval             |
| `question`         | An agent is asking the user a question (via Claude Code hook) |
| `hitl`             | A workflow HITL step is waiting for user input                |
| `sync`             | A sync operation completed for a ChangeSpec                   |
| `axe`              | Hourly error digest summarizing recent axe errors             |
| `mentors_complete` | All mentors finished for a ChangeSpec entry (or none matched) |
| (workflow)         | Workflow completion (success or failure)                      |

### Mentors-Complete Notification

A `mentors_complete` notification fires once per `(ChangeSpec, COMMITS entry)` under either of two conditions:

- **All mentors terminal** — every mentor that was started for the entry has reached a terminal status (`PASSED`,
  `COMMENTED`, `FAILED`, `DEAD`, or `KILLED`).
- **No matching profile** — every hook is ready and no mentor profile matched the ChangeSpec, so no mentors will run.

Selecting the notification jumps to the CLs tab, focuses the target ChangeSpec, and pushes the Mentor Review modal when
at least one mentor produced reviewable output.

Idempotency is enforced via `~/.sase/notifications/mentors_complete.json`, keyed on
`(project_file, changespec_name, entry_id)` — so the notification survives process restarts and `.gp` archival without
re-firing. The sender suppresses the notification on the same axe cycle that just wrote the `MENTORS` field for the
latest entry, preventing premature firing on `Draft → Ready` transitions.

## Notification Fields

Each notification contains:

| Field          | Type         | Description                                                                                            |
| -------------- | ------------ | ------------------------------------------------------------------------------------------------------ |
| `id`           | string       | UUID4 unique identifier                                                                                |
| `timestamp`    | string       | ISO-8601 creation timestamp                                                                            |
| `sender`       | string       | Source identifier (e.g., "plan", "sync", "axe")                                                        |
| `notes`        | list[string] | Human-readable message lines                                                                           |
| `files`        | list[string] | Associated file paths (e.g., plan files, error digest files)                                           |
| `action`       | string       | Action type: `HITL`, `JumpToChangeSpec`, `PlanApproval`, etc.                                          |
| `action_data`  | dict         | Action-specific data (e.g., response directory, CL name)                                               |
| `read`         | bool         | Whether the notification has been read                                                                 |
| `dismissed`    | bool         | Whether the notification has been dismissed                                                            |
| `silent`       | bool         | Silent notifications are stored but hidden from the TUI                                                |
| `muted`        | bool         | Muted notifications appear under the MUTED section and are excluded from the bell indicator and toasts |
| `snooze_until` | string\|null | ISO-8601 timestamp at which a snoozed notification automatically un-mutes                              |

## Silent Notifications

Notifications from hidden background agents (summarize-hook, fix-hook, mentor) are created with `silent=True`. Silent
notifications are written to the JSONL file (preserving the audit trail) but excluded from the TUI unread count, bell
indicator, toast, notification modal, and Telegram delivery.

Agent completion / failure events specifically suppress their notifications when the originating agent is a hidden
background agent. This keeps the inbox focused on user-facing agent work and prevents the firehose of internal hook
agents from drowning out real updates.

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
