# Notifications

## Overview

Sase includes a notification system that surfaces important events from background processes (axe, workflows, mentors)
to the user through the ACE TUI. Notifications are stored as JSONL and persisted to
`~/.sase/notifications/notifications.jsonl`.

Plan, epic-plan, question, and agent-launch approvals use the notification row as a typed transport projection of a
durable interaction gate. The reviewed content, option-query branches, validation schemas, and hash-verified commands
live in `~/.sase/interaction_requests/<kind>/<request-id>/`; ACE, mobile, Telegram, and typed CLI actions all resolve
that same bundle.

## Viewing Notifications

Press `i` on any tab in ACE to open the notifications modal. Notifications display relative timestamps (e.g., "2m ago",
"1h ago") and can be marked as read or dismissed.

### Modal Keybindings

| Key                 | Action                                                                         |
| ------------------- | ------------------------------------------------------------------------------ |
| `j` / `k`           | Navigate between notifications                                                 |
| `Enter`             | Select notification (jump to PR, approve plan, etc)                            |
| `d`                 | Open Gate Debug for the highlighted row                                        |
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
top-bar indicator, toast pipeline, and arrival bell ignore them.

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

### Visual and Audible Delivery

New unmuted notifications remain visually prominent through the top-bar indicator and action-specific toasts. A
genuinely new `PlanApproval` or `EpicApproval` rings once on arrival, alongside its priority inbox row, warning toast,
and the producer's desktop notification. Already-handled plan reviews discovered during polling and the intermediate
post-approval handoff remain silent. Questions, launch/custom/HITL gates, errors, agent completions, and ordinary
notifications retain their arrival bell.

Snooze expiry is an explicit reminder chosen by the user and remains audible for every notification class, including a
snoozed tale or epic review.

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
`sase artifact create -p <path> [-l <label>] [-k <kind>]` are read from the persistent artifact index and appended last
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

### Report Notifications

Any producer — a chop, a hook, or an agent — may attach a structured report to a notification by setting
`action: "ViewReport"`. The report is a **chop report document** (`{"title": ..., "blocks": [...]}`), the same artifact
`sase.chops.ChopReport` builds and the AXE tab already renders, so the notification carries no producer-private schema.

`action_data` describes where the document lives:

| Key            | Meaning                                                                                 |
| -------------- | --------------------------------------------------------------------------------------- |
| `report_path`  | Absolute (or `~`-prefixed) path to a JSON report document the producer keeps up to date |
| `report`       | A JSON-encoded report document embedded in the notification — an immutable snapshot     |
| `report_title` | Optional display title override; otherwise the document's own `title`, else `"Report"`  |

Both keys are optional and both may be present. Resolution order, and the provenance the reader sees:

1. `report_path` resolves, loads, and validates → **live**, stamped with the file's mtime (`live · updated 2m ago`).
2. Otherwise `report` parses and validates → **snapshot**, stamped with the notification timestamp
   (`snapshot · captured 3h ago`).
3. Otherwise → one explicit failure line naming the reason, plus the path that was tried. Never an exception, never an
   empty pane.

Pointing at a stable published path lets an hours-old notification open the _current_ picture, while the inline snapshot
guarantees the pane still renders honestly if the producer's state was wiped.

The loader (`sase.notifications.load_notification_report`) is fail-closed and never raises. It performs no network
access and no subprocess calls, and it rejects:

- a relative or `~`-unexpandable path, a missing path, or a path that is not a regular file;
- a file larger than 256 KiB — a size failure, not a truncation;
- content that is not a JSON object, or that fails chop-report validation through the Rust schema authority
  (`sase.chops.validate_chop_report`).

Every failure becomes a bounded, human-readable `error` string such as `report file not found`,
`report file is too large (312 KiB)`, or ``report document is invalid: unknown variant `bogus` ``. Rendering is safe by
construction: `render_chop_report` builds Rich text with explicit styles and never interprets console markup or ANSI
from the document.

In ACE, selecting a `ViewReport` notification renders the report in the modal's right pane under its provenance line,
with a dim `attachments:` footer when the notification also carries files. Pressing Enter re-reads the document and
opens the full-screen report modal, so the modal always shows the freshest published report rather than the pane's
cached load. That modal binds `Ctrl+D`/`Ctrl+U` for half-page scrolling, `j`/`k` for lines, `g`/`G` for top/bottom, `y`
to copy the report path, `e` to open the file in `$EDITOR`, and `Esc`/`q` to close. `y` and `e` warn instead for an
inline snapshot, which has no file path. `ViewReport` is an ordinary informational action: selecting it marks the
notification read.

### Action-less Notifications

A notification with no `action` is a valid, common shape — an informational row with nothing to open. Selecting one in
ACE marks it read and does nothing else; it is a silent no-op, not a producer error. Only a non-empty `action` string
this build does not recognize produces an "Unsupported notification action" warning.

## Notification Fields

Each notification contains:

| Field          | Type         | Description                                                                                                                                                     |
| -------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`           | string       | UUID4 unique identifier                                                                                                                                         |
| `timestamp`    | string       | ISO-8601 creation timestamp                                                                                                                                     |
| `sender`       | string       | Source identifier (e.g., "plan", "sync", "axe")                                                                                                                 |
| `icon`         | string\|null | Optional single emoji or display glyph                                                                                                                          |
| `notes`        | list[string] | Human-readable message lines                                                                                                                                    |
| `files`        | list[string] | Associated file paths (e.g., plan files, error digest files, generated agent images)                                                                            |
| `tags`         | list[string] | Optional normalized labels for filtering and modal tabs                                                                                                         |
| `action`       | string\|null | Action type: `HITL`, `PlanApproval`, `EpicApproval`, `UserQuestion`, `LaunchApproval`, `ViewReport`, etc. `null` means the notification is purely informational |
| `action_data`  | dict         | String identifiers and owned paths for the typed action; rich gate definitions stay in `request.json`                                                           |
| `read`         | bool         | Whether the notification has been read                                                                                                                          |
| `dismissed`    | bool         | Whether the notification has been dismissed                                                                                                                     |
| `silent`       | bool         | Silent notifications are stored but hidden from the TUI                                                                                                         |
| `muted`        | bool         | Muted notifications appear under `Muted` and are excluded from the indicator, arrival bell, and toasts                                                          |
| `snooze_until` | string\|null | ISO-8601 timestamp at which a snoozed notification automatically un-mutes                                                                                       |

## Silent Notifications

Notifications from hidden background agents (summarize-hook, fix-hook, mentor) are created with `silent=True`. Silent
notifications are written to the JSONL file (preserving the audit trail) but excluded from the TUI unread count, top-bar
indicator, arrival bell, toast, notification modal, and Telegram delivery. They remain visible to local inspection
commands such as `sase notify list`.

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
registered privileged actions (`PlanApproval`, `EpicApproval`, `UserQuestion`, `LaunchApproval`, `CustomGate`, and
`HITL`) because a raw row has no trusted command bundle.

The first-class gate API reads a versioned gate specification from stdin:

```bash
sase gate create < gate-request.json
```

For example, this custom gate offers a restart-and-verify group plus a separate rejection branch:

```json
{
  "schema_version": 3,
  "kind": "custom",
  "request_id": "restart-api",
  "producer": { "agent": "maintenance" },
  "continuation_mode": "resume_agent",
  "gate_timeout_seconds": 900,
  "presentation": {
    "sender": "maintenance",
    "icon": "🛡️",
    "notes": ["Restart the API after reviewing the health report?"],
    "preview": "preview.md"
  },
  "query": "(restart AND verify) OR reject",
  "primary_branch": ["restart", "verify"],
  "options": [
    {
      "id": "restart",
      "label": "Restart service",
      "icon": "🚀",
      "default_selected": true,
      "feedback": "required",
      "command": { "argv": ["commands/restart"] }
    },
    {
      "id": "verify",
      "label": "Verify service health",
      "icon": "🩺",
      "default_selected": true,
      "feedback": "disabled",
      "command": { "argv": ["commands/verify"] }
    },
    {
      "id": "reject",
      "label": "Do not restart",
      "icon": "❌",
      "feedback": "optional",
      "command": { "argv": ["commands/reject"] }
    }
  ],
  "groups": [
    {
      "options": ["restart", "verify"],
      "label": "Restart service",
      "icon": "🚀"
    }
  ],
  "resources": [
    {
      "path": "commands/restart",
      "role": "command",
      "content": "#!/bin/sh\nprintf '{\"status\":\"restarted\"}\\n'\n"
    },
    {
      "path": "commands/verify",
      "role": "command",
      "content": "#!/bin/sh\nprintf '{\"status\":\"healthy\"}\\n'\n"
    },
    {
      "path": "commands/reject",
      "role": "command",
      "content": "#!/bin/sh\nprintf '{\"status\":\"rejected\"}\\n'\n"
    },
    {
      "path": "preview.md",
      "role": "preview",
      "content": "# API health report\n\nAll checks passed.\n"
    }
  ],
  "auto": false
}
```

`presentation.icon`, `option.icon`, and `group.icon` each accept one emoji or display glyph. Each `OR` branch is a
mutually exclusive resolution path. A singleton branch renders as one button; an `AND` branch renders selectable option
toggles plus a submit button. The selected ids must be a non-empty subset of exactly one branch. `default_selected`
defaults to true, and a matching `groups` entry configures an AND branch's submit label and icon. `feedback` is
`disabled`, `optional`, or `required`; custom options default to `optional`, and a group selection uses the strongest
mode among its selected members. Automatic resolution is forbidden for custom gates. `primary_branch` must name one
complete branch in canonical query order. ACE submits it with Enter while Space toggles the focused AND member;
submitting a primary group preserves the reviewer's current toggles. ACE also numbers top-level branches in canonical
order: the fixed keys `1`–`9` submit their matching branches directly. AND-member toggles remain unnumbered.

Every option references a bundle-owned `command` resource and is executed in query order as an argv array without a
shell after its hash is reverified. A selected-command failure is recorded in the bundle error log and leaves the gate
answerable. The write-once response records `selected_option_ids`, `option_results`, and normalized top-level `feedback`
consistently for every transport.

On success, creation prints a stable JSON descriptor containing `schema_version`, `notification_id`, `request_id`,
`kind`, bundle/request/response/preview paths, `continuation_mode`, `auto_resolution`, and hashes. The descriptor's
`request_id` and `kind` are the exact values accepted by `sase gate wait`. Typed front doors such as
`sase plan propose`, `sase questions`, and agent-initiated launch requests call the same in-process gate service
directly; they do not spawn this CLI. Agents should normally use the generated `/sase_gate` skill to author this JSON.

Wait mechanically for a gate without reading or polling bundle files directly:

```bash
sase gate wait --id <request_id> --kind <kind>
sase gate wait --id <request_id> --kind <kind> --json
sase gate wait --id <request_id> --kind <kind> --timeout 60
```

Human output is colored and summarizes the selected options, feedback, and response path. `-j/--json` emits the stable
shape `status`, `selected_option_ids`, `feedback`, and `response_path`. Status is `answered`, `cancelled`, or `timeout`,
with exit codes 0, 3, and 4 respectively. A CLI timeout can shorten but never extend the request's own gate timeout.

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
request records the continuation mode, optional gate timeout, typed payload, presentation metadata and icon,
option-query branches, the declared primary branch, options with configurable icons and feedback modes, AND-group submit
metadata, input/result schemas, and hashes for the request and owned resources. Commands are argv arrays executed
without a shell. Plan editing is the one non-terminal operation: after `$EDITOR` exits, SASE revalidates the authored
tier and refreshes the reviewed hashes before approval can continue.

Manual creation succeeds only after the bundle, notification row, and pending-action registration are durable. A partial
failure is compensated, and retries are idempotent by request ID. Manual and automatic selections use the same hash,
input, result, and write-once response validation. The pending-action 24-hour stale threshold is transport-only; it may
hide remote controls but does not terminate a waiting producer. Only cancellation or an explicit per-request gate
timeout is terminal. Every terminal response or cancellation marks the pending action handled and dismisses the
notification row, regardless of gate kind or client surface. When ACE opens the notification modal, it also repairs live
gate rows whose bundles became terminal without a corresponding dismissal.

ACE, Telegram, and mobile render branches in query order from the same normalized envelope structure. Singleton branches
are buttons. AND branches expose one toggle per option and a configurable submit control; the primary AND branch starts
expanded. Top-level branches have fixed one-based digit selectors in canonical query order, while AND members remain
unnumbered and use Space to toggle. Enter submits the declared primary branch, Ctrl+S submits the active branch, and `q`
or Escape cancels the modal. Surfaces submit only `selected_option_ids` and feedback, and the shared executor runs the
selected commands in query order.

Tale plan approval uses `(approve AND commit) OR reject OR feedback`. The approve and commit options start selected, the
group submit is labeled **Tale**, and the two singleton branches remain **Reject** and **Send Feedback**. Epic plans use
`approve OR reject OR feedback`.

The typed projections remain deliberately distinct:

| Gate kind   | Notification action | Recommended producer                              |
| ----------- | ------------------- | ------------------------------------------------- |
| `plan`      | `PlanApproval`      | `sase plan propose` with an authored `tier: tale` |
| `epic_plan` | `EpicApproval`      | `sase plan propose` with an authored `tier: epic` |
| `question`  | `UserQuestion`      | `sase questions`                                  |
| `launch`    | `LaunchApproval`    | Agent-initiated `sase launch request`             |
| `custom`    | `CustomGate`        | `sase gate create`                                |

Workflow `HITL` remains a legacy producer, but a HITL notification that references a neutral bundle is resolved through
the same hash-verified executor in ACE and Telegram. Only legacy HITL bundles use the direct response-file writer.

### Debugging a gate

Press `d` on any notification row or from an open plan, epic, question, launch, custom-gate, or workflow HITL panel to
open **Gate Debug**. The overlay keeps the underlying form mounted, so closing it returns to the same selected branch,
checked group options, and typed feedback. Non-gate inbox rows use the same view and show an explicit no-bundle state
alongside their raw notification JSON.

Gate Debug loads bundle I/O and hash verification away from the TUI event loop. Its tabs show the lifecycle overview,
the canonical `request.json`, the terminal `response.json` or `cancellation.json`, bounded execution error records, and
the raw row from `notifications.jsonl`. The overview re-verifies request and resource hashes live and includes timeout,
pending-action transport/staleness, and notification state. Missing, malformed, or oversized artifacts render as
diagnostics instead of preventing the modal from opening.

| Key                 | Gate Debug action                                             |
| ------------------- | ------------------------------------------------------------- |
| `[` / `]`           | Switch tabs                                                   |
| `j` / `k`           | Scroll one line                                               |
| `Ctrl+D` / `Ctrl+U` | Scroll half a page                                            |
| `g` / `G`           | Jump to the top / bottom                                      |
| `y`                 | Copy the current tab's raw text                               |
| `Y`                 | Copy the gate bundle path                                     |
| `e`                 | Open the current tab's backing artifact in `$EDITOR`          |
| `d` / `Esc` / `q`   | Close Gate Debug and return to the underlying notification UI |

### Compatibility window

Readers resolve the neutral bundle first and then fall back to in-flight legacy plan, question, launch, or HITL request
directories. New producers do not dual-write the old trees. Keep these fallbacks for at least one complete SASE release
after neutral writers ship and beyond the 24-hour remote-action stale window. The cross-kind resolver regression test
locks this rule in; removing a fallback requires a separately announced migration after that window, updated fixtures,
and explicit release notes.

Unanswered schema-v2 neutral bundles also remain hash-verifiable and answerable. Readers project their historical first
branch as the primary action in memory; new gate creation requires schema v3 and an explicit `primary_branch`.

Question summaries use the same resolver, so ACE can render both neutral and legacy questions. Gate command execution
from ACE is scheduled as tracked background work rather than running on Textual's event loop.

## Storage

Notifications are stored in JSONL format at `~/.sase/notifications/notifications.jsonl`. The production store backend is
`sase_core_rs`: appends and state mutations take a shared sidecar lock, and rewrites use a tempfile plus rename so
multiple axe processes and the TUI can access the file without truncate-before-lock exposure. Common state-only updates
such as mark-read, mark-all-read, mute, snooze, and dismiss use a count-only Rust mutation path unless the caller needs
rehydrated notification rows; this keeps inbox counters cheap when ACE or a bridge process only needs mutation metadata.

Source: `src/sase/notifications/`
