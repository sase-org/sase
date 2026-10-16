---
title: Notifications modal
description: The notifications modal, snooze scheduling, notification actions, and toasts.
---

# Notifications modal

This page lists the notifications modal, snooze scheduling, notification actions, and
toasts.

## Notifications Modal {#notifications-modal-1}

Press `i` to open the notifications modal. On the Agents tab, `Enter` opens the selected
agent's pending gate or Patch directly, without the modal. See the
[notifications reference](../automation/notifications.md) for the full keybinding
reference, modal tabs, priority/error/muted classification, and the per-notification
snooze and mute affordances.

Rows and the detail header begin with the notification's single-glyph icon when one is
present, with a per-action fallback icon otherwise. The text action badge remains
visible as the secondary label.

Press `d` on the highlighted inbox row to open Gate Debug, even when the row is not
gate-backed or its gate modal can no longer load. The same `d` binding is available
inside plan/epic approval, user-question, launch-approval, custom-gate, and workflow
HITL panels. Gate Debug presents Overview, Request, Response, Errors, and raw Row tabs;
`[` / `]` switch tabs, `y` copies the current tab, `Y` copies the bundle path, `e` opens
the backing file, and `d`, `q`, or `Esc` closes the overlay without losing state in the
underlying panel.

The `inbox:` top-bar group renders one colored `<icon><count>` chip per
notification-panel tab, in the panel's own order and colors, or a dim `inbox: 0` when
nothing is pending. See
[Top-Bar Indicator](../automation/notifications.md#top-bar-indicator) for the
snoozed-only and overflow forms.

### Snooze Reminder Scheduling

Snooze expiry does not depend on the general refresh cadence. sase's TUI keeps at most
one timer for the nearest deadline reported by the current notification snapshot, so
reminders fire on time even with clean inotify state or `--refresh-interval 0` (which
disables ordinary auto-refresh). The timer callback stays thin and synchronous: it
compares cached wall-clock values on Textual's message pump and hands the store read to
a coalesced proc, so no disk or worker I/O runs on the pump and an expired snooze never
triggers a full Agents-list rebuild.

While any snooze is pending, sase's TUI rechecks the wall clock at most one second
apart, so a suspended host, a resumed session, or a forward/backward system-clock change
re-evaluates the authoritative UTC deadline promptly instead of waiting out a monotonic
timer. Startup reconciliation, notification-file watcher events, ordinary polling, and
modal snooze/resnooze/unmute/dismiss completions all route through the same coalescing
guard, so an external mutation can replace or cancel the cached nearest deadline
immediately. The coordinator starts after first paint and its timer and task are
cancelled during normal and controlled teardown.

Once due, sase's TUI performs one current-state snapshot read, applies counts, toasts,
and status projections, then schedules the next future deadline. Each observed resurface
batch produces toasts (one per row, or grouped per severity when more than three rows
arrive together) and at most one tmux bell, unless a
[delivery rule](../automation/notifications.md#delivery-rules) overrides it —
including rows that were marked read while snoozed — and no repeat on later polls.
Cancelled, dismissed, permanently muted, and not-yet-due rows never ring. If another
process wins the expiry, the persisted unread state and `resurfaced_at` still make the
transition observable here. Resurfaced rows sort as recent activity in the modal while
continuing to display their original sent time. See the
[notifications reference](../automation/notifications.md#snooze-expiry-and-resurfacing)
for the full state and timing contract.

## Notification Actions

Some notifications carry an `action` field that triggers a handler when the notification
is selected. The following notification action types are supported:

| Action                | Source          | Behavior                                                                                                                                                                                               |
| --------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `CustomGate`          | Agent/tool      | Opens the generic choices, add-ons, and feedback modal                                                                                                                                                 |
| `GateExecutionFailed` | Gate executor   | Opens the resume / restart / cancel dialog, or the error report when none applies                                                                                                                      |
| `HITL`                | Workflow        | Opens the workflow human-in-the-loop response modal                                                                                                                                                    |
| `JumpToAgent`         | Agent/workflow  | Jumps to the matching Agents-tab row, revealing it first like the Node Finder: expands collapsed folds, grouping banners, and panels; shows `I`-hidden rows; clears a hiding Agents query with a toast |
| `JumpToPatch`         | Sync/workflow   | Jumps to the referenced Patch on the Patches sub-tab                                                                                                                                                   |
| `JumpToMentorReview`  | Mentors         | Jumps to the Patch and opens mentor review output when available                                                                                                                                       |
| `LaunchApproval`      | Agent           | Opens the launch approval modal for an agent-requested launch                                                                                                                                          |
| `OpenToolRun`         | Tool run        | Selects the settled run's Agents-tab node with its ⚒ Runs card active and the run's block selected, or opens Admin Center → Tools focused on the run                                                   |
| `PlanApproval`        | Agent           | Opens the plan approval modal                                                                                                                                                                          |
| `RemoteAttention`     | Remote machine  | Opens the remote question or gate modal and submits to the owning machine                                                                                                                              |
| `SudoRequest`         | Agent           | Opens the [sudo review modal](../automation/sudo.md#review-ux); approving runs in a terminal                                                                                                    |
| `Tmux`                | External bridge | Runs `tm <workspace-name>` for the notification's `action_data.workspace_dir`                                                                                                                          |
| `UserQuestion`        | Agent           | Opens the structured user-question response modal                                                                                                                                                      |
| `ViewErrorReport`     | Axe/agent       | Opens `action_data.error_report_path`, or the first attached file, in `$EDITOR`                                                                                                                        |

The axe `error_digest` job creates `ViewErrorReport` notifications whose digest files
live under `~/.sase/axe/error_digests/digest_<timestamp>.txt`; user-agent failures can
use the same action for their own attached error reports.

The custom-gate modal shows the sender and notes or verified preview, one icon-led
button per terminal choice, and checkboxes for that choice's independently selectable
add-on commands. The Decision column holds those controls only; an option that declares
typed input wears a dim `✎ n inputs` badge and collects those values in the dedicated
input panel instead (see [Remapping Gate Modal Keys](global-controls.md#remapping-gate-modal-keys)).
Required feedback also opens that panel, whose submit stays blocked until non-empty text
is present; optional feedback still answers in one keystroke and is attached by pressing
`i` first, and disabled feedback shows no note field at all. Unsupported future actions
produce a warning instead of silently doing nothing.

Custom gates and neutral HITL gates execute through the shared hash-verifying gate
executor. sase's TUI schedules the terminal command and each selected add-on through the
tracked proc queue, streams live stdout/stderr to the proc, shows each command as a
reporter phase, and refreshes the inbox when the proc completes. Older HITL bundles
retain the direct response-file fallback; see
[TUI migration notes](../upgrading/tui.md#hitl-and-launch-request-fallbacks).

### Toast Notifications

Each newly-arrived notification produces a short toast in the TUI. The toast text is
derived per-action type (plan, question, HITL, axe error, Patch sync, agent update) so
the message previews the actual event rather than a generic "N new notification(s)"
line. Severity is also picked per type: plans, questions, and HITL render as warnings;
axe errors (and sync failures) render as errors; everything else renders as information.

A genuinely new tale or epic plan review rings the terminal bell on arrival (one bell
announcement, sent as three short tmux beeps) and remains visually prominent as a
warning toast and priority inbox row. Already-answered plan reviews discovered during
polling and the post-approval coder or epic handoff stay silent. Questions, other
audible notification classes, and explicit snooze-expiry reminders retain their existing
bell behavior; snoozing a plan review therefore still produces the requested reminder
bell when it expires.

These are defaults.
[`ace.notification_rules`](../automation/notifications.md#delivery-rules) can
suppress a toast or replace the bell with a sound file or silence for any notification,
including snooze-expiry reminders; rows whose toast is suppressed are left out of the
grouped-toast count.

When more than 3 notifications arrive in the same poll tick, per-notification toasts are
consolidated into one grouped toast per severity bucket (e.g.,
`2 warnings: 1 plan, 1 question`). Ordering is urgency-first: errors, then warnings,
then information. Silent notifications are excluded from this pipeline entirely.

Agent completion and failure toasts include the `%id`-set agent name with an `@` prefix
when present (e.g., `CLAUDE(opus) @sase-q.land completed: ace(run)-...`); anonymous
agents (no `agent_name`) keep the prior format.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Notifications](../automation/notifications.md) — notification types, tags, and CLI.
- [Global controls](global-controls.md) — keys, palette, command line, refresh.
- [TUI migration notes](../upgrading/tui.md) — HITL response-file fallback.
