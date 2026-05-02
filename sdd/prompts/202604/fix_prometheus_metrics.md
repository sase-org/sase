---
plan: sdd/tales/202604/fix_prometheus_metrics.md
---
Something seems wrong with the way we track and/or display prometheus metrics related to agent invocations. For example,
no data is ever displayed in the "Agent Run Duration" chart and the `sase telemetry dashboard` (see below) shows just 1
LLM invocation in the last 7 days, which I know is wrong. Can you help me diagnose the root cause of this issue and fix
it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```

bryan in 🌐 athena in sase on  master [!] is 📦 v0.1.0 via 🐍 v3.10.18 took 15s
❯ sat dashboard -r 7d
Telemetry Dashboard [summary] — refreshing every 5s — Ctrl+C to exit

╭─── Active Agents ────╮ ╭─ Active Workspaces ──╮ ╭──── Active Beads ────╮
│          0           │ │          0           │ │          0           │
│  :          0        │ │  :          0        │ │  :          0        │
│                      │ │                      │ │                      │
│                      │ │                      │ │                      │
╰──────────────────────╯ ╰──────────────────────╯ ╰──────────────────────╯

╭────────── LLM Provider ──────────╮                          ╭──────── Axe Orchestrator ────────╮                          ╭── Hooks / Mentors / Workflows ───╮                          ╭───────── Notifications ──────────╮
│ Llm Cache Read             11273 │                          │ Axe Lumberjack                 0 │                          │ Zombie                         0 │                          │ Notifications                165 │
│ Tokens                           │                          │ Restarts                         │                          │ Detections                       │                          │ Sent                             │
│ Llm Input                      2 │                          │ Axe Lumberjacks                0 │                          ╰──────────────────────────────────╯                          ╰──────────────────────────────────╯
│ Tokens                           │                          │ Active                           │
│ Llm Invocations                1 │                          ╰──────────────────────────────────╯
│ Llm Output                   262 │
│ Tokens                           │
│ Llm Invocation   p50=10s p95=10s │
│ Duration                 p99=10s │
│ Seconds                          │
╰──────────────────────────────────╯



























































```
