---
title: Notification storage
description: Storage behavior for SASE notifications.
---

# Notification storage

This page describes where SASE stores notification state.

## Storage

Notifications are stored in JSONL format at `~/.sase/notifications/notifications.jsonl`.
The production store backend is `sase_core_rs`: appends and state mutations take a
shared sidecar lock, and rewrites use a tempfile plus rename so multiple axe processes
and the TUI can access the file without truncate-before-lock exposure. Common state-only
updates such as mark-read, mark-all-read, mute, snooze, and dismiss use a count-only
Rust mutation path unless the caller needs rehydrated notification rows; this keeps
inbox counters cheap when sase's TUI or a bridge process only needs mutation metadata.

sase's TUI snapshot reads memoize the parsed store against the JSONL path, the
`include_dismissed` flag, and an mtime+size change token, so an unchanged live file is
not re-parsed on the TUI refresh cadence. A parsed snapshot is cached only when the
change token is the same before and after the read, so a write that lands mid-read is
picked up by the next read instead of being masked. A due `next_snooze_deadline` still
forces a re-read when the caller asked to expire snoozes.

The store keeps itself O(live). The hourly `notification_store_compact` housekeeping job
drives compaction so a multi-megabyte re-parse does not sit on an interactive path. When
`notifications.jsonl` reaches 4 MiB or holds at least 1,000 dismissed, unsnoozed rows,
archiving becomes eligible during the hourly pass, a cache-missing read, or a rewrite
under the same exclusive lock. Dismissed rows whose latest activity is older than 3 days
are appended to a sibling `notifications-archive.jsonl` and dropped from the live file,
then the live file is replaced atomically so a crash mid-compaction loses no row.
Snoozed rows are never archived while snoozed, and dismissed rows inside the retention
window stay put so the inbox UI's `include_dismissed` view is unchanged. Activity means
`resurfaced_at` when present, otherwise the creation `timestamp`. Undismissed rows stay
in the live file; the read/unread flag does not determine eligibility. `sase logs pack`
reads the archive alongside the live file, so a window older than the retention period
still packs complete.

## Oversized payloads

The Python notification-store wrappers externalize `notes` and `action_data` values
larger than 8 KiB by default. Each value is written atomically to
`~/.sase/notifications/blobs/<sha256>`, and identical values share one file. The Rust
store API remains opt-in for callers outside those wrappers.

The stored value uses the Rust-defined reference form
`sase-notification-blob:v1:<sha256>:<byte-length>`. A note keeps its first 80 characters
as a preview, followed by `…` and the reference. The notification payload resolver
passes ordinary values through unchanged, returns the full text for a valid reference,
and returns `None` when a referenced sidecar is missing. Readers can keep showing the
stored note preview when resolution reports a missing sidecar.

The hourly `notification_store_compact` pass uses the same 8 KiB limit to migrate
oversized values already in the live store. References are idempotent, so each value is
migrated once; existing archive rows are left as they are. Compaction also removes
`files` entries whose paths no longer exist and reports both counts. Sidecar garbage
collection considers references in the live JSONL and its archive, and removes only
unreferenced sidecars older than one hour. Fresh files are left in place to protect
writes that are still in flight.

Readers that need full content resolve the reference when the user asks for it. The TUI
resolves report snapshots and run-prune review data, Telegram resolves completion
prompts, notes, and attached commit messages, and `sase notify show` resolves all
payload fields. Waiter-expiry actions resolve the full waiter list; a missing sidecar
keeps the notice open. Waiter reconciliation compares resolved content so unchanged
large lists do not trigger writes. Lists and mobile notification cards can use the
stored note preview. Missing note sidecars leave that preview available; a missing
action-data sidecar has no inline value to show.

The TUI's `JumpToAgent` action uses the notification's short identity fields to select
the agent, whose prompt pane reads the full raw prompt from its artifact directory. It
does not need to hydrate the notification's duplicate prompt on inbox refresh.

Completion notifications point to the existing raw prompt file when it exactly matches
the prompt, avoiding a second copy. Failure summaries over 4 KiB are shortened and point
to their full error report.

## Snooze timing

The Rust store also owns every temporal semantic: it validates and normalizes snooze
deadlines, expires due rows atomically under the same lock as the read, stamps
`resurfaced_at`, and reports both `expired_ids` and the earliest remaining
`next_snooze_deadline` alongside the projected counts. Consumers schedule their timers
from that projected deadline instead of polling. Concurrent expiring readers converge on
one store state without losing appended rows.

Source: `src/sase/notifications/`

## Related

- [Notifications](notifications.md)
