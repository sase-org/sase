---
title: Notifications
description: View, sort, mute, snooze, and receive notification updates in SASE.
---

# Notifications

This page explains how to view and manage notifications in SASE.

## Overview

Sase includes a notification system that surfaces important events from background
processes (axe, workflows, mentors) to the user through sase's TUI. Notifications are
stored as JSONL and persisted to `~/.sase/notifications/notifications.jsonl`.

Plan, epic-plan, question, agent-launch, sudo, and task-triage approvals use the
notification row as a typed transport projection of a durable interaction gate. The
reviewed content, option-query branches, validation schemas, and hash-verified commands
live in `~/.sase/interaction_requests/<kind>/<request-id>/`; sase's TUI, mobile,
Telegram, and typed CLI actions all resolve that same bundle. Sudo requests add a
terminal-only approval path; see [Sudo Requests](sudo.md).

### Remote Attention

When remote machines are enrolled, sase's TUI normal refresh polls their global pending
attention inventory independently of the Agents rows currently visible or followed. Each
authorized remote question or gate becomes a durable unread notification in the
**Attention** panel, labeled with the owning machine alias. Selecting the notification
opens the same answer/approve modal as the corresponding remote Agents row and submits
the decision through the durable `sase machine attention` operation.

The inbox reconciles requests by origin installation, request ID, and revision. Read and
dismissed are local browsing state, never an answer to the remote request: re-polling
the same revision refreshes the row's content but keeps your read or dismissed choice,
along with existing mute and snooze choices. A new revision creates a fresh unread row
that needs renewed review, and sase's TUI dismisses the superseded revision. When a
fresh, complete host inventory no longer contains a request, sase's TUI dismisses the
stale row. Only rows sase's TUI dismissed itself come back, unread, if that same
revision is reported pending again. A failed, unavailable, cached, stale, partial, or
paged (more results pending) host inventory does not settle missing requests, so a
transient outage cannot silently remove a pending decision. If the owning alias is later
removed or quarantined, submission stops with a diagnostic instead of routing the answer
elsewhere.

## Viewing Notifications

Press `i` on any tab in sase's TUI to open the notifications modal. The modal receives
the complete unread, non-silent inbox dataset, so every populated tab and every eligible
row remains accessible even when the backlog is large. Rows in the list show relative
timestamps (e.g., "2m ago", "1h ago") and can be marked as read or dismissed. Dismissed
rows are not gone for good: the [dismissed view](#dismissed-view) lists them again for
review and one-key restore. The detail pane shows the selected notification's absolute
send time alongside its relative age (`sent today 13:18:42 · 4m ago`), tiered as
`today HH:MM:SS` / `yesterday HH:MM` / `Mon D HH:MM` / `Mon D 'YY HH:MM` in the
configured timezone.

### Modal Keybindings

| Key                 | Action                                                                      |
| ------------------- | --------------------------------------------------------------------------- |
| `j` / `k`           | Navigate between notifications                                              |
| `Enter`             | Select notification (jump to PR, approve plan, etc)                         |
| `d`                 | Open Gate Debug for the highlighted row                                     |
| `x`                 | Dismiss notification, or dismiss marked rows when marks are present         |
| `u`                 | Restore (undismiss) the highlighted dismissed row, or marked rows           |
| `m`                 | Toggle the per-row mark on the highlighted notification                     |
| `M`                 | Toggle mute on the highlighted notification, or marked rows                 |
| `s`                 | Snooze the highlighted notification, or marked rows (opens duration picker) |
| `e`                 | Open attached file in `$EDITOR`                                             |
| `V`                 | Open the current image attachment in the image viewer                       |
| `Ctrl+N` / `Ctrl+P` | Cycle through attached files                                                |
| `Ctrl+D` / `Ctrl+U` | Scroll file content down / up                                               |
| `g` / `G`           | Jump the detail pane to the top / bottom of its contents                    |
| `1`–`9` / `0`       | Jump to the 1st–9th or 10th current tab; a missing position does nothing    |
| `[` / `]`           | Cycle notification tabs                                                     |
| `+`                 | Cycle newest-first through the selected row's `+1` evidence, then default   |
| `R`                 | Mark every unread notification in the **active tab** read (confirms first)  |
| `S`                 | Toggle the active tab between sectioned and newest-first rows               |
| `T`                 | Toggle between the unread inbox and the dismissed-notifications view        |
| `Esc` / `q`         | Close modal                                                                 |

The detail-pane scroll keys work with either the notification list or detail pane
focused. Apostrophe jump mode consumes hint keys first, so `g` and `G` select matching
jump hints while hints are visible instead of scrolling the detail pane. The same
first-refusal applies to digits: `2` selects the second tab in normal mode, while `'`
then `2` (or a two-character hint such as `10`) jumps to the matching row without
changing tabs.

Every gate-backed notification (plan, epic, question, launch, workflow HITL, custom,
sudo, task-triage, flag-triage, snooze, stale-cleanup, and required-plugin) and every
[remote attention](#remote-attention) row requires confirmation (`y` / `n`) before
dismissal to prevent accidental loss of pending decisions. The same `y` / `n`
confirmation is used for bulk dismissal when at least one marked protected notification
is included in the batch.

### Dismissed View

Press `T` to switch the modal between the unread inbox and the dismissed view, which
lists dismissed rows that are still unread; the title reads `Notifications (dismissed)`
while that view is active. Press `u` to restore the highlighted row (or every marked
row) to the inbox, then press `T` again to return to the normal inbox.

A dismissed live gate stays unread — selecting it never marks it read, and dismissing it
never does either — so it always resurfaces in the dismissed view until it is answered
or restored. Rows that are both read and dismissed (for example after `R` marks their
tab read) are outside the inbox's unread scope and stay out of both views; the pending
gate bundle itself remains reachable through the gate CLI (`sase gate list` /
`sase gate show`).

`R` is scoped to the tab you are on, not the whole inbox, and it is a wider write than
it looks: it marks the tab read in the notification store, which includes rows matching
that tab that sase's TUI has not loaded into the visible list. Because of that, it opens
a danger confirmation naming the tab (`Mark Notification Tab Read?`) that defaults to
**Cancel**; it cannot be undone from sase's TUI. The target is frozen when the prompt
opens, so switching tabs while the confirmation is up cannot redirect the write to a
different tab, and a tab with nothing in the visible list never prompts at all. The
mutation itself runs as a proc, so a slow store write does not block the modal. On
confirmation the marked-read rows leave the visible list immediately, the emptied tab
disappears from the tab strip, and the modal moves to the nearest surviving tab (or
shows `No unread notifications` when that was the last tab). A toast reports how many
notifications the store marked read.

### Gate Detail Pane

Highlighting any gate-backed row — plan, epic, question, launch, custom, sudo,
task-triage, flag-triage, snooze, stale-cleanup, required-plugin, or workflow HITL —
always renders a live decision card in the right pane: a status line
(`Awaiting your decision`, `Answered`, `Cancelled`, `Timed out`, or
`Gate details unavailable`), the notification's context and tags, a `Decision` block
listing every branch in canonical query order with the primary branch marked, and an
`Attachments` line when the gate has files. The card renders instantly from the
notification row and enriches itself with the verified bundle a moment later without
blocking navigation. When a bundle cannot be resolved, hashed, or parsed — a deleted
directory, a corrupted `request.json`, a legacy bundle layout — the card degrades to
`▲ Gate details unavailable` rather than going blank; press `d` to open Gate Debug and
see exactly why. Every other notification, including attachment-less ones, gets a
compact summary card instead of an empty pane.

### `+1` Evidence

A sender can append corroborating evidence to an existing notification without creating
a duplicate row. The list renders a `[+N]` badge after the title; the count includes
older evidence dropped by bounded retention. The default detail card adds a
`+1 EVIDENCE` block with each retained sender, age, and note. Report cards also show the
total and latest retained evidence age in their provenance line.

Each row retains its newest 500 entries and counts older dropped entries in `N`. SASE
collapses whitespace in each note and stores at most 2,000 characters. Repeated entries
from the same sender remain separate occurrences.

Press `+` to replace the detail pane with the newest retained `+1`, then walk backward
through older entries. One more press after the oldest entry wraps to the normal detail
pane. Changing rows or tabs also resets the cycle. A row with no retained evidence shows
a status hint and leaves the pane unchanged.

Appending a `+1` is deliberately evidence-only: it does not change the notification's
read, dismissed, muted, or snoozed state, activity ordering, or delivery cursors.

### Tabs and Ordering

The modal renders a compact tab strip above the list whenever there is at least one tab.
It is hidden only at zero tabs, which is also when the list itself is replaced by the
`No unread notifications` message — so the strip never pops in and out, and the list
never shifts, as dismiss, mute, and snooze actions collapse the tabs down to one.
**Every notification belongs to exactly one tab** — the Rust core decides which one by a
fixed precedence, so the panel, the top-bar indicator, and the mobile snapshot always
agree; see [Tags](notification-tags.md#tags) below for that precedence in full. Tabs
then sort by [priority](../config/ace-behavior.md#acenotificationtabs) descending, with
the core's order as the tiebreak at equal priority. The tabs, at their default
priorities:

| Tab       | Icon | Priority | Contents                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------- | ---- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Gates`   | `⚑`  | `60`     | Plan and epic approvals, user questions, workflow HITL prompts, launch approvals, and generic gates without a declared panel.                                                                                                                                                                                                                                                                                 |
| Panel     | `◆`  | `50`     | Gates with `presentation.panel`. At equal priority they keep the core's label order after `Gates`; remote questions and gates use `Attention` (`?`), while built-in task triage gates use `Beads` (`◈`) and woken `BeadSnooze`, due `FlagTriage`, and `BeadStaleCleanup` gates land there too. The shipped `beads` priority is `0`, so `Beads` sits between custom tags and `Snoozed` and renders a `▾` mark. |
| `Errors`  | `✖`  | `40`     | Axe digests, failed file hooks, and agent errors (`axe`, `file-hooks`, or `user-agent` with `ViewErrorReport`).                                                                                                                                                                                                                                                                                               |
| `General` | `✉`  | `30`     | Untagged, unmuted notifications with no other classification.                                                                                                                                                                                                                                                                                                                                                 |
| `Done`    | `#`  | `20`     | Notifications carrying the `done` tag, pinned before other custom tags.                                                                                                                                                                                                                                                                                                                                       |
| Custom    | `#`  | `10`     | Other normalized notification tags, sorted alphabetically after `Done` at equal priority. Sudo requests declare no panel, so they land in the `sudo` tag tab rather than `Gates`.                                                                                                                                                                                                                             |
| `Snoozed` | `☾`  | `-10`    | Muted notifications with a future wake time — snoozed notifications and notifications for snoozed task beads alike.                                                                                                                                                                                                                                                                                           |
| `Muted`   | `⊘`  | `-20`    | Muted notifications with no wake time.                                                                                                                                                                                                                                                                                                                                                                        |

Each tab's icon resolves through the same chain as its color; see
[Tab icons](notification-tags.md#tab-icons) below. A tab whose effective priority
differs from its default renders one extra cell immediately after the count: `▴` (amber
`#FFAF00`) when raised, `▾` (grey `#8A8A8A`) when lowered. Compact-mode tabs keep the
mark after shedding the label. The top-bar indicator chips omit it — a chip is already
`<icon><count>`, and the badge's left-to-right order plus the hover tooltip
(`▾ priority 0`) spell out the deviation.

The first ten tabs, in that same current order, carry an unboxed shortcut digit
immediately before the icon: `1`–`9`, then `0` for the tenth. The mapping is positional
and is resolved from the live classified order on every keypress and every render, so
dismiss, mute, snooze, mark-read, and priority changes cannot leave a stale digit. Tabs
past the tenth stay unnumbered and remain reachable with `[` / `]` or the mouse.
Pressing a digit with no tab at that position is a no-op that stays inside the modal.

The strip reflows to fit its measured width rather than clipping, in three tiers. Full
shows shortcut, icon, label, count, and optional priority mark for every tab. When that
would overflow, compact keeps the shortcut on every tab, sheds inactive labels, and
retains the active name. When compact still does not fit, micro packs shortcut, icon,
and count with tighter separators. Shortcut digits are never shed. Shedding labels is
what keeps a tab from falling off the end of the line, where it would be both invisible
and unclickable; a resize re-renders the strip only when the width actually changed.

A row with multiple tags therefore occupies exactly one tab, not one per tag; dismissing
it removes the row from at most one tab's count.

#### Sections

Tabs can render their rows under ordered section headers. The shipped strategy is
enabled for `Beads`, where task-bead rows are grouped by task type in catalog order:
Bug, CI failure, Feature, Flaky test, and Memory, followed by Due, Cleanup, and Other
for rows without a task-type chip. Rows inside each section keep the same activity
ordering described below.

Press `S` to toggle the active tab between grouped sections and `recent`, a flat
newest-first render. The choice is per tab and lasts only for the current sase's TUI
process. Tabs without a grouping strategy stay flat and report that they have no
sections.

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
target every live marked row instead of the highlighted row. Gate-backed and remote
attention rows in a marked dismiss batch use the same `y` / `n` confirmation prompt as a
single dismissal.

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

- **sase's TUI session** — one second, including after suspend/resume, a restart, or a
  system-clock change, and independently of `--refresh-interval`. sase's TUI schedules a
  deadline-driven coordinator rather than relying on the general refresh tick.
- **Mobile gateway** — the next authenticated list or detail read, which expires the row
  and publishes a `notifications_changed` event so connected clients refresh.
- **Telegram outbound job** — the next scheduled job run.

If every consumer is offline, no alert is emitted at the deadline; the durable guarantee
is instead that the **first** later current-state read atomically catches the row up
before returning any state. Expiry is therefore never lost, only deferred to the next
reader.

Because expiry happens under the store lock, exactly one concurrent reader observes a
given row in its `expired_ids` transition metadata. Every other consumer still observes
the result through the persistent `muted`, `read`, and `resurfaced_at` fields, so a
losing process never misses the resurfacing. sase's TUI emits one toast and one tmux
bell per observed resurface batch and does not repeat it on later polls.

#### Activity Ordering

Every consumer orders notifications by an effective activity key rather than the raw
creation time:

```text
activity_at(notification)     = resurfaced_at ?? timestamp
activity_cursor(notification) = (activity_at, notification_id)
```

`timestamp` keeps its immutable meaning as the original creation time and is what the UI
displays as the sent time. The activity key is what makes a resurfaced snooze
first-class recent activity: an old row moves to the top of sase's TUI modal, the first
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
(`read_current_notification_snapshot()` and the CLI, sase's TUI, mobile, and Telegram
projections built on it) atomically expire due rows under the store lock before
projecting rows, counts, `expired_ids`, and the next active deadline.

### Top-Bar Indicator

The `inbox:` group in the TUI top bar renders one colored `<icon><count>` chip per
notification-panel tab (see [Tabs and Ordering](#tabs-and-ordering)), in the panel's own
left-to-right order, so the badge and the panel always agree on what each count means:

- **Nothing pending** — a dim `inbox: 0`.
- **Snoozed only** — `inbox: ☾4`: the count renders in the Snoozed tab's resolved color
  at a dimmer weight than an actionable count, prefixed by the Snoozed tab's own icon
  instead of a trailing `z` suffix.
- **Anything else** — one `<icon><count>` chip per visible tab, each the tab's icon and
  count in its own resolved color at full weight, joined by a single space, for example
  `inbox: ⚑2 ✖3 ◈1`. Each chip is self-identifying, so there is no separator glyph
  between chips — the `·` separates groups, not tab chips — and no `✉` anchor: once
  `general` owns `✉` as its own tab icon, prefixing the whole badge with it would render
  the same glyph twice, meaning two different things. As soon as any non-snoozed tab has
  a count, the Snoozed chip drops out of the badge entirely — it does not compete for
  the limited chip budget — but the snoozed count still appears in the tooltip.
- **Overflow** — at most
  [`ace.notification_indicator_max_counts`](../config/ace-behavior.md#acenotificationtabs)
  chips (4 by default), taken in panel order; any remaining tabs collapse into one
  trailing dim `+K` chip, joined by the same single space. Every suppressed tab is still
  described in the tooltip.

The chip budget is display-only. It does not limit the notification modal dataset, tab
counts, or the Agents `Enter` action. On the Agents tab, `Enter` searches the complete
unread dataset for the selected agent's pending gate (every gate kind), so older pending
agent decisions remain reachable regardless of indicator overflow or backlog size.

Hovering the indicator opens a tooltip briefing: a header count of unread rows (snoozed
and muted rows are informational and excluded from that header count) followed by one
line per tab showing its icon, its count, its oldest unread activity (`oldest 14m ago`)
or, for the Snoozed tab, when it next wakes (`next wakes in 43m`). Tab labels in the
tooltip are colored the same as their indicator chip, so the tooltip doubles as a
legend. See [Tab colors](notification-tags.md#tab-colors) and
[Tab icons](notification-tags.md#tab-icons) for how each tab's color and icon are
resolved.

Silent notifications never contribute to the indicator (see
[Silent Notifications](notification-types.md#silent-notifications) below).

### Visual and Audible Delivery

New unmuted notifications remain visually prominent through the top-bar indicator and
action-specific toasts. A genuinely new `PlanApproval` or `EpicApproval` rings once on
arrival, alongside its priority inbox row, warning toast, and the producer's desktop
notification. sase's TUI toast says `Tale ready` or `Epic ready`; an epic adds the
gate-time phase, dependency-wave, and non-zero phase-size counts, while batched toasts
count tales and epics separately. Already-handled plan reviews discovered during polling
and the intermediate post-approval handoff remain silent. Task triage, stale-cleanup,
questions, launch/custom/HITL/sudo gates, errors, agent completions, and ordinary
notifications retain their arrival bell. Priority actions include `PlanApproval`,
`EpicApproval`, `UserQuestion`, `LaunchApproval`, `TaskTriage`, `BeadSnooze`,
`FlagTriage`, `BeadStaleCleanup`, `PluginsRequired`, `GateExecutionFailed`,
`JumpToMentorReview`, and `RemoteAttention`.

Snooze expiry is an explicit reminder chosen by the user and, by default, remains
audible for every notification class, including a snoozed tale or epic review. A
delivery rule that matches the resurfaced row still applies to it.

Every toast and arrival sound described here is the default. `ace.notification_rules`
overrides TUI behavior per notification and may suppress Telegram delivery; see
[Delivery Rules](#delivery-rules).

### Delivery Rules

`ace.notification_rules` is an ordered list of rules that decide, per new notification,
whether sase's TUI shows a toast, how the arrival is announced (the terminal bell, a
sound file of your choosing, or silence), and whether the row may be delivered to
Telegram. With no rules configured every notification toasts and rings the bell once per
poll, exactly as described above, and Telegram delivery is permitted (subject to the
transport's own eligibility checks).

```yaml
ace:
  notification_rules:
    - name: quiet-task-beads
      description: Task-bead triage is too noisy to announce right now.
      match:
        tab: beads
      toast: false
      sound: none
    - name: mac-chime
      sound: /System/Library/Sounds/Glass.aiff
```

| Key           | Type    | Meaning                                                       |
| ------------- | ------- | ------------------------------------------------------------- |
| `name`        | string  | Label for `sase notify rules`, doctor output, and diagnostics |
| `description` | string  | Free prose explaining why the rule exists                     |
| `priority`    | integer | Evaluation weight, `-1000..1000`; higher is consulted earlier |
| `match`       | mapping | Criteria. Omitted or `{}` matches every notification          |
| `toast`       | boolean | Whether a TUI toast is shown                                  |
| `sound`       | string  | `bell`, `none`, or the path of a sound file                   |
| `telegram`    | boolean | Whether Telegram delivery is permitted (`false` suppresses)   |

Every key is optional, and an unknown key drops the whole rule rather than being
ignored: a rule applies exactly as written or not at all. A rule with no `name` is
reported as `rule[<index>]`, counting from `0` across the rules that survived. sase
versions that predate delivery rules report `ace.notification_rules` as an unknown key
in `sase config validate` and `sase doctor`.

#### Matching

Six criteria, each drawn from something visible on the notification row:

| Criterion | Matched against                                                                                                                 |
| --------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `tab`     | The tab that owns the row (see [Tabs and Ordering](#tabs-and-ordering)): `beads`, `hitl`, `errors`, `general`, a tag, and so on |
| `sender`  | The notification's sender                                                                                                       |
| `action`  | The notification's action; an empty string for a row with no action                                                             |
| `tags`    | Any one of the notification's tags                                                                                              |
| `title`   | The first note, which the panel shows as the row headline                                                                       |
| `note`    | Any line of the notification's notes                                                                                            |

- Every value is a **case-insensitive glob**: `*`, `?`, `[abc]`, `[a-c]`, and `[!abc]`.
  A value with no wildcard is therefore an exact, case-insensitive match. There is no
  substring or fuzzy matching: `title: "Plan ready"` does not match
  `Plan ready for review`, while `title: "Plan ready*"` does. Write `[*]` for a literal
  `*`. A `[` with no closing `]` matches a literal `[`.
- A criterion takes one string or a list of strings; a list is **any-of**.
- Several criteria in one `match` are **all-of**.
- `tab: gates` is an alias for `tab: hitl`, because the panel labels that tab `Gates`.
  The muted and snoozed tabs are `__muted__` and `__snoozed__`.

The tab a row matches is the tab the panel shows it under, because both come from the
same core classification. `sase notify rules --explain` reports the tab of the row as it
is stored now, so a muted or snoozed row reports `__muted__` or `__snoozed__`.

#### Resolution

Rules are consulted in descending `priority`, with ties broken by position in the merged
list. For `toast`, `sound`, and `telegram` **independently**, the first matching rule
that sets that field decides it. A field no matching rule sets keeps the default: toast
shown, sound `bell`, Telegram permitted. A rule that sets only `toast` therefore never
blocks a later rule from choosing the sound or suppressing Telegram. `telegram: true`
permits Telegram delivery but never bypasses the transport's read/mute/silent,
first-run, cursor, or other eligibility checks.

The merged list follows config layering: rules from `~/.config/sase/sase.yml` come
first, then rules from machine overlays such as `sase_<machine>.yml`, then project-local
rules. A machine-wide `sound` rule in an overlay can sit under a narrower rule in
`sase.yml` without re-stating it. Use `priority` only when a later layer must
deliberately override an earlier one.

Because the first match wins, no negation is needed. To silence everything except gates,
say what gates do, then silence everything else:

```yaml
ace:
  notification_rules:
    - name: gates-announce
      match:
        tab: gates
      toast: true
      sound: bell
    - name: silence-the-rest
      toast: false
      sound: none
```

A gate row matches `gates-announce`, which decides both fields before the second rule is
consulted. Every other row falls through to `silence-the-rest`, whose empty `match`
matches all notifications.

#### Sounds

`sound` is a single value with two reserved words, compared case-insensitively:

| Value    | Announcement                                                           |
| -------- | ---------------------------------------------------------------------- |
| `bell`   | The terminal bell through tmux, three rings (the default)              |
| `none`   | Silence                                                                |
| anything | The path of a sound file, with `~` and `$VAR` expanded and then played |

A file literally named `bell` or `none` is addressed as `./bell`. sase's TUI picks the
first audio player found on `PATH`:

| Platform | Players, in order                             |
| -------- | --------------------------------------------- |
| macOS    | `afplay`                                      |
| Linux    | `paplay`, `aplay`, `ffplay -nodisp -autoexit` |

A missing file, a missing player, a player that fails or hangs, or an unsupported
platform never interrupts the poll: the announcement is simply silent. A player that
runs longer than 30 seconds is stopped. `bell` rings through tmux only, using the
`tmux_ring_bell` helper found on `PATH`: when sase's TUI is not running inside a tmux
pane (`$TMUX_PANE` unset) or the helper is missing, `bell` is silent. Playback runs on a
worker thread, so it cannot stall the TUI. A sound file also plays detached from the
poll that triggered it — a long chime never holds up the notification tick or the agent
refresh behind it — and only one file plays at a time, so notifications arriving faster
than the file is long cannot stack up players.

Each poll announces **at most one sound**. It is the resolved sound of the first new
notification, in activity order, whose sound is not `none`; if every arriving row
resolves to `none`, the tick is silent. A burst of five notifications is one chime, not
five.

#### What a rule does not change

`toast: false` suppresses the toast, and `sound: none` the sound; nothing else changes.
The notification is still stored, still unread, still counted in the top-bar indicator,
and still listed in the panel under its tab. Rules never affect whether a notification
is created, read, muted, or snoozed. Suppressed rows are also left out of grouped
toasts: a batch of six with three suppressed produces three individual toasts rather
than one group of six.

`telegram: false` suppresses only the Telegram announcement (including its attachments
and keyboards). The row stays stored and unread, gate requests and TUI access are
unchanged, direct Telegram command replies still work, and already-sent messages are
left alone. Suppression is evaluated at each outbound poll: it does not mutate the
notification or advance the delivery cursor, so a later eligible row still advances the
cursor normally and removing the rule may make older unread rows ahead of the cursor
eligible again. There is no suppression ledger or backfill.

Example: keep Beads rows in SASE without sending them to Telegram:

```yaml
ace:
  notification_rules:
    - name: quiet-task-beads-telegram
      description: Keep Beads notifications in SASE without sending them to Telegram.
      match:
        tab: beads
      telegram: false
```

#### Inspecting rules

- `sase notify rules` prints the merged rules in the order they are consulted, with the
  config layer each came from, its criteria, and the behaviors it sets. Entries that
  were dropped as malformed are listed with the reason.
- `sase notify rules --explain <id>` (`-e`) takes a stored notification ID or unique
  prefix and prints the fields the rules match on, then for `toast`, `sound`, and
  `telegram` the rule that decided it or that the default applied. Telegram is reported
  as rule permission/suppression, not a guarantee that Telegram is enabled or that a
  message was sent. Add `-j/--json` to either form for machine-readable output.
- `sase doctor -C config.notification_rules` flags unknown keys, a `match` that is not a
  mapping, a glob with an unclosed `[`, an empty criterion list, a `sound` file that
  does not exist, a sound file with no audio player available on this platform, and a
  rule that sets neither `toast`, `sound`, nor `telegram`.

## Related

- [Notification types](notification-types.md)
- [Notification tags](notification-tags.md)
- [Notification CLI](notification-cli.md)
- [Command-backed interaction gates](notification-gates.md)
- [Notification storage](notification-storage.md)
