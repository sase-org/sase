---
keyword: Proc
aliases:
  - procs
  - background task
  - background tasks
---

A Proc is a durable background process SASE records, supervises, and can stream or kill.
Procs live in `~/.sase/procs/procs.jsonl` with combined output logs and are surfaced by
`sase proc` and ACE's Procs tab. Historical proc rows may use `command`, `tui`, or
`detached` kind values, but those names are compatibility labels rather than permanent
semantic categories. Distinct from a task bead, which is a work item, and from an
asyncio task.
