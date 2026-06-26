---
plan: sdd/tales/202606/update_dedup_plugin_rows.md
---
  We seem to show the same plugin repos multiple times in the `sase update` command's output (see below). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

```
❯ sase update
╭───────────────────────────────────── SASE Update ─────────────────────────────────────╮
│ ·    sase             0.5.0     (already current)                                     │
│ ·    sase-core-rs     0.2.0     (already current)                                     │
│ ·    sase-github      0.1.2     (already current)                                     │
│ ·    sase-telegram    0.1.3     (already current)                                     │
│ ·    sase-github      0.1.2     (already current)                                     │
│ ·    sase-telegram    0.1.3     (already current)                                     │
│ ✗    maturin          1.14.1    (removed)                                             │
│                                                                                       │
│ Updated packages in 39s · 6 already current · 1 package removed                       │
│ Restart running sase agents to pick up the new version.                               │

```