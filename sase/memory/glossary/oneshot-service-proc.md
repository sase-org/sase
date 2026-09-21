---
keyword: Oneshot Service Proc
aliases:
  - oneshot
  - background command
---

A oneshot service proc runs once to completion and is never restarted. Transient
oneshots are created at runtime by the TUI's `!` background commands or
`sase service proc run`; they run outside the sase service's process tree, so restarting
the sase service does not kill them. Distinct from a job, which a routine runs on a
schedule.
