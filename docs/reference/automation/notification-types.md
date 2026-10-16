---
title: Notification types
description: Notification payloads, fields, and silent notification behavior.
---

# Notification types

This page describes notification payload types, fields, and silent notifications.

<a id="notification-types-1"></a>

## Notification Types

The following events generate notifications:

| Sender                         | Event                                                                                                                                                                                                |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plan` / `epic`                | A tale or epic plan is ready for user review and approval                                                                                                                                            |
| `bead`                         | A task bead needs triage, a snoozed task woke, a due `flag` task bead needs `FlagTriage`, or stale uncorroborated tasks need `BeadStaleCleanup`                                                      |
| `plugin`                       | A project's required plugins are missing; the gate offers to install them                                                                                                                            |
| `launch`                       | A running agent requested a new agent launch for approval                                                                                                                                            |
| `question`                     | An agent is asking the user a question (via `/sase_questions`)                                                                                                                                       |
| `sudo`                         | An agent requested reviewed privileged execution (via `sase sudo request`); see [Sudo Requests](sudo.md)                                                                                             |
| `custom`                       | A `sase gate create` custom gate is waiting for review, unless its `presentation.sender` names another sender                                                                                        |
| `hitl`                         | A workflow HITL step is waiting for user input                                                                                                                                                       |
| `sync`                         | A sync operation completed for a Patch                                                                                                                                                               |
| `axe`                          | Hourly error digest summarizing recent axe errors                                                                                                                                                    |
| `service`                      | A desired-running service proc entered crash-loop or the restart policy gave up on it; the notes name the reason, restart count, log path, and the reviving `sase service proc start <name>` command |
| `file-hooks`                   | A configured per-file hook completed or failed, or a producer-side dispatch failure before a command ran                                                                                             |
| `mentors`                      | All mentors finished for a Patch entry (or none matched)                                                                                                                                             |
| `wait_checks`                  | A `%wait` dependency ended in a terminal state that can never satisfy the waiter                                                                                                                     |
| `gate`                         | A gate turn's follow-up handoff failed; the notes name the failed stage and the resume command                                                                                                       |
| `agent_hold`                   | A `%hold` or `sase agent hold` admission hold was armed or released                                                                                                                                  |
| `runner_slot_admission`        | A held agent and the agent holding it are blocking each other (hold deadlock)                                                                                                                        |
| Workflow-specific sender label | Workflow completion (success or failure)                                                                                                                                                             |

### Task Triage Notification

The five-minute `bead_task_triage` job creates one human-only `TaskTriage` gate for each
ready task bead that has accumulated at least its
[effective `+1` bar](../work-units/beads.md#per-type-triage-bar) of independent `+1`
reports — its task type's own `triage.min_plus_ones`, or
[`bead.task_triage.min_plus_ones`](../config/automation-behavior.md#bead) for an untyped
or unregistered type. A sub-threshold task is withheld from triage — it stays stored as
`ready`, only the gate is withheld — and a `TaskTriage` gate already raised for a task
that later falls below the bar is canceled and its notification dismissed on the job's
next tick.

After upgrading, gates already raised for beads below the new bar are canceled and their
notifications dismissed automatically on the first `checks`-lane tick. Run
`sase axe job run bead_task_triage` to force that tick immediately. To see the matching
cleanup gate without waiting for the hour, run `sase axe job run bead_stale_cleanup`.

Its compact notification note (`notes[0]`) is `<bead-id> — <title>` and it lands in the
`Beads` panel while retaining the `bead` and `task` tags. Every gate whose subject is a
typed task bead also declares a
[`presentation.chip`](notification-gates.md#command-backed-interaction-gates-1) — the
type glyph, the slug as its label, and the type accent — plus a second note (`notes[1]`)
with the compact typed facts line, for example
`Flaky test · Test node ID: tests/x.py::test_y · Evidence: 3/50 under -n 8`. The type
slug is appended as a display tag. An untyped bead's notification stays a single note
with no chip. The filing agent, when known, appears as a **Filed by** line in the
Markdown preview above the task's description and notes; the notes section is present
only when the bead has notes. The gate offers three branches:

- **Launch** is the default. It submits an unattributed proc that runs
  `sase bead work <task-id> --yes-to-all`; optional feedback is appended to the worker
  prompt.
- **Close** requires feedback and closes the bead with that reason and
  `resolution=canceled`.
- **Snooze** collects one required `duration` line containing a wake time with an
  optional `+N` suffix, for example `3d`, `2026-08-09T09:00:00-04:00`, or `3d +2`, the
  same vocabulary as
  [`sase bead snooze`](../work-units/bead-triage.md#snoozing-a-task-bead). Feedback is
  optional here and records **why** the task was deferred. An unparsable value fails the
  option and leaves the gate pending rather than losing the bead's only triage gate. It
  defers the bead — the triage gate settles and a `BeadSnooze` wake gate takes its place
  once the reconciler's next tick runs; see
  [Snoozed Task Notification](#snoozed-task-notification) below.

No decision branch is chosen automatically. While one of `TaskTriage`/`BeadSnooze`
remains pending for a bead, the job that owns both kinds (`bead_task_triage`) suppresses
duplicates and keeps the two mutually exclusive — a task bead never holds both at once.
After the bead mutation commits, `sase bead close` makes a best-effort attempt to cancel
the matching pending gate; a cancellation failure does not fail the close, and the next
reconciliation remains the backstop. Choosing **Launch** in `TaskTriage` answers that
gate normally, and a successful launch submission from sase's TUI Beads pane explicitly
cancels it. A direct `sase bead work <task-id>` command does not settle an older gate
itself; while a live agent is working the bead, the next reconciliation cancels that
stale gate with reason `bead_work_in_flight`. The same liveness rule covers `BeadSnooze`
and `FlagTriage`. If the bead's status otherwise changes out of band (leaves `ready`,
gets snoozed, or wakes), the job cancels the gate of the wrong kind and creates the
right one on its next tick. If a gate becomes terminal, disappears, or uses an obsolete
presentation or option-input contract while still expected, the next five-minute scan
creates a replacement with a new generation-specific request ID, except while the task
bead's detached launch is still in flight or a live agent is working the bead.

### Snoozed Task Notification

A snoozed task bead's `BeadSnooze` gate is born already snoozed: the reconciler creates
it with `presentation.panel: "beads"` and `presentation.snooze_until` set to the bead's
wake time, so the notification is muted with that deadline in one atomic step — there is
no window where it appears unread. It sits in the `Snoozed` tab for the whole deferral
(see [Tabs and Ordering](notifications.md#tabs-and-ordering)) and resurfaces in the
`Beads` panel tab, unmuted, exactly like any other snooze expiry once its wake time
arrives. The compact notification note (`notes[0]`) is still `<bead-id> — <title>`.
Every gate whose subject is a typed task bead also declares the same
[`presentation.chip`](notification-gates.md#command-backed-interaction-gates-1) and
typed facts `notes[1]` as a typed triage gate; an untyped bead stays a single note with
no chip. The preview shows who snoozed the bead, when, why, the wake time, and `+1`
progress toward any configured target.

The gate offers three branches:

- **Close** is the default. Empty feedback closes the bead with a preset reason
  (`"Snoozed until <until> with no new evidence; closing as stale."`); any feedback text
  replaces that reason verbatim. Resolution is `canceled`.
- **Ready** returns the bead to `ready` with a preset note, and the ordinary
  `TaskTriage` gate takes over on the reconciler's next tick.
- **Snooze** collects the same required `duration` line as the triage gate's snooze
  option and re-snoozes the bead with a new wake time and optional `+N` target; an
  unparsable value fails the option and leaves the gate pending rather than losing the
  bead. Feedback is optional and replaces the recorded deferral reason.

Reaching a configured `+1` target wakes the bead independently of the wake-time gate:
the bead promotes straight to `ready` with a preset note, and the pending `BeadSnooze`
gate is canceled in favor of a fresh `TaskTriage` gate. The two wake conditions race;
whichever is reached first wins.

### Flag Triage Notification

A due task bead of type `flag` raises one `FlagTriage` gate through the same
`bead_task_triage` reconciler that owns the other two task-bead gate kinds. The
notification lands in the `Beads` panel with `bead` and `task` tags plus the `flag` type
chip and tag. Its preview shows the flag key, kind, both-branch prose, `remove_when`,
both removal thresholds, the due countdown, the registry definition, notes, and call
sites.

The gate offers four branches:

- **Remove** is the primary path. It deletes the Off branch and makes the On branch
  unconditional, requires the winning branch (`enabled` or `disabled`) for the worker
  brief, and launches a worker to remove the registry entry and close the flag bead.
- **Extend** requires a new date/release threshold and a reason, then pushes both
  thresholds out and leaves the bead live.
- **Keep** requires a rationale for making the behavior permanent. It was never a
  feature flag; convert it to an ordinary config field and close the bead.
- **Close** abandons the removal. It requires a reason and closes the bead;
  registry/bead integrity checks catch any surviving orphaned flag.

### Stale Task Cleanup Notification

The hourly `bead_stale_cleanup` job raises one human-only `BeadStaleCleanup` gate once
at least
[`bead.task_triage.stale_cleanup_min_beads`](../config/automation-behavior.md#bead)
ready task beads have sat below the `+1` bar for
[`bead.task_triage.stale_after_days`](../config/automation-behavior.md#bead) days. The
notification lands in the `Beads` panel with `bead`, `task`, and `stale` tags. Its
preview lists the offered roster (at most 50 beads, oldest first) and names how many
additional stale beads were omitted when the backlog is larger. Each offered bead is a
close/keep control defaulting to close; the single **Close selected** branch closes the
reviewer-selected subset as `canceled`. Selecting nothing fails the command and leaves
the gate pending. The job keeps at most one of these gates at a time and cancels it when
the backlog drops below the bar. Run `sase axe job run bead_stale_cleanup` to raise or
refresh that gate without waiting for the next hourly housekeeping tick.

### Required Plugin Notification

The five-minute `plugins_required` job raises one human-only `PluginsRequired` gate per
enabled project whose `plugins.required` entries are missing or version-mismatched. The
notification lands in the `Plugins` panel with `plugin` and `required` tags. Its preview
lists each unsatisfied requirement and notes that a successful install restarts the
scheduler.

The gate offers two branches:

- **Install** is the primary path. It performs one combined install for every missing
  requirement, sharing a bounded public-index probe and resolving each plugin from the
  index unless public PyPI returns a definitive 404, in which case that plugin uses git.
  When planning or the `uv` mutation fails, including when sase is not a `uv tool`
  install, the gate stays pending rather than reporting a phantom success.
- **Dismiss** records the decision so the same missing set is not re-offered until it
  changes.

The job cancels the gate when the required set becomes satisfied. Agent and
non-interactive contexts still fail closed and never auto-install. Run
`sase axe job run plugins_required` to raise or refresh those gates without waiting for
the next five-minute checks tick.

### Blocked Wait and Hold Notifications

These informational rows have no action, so they carry nothing to approve. Each one is
deduplicated, and a repeat occurrence appends `+1` evidence to the existing row instead
of creating a new one.

- **Terminally blocked waits.** The `wait_checks` job notifies once per parked waiter
  whose named `%wait` dependency already ended with an outcome that can never satisfy
  the wait, such as a failed or killed agent. Waiters whose runner is provably dead are
  skipped and never notified. The notes name the waiter, the blocking dependency, its
  artifact directory, and its outcome, and suggest killing and relaunching the waiter or
  deliberately clearing the wait. The row attaches both artifact directories and carries
  the `wait`, `blocked`, and `terminal-dependency` tags; later checks append
  `Still blocked on …` evidence.
- **Hold armed and released.** Arming a `sase agent hold` admission hold posts one
  `agent_hold` row per armer with the `agent-hold` and `armed` tags, its expiry, and any
  frozen `pending` capture counts. The
  [`%hold`](../macros/directive-launch.md#hold-directive) directive pre-arms the same
  durable hold during launch submission. Re-arming appends `+1` evidence. A release
  posts an `agent-hold` / `released` row with the reason, including automatic release
  after the armer dies or the TTL expires. Expiry evidence names the exact TTL boundary
  and retains the stored arm-time capture summary.
- **Hold deadlocks.** When runner-slot admission finds that a held agent and the agent
  holding it are blocking each other, it posts a `Hold deadlock` row with the `hold`,
  `deadlock`, and `blocked` tags and both artifact directories. This happens when the
  armer is itself still waiting or queued on the held agent, directly or through its own
  `%wait` chain. The notification only reports the deadlock: the hold's TTL still
  guarantees progress, and releasing the hold or killing one side resolves it sooner.

### Agent Completion Attachments

Agent completion notifications attach the standard chat transcript and diff first. On
failures they also include the error report and output log when those files exist. When
a successful agent added or modified 10 or fewer Markdown files, SASE renders
best-effort PDF artifacts and appends those PDFs after the standard artifacts. When the
run added or modified image files, SASE appends those generated images after any
Markdown PDFs. When the run added or modified video files, SASE appends those generated
videos after generated images. Explicit artifacts created during the run with
`sase artifact create -p <path> [-l <label>] [-k <kind>]` are read from the persistent
artifact index and appended last when their stored files still exist. Supported Markdown
extensions are `.md` and `.markdown`; supported image extensions are `.png`, `.jpg`,
`.jpeg`, `.webp`, and `.gif`; supported video extensions are `.mp4`, `.m4v`, `.mov`, and
`.webm`.

Attachment paths are discovered from local git changes, untracked files, saved
proposal/commit diffs, and the latest commit when the agent committed or opened a PR.
Missing, deleted, unsupported, and duplicate paths are ignored. If more than 10 Markdown
sources remain after filtering, SASE skips Markdown PDF rendering for that completion
and includes a note explaining the limit. The final PDF, image, and video lists are also
written to `done.json` as `markdown_pdf_paths`, `image_paths`, and `video_paths` for
agent metadata consumers. Explicit artifact paths are read from the explicit-artifact
association index at notification time, deduplicated against the standard attachments,
and ignored if the index is unavailable.

In sase's TUI, completion artifacts are opened from the Agents tab with `a`. The
artifact panel supports marking multiple files and opening the full artifact sequence,
so notification attachments, generated PDFs/images/videos, plan files, and explicit
artifacts use one selection workflow. Generated videos are included as ordinary file
artifacts. sase's TUI may also include image and video files referenced by saved prompt
artifacts in that picker. Those prompt-referenced media are persisted or synthesized as
sase's TUI artifact-list entries, but they are not appended to notification delivery
payloads unless they also appear in `done.json.image_paths` / `done.json.video_paths` or
were saved explicitly with `sase artifact create`.

When an agent sets output variables with `sase var set`, non-reserved variables are
snapshotted into the completion notification as sorted JSON and rendered in Telegram
agent-completion messages. The SASE-managed `artifacts` list from `sase artifact create`
is included like any other non-reserved variable. The snapshot preserves structured
values (including nested lists and maps); each value is already bounded by the 64 KiB
encoded-variable limit, and the notification store does not impose a smaller
`action_data` limit. The reserved repeat-control variable `STOP` is omitted from
Telegram completion summaries.

The Agents tab also treats user-agent completions as unread work items. When a terminal
agent is selected after it has been marked unread, or when the user jumps to it with the
unread-agent shortcut, sase's TUI clears the row's unread marker and dismisses the
matching completion notification. A host-owned settlement row (`epic-launch` or
`monitor-settlement`) that names the exact `(cl_name, raw_suffix)` of that row or of any
turn on its `parent_timestamp` chain — for example, an epic launch approved through the
EpicApproval gate names the gate's launch monitor, and reading the session row clears it
— is acknowledged with the row and dismissed alongside the completion notification. Plan
approvals and user questions remain explicit response workflows and are not auto-read
merely by selection.

Unread state on the Agents tab is projected from the active user-agent completion
notifications in the store, plus any active host-owned settlement notification — the
notification an epic launch or monitor handoff posts when an agent session finishes
(senders `epic-launch` or `monitor-settlement`) — whose `(cl_name, raw_suffix)` matches
the Agents-tab row or any turn on its `parent_timestamp` chain, not only direct
children. Unread state is not written as separate per-row state. A finished agent row
whose session settles is therefore flagged unread until that notification is dismissed;
when the underlying notification is dismissed (per-row selection, response modal, or any
other path) the row's unread marker clears on the next refresh. A host-owned settlement
notification that names the exact `(cl_name, raw_suffix)` of an agent row or of a turn
on its `parent_timestamp` chain is acknowledged with that row — read, dismissed, or
marked — exactly like the row's completion notification. Manually toggling a row unread
with `U` overrides this projection locally so a deliberately re-flagged row is not
immediately re-cleared. Plan approvals and user questions still require an explicit `y`
/ `n` response and are never auto-dismissed by row navigation.

A newly arrived completion notification also drives a targeted Agents-tab refresh:
sase's TUI reloads only the matching agents' artifact directories rather than rebuilding
the whole list. Host-owned settlement notifications from epic launches and monitor
handoffs (senders `epic-launch` and `monitor-settlement`) refresh the agent session they
name the same way, so a settled session updates without waiting for the next full
refresh. When the named row is acknowledged, the settlement row is dismissed with it:
the match requires both `cl_name` and `raw_suffix` to equal the row's key, since
`cl_name` alone is the project-wide patch name shared by every agent and would clear
unrelated settlement rows. The finished node shows its terminal status and unread marker
on the toast tick, from an exact read-only status probe. The targeted reload that
follows is authoritative.

See [`agent_images.md`](../../agent_images.md) for the full attachment contract and
sase's TUI image preview notes.

For user-agent completion and failure notifications, `action_data` also includes
`bead_display` when the agent name maps to a bead created by `sase bead work`. The value
includes the bead ID plus the issue description or title when the bead can be resolved,
and falls back to the ID alone otherwise. Cross-project lookups prefer the agent's
owning project, then the caller's current bead view, then all known SASE projects.

### Mentors-Complete Notification

A mentors-complete notification uses sender `mentors` and fires once per
`(Patch, STITCHES entry)` under either of two conditions:

- **All mentors terminal** — every mentor that was started for the entry has reached a
  terminal status (`PASSED`, `COMMENTED`, `FAILED`, `DEAD`, or `KILLED`).
- **No matching profile** — every hook is ready and no mentor profile matched the Patch,
  so no mentors will run.

Selecting the notification jumps to the Patches sub-tab, focuses the target Patch, and
pushes the Mentor Review modal when at least one mentor produced reviewable output.

Idempotency is enforced via `~/.sase/notifications/mentors_complete.json`, keyed on
`(project_file, changespec_name, entry_id)` — so the notification survives process
restarts and project-spec archival without re-firing. The sender suppresses the
notification on the same axe cycle that just wrote the `MENTORS` field for the latest
entry, preventing premature firing on `Draft → Ready` transitions.

### Auto-Restart Episode Notifications

See [Agent auto-restart](../agent-auto-restart.md) for the full feature guide.

The update-skew healer (`sase agent auto-restart run`) posts one upserted amber `↻` row
per update episode under sender `agent.auto-restart` (`action: "ViewReport"`). The first
relaunch in an episode creates the row — and its single information toast. Every further
relaunch in the episode appends one `+1` note (which never toasts) and refreshes the
title, notes, and inline report snapshot in place without moving delivery cursors, so
the refresh never re-toasts or re-pushes. `notes[0]` is the calm title
(`↻ Restarted 5 agents after sase update 9fd8a08`, or the single-agent form) and never
contains "fail" or "error"; exception text appears only in note 2 or later. The live
report at `~/.sase/agent_auto_restart/episodes/<slug>.report.json` is a projection of
the episode's ledger records (headline, update/culprit/witness kv, per-agent rows with a
live Now column, left-alone bullets, why-text, prevention line) and is re-rendered on
every ledger change. A dismissed episode row is never revived: the next restart in that
episode opens `<episode>#2`. Declined, post-provider, and re-broken replacements
re-surface the agent's own failure notification (`sender=user-agent`, `ViewErrorReport`,
Errors bucket) with the escalation sentence appended; only the storm breaker posts as
`agent.auto-restart` at error severity.

### Report Notifications

Any producer — a job, a hook, or an agent — may attach a structured report to a
notification by setting `action: "ViewReport"`. The report is a **job report document**
(`{"title": ..., "blocks": [...]}`), the same artifact `sase.jobs.JobReport` builds and
the Services tab already renders, so the notification carries no producer-private
schema.

`action_data` describes where the document lives:

| Key            | Meaning                                                                                 |
| -------------- | --------------------------------------------------------------------------------------- |
| `report_path`  | Absolute (or `~`-prefixed) path to a JSON report document the producer keeps up to date |
| `report`       | A JSON-encoded report document embedded in the notification — an immutable snapshot     |
| `report_title` | Optional display title override; otherwise the document's own `title`, else `"Report"`  |

Both keys are optional and both may be present. Resolution order, and the provenance the
reader sees:

1. `report_path` resolves, loads, and validates → **live**, stamped with the file's
   mtime (`live · updated 2m ago`).
2. Otherwise `report` parses and validates → **snapshot**, stamped with the notification
   timestamp (`snapshot · captured 3h ago`).
3. Otherwise → one explicit failure line naming the reason, plus the path that was
   tried. Never an exception, never an empty pane.

Pointing at a stable published path lets an hours-old notification open the _current_
picture, while the inline snapshot guarantees the pane still renders honestly if the
producer's state was wiped.

The loader (`sase.notifications.load_notification_report`) is fail-closed and never
raises. It performs no network access and no subprocess calls, and it rejects:

- a relative or `~`-unexpandable path, a missing path, or a path that is not a regular
  file;
- a file larger than 256 KiB — a size failure, not a truncation;
- content that is not a JSON object, or that fails job-report validation through the
  Rust schema authority (`sase.jobs.validate_job_report`).

Every failure becomes a bounded, human-readable `error` string such as
`report file not found`, `report file is too large (312 KiB)`, or
``report document is invalid: unknown variant `bogus` ``. Rendering is safe by
construction: `render_chop_report` builds Rich text with explicit styles and never
interprets console markup or ANSI from the document.

In sase's TUI, selecting a `ViewReport` notification renders the report in the modal's
right pane under its provenance line, with a dim `attachments:` footer when the
notification also carries files. Pressing Enter re-reads the document and opens the
full-screen report modal, so the modal always shows the freshest published report rather
than the pane's cached load. That modal binds `Ctrl+D`/`Ctrl+U` for half-page scrolling,
`j`/`k` for lines, `g`/`G` for top/bottom, `y` to copy the report path, `e` to open the
file in `$EDITOR`, and `Esc`/`q` to close. `y` and `e` warn instead for an inline
snapshot, which has no file path. `ViewReport` is an ordinary informational action:
selecting it marks the notification read.

### Action-less Notifications

A notification with no `action` is a valid, common shape — an informational row with
nothing to open. Selecting one in sase's TUI marks it read and does nothing else; it is
a silent no-op, not a producer error. Only a non-empty `action` string this build does
not recognize produces an "Unsupported notification action" warning.

## Notification Fields

Each notification contains:

| Field               | Type         | Description                                                                                                                                                                                                                         |
| ------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                | string       | UUID4 unique identifier                                                                                                                                                                                                             |
| `timestamp`         | string       | ISO-8601 creation timestamp; immutable, and never rewritten by a snooze or resurface                                                                                                                                                |
| `sender`            | string       | Source identifier (e.g., "plan", "sync", "axe")                                                                                                                                                                                     |
| `icon`              | string\|null | Optional single emoji or display glyph                                                                                                                                                                                              |
| `color`             | string\|null | Optional sender-declared `#RRGGBB` accent for the notification-panel tab                                                                                                                                                            |
| `notes`             | list[string] | Human-readable message lines                                                                                                                                                                                                        |
| `files`             | list[string] | Associated file paths (e.g., plan files, error digest files, generated agent images)                                                                                                                                                |
| `tags`              | list[string] | Optional normalized labels for filtering and modal tabs                                                                                                                                                                             |
| `action`            | string\|null | Action type: `HITL`, `PlanApproval`, `EpicApproval`, `TaskTriage`, `BeadStaleCleanup`, `UserQuestion`, `LaunchApproval`, `ViewReport`, etc. `null` means the notification is purely informational                                   |
| `action_data`       | dict         | String identifiers and owned paths for the typed action; rich gate definitions stay in `request.json`                                                                                                                               |
| `read`              | bool         | Whether the notification has been read                                                                                                                                                                                              |
| `dismissed`         | bool         | Whether the notification has been dismissed                                                                                                                                                                                         |
| `silent`            | bool         | Silent notifications are stored but hidden from the TUI                                                                                                                                                                             |
| `muted`             | bool         | Muted notifications appear under `Muted` (or `Snoozed`, with a wake time set) and are excluded from the arrival bell and toasts; the indicator counts them separately (see [Top-Bar Indicator](notifications.md#top-bar-indicator)) |
| `snooze_until`      | string\|null | Canonical UTC RFC-3339 instant at which a snoozed notification automatically un-mutes; `null` once expired or cancelled                                                                                                             |
| `resurfaced_at`     | string\|null | UTC instant stamped when a snooze expired; drives activity ordering and delivery cursors. `null` for rows that never resurfaced                                                                                                     |
| `dedup_key`         | string\|null | Optional sender-scoped key used to append evidence instead of creating another row                                                                                                                                                  |
| `plus_ones`         | list[object] | Retained corroboration entries, each containing `timestamp`, `sender`, and `note`                                                                                                                                                   |
| `plus_ones_dropped` | int          | Number of older corroboration entries omitted by bounded retention; included in the displayed and JSON `plus_one_count`                                                                                                             |

## Silent Notifications

Notifications from hidden background agents (summarize-hook, fix-hook, mentor) are
created with `silent=True`. Silent notifications are written to the JSONL file
(preserving the audit trail) but excluded from the TUI unread count, top-bar indicator,
arrival bell, toast, notification modal, and Telegram delivery. They remain visible to
local inspection commands such as `sase notify list`.

Agent completion and failure events from hidden background agents still write a
notification row, but with the silent flag set. This keeps the JSONL audit trail
complete while keeping the inbox focused on user-facing agent work.

### Plan decision `%auto` receipts

When a plan or epic gate with at least one decision auto-resolves (`source`
`auto_resolution`), sase posts one quiet receipt notification:

- `action` is null, so it is not a gate and opens nothing;
- `silent` is true and `muted` is left false;
- tag `plan_decisions_receipt`;
- dedup key `plan-decisions-receipt-<request id>`;
- plans with no decisions post nothing.

A verified correction row that stayed on renders `corrects: '<quote>'`. A
`claim_not_found` row left off without human review renders `claim not found` so the
skipped correction is not silently lost.

Visibility is an intentional exception to the Silent Notifications rules: visible in the
ACE inbox direct page and delivered quietly by Telegram, with no unread bump, toast, or
bell, while remaining visible to `sase notify list`.

## Related

- [Notifications](notifications.md)
- [Notification tags](notification-tags.md)
- [Notification CLI](notification-cli.md)
