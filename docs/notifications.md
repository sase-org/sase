# Notifications

## Overview

Sase includes a notification system that surfaces important events from background processes (axe, workflows, mentors)
to the user through the ACE TUI. Notifications are stored as JSONL and persisted to
`~/.sase/notifications/notifications.jsonl`.

## Viewing Notifications

Press `i` on any tab in ACE to open the notifications modal. Notifications display relative timestamps (e.g., "2m ago",
"1h ago") and can be marked as read or dismissed.

### Modal Keybindings

| Key                 | Action                                                                         |
| ------------------- | ------------------------------------------------------------------------------ |
| `j` / `k`           | Navigate between notifications                                                 |
| `Enter`             | Select notification (jump to CL, approve plan, etc)                            |
| `x`                 | Dismiss notification (or bulk-dismiss every marked row when marks are present) |
| `m`                 | Toggle the per-row mark on the highlighted notification                        |
| `M`                 | Toggle mute on the highlighted notification                                    |
| `s`                 | Snooze the highlighted notification (opens duration picker)                    |
| `e`                 | Open attached file in `$EDITOR`                                                |
| `V`                 | Open the current image attachment in the image viewer                          |
| `Ctrl+N` / `Ctrl+P` | Cycle through attached files                                                   |
| `Ctrl+D` / `Ctrl+U` | Scroll file content down / up                                                  |
| `R`                 | Mark all notifications as read                                                 |
| `Esc` / `q`         | Close modal                                                                    |

Plan and question notifications require confirmation (`y` / `n`) before dismissal to prevent accidental loss of pending
approvals. The same `y` / `n` confirmation is used for bulk dismissal when at least one marked plan or question
notification is included in the batch.

### Sectioned Layout

The modal renders notifications in four fixed-order sections, each with a colored header row and per-section count:

| Section      | Color  | Contents                                                                                                                                |
| ------------ | ------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| **PRIORITY** | Red    | Plan approvals, user questions, mentor reviews, non-error axe notifications, and CRS workflow results                                   |
| **ERRORS**   | Orange | Axe error digests and agent error reports (sender `axe` or `user-agent` paired with the `ViewErrorReport` action)                       |
| **INBOX**    | Gold   | Everything else                                                                                                                         |
| **MUTED**    | Cyan   | Notifications the user has muted (or that are still snoozed). Mute dominates priority — a muted plan appears under MUTED, not PRIORITY. |

Empty sections are not rendered. Section header rows are non-selectable; `j` / `k` skip over them automatically.

Within each section, rows are ordered newest-first by their `timestamp` field. The fixed section order (PRIORITY →
ERRORS → INBOX → MUTED) is never reshuffled — only the rows inside each section are sorted. Rows with equal timestamps
keep their original arrival order, and rows whose timestamp can't be parsed fall to the bottom of their section rather
than breaking the modal. The sort runs on every modal rebuild, so live actions like mark-read, dismiss, mute, and snooze
update the visible order immediately.

### Marks and Bulk Dismiss

Press `m` on a notification to toggle a per-row mark. Marks are scoped to the open modal — closing the modal clears
them. While at least one row is marked, `x` switches from "dismiss the highlighted row" to "dismiss every marked row";
plan and question rows in the batch use the same `y` / `n` confirmation prompt as a single dismissal.

### Mute and Snooze

Press `M` on a notification to toggle its muted state. Muted notifications are dimmed in the list, prefixed with `~`,
and moved to the **MUTED** section. They are still delivered to the JSONL store and remain visible in the modal — only
the bell indicator and toast pipeline ignore them.

Press `s` to snooze a notification for `15m`, `1h`, `4h`, or until tomorrow morning. Snoozed notifications are
implicitly muted (so they fall into the MUTED section) and display a `⏰ <remaining>` badge counting down to the snooze
expiry. Toggling mute off cancels any pending snooze. The snooze expiry is persisted, so the notification re-emerges
from MUTED on its own once the timer runs out.

### Top-Bar Indicator

The notification indicator in the TUI top bar takes its color from the highest-priority unread bucket present:

- **Orange** — at least one unread PRIORITY or ERRORS notification (plan approval, user question, mentor review, axe
  error digest, agent error report, …)
- **Gold** — only regular INBOX notifications are unread
- **Cyan** — only MUTED (or snoozed) notifications are unread
- **Dim zero** — no unread notifications at all

Silent notifications never contribute to the indicator (see [Silent Notifications](#silent-notifications) below).

## Notification Types

The following events generate notifications:

| Sender                         | Event                                                          |
| ------------------------------ | -------------------------------------------------------------- |
| `plan`                         | A plan file is ready for user review and approval              |
| `question`                     | An agent is asking the user a question (via `/sase_questions`) |
| `hitl`                         | A workflow HITL step is waiting for user input                 |
| `sync`                         | A sync operation completed for a ChangeSpec                    |
| `axe`                          | Hourly error digest summarizing recent axe errors              |
| `mentors`                      | All mentors finished for a ChangeSpec entry (or none matched)  |
| Workflow-specific sender label | Workflow completion (success or failure)                       |

### Agent Completion Attachments

Agent completion notifications attach the standard chat transcript and diff first. On failures they also include the
error report and output log when those files exist. When a successful agent added or modified 10 or fewer Markdown
files, SASE renders best-effort PDF artifacts and appends those PDFs after the standard artifacts. When the run added or
modified image files, SASE appends those generated images after any Markdown PDFs. Supported Markdown extensions are
`.md` and `.markdown`; supported image extensions are `.png`, `.jpg`, `.jpeg`, `.webp`, and `.gif`.

Attachment paths are discovered from local git changes, untracked files, saved proposal/commit diffs, and the latest
commit when the agent committed or opened a PR. Missing, deleted, unsupported, and duplicate paths are ignored. If more
than 10 Markdown sources remain after filtering, SASE skips Markdown PDF rendering for that completion and includes a
note explaining the limit. The final PDF and image lists are also written to `done.json` as `markdown_pdf_paths` and
`image_paths` for agent metadata consumers.

In ACE, completion artifacts are opened from the Agents tab with `A`. The artifact panel supports marking multiple files
and opening the full artifact sequence, so notification attachments, generated PDFs/images, plan files, and explicit
artifacts use one selection workflow. ACE may also include image files referenced by saved prompt artifacts in that
picker; those prompt-referenced images are local artifact-list entries and are not appended to notification delivery
payloads unless they also appear in `done.json.image_paths`.

The Agents tab also treats user-agent completions as unread work items. When a terminal agent is selected after it has
been marked unread, or when the user jumps to it with the unread-agent shortcut, ACE clears the row's unread marker and
dismisses the matching completion notification. Plan approvals and user questions remain explicit response workflows and
are not auto-read merely by selection.

Unread state on the Agents tab is projected from the active user-agent completion notifications in the store rather than
written as separate per-row state — when the underlying notification is dismissed (per-row selection, response modal, or
any other path) the row's unread marker clears on the next refresh. Manually toggling a row unread with `U` overrides
this projection locally so a deliberately re-flagged row is not immediately re-cleared. Plan approvals and user
questions still require an explicit `y` / `n` response and are never auto-dismissed by row navigation.

See [`agent_images.md`](agent_images.md) for the full attachment contract and ACE image preview notes.

For user-agent completion and failure notifications, `action_data` also includes `bead_display` when the agent name maps
to a bead created by `sase bead work`. The value includes the bead ID plus the issue description or title when the bead
can be resolved, and falls back to the ID alone otherwise. Cross-project lookups prefer the agent's owning project, then
the caller's current bead view, then all known SASE projects.

### Mentors-Complete Notification

A mentors-complete notification uses sender `mentors` and fires once per `(ChangeSpec, COMMITS entry)` under either of
two conditions:

- **All mentors terminal** — every mentor that was started for the entry has reached a terminal status (`PASSED`,
  `COMMENTED`, `FAILED`, `DEAD`, or `KILLED`).
- **No matching profile** — every hook is ready and no mentor profile matched the ChangeSpec, so no mentors will run.

Selecting the notification jumps to the CLs tab, focuses the target ChangeSpec, and pushes the Mentor Review modal when
at least one mentor produced reviewable output.

Idempotency is enforced via `~/.sase/notifications/mentors_complete.json`, keyed on
`(project_file, changespec_name, entry_id)` — so the notification survives process restarts and project-spec archival
without re-firing. The sender suppresses the notification on the same axe cycle that just wrote the `MENTORS` field for
the latest entry, preventing premature firing on `Draft → Ready` transitions.

## Notification Fields

Each notification contains:

| Field          | Type         | Description                                                                                            |
| -------------- | ------------ | ------------------------------------------------------------------------------------------------------ |
| `id`           | string       | UUID4 unique identifier                                                                                |
| `timestamp`    | string       | ISO-8601 creation timestamp                                                                            |
| `sender`       | string       | Source identifier (e.g., "plan", "sync", "axe")                                                        |
| `notes`        | list[string] | Human-readable message lines                                                                           |
| `files`        | list[string] | Associated file paths (e.g., plan files, error digest files, generated agent images)                   |
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
indicator, toast, notification modal, and Telegram delivery. They remain visible to local inspection commands such as
`sase notify list`.

Agent completion and failure events from hidden background agents still write a notification row, but with the silent
flag set. This keeps the JSONL audit trail complete while keeping the inbox focused on user-facing agent work.

## CLI

The `sase notify` command can create notifications and inspect the local notification inbox.

Create remains backward-compatible with the original bare command form:

```bash
echo '{"sender": "test", "notes": ["Hello"]}' | sase notify
sase notify -s my_sender < notification.json
sase notify create -s my_sender < notification.json
```

For read-only inspection, list recent notifications as either a compact table or stable JSON:

```bash
sase notify list
sase notify list -j -l 20
sase notify list -j --sender axe
sase notify list -j --unread
sase notify list -j -q digest
sase notify list -j --all
```

`sase notify list -j` prints notifications newest first with `id`, `timestamp`, `age`, `sender`, `priority`, `notes`,
`files`, `action`, `action_data`, `read`, `dismissed`, `silent`, `muted`, and `snooze_until`. Dismissed notifications
are hidden unless `--all` is provided.

Inspect one notification by id:

```bash
sase notify show --id <notification_id>
sase notify show --id <notification_id> -f json
sase notify show --id <notification_id> -f markdown
```

The default `show` format is markdown. It includes the notification notes, attached file paths, action data, and state
flags. Axe error digest notifications usually point to the actionable report through `files` or
`action_data.error_report_path`; read that attached file for the detailed errors.

To create a local test notification with a persistent PNG attachment for ACE modal image-preview checks, run
`tools/test_image_notification` from the repository root.

See [`docs/configuration.md`](configuration.md#sase-notify) for the full CLI reference.

## Storage

Notifications are stored in JSONL format at `~/.sase/notifications/notifications.jsonl`. The production store backend is
`sase_core_rs`: appends and state mutations take a shared sidecar lock, and rewrites use a tempfile plus rename so
multiple axe processes and the TUI can access the file without truncate-before-lock exposure. Common state-only updates
such as mark-read, mark-all-read, mute, snooze, and dismiss use a count-only Rust mutation path unless the caller needs
rehydrated notification rows; this keeps inbox counters cheap when ACE or a bridge process only needs mutation metadata.

Source: `src/sase/notifications/`
