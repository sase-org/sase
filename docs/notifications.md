# Notifications

## Overview

Sase includes a notification system that surfaces important events from background
processes (axe, workflows, mentors) to the user through the ACE TUI. Notifications are
stored as JSONL and persisted to `~/.sase/notifications/notifications.jsonl`.

Plan, epic-plan, question, agent-launch, and task-triage approvals use the notification
row as a typed transport projection of a durable interaction gate. The reviewed content,
option-query branches, validation schemas, and hash-verified commands live in
`~/.sase/interaction_requests/<kind>/<request-id>/`; ACE, mobile, Telegram, and typed
CLI actions all resolve that same bundle.

## Viewing Notifications

Press `i` on any tab in ACE to open the notifications modal. Rows in the list show
relative timestamps (e.g., "2m ago", "1h ago") and can be marked as read or dismissed.
The detail pane shows the selected notification's absolute send time alongside its
relative age (`sent today 13:18:42 · 4m ago`), tiered as `today HH:MM:SS` /
`yesterday HH:MM` / `Mon D HH:MM` / `Mon D 'YY HH:MM` in the configured timezone.

### Modal Keybindings

| Key                 | Action                                                                      |
| ------------------- | --------------------------------------------------------------------------- |
| `j` / `k`           | Navigate between notifications                                              |
| `Enter`             | Select notification (jump to PR, approve plan, etc)                         |
| `d`                 | Open Gate Debug for the highlighted row                                     |
| `x`                 | Dismiss notification, or dismiss marked rows when marks are present         |
| `m`                 | Toggle the per-row mark on the highlighted notification                     |
| `M`                 | Toggle mute on the highlighted notification, or marked rows                 |
| `s`                 | Snooze the highlighted notification, or marked rows (opens duration picker) |
| `e`                 | Open attached file in `$EDITOR`                                             |
| `V`                 | Open the current image attachment in the image viewer                       |
| `Ctrl+N` / `Ctrl+P` | Cycle through attached files                                                |
| `Ctrl+D` / `Ctrl+U` | Scroll file content down / up                                               |
| `[` / `]`           | Switch notification tabs                                                    |
| `R`                 | Mark every unread notification in the **active tab** read (confirms first)  |
| `Esc` / `q`         | Close modal                                                                 |

Plan, launch, question, and task-triage notifications require confirmation (`y` / `n`)
before dismissal to prevent accidental loss of pending decisions. The same `y` / `n`
confirmation is used for bulk dismissal when at least one marked protected notification
is included in the batch.

`R` is scoped to the tab you are on, not the whole inbox, and it is a wider write than
it looks: it marks the tab read in the notification store, which includes rows matching
that tab that ACE has not loaded into the visible list. Because of that, it opens a
danger confirmation naming the tab (`Mark Notification Tab Read?`) that defaults to
**Cancel**; it cannot be undone from ACE. The target is frozen when the prompt opens, so
switching tabs while the confirmation is up cannot redirect the write to a different
tab, and a tab with nothing in the visible list never prompts at all. The mutation
itself runs as a proc, so a slow store write does not block the modal.

### Gate Detail Pane

Highlighting any gate-backed row — plan, epic, question, launch, custom, task-triage,
flag-triage, or workflow HITL — always renders a live decision card in the right pane: a
status line (`Awaiting your decision`, `Answered`, `Cancelled`, `Timed out`, or
`Gate details unavailable`), the notification's context and tags, a `Decision` block
listing every branch in canonical query order with the primary branch marked, and an
`Attachments` line when the gate has files. The card renders instantly from the
notification row and enriches itself with the verified bundle a moment later without
blocking navigation. When a bundle cannot be resolved, hashed, or parsed — a deleted
directory, a corrupted `request.json`, a legacy bundle layout — the card degrades to
`▲ Gate details unavailable` rather than going blank; press `d` to open Gate Debug and
see exactly why. Every other notification, including attachment-less ones, gets a
compact summary card instead of an empty pane.

### Tabs and Ordering

The modal renders a compact tab strip above the list whenever there is at least one tab.
It is hidden only at zero tabs, which is also when the list itself is replaced by the
`No unread notifications` message — so the strip never pops in and out, and the list
never shifts, as dismiss, mute, and snooze actions collapse the tabs down to one.
**Every notification belongs to exactly one tab** — the Rust core decides which one by a
fixed precedence, so the panel, the top-bar indicator, and the mobile snapshot always
agree; see [Tags](#tags) below for that precedence in full. The tabs, in the panel's
display order:

| Tab       | Icon | Contents                                                                                                                                                                                         |
| --------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Gates`   | `⚑`  | Plan and epic approvals, user questions, workflow HITL prompts, launch approvals, and generic gates without a declared panel.                                                                    |
| Panel     | `◆`  | Gates with `presentation.panel`, sorted alphabetically after `Gates`; built-in task triage gates use the `Beads` panel (`◈`), and woken `BeadSnooze` plus due `FlagTriage` gates land there too. |
| `Errors`  | `✖`  | Axe digests, failed file hooks, and agent errors (`axe`, `file-hooks`, or `user-agent` with `ViewErrorReport`).                                                                                  |
| `General` | `✉`  | Untagged, unmuted notifications with no other classification.                                                                                                                                    |
| `Done`    | `#`  | Notifications carrying the `done` tag, pinned before other custom tags.                                                                                                                          |
| Custom    | `#`  | Other normalized notification tags, sorted alphabetically after `Done`.                                                                                                                          |
| `Snoozed` | `☾`  | Muted notifications with a future wake time — snoozed notifications and notifications for snoozed task beads alike.                                                                              |
| `Muted`   | `⊘`  | Muted notifications with no wake time.                                                                                                                                                           |

Each tab's icon resolves through the same chain as its color; see
[Tab icons](#tab-icons) below.

The strip reflows to fit its measured width rather than clipping. When the full-label
render would overflow, every inactive tab sheds its label and is identified by icon and
count alone, while the active tab keeps its name so the strip still says where you are.
Shedding labels is what keeps a tab from falling off the end of the line, where it would
be both invisible and unclickable; a resize re-renders the strip only when the width
actually changed.

A row with multiple tags therefore occupies exactly one tab, not one per tag; dismissing
it removes the row from at most one tab's count.

Within the active tab, rows are ordered newest-first by their **activity time** —
`resurfaced_at` when a snooze has expired, otherwise `timestamp` (see
[Activity Ordering](#activity-ordering)). Rows with equal activity times keep their
original arrival order, and rows whose activity time can't be parsed fall to the bottom
rather than breaking the modal. The sort runs on every modal rebuild, so live actions
like mark-read, dismiss, mute, and snooze update the visible order immediately.
Switching tabs with `[` / `]` or a mouse click clears modal-local marks so a hidden row
is never bulk-dismissed by accident.

### Marks and Bulk Actions

Press `m` on a notification to toggle a per-row mark. Marks are scoped to the open modal
— closing the modal clears them. While at least one row is marked, `x`, `M`, and `s`
target every live marked row instead of the highlighted row. Plan, launch, question, and
task-triage rows in a marked dismiss batch use the same `y` / `n` confirmation prompt as
a single dismissal.

Successful marked mute, unmute, snooze, and dismiss actions consume the acted-on marks.
Stale marks are pruned; if no live marks remain, `M` and `s` fall back to the
highlighted row rather than writing an empty batch. Marked mute uses one shared state
for the whole target set: if any marked target is unmuted, `M` mutes all targets;
otherwise it unmutes all targets and cancels any pending snoozes.

### Mute and Snooze

Press `M` on a notification to toggle its muted state, or on marked rows to toggle the
whole marked set. Muted notifications are dimmed in the list, prefixed with `~`, and
moved to the `Muted` tab. They are still delivered to the JSONL store, remain visible in
the modal, and get their own counted chip in the top-bar indicator — only the toast
pipeline and arrival bell ignore them.

Press `s` to snooze a notification, or marked rows, for `15m`, `1h`, `4h`, or until
tomorrow morning. A marked snooze computes one deadline and applies it to every target.
Snoozed notifications are implicitly muted, but a future wake time routes them to the
`Snoozed` tab rather than `Muted` (see [Tabs and Ordering](#tabs-and-ordering)), and
they display a `⏰ <remaining>` badge counting down to the snooze expiry. Toggling mute
off cancels any pending snooze. The snooze deadline is persisted as a canonical UTC
instant, so the notification re-emerges from `Snoozed` on its own once the deadline
passes — see [Snooze Expiry and Resurfacing](#snooze-expiry-and-resurfacing) for the
exact state transitions, timing guarantee, and recovery behavior.

### Snooze Expiry and Resurfacing

#### Exact Elapsed Versus Calendar Time

Duration presets (`15m`, `1h`, `4h`) mean _exactly_ that much elapsed time, so they are
added on the UTC timeline. A four-hour snooze started just before a DST transition still
expires after four real hours, not three or five. Calendar presets such as "tomorrow
morning" resolve in the configured IANA timezone first (09:00 local) and are then
converted to UTC for storage. Display formatting stays local; the stored deadline is
always a canonical UTC RFC-3339 instant.

New snooze writes accept only timezone-aware, parseable, future instants. A naive,
malformed, or already-past deadline is rejected before any row changes, and a rejected
bulk snooze leaves every target untouched. Snoozing a dismissed or unknown notification
is likewise a no-op rather than a silent success, so the modal never shows a false
"Snoozed" state — a store failure or stale row reloads authoritative state and shows an
actionable error instead.

#### State Transitions

| Event             |   `muted` | `snooze_until`                 |    `read` | `resurfaced_at` | Delivery result                                       |
| ----------------- | --------: | ------------------------------ | --------: | --------------- | ----------------------------------------------------- |
| Snooze active row |    `true` | validated future UTC instant   | unchanged | unchanged       | hidden from active delivery until due                 |
| Resnooze          |    `true` | replacement future UTC instant | unchanged | unchanged       | only the replacement deadline is scheduled            |
| Expire active row |   `false` | `null`                         |   `false` | expiry instant  | one new activity generation becomes visible           |
| Explicit unmute   |   `false` | `null`                         | unchanged | unchanged       | timer is cancelled, not treated as an expiry          |
| Dismiss           | unchanged | `null`                         | unchanged | unchanged       | pending snooze is cancelled and can never alert later |

Expiry is atomic and batched: every row that is due at the same reconciliation stamps
the _same_ `resurfaced_at` instant, becomes unmuted and unread, and clears its deadline.
A row that was marked read while snoozed still returns to the inbox as unread. Permanent
mutes (muted with no deadline) are never touched, and dismissed rows are skipped
entirely, so a dismissed notification can never ring later.

#### Timing Guarantee

While a supporting long-lived consumer is running, a snoozed notification becomes
current within that consumer's tolerance of its wall-clock deadline:

- **ACE session** — one second, including after suspend/resume, a restart, or a
  system-clock change, and independently of `--refresh-interval`. ACE schedules a
  deadline-driven coordinator rather than relying on the general refresh tick.
- **Mobile gateway** — the next authenticated list or detail read, which expires the row
  and publishes a `notifications_changed` event so connected clients refresh.
- **Telegram outbound chop** — the next scheduled chop run.

If every consumer is offline, no alert is emitted at the deadline; the durable guarantee
is instead that the **first** later current-state read atomically catches the row up
before returning any state. Expiry is therefore never lost, only deferred to the next
reader.

Because expiry happens under the store lock, exactly one concurrent reader observes a
given row in its `expired_ids` transition metadata. Every other consumer still observes
the result through the persistent `muted`, `read`, and `resurfaced_at` fields, so a
losing process never misses the resurfacing. ACE emits one toast and one tmux bell per
observed resurface batch and does not repeat it on later polls.

#### Activity Ordering

Every consumer orders notifications by an effective activity key rather than the raw
creation time:

```text
activity_at(notification)     = resurfaced_at ?? timestamp
activity_cursor(notification) = (activity_at, notification_id)
```

`timestamp` keeps its immutable meaning as the original creation time and is what the UI
displays as the sent time. The activity key is what makes a resurfaced snooze
first-class recent activity: an old row moves to the top of the ACE modal, the first
`sase notify list` page, and the first mobile page instead of staying buried. The
notification-ID tie-breaker is required anywhere a cursor is persisted (mobile
`newer_than`/high-water, Telegram delivery) so two rows sharing an activity instant
cannot hide one another.

#### Legacy and Malformed Deadlines

A legacy row whose `snooze_until` is unparseable or timezone-naive must not stay
silently muted forever. The current-state reconciliation path treats it as immediately
due: the row resurfaces at once and is reported as an expiry, while every new mutation
path rejects such a value outright. Rows written before the resurface field existed
default cleanly to `resurfaced_at: null`.

#### Raw Versus Current-State Reads

Raw audit reads (`load_notifications()`, the non-expiring snapshot read) deliberately
never mutate time-driven state, so inspection and export paths cannot cause a resurface
as a side effect. User-facing "current inbox" reads
(`read_current_notification_snapshot()` and the CLI, ACE, mobile, and Telegram
projections built on it) atomically expire due rows under the store lock before
projecting rows, counts, `expired_ids`, and the next active deadline.

### Top-Bar Indicator

The notification indicator in the TUI top bar renders one colored `<icon><count>` chip
per notification-panel tab (see [Tabs and Ordering](#tabs-and-ordering)), in the panel's
own left-to-right order, so the badge and the panel always agree on what each count
means:

- **Nothing pending** — a dim `✉ 0`. This is the only state that keeps the `✉` anchor;
  see below for why.
- **Snoozed only** — `☾4`: the count renders in the Snoozed tab's resolved color at a
  dimmer weight than an actionable count, prefixed by the Snoozed tab's own icon instead
  of a trailing `z` suffix.
- **Anything else** — one `<icon><count>` chip per visible tab, each the tab's icon and
  count in its own resolved color at full weight, joined by a single space, for example
  `⚑2 ✖3 ◈1`. Each chip is self-identifying, so there is no separator glyph and no `✉`
  anchor — once `general` owns `✉` as its own tab icon, prefixing the whole badge with
  it would render the same glyph twice, meaning two different things. As soon as any
  non-snoozed tab has a count, the Snoozed chip drops out of the badge entirely — it
  does not compete for the limited chip budget — but the snoozed count still appears in
  the tooltip.
- **Overflow** — at most
  [`ace.notification_indicator_max_counts`](configuration.md#acenotification_tabs) chips
  (4 by default), taken in panel order; any remaining tabs collapse into one trailing
  dim `+K` chip, joined by the same single space. Every suppressed tab is still
  described in the tooltip.

Hovering the indicator opens a tooltip briefing: a header count of unread rows (snoozed
and muted rows are informational and excluded from that header count) followed by one
line per tab showing its icon, its count, its oldest unread activity (`oldest 14m ago`)
or, for the Snoozed tab, when it next wakes (`next wakes in 43m`). Tab labels in the
tooltip are colored the same as their indicator chip, so the tooltip doubles as a
legend. See [Tab colors](#tab-colors) and [Tab icons](#tab-icons) for how each tab's
color and icon are resolved.

Silent notifications never contribute to the indicator (see
[Silent Notifications](#silent-notifications) below).

### Visual and Audible Delivery

New unmuted notifications remain visually prominent through the top-bar indicator and
action-specific toasts. A genuinely new `PlanApproval` or `EpicApproval` rings once on
arrival, alongside its priority inbox row, warning toast, and the producer's desktop
notification. The ACE toast says `Tale ready` or `Epic ready`; an epic adds the
gate-time phase, dependency-wave, and non-zero phase-size counts, while batched toasts
count tales and epics separately. Already-handled plan reviews discovered during polling
and the intermediate post-approval handoff remain silent. Task triage, questions,
launch/custom/HITL gates, errors, agent completions, and ordinary notifications retain
their arrival bell.

Snooze expiry is an explicit reminder chosen by the user and remains audible for every
notification class, including a snoozed tale or epic review.

## Notification Types

The following events generate notifications:

| Sender                         | Event                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| `plan` / `epic`                | A tale or epic plan is ready for user review and approval                            |
| `bead`                         | A task bead needs triage, a snoozed task woke, or a due flag bead needs `FlagTriage` |
| `launch`                       | A running agent requested a new agent launch for approval                            |
| `question`                     | An agent is asking the user a question (via `/sase_questions`)                       |
| `hitl`                         | A workflow HITL step is waiting for user input                                       |
| `memory.proposed`              | A long-term memory proposal is ready for human review                                |
| `sync`                         | A sync operation completed for a Patch                                               |
| `axe`                          | Hourly error digest summarizing recent axe errors                                    |
| `file-hooks`                   | A configured per-file hook completed or failed                                       |
| `mentors`                      | All mentors finished for a Patch entry (or none matched)                             |
| Workflow-specific sender label | Workflow completion (success or failure)                                             |

### Task Triage Notification

The five-minute `bead_task_triage` chop creates one human-only `TaskTriage` gate for
each ready task bead. Its compact notification note is `<bead-id> — <title>` and it
lands in the `Beads` panel while retaining the `bead` and `task` tags. The filing agent,
when known, appears as a **Filed by** line in the Markdown preview above the task's
description and notes; the notes section is present only when the bead has notes. The
gate offers three branches:

- **Launch** is the default. It submits an unattributed proc that runs
  `sase bead work <task-id> --yes-to-all`; optional feedback is appended to the worker
  prompt.
- **Close** requires feedback and closes the bead with that reason and
  `resolution=canceled`.
- **Snooze** collects one required `duration` line containing a wake time with an
  optional `+N` suffix, for example `3d`, `2026-08-09T09:00:00-04:00`, or `3d +2`, the
  same vocabulary as [`sase bead snooze`](beads.md#snoozing-a-task-bead). Feedback is
  optional here and records **why** the task was deferred. An unparsable value fails the
  option and leaves the gate pending rather than losing the bead's only triage gate. It
  defers the bead — the triage gate settles and a `BeadSnooze` wake gate takes its place
  once the reconciler's next tick runs; see
  [Snoozed Task Notification](#snoozed-task-notification) below.

No decision branch is chosen automatically. While one of `TaskTriage`/`BeadSnooze`
remains pending for a bead, the chop that owns both kinds (`bead_task_triage`)
suppresses duplicates and keeps the two mutually exclusive — a task bead never holds
both at once. After the bead mutation commits, `sase bead close` makes a best-effort
attempt to cancel the matching pending gate; a cancellation failure does not fail the
close, and the next reconciliation remains the backstop. Choosing **Launch** in
`TaskTriage` answers that gate normally, and a successful launch submission from ACE's
Beads pane explicitly cancels it. A direct `sase bead work <task-id>` command does not
settle an older gate itself; because the launch changes the stored status, the next
reconciliation cancels that stale gate. If the bead's status otherwise changes out of
band (leaves `ready`, gets snoozed, or wakes), the chop cancels the gate of the wrong
kind and creates the right one on its next tick. If a gate becomes terminal, disappears,
or uses an obsolete presentation or option-input contract while still expected, the next
five-minute scan creates a replacement with a new generation-specific request ID, except
while the task bead's detached launch is still in flight.

### Snoozed Task Notification

A snoozed task bead's `BeadSnooze` gate is born already snoozed: the reconciler creates
it with `presentation.panel: "beads"` and `presentation.snooze_until` set to the bead's
wake time, so the notification is muted with that deadline in one atomic step — there is
no window where it appears unread. It sits in the `Snoozed` tab for the whole deferral
(see [Tabs and Ordering](#tabs-and-ordering)) and resurfaces in the `Beads` panel tab,
unmuted, exactly like any other snooze expiry once its wake time arrives. The preview
shows who snoozed the bead, when, why, the wake time, and `+1` progress toward any
configured target.

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

A due flag bead raises one `FlagTriage` gate through the same `bead_task_triage`
reconciler that owns task gates. The notification lands in the `Beads` panel with `bead`
and `flag` tags. Its preview shows the flag key, both removal thresholds, the due
countdown, the registry definition, notes, and call sites.

The gate offers four branches:

- **Remove** is the primary path. It requires the winning branch (`enabled` or
  `disabled`) and launches a worker to delete the losing branch, remove the registry
  entry, and close the flag bead.
- **Extend** requires a new date/release threshold and a reason, then rewrites the flag
  bead's `remove_by` metadata and leaves it live.
- **Keep** requires a rationale for making the behavior permanent and routes the flag
  toward `ops` or an ordinary config field.
- **Close** requires a reason and closes the bead; registry/bead integrity checks catch
  any surviving orphaned flag.

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

In ACE, completion artifacts are opened from the Agents tab with `a`. The artifact panel
supports marking multiple files and opening the full artifact sequence, so notification
attachments, generated PDFs/images/videos, plan files, and explicit artifacts use one
selection workflow. Generated videos are included as ordinary file artifacts. ACE may
also include image and video files referenced by saved prompt artifacts in that picker.
Those prompt-referenced media are persisted or synthesized as ACE artifact-list entries,
but they are not appended to notification delivery payloads unless they also appear in
`done.json.image_paths` / `done.json.video_paths` or were saved explicitly with
`sase artifact create`.

When an agent sets output variables with `sase var set`, non-reserved variables are
snapshotted into the completion notification as sorted JSON and rendered in Telegram
agent-completion messages. The snapshot preserves structured values (including nested
lists and maps); each value is already bounded by the 64 KiB encoded-variable limit, and
the notification store does not impose a smaller `action_data` limit. The reserved
repeat-control variable `STOP` is omitted from Telegram completion summaries.

The Agents tab also treats user-agent completions as unread work items. When a terminal
agent is selected after it has been marked unread, or when the user jumps to it with the
unread-agent shortcut, ACE clears the row's unread marker and dismisses the matching
completion notification. Plan approvals and user questions remain explicit response
workflows and are not auto-read merely by selection.

Unread state on the Agents tab is projected from the active user-agent completion
notifications in the store rather than written as separate per-row state — when the
underlying notification is dismissed (per-row selection, response modal, or any other
path) the row's unread marker clears on the next refresh. Manually toggling a row unread
with `U` overrides this projection locally so a deliberately re-flagged row is not
immediately re-cleared. Plan approvals and user questions still require an explicit `y`
/ `n` response and are never auto-dismissed by row navigation.

See [`agent_images.md`](agent_images.md) for the full attachment contract and ACE image
preview notes.

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

### Memory Proposal Notification

`sase memory write --notify` first saves the proposal, then best-effort creates a
`memory.proposed` notification. The notification includes the `memory` tag, evidence
entries that resolved to local file paths, `action: memory_review`, and
`action_data.proposal_id`. Selecting it in ACE suspends the main TUI and opens the same
interactive review app as `sase memory review`, preselected on that proposal. Review
decisions still happen in that app; the notification is only the entry point. Proposal
creation still succeeds if notification delivery fails, and the CLI reports the
notification id when delivery succeeds.

### Report Notifications

Any producer — a chop, a hook, or an agent — may attach a structured report to a
notification by setting `action: "ViewReport"`. The report is a **chop report document**
(`{"title": ..., "blocks": [...]}`), the same artifact `sase.chops.ChopReport` builds
and the AXE tab already renders, so the notification carries no producer-private schema.

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
- content that is not a JSON object, or that fails chop-report validation through the
  Rust schema authority (`sase.chops.validate_chop_report`).

Every failure becomes a bounded, human-readable `error` string such as
`report file not found`, `report file is too large (312 KiB)`, or
``report document is invalid: unknown variant `bogus` ``. Rendering is safe by
construction: `render_chop_report` builds Rich text with explicit styles and never
interprets console markup or ANSI from the document.

In ACE, selecting a `ViewReport` notification renders the report in the modal's right
pane under its provenance line, with a dim `attachments:` footer when the notification
also carries files. Pressing Enter re-reads the document and opens the full-screen
report modal, so the modal always shows the freshest published report rather than the
pane's cached load. That modal binds `Ctrl+D`/`Ctrl+U` for half-page scrolling, `j`/`k`
for lines, `g`/`G` for top/bottom, `y` to copy the report path, `e` to open the file in
`$EDITOR`, and `Esc`/`q` to close. `y` and `e` warn instead for an inline snapshot,
which has no file path. `ViewReport` is an ordinary informational action: selecting it
marks the notification read.

### Action-less Notifications

A notification with no `action` is a valid, common shape — an informational row with
nothing to open. Selecting one in ACE marks it read and does nothing else; it is a
silent no-op, not a producer error. Only a non-empty `action` string this build does not
recognize produces an "Unsupported notification action" warning.

## Notification Fields

Each notification contains:

| Field           | Type         | Description                                                                                                                                                                                                         |
| --------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`            | string       | UUID4 unique identifier                                                                                                                                                                                             |
| `timestamp`     | string       | ISO-8601 creation timestamp; immutable, and never rewritten by a snooze or resurface                                                                                                                                |
| `sender`        | string       | Source identifier (e.g., "plan", "sync", "axe")                                                                                                                                                                     |
| `icon`          | string\|null | Optional single emoji or display glyph                                                                                                                                                                              |
| `notes`         | list[string] | Human-readable message lines                                                                                                                                                                                        |
| `files`         | list[string] | Associated file paths (e.g., plan files, error digest files, generated agent images)                                                                                                                                |
| `tags`          | list[string] | Optional normalized labels for filtering and modal tabs                                                                                                                                                             |
| `action`        | string\|null | Action type: `HITL`, `PlanApproval`, `EpicApproval`, `TaskTriage`, `UserQuestion`, `LaunchApproval`, `ViewReport`, etc. `null` means the notification is purely informational                                       |
| `action_data`   | dict         | String identifiers and owned paths for the typed action; rich gate definitions stay in `request.json`                                                                                                               |
| `read`          | bool         | Whether the notification has been read                                                                                                                                                                              |
| `dismissed`     | bool         | Whether the notification has been dismissed                                                                                                                                                                         |
| `silent`        | bool         | Silent notifications are stored but hidden from the TUI                                                                                                                                                             |
| `muted`         | bool         | Muted notifications appear under `Muted` (or `Snoozed`, with a wake time set) and are excluded from the arrival bell and toasts; the indicator counts them separately (see [Top-Bar Indicator](#top-bar-indicator)) |
| `snooze_until`  | string\|null | Canonical UTC RFC-3339 instant at which a snoozed notification automatically un-mutes; `null` once expired or cancelled                                                                                             |
| `resurfaced_at` | string\|null | UTC instant stamped when a snooze expired; drives activity ordering and delivery cursors. `null` for rows that never resurfaced                                                                                     |

## Silent Notifications

Notifications from hidden background agents (summarize-hook, fix-hook, mentor) are
created with `silent=True`. Silent notifications are written to the JSONL file
(preserving the audit trail) but excluded from the TUI unread count, top-bar indicator,
arrival bell, toast, notification modal, and Telegram delivery. They remain visible to
local inspection commands such as `sase notify list`.

Agent completion and failure events from hidden background agents still write a
notification row, but with the silent flag set. This keeps the JSONL audit trail
complete while keeping the inbox focused on user-facing agent work.

## Tags

Senders may attach `tags` to a notification. Tags are normalized when notifications are
created: whitespace is trimmed, empty values are dropped, values are lowercased, and
duplicates are removed while preserving sender order. Tags do not change priority, error
classification, unread counts, mute, snooze, or auto-dismiss matching.

Successful visible and hidden user-agent completion notifications that jump back to the
agent row carry the `done` tag. Failed user-agent notifications do not carry `done`;
failures remain error reports.

Memory proposal notifications created by `sase memory write --notify` carry the `memory`
tag. Use the `memory` tab in ACE or `sase notify list --tag memory` to find proposal
review notification rows.

In ACE, tags create modal tabs above the notification list after the synthetic `Gates`,
declared panel tabs, `Errors`, `General`, and `Done` tabs. **Every notification belongs
to exactly one tab.** The Rust core decides which one, by this precedence, so the panel,
the top-bar indicator, and the mobile snapshot always agree:

1. `Snoozed` — muted with a `snooze_until` wake time
2. `Muted` — muted with no wake time
3. the gate's declared `presentation.panel`
4. `Gates` — a human-in-the-loop gate action (the core still keys this synthetic tab
   `hitl`; only the display label is `Gates`)
5. `Errors` — an error report
6. the **first** stored tag, in sender order
7. `General` — everything else

A row with two tags therefore occupies one tab and is counted once; dismissing it
removes at most one tab. Later tags still render as badges on the row, but they do not
create tabs.

A gate may declare `presentation.panel` to place its notification in a named panel tab.
Panel names are stripped, lowercased, limited to 32 characters, and may contain
lowercase letters, digits, underscores, and hyphens. The synthetic names `errors`,
`gates`, `general`, `hitl`, `muted`, and `snoozed`, along with names beginning with
`__`, are reserved. A panel name matching a tag merges into that tag's tab, which then
sorts as a panel tab.

### Tab colors

Every tab renders with a color, so a brand-new tag tab is never colorless. The color
resolves by precedence, highest first:

1. [`ace.notification_tabs.<tab>.color`](configuration.md#acenotification_tabs), when
   non-empty
2. the color a sender declared on a notification in that tab
3. the built-in default for a tab ACE ships knowing about (`hitl`, `errors`, `beads`,
   `general`, `snoozed`, `muted`)
4. a stable auto-palette entry derived from the tab key, so the same tag keeps the same
   color across restarts

A sender declares a color with `presentation.color` on a gate, or the `color` field of
`sase notify create` JSON input. It must be a `#RRGGBB` hex string; anything else is
rejected at write time rather than stored as junk that would render as an unstyled chip.
When several rows in a tab declare a color, the tab wears the one from the row the panel
lists first — the most recent activity — so the color is deterministic rather than
dependent on render order.

The `done` tab is intended as the quick path for successful agent completions; reading
or jumping to a done Agents-tab row dismisses its matching completion notification, so
it disappears from the `Done` tab after the next refresh. Failed agent notifications
stay untagged by `done` and continue to render under the `Errors` tab.

### Tab icons

Every tab renders with an icon, so the top-bar indicator's chips and the modal's tab
strip are self-identifying instead of relying on color alone. The icon resolves by
precedence, highest first:

1. [`ace.notification_tabs.<tab>.icon`](configuration.md#acenotification_tabs), when
   non-empty
2. the icon a sender declared on a notification in that tab
3. the built-in default for a tab ACE ships knowing about (`hitl`, `errors`, `beads`,
   `general`, `snoozed`, `muted`)
4. a default keyed by the tab's own kind (`panel`, `tag`), so a tab ACE has never heard
   of still gets a glyph that means something about what it is
5. `•`, reachable only when a tab arrives with no kind at all

Unlike color, an icon never falls back to a hashed auto-palette entry: an arbitrary
color is still a usable identifier, but an arbitrary glyph would teach the reader
something false, so the chain always bottoms out at a meaningful or honestly generic
mark instead. The bundled defaults are `⚑` `hitl`, `✖` `errors`, `◈` `beads`, `✉`
`general`, `☾` `snoozed`, and `⊘` `muted`; a gate-declared panel with no closer match
falls to the kind default `◆`, and a tag tab falls to `#`.

ACE resolves icons over the whole ordered tab list before rendering. Configured icons,
sender-declared icons, and the bundled defaults are never rewritten. If two SASE-chosen
generic icons from rung 4 or 5 would collide, ACE walks the tab key and uses the first
unused ASCII letter or digit from that key: `axe` can become `a`, then `x`, then `e`;
`file-hooks` can become `f`; `123-deploy` can become `1`. If every alphanumeric
character in the key is already claimed, the tab keeps the generic mark rather than
inventing a false glyph. Explicit duplicates remain explicit: if two configured tabs or
two gates choose the same glyph, ACE renders that glyph for both. Run
`sase doctor -C config.notification_tabs` to report configured duplicates.

A sender declares an icon with `presentation.panel_icon` on a gate (see
[Command-backed interaction gates](#command-backed-interaction-gates) below); there is
no raw-notification equivalent, since a raw row's own `icon` field styles the row, not
its tab. When several rows in a tab declare a `panel_icon`, the tab wears the one from
the row the panel lists first — the most recent activity — exactly as color does. A
`panel_icon` is donated only to the tab named by the same gate's `presentation.panel`,
so a muted or snoozed row does not carry its panel glyph into `Snoozed` or `Muted`.

## CLI

The `sase notify` command can create notifications and inspect the local notification
inbox.

Bare `sase notify` is a read-only shortcut for `sase notify list`. Use
`sase notify create` when writing a notification from JSON input:

```bash
echo '{"sender": "test", "icon": "👋", "notes": ["Hello"], "tags": ["review"]}' | sase notify create
echo '{"sender": "audit", "notes": ["Background result"], "silent": true}' | sase notify create
sase notify create -s my_sender < notification.json
sase notify create -s my_sender --tag review --tag handoff < notification.json
```

Raw creation validates and preserves the optional single-glyph JSON `icon`, the optional
`#RRGGBB` JSON `color` (see [Tab colors](#tab-colors)), and the JSON `silent` field. It
rejects registered privileged actions (`PlanApproval`, `EpicApproval`, `TaskTriage`,
`UserQuestion`, `LaunchApproval`, `CustomGate`, and `HITL`) because a raw row has no
trusted command bundle.

The first-class gate API reads a versioned gate specification from stdin:

```bash
sase gate create < gate-request.json
```

For example, this custom gate offers a restart-and-verify group plus a separate
rejection branch:

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
    "panel": "deployments",
    "panel_icon": "🚀",
    "origin_agent": "maintenance.agent",
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

`presentation.panel` selects the named notification panel tab described in
[Tags](#tags), and **requires** `presentation.panel_icon` alongside it — a gate that
names a tab is the thing introducing that tab to the user, so it is the thing
responsible for saying what the tab looks like. Omitting `panel_icon` while declaring
`panel` fails gate creation with a `missing_presentation` error.
`presentation.origin_agent` attributes the gate to the agent it was filed on behalf of;
it is stripped, limited to 128 characters, and stored without consulting the local agent
registry so remote agent names remain valid. All three fields are projected into
notification `action_data` as `panel`, `panel_icon`, and `origin_agent`; producers may
not write those protected keys directly through `presentation.action_data`.

`presentation.title` is the one-line decision headline shown in the notification panel's
[gate detail pane](#gate-detail-pane) and in the custom gate review modal's header. It
is stripped, limited to 120 characters, must be a single line, and must not contain
control characters; a missing title falls back to the gate kind's display title (for
example `Custom Gate`). It is **required for `kind: "custom"`** — along with a non-empty
`presentation.icon` and at least one non-blank `presentation.notes` entry — because a
custom gate has no other source for the headline, icon, and context the panel renders.
`plan`, `epic_plan`, `question`, `launch`, and `hitl` gates keep their existing
contracts and do not require a title. `presentation.title` is projected into
notification `action_data` as `gate_title`; producers may not write that protected key
directly through `presentation.action_data`.

`presentation.color` suggests the `#RRGGBB` accent for the tab the gate's notification
lands in, as described in [Tab colors](#tab-colors); a malformed value fails gate
creation with an `invalid_color` error.

`presentation.panel_icon` suggests one emoji or display glyph for the tab the gate's
notification lands in, as described in [Tab icons](#tab-icons); a malformed value fails
gate creation with an `invalid_presentation` error. It is a separate field from
`presentation.icon` rather than a reuse of it, because `presentation.icon` is the
**row's** icon and rows sharing one panel legitimately differ — donating the row icon to
the tab would make the tab's glyph flip depending on which row arrived most recently.
`panel_icon` is a property of the tab, and gates sharing a panel are expected to agree
on it.

`presentation.icon`, `option.icon`, and `group.icon` each accept one emoji or display
glyph. Each `OR` branch is a mutually exclusive resolution path. A singleton branch
renders as one button; an `AND` branch renders selectable option toggles plus a submit
button. The selected ids must be a non-empty subset of exactly one branch.
`default_selected` defaults to true, and a matching `groups` entry configures an AND
branch's submit label and icon. `feedback` is `disabled`, `optional`, or `required`;
custom options default to `optional`, and a group selection uses the strongest mode
among its selected members. Automatic resolution is forbidden for custom gates.
`primary_branch` must name one complete branch in canonical query order. ACE submits it
with Enter while Space toggles the focused AND member; submitting a primary group
preserves the reviewer's current toggles. ACE also numbers top-level branches in
canonical order: the fixed keys `1`–`9` submit their matching branches directly.
AND-member toggles remain unnumbered.

Every option references a bundle-owned `command` resource and is executed in query order
as an argv array without a shell after its hash is reverified. A selected-command
failure is recorded in the bundle error log and leaves the gate answerable. The
write-once response records `selected_option_ids`, `option_results`, and normalized
top-level `feedback` consistently for every transport.

On success, creation prints a stable JSON descriptor containing `schema_version`,
`notification_id`, `request_id`, `kind`, bundle/request/response/preview paths,
`continuation_mode`, `auto_resolution`, and hashes. The descriptor's `request_id` and
`kind` are the exact values accepted by `sase gate wait`. Typed front doors such as
`sase plan propose`, `sase questions`, and agent-initiated launch requests call the same
in-process gate service directly; they do not spawn this CLI. Agents should normally use
the generated `/sase_gate` skill to author this JSON.

Wait mechanically for a gate without reading or polling bundle files directly:

```bash
sase gate wait --id <request_id> --kind <kind>
sase gate wait --id <request_id> --kind <kind> --json
sase gate wait --id <request_id> --kind <kind> --timeout 60
```

Human output is colored and summarizes the selected options, feedback, and response
path. `-j/--json` emits the stable shape `status`, `selected_option_ids`, `feedback`,
and `response_path`, plus `input`, `option_inputs`, and `option_results` off the
write-once response (populated only once the gate is answered) and `operations` — the
repeatable actions a reviewer ran before deciding, from the execution journal, reported
regardless of how the gate ended. Status is `answered`, `cancelled`, or `timeout`, with
exit codes 0, 3, and 4 respectively. A CLI timeout can shorten but never extend the
request's own gate timeout.

`sase gate answer`, `sase gate act`, and `sase gate show` are the headless counterparts
to the ACE modals: `answer` selects a branch and supplies each selected option's
declared input (`--set field=value` typed by its declaration,
`--option-input <opt>=@file.json` for a whole per-option value, or `--input @file.json`
for the legacy shared value) and resumes or restarts a partially executed AND branch
with `--resume` / `--restart`; `act` runs one declared action headlessly, including
opening `$EDITOR` for an `edit_file` action, without answering the gate; `show` prints a
gate's declared branches, each option's input fields, and its declared actions, so an
author can check that the gate they wrote asks for what they intended. See `--help` on
each for the full flag reference.

For read-only inspection, list recent notifications as either a compact table or stable
JSON:

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

Use the explicit `list` subcommand when passing list flags; for example, use
`sase notify list -j`, not `sase notify -j`.

`sase notify list -j` prints notifications newest first with `id`, `timestamp`, `age`,
`sender`, `icon`, `priority`, `notes`, `files`, `tags`, `action`, `action_data`, `read`,
`dismissed`, `silent`, `muted`, `snooze_until`, and `resurfaced_at`. The `-q/--query`
filter matches tags as well as ids, senders, notes, files, actions, and action data.
Dismissed notifications are hidden unless `--all` is provided.

`list` and `show` are current-state reads: they atomically expire any due snooze before
projecting, and they order and limit by the activity key, so a resurfaced old
notification appears on the first `-l 1` page while still reporting its original
`timestamp` and `age`.

Inspect one notification by id:

```bash
sase notify show --id <notification_id>
sase notify show --id <notification_id> -f json
sase notify show --id <notification_id> -f markdown
```

The default `show` format is markdown. It includes the notification tags, notes,
attached file paths, action data, and state flags. Axe error digest notifications
usually point to the actionable report through `files` or
`action_data.error_report_path`; read that attached file for the detailed errors.

To create a local test notification with a persistent PNG attachment for ACE modal
image-preview checks, run `tools/test_image_notification` from the repository root.

See [`docs/configuration.md`](configuration.md#sase-notify) for the full CLI reference.

## Command-backed interaction gates

Each new gate is written once under `~/.sase/interaction_requests/<kind>/<request-id>/`.
The bundle contains canonical `request.json`, eventual write-once `response.json`,
reviewed previews or attachments, and adapter-owned commands. The request records the
continuation mode, optional gate timeout, typed payload, presentation metadata and icon,
option-query branches, the declared primary branch, options with configurable icons and
feedback modes, AND-group submit metadata, input/result schemas, and hashes for the
request and owned resources. Commands are argv arrays executed without a shell. A gate
may also declare repeatable, non-terminal **actions** the reviewer can run any number of
times without answering the gate; see [Gate actions](#gate-actions) below.

Manual creation succeeds only after the bundle, notification row, and pending-action
registration are durable. A partial failure is compensated, and retries are idempotent
by request ID. Manual and automatic selections use the same hash, input, result, and
write-once response validation. The pending-action 24-hour stale threshold is
transport-only; it may hide remote controls but does not terminate a waiting producer.
Only cancellation or an explicit per-request gate timeout is terminal. Every terminal
response or cancellation marks the pending action handled and dismisses the notification
row, regardless of gate kind or client surface. When ACE opens the notification modal,
it also repairs live gate rows whose bundles became terminal without a corresponding
dismissal.

ACE, Telegram, and mobile derive gate-kind capabilities from the shared adapter registry
and render branches in query order from the same normalized envelope structure.
Registering a new branch-actionable kind therefore makes it actionable on every surface
without adding per-surface action or kind allowlists. Singleton branches are buttons.
AND branches expose one toggle per option and a configurable submit control; the primary
AND branch starts expanded. Top-level branches have fixed one-based digit selectors in
canonical query order, while AND members remain unnumbered and use Space to toggle.
Enter submits the declared primary branch, Ctrl+S submits the active branch, and `q` or
Escape cancels the modal. Surfaces submit `selected_option_ids`, feedback, and each
selected option's declared input (see [Gate inputs](#gate-inputs) below), and the shared
executor runs the selected commands in query order.

Tale plan approval uses `(approve AND commit) OR reject OR feedback`. The approve and
commit options start selected, the group submit is labeled **Tale**, and the two
singleton branches remain **Reject** and **Send Feedback**. Epic plans use
`approve OR reject OR feedback`.

The typed projections remain deliberately distinct. Their default feedback, generic-form
rendering, and branch-action capabilities are declared by the same adapter entries that
map kinds to notification actions:

| Gate kind     | Notification action | Recommended producer                              |
| ------------- | ------------------- | ------------------------------------------------- |
| `plan`        | `PlanApproval`      | `sase plan propose` with an authored `tier: tale` |
| `epic_plan`   | `EpicApproval`      | `sase plan propose` with an authored `tier: epic` |
| `task_triage` | `TaskTriage`        | AXE's built-in `bead_task_triage` chop            |
| `flag_triage` | `FlagTriage`        | AXE's built-in `bead_task_triage` chop            |
| `question`    | `UserQuestion`      | `sase questions`                                  |
| `launch`      | `LaunchApproval`    | Agent-initiated `sase launch request`             |
| `custom`      | `CustomGate`        | `sase gate create`                                |

`TaskTriage` uses `launch OR close OR snooze`, with Launch as the primary branch. Launch
accepts optional feedback and submits or reuses one globally visible unattributed proc
whose command is `sase bead work <bead-id> --yes-to-all`; the gate response records that
proc ID. Close requires feedback, closes the task bead with `resolution=canceled`, and
uses the feedback as its close reason. Snooze requires a wake-time expression and moves
the task to `snoozed`, after which reconciliation replaces this gate with a `BeadSnooze`
gate. The gate preview is generated from the bead's title, description, and notes, with
the notes section present only when the bead has notes. Automatic resolution is
forbidden, and all client surfaces use the same host-side side effects.

Workflow `HITL` remains a legacy producer, but a HITL notification that references a
neutral bundle is resolved through the same hash-verified executor in ACE and Telegram.
Only legacy HITL bundles use the direct response-file writer.

### Gate inputs

An option's command reads its input as **stdin JSON**, never as command arguments —
templating reviewer-supplied values into `argv` would break the hashed-command trust
model, so there is no "extra args" escape hatch. An option declares what it needs under
`inputs`, a closed, declarative vocabulary that compiles into the option's
`input_schema` at creation time. `input_schema` stays the single enforcement layer: the
executor validates the submitted value against the compiled schema, so a reader that
knows nothing about `inputs` still enforces correctly.

```json
{
  "id": "restart",
  "label": "Restart service",
  "command": { "argv": ["commands/restart"] },
  "feedback": "optional",
  "inputs": [
    {
      "id": "target_env",
      "label": "Environment",
      "type": "enum",
      "required": true,
      "choices": ["staging", "production"]
    },
    { "id": "delay_seconds", "label": "Delay (seconds)", "type": "int", "default": 0 },
    { "id": "api_token", "label": "API token", "type": "line", "secret": true }
  ]
}
```

Each field has an `id` (the JSON property name, `^[a-z][a-z0-9_]*$`), a `label`, and a
`type`:

| `type`  | Compiles to                                 |
| ------- | ------------------------------------------- |
| `word`  | Non-empty string with no whitespace         |
| `line`  | String with no newlines                     |
| `text`  | Any string                                  |
| `path`  | Non-empty single-line string                |
| `agent` | Same as `word`                              |
| `int`   | Integer                                     |
| `bool`  | Boolean                                     |
| `float` | Number                                      |
| `enum`  | One of a declared, non-empty `choices` list |

`repeatable: true` wraps the compiled fragment in a JSON array. `choices` accepts either
plain strings or `{value, label}` objects and is required (and only valid) for `enum`.
`default`, `placeholder`, and `help` are optional; a declared `default` is validated
against the field's own compiled fragment, so a default no client could submit is a
creation error rather than a gate that fails on first answer. `secret: true` reaches the
command's stdin unredacted but is written to `response.json` and the execution journal
as `{"$redacted": true}` — masked display alone would not be enough, since the response
file is durable audit data. That covers every place those two files hold the value:
`option_inputs`, the legacy shared `input` beside it, and the stored command result. A
command is free to echo its stdin back, so any result string that merely _contains_ a
submitted secret is replaced whole rather than spliced. Only non-empty string secrets
are matched, because a secret boolean or small integer carries no entropy and matching
on it would redact unrelated output. The journal's `result_digest` is taken from the raw
result and still identifies exactly what the command returned.

`inputs` and a raw `input_schema` are mutually exclusive per option: declaring both is a
creation error unless the raw schema exactly equals what `inputs` would compile to. An
option declaring neither means "this command takes no input", which compiles to the
honest `{"type": "object", "additionalProperties": false}` schema; an author who
genuinely wants the permissive schema writes `"input_schema": {}` explicitly. A declared
`format` keyword is annotation-only — the executor validates with no `FormatChecker` —
so it is documentation, never a constraint. Every stored schema is pinned to the Draft
2020-12 dialect.

At creation, every option's effective schema is checked for **answerability**: SASE
builds the richest value a client could actually submit and checks that the schema can
accept it. For an option declaring `inputs`, that value is `{}` plus every declared
field's default plus `feedback` when the option's feedback mode allows it, validated
against the compiled schema. For an option declaring a raw `input_schema` and no
`inputs`, the reviewer types the value into a raw-schema editor — ACE's YAML editor,
`sase gate answer --option-input`, or the mobile bridge's `option_inputs` — so every
property declared under `properties` is producible and the schema's own constraints on
those properties (patterns, bounds, types) are the reviewer's to satisfy. What still
fails closed is a `required` name that nothing renders a control for: a name absent from
`properties`, or `feedback` on an option whose feedback mode is `disabled`. An option
that could never be answered by any surface fails `sase gate create` with
`unanswerable_option`, naming the offending required property, instead of being accepted
and dying silently on first submission. Every input value is also bounded, both at
creation and at submission: canonical JSON at most 64 KiB, nesting depth at most 16, at
most 128 properties in one object, and at most 512 items in one array.

**Feedback is one rule everywhere.** The reviewer's free-text note is injected as
`input.feedback` for a selected option **iff that option's effective `input_schema`
declares a `feedback` property** — an option with no `feedback` property is left alone,
and an option with an ordinary `feedback` field declared under its own `inputs` is
respected as-is. The same rule runs inside the shared executor for every caller — ACE,
mobile, Telegram, and `sase gate answer` alike — so a gate answers identically
regardless of where it was tapped.

**Submission is per option.** A surface submits `option_inputs`, a mapping of selected
option id to that option's own JSON value; a two-member AND branch can hand each member
a different value without either schema having to tolerate the other's fields. The
legacy shared-value contract (`input_data`, one JSON value applied to every selected
option) still works for bundles that predate per-option submission; the two are mutually
exclusive, and supplying both is a creation-time `conflicting_input` error.
`response.json` always records `option_inputs` (every entry is the same value under the
legacy path) alongside the existing `input` field, so nothing that reads `input` today
breaks.

### Gate actions

A gate action is a control the reviewer may run **as many times as they need** and that
**never answers the gate** — it exists so a reviewer can iterate toward a decision (edit
the plan until it validates, read a diff, run a dry run) instead of being forced to
answer or cancel immediately. Actions are declared in the request's `operations` array
(the field name that predates this mechanism, kept for wire compatibility) and rendered
in an **Actions** section, kept visually distinct from and above **Decision**; the
section is omitted entirely when a gate declares no actions.

Two kinds are declared:

- **`edit_file`** opens an editable resource in `$EDITOR`. `edit_target: "resource"`
  (the default) edits the bundle's own copy, exactly as before. `edit_target: "origin"`
  instead opens the durable file the resource was copied from — for example, a plan or
  epic gate's `edit_plan` action opens the file under `~/.sase/plans/` that
  `sase plan propose` wrote, not the bundle's snapshot of it. The edit is copied into
  the bundle and accepted only when the kind adapter validates it (for plan and epic
  gates, only when `sase plan validate` passes); on rejection the bundle keeps its last
  accepted revision and the reviewer's draft stays in the origin file rather than being
  discarded, so reopening the editor resumes their work. **While an origin file holds an
  edit the gate never accepted, every submit control is disabled — including reject —**
  and the surface shows a banner naming the file; discarding the draft (a separate,
  confirmed action) restores the origin from the last accepted revision.
- **`run_command`** runs an owned bundle command and shows the reviewer its output. Its
  stdout must be one JSON value validated against the action's own `result_schema`; the
  surface reads a small closed display record out of it — `summary` (a one-line toast),
  `body` (rendered per the declared `display`: `markdown`, `text`, `json`, or `none`),
  and `refresh` (whether the surface should reload and re-verify the bundle before
  re-rendering) — and everything else stays in the result and the execution journal.
  `targets` lists the editable resources the command is allowed to rewrite; after the
  command exits every resource is re-hashed, and a change to any resource **not** listed
  in `targets` is a `hash_mismatch` failure. This is what stops a display command from
  quietly rewriting the very command the reviewer is about to approve.

An action never writes `response.json` and refuses to run once the gate already has a
response or a cancellation. Every run — successful or failed — appends to the bundle's
execution journal (`journal.jsonl`), which is also what `sase gate wait --json` reports
under `operations`: the audit trail of what a reviewer ran before deciding.

An action may declare a single-character `key` (for example `key: "e"` on the plan and
epic `edit_plan` action). Creation rejects a key already reserved by the static gate
modal bindings (`q`, `d`, `g`, `G`, and the digit branch selectors `1`-`9`) or reused by
another action on the same gate. A collision with the reviewer's own configured gate
modal keymaps cannot be known at creation time; ACE resolves it at render time by
reassigning from a deterministic fallback pool and displaying whichever key it actually
bound.

### Debugging a gate

Press `d` on any notification row or from an open plan, epic, question, launch,
custom-gate, or workflow HITL panel to open **Gate Debug**. The overlay keeps the
underlying form mounted, so closing it returns to the same selected branch, checked
group options, and typed feedback. Non-gate inbox rows use the same view and show an
explicit no-bundle state alongside their raw notification JSON.

Gate Debug loads bundle I/O and hash verification away from the TUI event loop. Its tabs
show the lifecycle overview, the canonical `request.json`, the terminal `response.json`
or `cancellation.json`, bounded execution error records, and the raw row from
`notifications.jsonl`. The overview re-verifies request and resource hashes live and
includes timeout, pending-action transport/staleness, and notification state. Missing,
malformed, or oversized artifacts render as diagnostics instead of preventing the modal
from opening.

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

Readers resolve the neutral bundle first and then fall back to in-flight legacy plan,
question, launch, or HITL request directories. New producers do not dual-write the old
trees. Keep these fallbacks for at least one complete SASE release after neutral writers
ship and beyond the 24-hour remote-action stale window. The cross-kind resolver
regression test locks this rule in; removing a fallback requires a separately announced
migration after that window, updated fixtures, and explicit release notes.

Unanswered schema-v2 neutral bundles also remain hash-verifiable and answerable. Readers
project their historical first branch as the primary action in memory; new gate creation
requires schema v3 and an explicit `primary_branch`.

Question summaries use the same resolver, so ACE can render both neutral and legacy
questions. Gate command execution from ACE is scheduled as tracked background work
rather than running on Textual's event loop.

## Storage

Notifications are stored in JSONL format at `~/.sase/notifications/notifications.jsonl`.
The production store backend is `sase_core_rs`: appends and state mutations take a
shared sidecar lock, and rewrites use a tempfile plus rename so multiple axe processes
and the TUI can access the file without truncate-before-lock exposure. Common state-only
updates such as mark-read, mark-all-read, mute, snooze, and dismiss use a count-only
Rust mutation path unless the caller needs rehydrated notification rows; this keeps
inbox counters cheap when ACE or a bridge process only needs mutation metadata.

The Rust store also owns every temporal semantic: it validates and normalizes snooze
deadlines, expires due rows atomically under the same lock as the read, stamps
`resurfaced_at`, and reports both `expired_ids` and the earliest remaining
`next_snooze_deadline` alongside the projected counts. Consumers schedule their timers
from that projected deadline instead of polling. Concurrent expiring readers converge on
one store state without losing appended rows.

Source: `src/sase/notifications/`
