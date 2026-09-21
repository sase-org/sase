---
keyword: Sase Scheduler
aliases:
  - scheduler
  - AXE
---

The sase scheduler is the builtin service proc behind `sase scheduler` that runs SASE's
background automation: it starts one process per routine and restarts crashed routines,
and routines run jobs. The sase service owns the scheduler's process lifetime; the
scheduler owns only its routine/job tree. AXE is its former name and remains an accepted
alias.
