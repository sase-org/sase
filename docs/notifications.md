# Notifications

## Overview

Sase includes a notification system that surfaces important events from background processes (axe, workflows, mentors)
to the user through the ACE TUI. Notifications are stored as JSONL and persisted to
`~/.sase/notifications/notifications.jsonl`.

Plan, epic-plan, question, and agent-launch approvals use the notification row as a typed transport projection of a
durable interaction gate. The reviewed content, terminal choices, validation schemas, and hash-verified commands live in
`~/.sase/interaction_requests/<kind>/<request-id>/`; ACE, mobile, Telegram, and typed CLI actions all resolve that same
bundle.

## Viewing Notifications

Press `i` on any tab in ACE to open the notifications modal. Notifications display relative timestamps (e.g., "2m ago",
"1h ago") and can be marked as read or dismissed.

### Modal Keybindings

| Key                 | Action                                                                         |
| ------------------- | ------------------------------------------------------------------------------ |
| `j` / `k`           | Navigate between notifications                                                 |
| `Enter`             | Select notification (jump to PR, approve plan, etc)                            |
| `x`                 | Dismiss notification (or bulk-dismiss every marked row when marks are present) |
| `m`                 | Toggle the per-row mark on the highlighted notification                        |
| `M`                 | Toggle mute on the highlighted notification                                    |
| `s`                 | Snooze the highlighted notification (opens duration picker)                    |
| `e`                 | Open attached file in `$EDITOR`                                                |
| `V`                 | Open the current image attachment in the image viewer                          |
| `Ctrl+N` / `Ctrl+P` | Cycle through attached files                                                   |
| `Ctrl+D` / `Ctrl+U` | Scroll file content down / up                                                  |
| `[` / `]`           | Switch notification tabs                                                       |
| `R`                 | Mark all notifications as read                                                 |
| `Esc` / `q`         | Close modal                                                                    |

Plan, launch, and question notifications require confirmation (`y` / `n`) before dismissal to prevent accidental loss of
pending approvals. The same `y` / `n` confirmation is used for bulk dismissal when at least one marked plan, launch, or
question notification is included in the batch.

### Tabs and Ordering

The modal renders a compact tab strip above the list when more than one top-level filter is present. Muted notifications
always move to `Muted`; otherwise HITL actions and errors take precedence over ordinary tags. Non-muted, non-HITL,
non-error notifications with multiple tags appear in each matching tag tab:

| Tab       | Contents                                                                                                                         |
| --------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `HITL`    | Plan and epic approvals, user questions, workflow HITL prompts, and launch approvals.                                            |
| `Errors`  | Axe error digests and agent error reports (sender `axe` or `user-agent` paired with the `ViewErrorReport` action).               |
| `General` | Untagged non-HITL, non-error, unmuted notifications.                                                                             |
| `Done`    | Non-HITL, non-error notifications carrying the `done` tag, pinned before other custom tags.                                      |
| Custom    | Other normalized notification tags, sorted alphabetically after `Done`; a multi-tagged row appears in each matching tab.         |
| `Muted`   | Notifications the user has muted or snoozed. Mute dominates every other classification; a muted plan appears under `Muted` only. |

Within the active tab, rows are ordered newest-first by their `timestamp` field. Rows with equal timestamps keep their
original arrival order, and rows whose timestamp can't be parsed fall to the bottom rather than breaking the modal. The
sort runs on every modal rebuild, so live actions like mark-read, dismiss, mute, and snooze update the visible order
immediately. Switching tabs with `[` / `]` or a mouse click clears modal-local marks so a hidden row is never
bulk-dismissed by accident.

### Marks and Bulk Dismiss

Press `m` on a notification to toggle a per-row mark. Marks are scoped to the open modal — closing the modal clears
them. While at least one row is marked, `x` switches from "dismiss the highlighted row" to "dismiss every marked row";
plan, launch, and question rows in the batch use the same `y` / `n` confirmation prompt as a single dismissal.

### Mute and Snooze

Press `M` on a notification to toggle its muted state. Muted notifications are dimmed in the list, prefixed with `~`,
and moved to the `Muted` tab. They are still delivered to the JSONL store and remain visible in the modal — only the
bell indicator and toast pipeline ignore them.

Press `s` to snooze a notification for `15m`, `1h`, `4h`, or until tomorrow morning. Snoozed notifications are
implicitly muted (so they fall into the `Muted` tab) and display a `⏰ <remaining>` badge counting down to the snooze
expiry. Toggling mute off cancels any pending snooze. The snooze expiry is persisted, so the notification re-emerges
from `Muted` on its own once the timer runs out.

### Top-Bar Indicator

The notification indicator in the TUI top bar takes its color from the highest-priority unread bucket present:

- **Orange** — at least one unread unmuted priority or error notification (plan approval, launch approval, user
  question, mentor review, axe error digest, agent error report, ...)
- **Gold** — only regular unmuted notifications are unread
- **Cyan** — only muted or snoozed notifications are unread
- **Dim zero** — no unread notifications at all

When muted unread notifications coexist with orange or gold actionable rows, the badge keeps the actionable count and
adds a trailing dot; the tooltip shows the exact priority/other/muted breakdown.

Silent notifications never contribute to the indicator (see [Silent Notifications](#silent-notifications) below).

## Notification Types

The following events generate notifications:

| Sender                         | Event                                                          |
| ------------------------------ | -------------------------------------------------------------- |
| `plan` / `epic`                | A tale or epic plan is ready for user review and approval      |
| `launch`                       | A running agent requested a new agent launch for approval      |
| `question`                     | An agent is asking the user a question (via `/sase_questions`) |
| `hitl`                         | A workflow HITL step is waiting for user input                 |
| `memory.proposed`              | A long-term memory proposal is ready for human review          |
| `sync`                         | A sync operation completed for a ChangeSpec                    |
| `axe`                          | Hourly error digest summarizing recent axe errors              |
| `mentors`                      | All mentors finished for a ChangeSpec entry (or none matched)  |
| Workflow-specific sender label | Workflow completion (success or failure)                       |

### Agent Completion Attachments

Agent completion notifications attach the standard chat transcript and diff first. On failures they also include the
error report and output log when those files exist. When a successful agent added or modified 10 or fewer Markdown
files, SASE renders best-effort PDF artifacts and appends those PDFs after the standard artifacts. When the run added or
modified image files, SASE appends those generated images after any Markdown PDFs. When the run added or modified video
files, SASE appends those generated videos after generated images. Explicit artifacts created during the run with
`sase artifact create -p <path> [-n <label>] [-k <kind>]` are read from the persistent artifact index and appended last
when their stored files still exist. Supported Markdown extensions are `.md` and `.markdown`; supported image extensions
are `.png`, `.jpg`, `.jpeg`, `.webp`, and `.gif`; supported video extensions are `.mp4`, `.m4v`, `.mov`, and `.webm`.

Attachment paths are discovered from local git changes, untracked files, saved proposal/commit diffs, and the latest
commit when the agent committed or opened a PR. Missing, deleted, unsupported, and duplicate paths are ignored. If more
than 10 Markdown sources remain after filtering, SASE skips Markdown PDF rendering for that completion and includes a
note explaining the limit. The final PDF, image, and video lists are also written to `done.json` as
`markdown_pdf_paths`, `image_paths`, and `video_paths` for agent metadata consumers. Explicit artifact paths are read
from the explicit-artifact association index at notification time, deduplicated against the standard attachments, and
ignored if the index is unavailable.

In ACE, completion artifacts are opened from the Agents tab with `a`. The artifact panel supports marking multiple files
and opening the full artifact sequence, so notification attachments, generated PDFs/images/videos, plan files, and
explicit artifacts use one selection workflow. Generated videos are included as ordinary file artifacts. ACE may also
include image and video files referenced by saved prompt artifacts in that picker. Those prompt-referenced media are
persisted or synthesized as ACE artifact-list entries, but they are not appended to notification delivery payloads
unless they also appear in `done.json.image_paths` / `done.json.video_paths` or were saved explicitly with
`sase artifact create`.

When an agent sets output variables with `sase var set`, non-reserved variables are snapshotted into the completion
notification and rendered in Telegram agent-completion messages. The reserved repeat-control variable `STOP` is omitted
from Telegram completion summaries.

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

Selecting the notification jumps to the PRs sub-tab, focuses the target ChangeSpec, and pushes the Mentor Review modal
when at least one mentor produced reviewable output.

Idempotency is enforced via `~/.sase/notifications/mentors_complete.json`, keyed on
`(project_file, changespec_name, entry_id)` — so the notification survives process restarts and project-spec archival
without re-firing. The sender suppresses the notification on the same axe cycle that just wrote the `MENTORS` field for
the latest entry, preventing premature firing on `Draft → Ready` transitions.

### Memory Proposal Notification

`sase memory write --notify` first saves the proposal, then best-effort creates a `memory.proposed` notification. The
notification includes the `memory` tag, evidence entries that resolved to local file paths, `action: memory_review`, and
`action_data.proposal_id`. Selecting it in ACE suspends the main TUI and opens the same interactive review app as
`sase memory review`, preselected on that proposal. Review decisions still happen in that app; the notification is only
the entry point. Proposal creation still succeeds if notification delivery fails, and the CLI reports the notification
id when delivery succeeds.

## Notification Fields

Each notification contains:

| Field          | Type         | Description                                                                                           |
| -------------- | ------------ | ----------------------------------------------------------------------------------------------------- |
| `id`           | string       | UUID4 unique identifier                                                                               |
| `timestamp`    | string       | ISO-8601 creation timestamp                                                                           |
| `sender`       | string       | Source identifier (e.g., "plan", "sync", "axe")                                                       |
| `icon`         | string\|null | Optional single emoji or display glyph                                                                |
| `notes`        | list[string] | Human-readable message lines                                                                          |
| `files`        | list[string] | Associated file paths (e.g., plan files, error digest files, generated agent images)                  |
| `tags`         | list[string] | Optional normalized labels for filtering and modal tabs                                               |
| `action`       | string       | Action type: `HITL`, `PlanApproval`, `EpicApproval`, `UserQuestion`, `LaunchApproval`, etc.           |
| `action_data`  | dict         | String identifiers and owned paths for the typed action; rich gate definitions stay in `request.json` |
| `read`         | bool         | Whether the notification has been read                                                                |
| `dismissed`    | bool         | Whether the notification has been dismissed                                                           |
| `silent`       | bool         | Silent notifications are stored but hidden from the TUI                                               |
| `muted`        | bool         | Muted notifications appear under the `Muted` tab and are excluded from the bell indicator and toasts  |
| `snooze_until` | string\|null | ISO-8601 timestamp at which a snoozed notification automatically un-mutes                             |

## Silent Notifications

Notifications from hidden background agents (summarize-hook, fix-hook, mentor) are created with `silent=True`. Silent
notifications are written to the JSONL file (preserving the audit trail) but excluded from the TUI unread count, bell
indicator, toast, notification modal, and Telegram delivery. They remain visible to local inspection commands such as
`sase notify list`.

Agent completion and failure events from hidden background agents still write a notification row, but with the silent
flag set. This keeps the JSONL audit trail complete while keeping the inbox focused on user-facing agent work.

## Tags

Senders may attach `tags` to a notification. Tags are normalized when notifications are created: whitespace is trimmed,
empty values are dropped, values are lowercased, and duplicates are removed while preserving sender order. Tags do not
change priority, error classification, unread counts, mute, snooze, or auto-dismiss matching.

Successful visible and hidden user-agent completion notifications that jump back to the agent row carry the `done` tag.
Failed user-agent notifications do not carry `done`; failures remain error reports.

Memory proposal notifications created by `sase memory write --notify` carry the `memory` tag. Use the `memory` tab in
ACE or `sase notify list --tag memory` to find proposal review notification rows.

In ACE, tags create modal tabs above the notification list after the synthetic `HITL`, `Errors`, and `General` tabs. The
`done` tab is intended as the quick path for successful agent completions; reading or jumping to a done Agents-tab row
dismisses its matching completion notification, so it disappears from the `Done` tab after the next refresh. Failed
agent notifications stay untagged by `done` and continue to render under the `Errors` tab.

## CLI

The `sase notify` command can create notifications and inspect the local notification inbox.

Bare `sase notify` is a read-only shortcut for `sase notify list`. Use `sase notify create` when writing a notification
from JSON input:

```bash
echo '{"sender": "test", "icon": "👋", "notes": ["Hello"], "tags": ["review"]}' | sase notify create
echo '{"sender": "audit", "notes": ["Background result"], "silent": true}' | sase notify create
sase notify create -s my_sender < notification.json
sase notify create -s my_sender --tag review --tag handoff < notification.json
```

Raw creation validates and preserves the optional single-glyph JSON `icon` and the JSON `silent` field. It rejects
registered privileged actions (`PlanApproval`, `EpicApproval`, `UserQuestion`, `LaunchApproval`, and `HITL`) because a
raw row has no trusted command bundle.

The low-level gate API reads a versioned gate specification from stdin:

```bash
sase notify create --gate < gate-request.json
```

Gate presentation and each choice or extra may carry a single-glyph `icon`. Choices may declare a `feedback` mode
(`disabled`, `optional`, or `required`) and ordered, independently selectable `extras`. On success the command prints a
stable JSON descriptor containing `schema_version`, `notification_id`, `request_id`, `kind`,
bundle/request/response/preview paths, `continuation_mode`, `auto_resolution`, and hashes. The descriptor's `request_id`
and `kind` are the exact values accepted by `sase notify wait`. Typed front doors such as `sase plan propose`,
`sase questions`, and agent-initiated launch requests call the same in-process gate service directly; they do not spawn
this CLI.

Wait mechanically for a gate without reading or polling bundle files directly:

```bash
sase notify wait --id <request_id> --kind <kind>
sase notify wait --id <request_id> --kind <kind> --json
sase notify wait --id <request_id> --kind <kind> --timeout 60
```

Human output is colored and summarizes the terminal choice, selected extras, feedback, and response path. `-j/--json`
emits the stable shape `status`, `choice_id`, `selected_extra_ids`, `feedback`, and `response_path`. Status is
`answered`, `cancelled`, or `timeout`, with exit codes 0, 3, and 4 respectively. A CLI timeout can shorten but never
extend the request's own gate timeout.

For read-only inspection, list recent notifications as either a compact table or stable JSON:

```bash
sase notify
sase notify list
sase notify list -j -l 20
sase notify list -j --sender axe
sase notify list -j --unread
sase notify list -j --tag done
sase notify list -j --tag memory
sase notify list -j -q digest
sase notify list -j --all
```

Use the explicit `list` subcommand when passing list flags; for example, use `sase notify list -j`, not
`sase notify -j`.

`sase notify list -j` prints notifications newest first with `id`, `timestamp`, `age`, `sender`, `icon`, `priority`,
`notes`, `files`, `tags`, `action`, `action_data`, `read`, `dismissed`, `silent`, `muted`, and `snooze_until`. The
`-q/--query` filter matches tags as well as ids, senders, notes, files, actions, and action data. Dismissed
notifications are hidden unless `--all` is provided.

Inspect one notification by id:

```bash
sase notify show --id <notification_id>
sase notify show --id <notification_id> -f json
sase notify show --id <notification_id> -f markdown
```

The default `show` format is markdown. It includes the notification tags, notes, attached file paths, action data, and
state flags. Axe error digest notifications usually point to the actionable report through `files` or
`action_data.error_report_path`; read that attached file for the detailed errors.

To create a local test notification with a persistent PNG attachment for ACE modal image-preview checks, run
`tools/test_image_notification` from the repository root.

See [`docs/configuration.md`](configuration.md#sase-notify) for the full CLI reference.

## Command-backed interaction gates

Each new gate is written once under `~/.sase/interaction_requests/<kind>/<request-id>/`. The bundle contains canonical
`request.json`, eventual write-once `response.json`, reviewed previews or attachments, and adapter-owned commands. The
request records the continuation mode, optional gate timeout, typed payload, presentation metadata and icon, terminal
choices with optional icons and feedback modes, independently selectable command extras, input/result schemas, and
hashes for the request and owned resources. Commands are argv arrays executed without a shell. Plan editing is the one
non-terminal operation: after `$EDITOR` exits, SASE revalidates the authored tier and refreshes the reviewed hashes
before approval can continue.

Manual creation succeeds only after the bundle, notification row, and pending-action registration are durable. A partial
failure is compensated, and retries are idempotent by request ID. Manual and automatic choices use the same hash, input,
result, and write-once response validation. The pending-action 24-hour stale threshold is transport-only; it may hide
remote controls but does not terminate a waiting producer. Only cancellation or an explicit per-request gate timeout is
terminal.

The typed projections remain deliberately distinct:

| Gate kind   | Notification action | Recommended producer                              |
| ----------- | ------------------- | ------------------------------------------------- |
| `plan`      | `PlanApproval`      | `sase plan propose` with an authored `tier: tale` |
| `epic_plan` | `EpicApproval`      | `sase plan propose` with an authored `tier: epic` |
| `question`  | `UserQuestion`      | `sase questions`                                  |
| `launch`    | `LaunchApproval`    | Agent-initiated `sase launch request`             |
| `custom`    | `CustomGate`        | `sase notify create --gate`                       |

Workflow `HITL` is registered at the adapter boundary but is not migrated to the command-backed producer in this
rollout; its existing behavior remains unchanged.

### Compatibility window

Readers resolve the neutral bundle first and then fall back to in-flight legacy plan, question, launch, or HITL request
directories. New producers do not dual-write the old trees. Keep these fallbacks for at least one complete SASE release
after neutral writers ship and beyond the 24-hour remote-action stale window. The cross-kind resolver regression test
locks this rule in; removing a fallback requires a separately announced migration after that window, updated fixtures,
and explicit release notes.

Question summaries use the same resolver, so ACE can render both neutral and legacy questions. Gate command execution
from ACE is scheduled as tracked background work rather than running on Textual's event loop.

## Storage

Notifications are stored in JSONL format at `~/.sase/notifications/notifications.jsonl`. The production store backend is
`sase_core_rs`: appends and state mutations take a shared sidecar lock, and rewrites use a tempfile plus rename so
multiple axe processes and the TUI can access the file without truncate-before-lock exposure. Common state-only updates
such as mark-read, mark-all-read, mute, snooze, and dismiss use a count-only Rust mutation path unless the caller needs
rehydrated notification rows; this keeps inbox counters cheap when ACE or a bridge process only needs mutation metadata.

Source: `src/sase/notifications/`
