---
plan: sdd/plans/202604/fix_prometheus.md
---
I am unable to use the `sase telemetry dashboard` command's `-c` option on this machine (see below). Can you help me
diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your
`/sase_plan` skill before making any file changes.

```
Prometheus is not reachable — falling back to summary mode.
Telemetry Dashboard [summary] — refreshing every 5s — Ctrl+C to exit
Telemetry Dashboard [summary] — refreshing every 5s — Ctrl+C to exit

╭─── Active Agents ────╮ ╭─ Active Workspaces ──╮ ╭──── Active Beads ────╮
│          0           │ │          0           │ │          0           │
│  :          0        │ │  :          0        │ │  :          0        │
│                      │ │                      │ │                      │
│                      │ │                      │ │                      │
╰──────────────────────╯ ╰──────────────────────╯ ╰──────────────────────╯

╭──────── Axe Orchestrator ────────╮                                               ╭── Hooks / Mentors / Workflows ───╮                                               ╭───────── Notifications ──────────╮
│ Axe Lumberjack                 0 │                                               │ Zombie                         0 │                                               │ Notifications                  2 │
│ Restarts                         │                                               │ Detections                       │                                               │ Sent                             │
│ Axe Lumberjacks                0 │                                               ╰──────────────────────────────────╯                                               ╰──────────────────────────────────╯
│ Active                           │
╰──────────────────────────────────╯

Dashboard stopped.

```
