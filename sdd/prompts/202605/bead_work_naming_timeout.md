---
plan: sdd/plans/202605/bead_work_naming_timeout.md
---
 Can you help me figure out why `sase bead work` is timing out / failing sometimes (see below)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
❯ sase bead work sase-1r
Epic sase-1r — Rust-backed agent launch migration: 9 phase agent(s) in 9 wave(s) plus 1 land agent (sase-1r.land).
  Wave 0: sase-1r.1 → sase-1r.1
  Wave 1: sase-1r.2 → sase-1r.2
  Wave 2: sase-1r.3 → sase-1r.3
  Wave 3: sase-1r.4 → sase-1r.4
  Wave 4: sase-1r.5 → sase-1r.5
  Wave 5: sase-1r.6 → sase-1r.6
  Wave 6: sase-1r.7 → sase-1r.7
  Wave 7: sase-1r.8 → sase-1r.8
  Wave 8: sase-1r.9 → sase-1r.9
  Land waits on: sase-1r.9
Launch these agents? [y/N] y
  Agent 1/10 naming timed out, continuing
```