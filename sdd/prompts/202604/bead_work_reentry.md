---
plan: sdd/tales/202604/bead_work_reentry.md
---
 Can you help me improve our epic bead integration so that the `sase bead work <epic_bead_id>` can be invoked multiple times for the same `<epic_bead_id>`? When invoked, `sase axe` (via a chop or
however we do it now) should spin up agents only for the phase beads that are still open. This will be useful to recover from errors (ex: if the CLI agent I was using had an authentication issue that
caused the previous phase agents to fail). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
