---
keyword: Proc
aliases:
  - procs
---

A Proc is a durable background process SASE records, supervises, and can stream or kill.
Procs live in `~/.sase/procs/procs.jsonl` with combined output logs and are surfaced by
`sase proc` and the Procs tab in sase's TUI. Historical proc rows may use `command`,
`tui`, or `detached` kind values, but those names are compatibility labels rather than
permanent semantic categories. Runs of service procs carry a `service` marker; the Procs
tab hides them by default. Distinct from a task bead, which is a work item, and from an
asyncio task.
