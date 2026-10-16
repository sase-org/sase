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
`notifications.jsonl` crosses 4 MiB or holds at least 1,000 dismissed rows, a
cache-missing read or rewrite may still compact under the same exclusive lock: dismissed
rows older than a 3-day retention window are appended to a sibling
`notifications-archive.jsonl` and dropped from the live file, then the live file is
replaced atomically so a crash mid-compaction loses no row. Snoozed rows are never
archived while snoozed, and dismissed rows inside the retention window stay put so the
inbox UI's `include_dismissed` view is unchanged. Unread and still-actionable rows stay
in the live file. `sase logs pack` reads the archive alongside the live file, so a
window older than the retention period still packs complete.

The Rust store also owns every temporal semantic: it validates and normalizes snooze
deadlines, expires due rows atomically under the same lock as the read, stamps
`resurfaced_at`, and reports both `expired_ids` and the earliest remaining
`next_snooze_deadline` alongside the projected counts. Consumers schedule their timers
from that projected deadline instead of polling. Concurrent expiring readers converge on
one store state without losing appended rows.

Source: `src/sase/notifications/`

## Related

- [Notifications](notifications.md)
