---
plan: sdd/tales/202605/plan_approved_runtime.md
---
 We aren't showing a runtime for some agent statuses that represent running agents (ex: see the "PLAN APPROVED" agent in the `sase ace` snapshot below). This agent entry should show a (incremented every 1s) runtime that is equal to the sum of two durationss: The difference between the BEGIN and PLAN timestamps + The difference between the current time and the CODE timestamp. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (3)  │  AXE (8)                                                                                                                                                          CODEX(gpt-5.5)  ■ IDLE  ✉ 1+0
 Agents: 3/3   [view: file]   [group: by status (o)]   (auto-refresh in 2s)
┌─ (untagged) · 3 ───────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▲ Needs Attention ━━━━━━━━━━━━━━  1 agent · 1 awaiting    ││                                                                                                                                                        │
│  │  sase (PLANNING) ×5 @aeu            10:24:44 · 1m53s    ││  AGENT DETAILS                                                                                                                                         │
│                                                            ││                                                                                                                                                        │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││  Project: sase                                                                                                                                         │
│  │  sase (RUNNING) ×4 @afk                       🏃‍♂️ 24s    ││  Workspace: #100                                                                                                                                       │
│  │  sase (PLAN APPROVED) ×6 @aed.plan                      ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                                   │
│                                                            ││  Model: CODEX(gpt-5.5)                                                                                                                                 │
│                                                            ││  VCS: GitHub                                                                                                                                           │
│                                                            ││  PID: 1157715                                                                                                                                          │
│                                                            ││  Name: @aed.plan                                                                                                                                       │
│                                                            ││  Timestamps: BEGIN | 2026-05-07 10:20:17                                                                                                               │
│                                                            ││              PLAN  | 2026-05-07 10:24:34                                                                                                               │
│                                                            ││              CODE  | 2026-05-07 10:25:17                                                                                                               │
│                                                            ││                                                                                                                                                        │
│                                                            ││  ──────────────────────────────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  AGENT XPROMPT                                                                                                                                         │
│                                                            ││                                                                                                                                                        │
│                                                            ││  #gh:sase When I startup `sase ace`, sometimes the notification panel is triggered even though I didn't use the `i` keymap. Can you help me            │
│                                                            ││  diagnose the root cause of this issue and fix it? #plan                                                                                               │
│                                                            ││                                                                                                                                                        │
│                                                            ││  ──────────────────────────────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  AGENT PROMPT                                                                                                                                          │
│                                                            ││                                                                                                                                                        │
│                                                            ││                                                                                                                                                        │
│                                                            ││  When I startup `sase ace`, sometimes the notification panel is triggered even though I didn't use the `i` keymap. Can                                 │
│                                                            ││  you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your                              │
│                                                            ││  `/sase_plan` skill before making any file changes.                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││                                                                                                                                                        │
│                                                            ││  ──────────────────────────────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  AGENT REPLY                                                                                                                                           │
│                                                            ││                                                                                                                                                        │
│                                                            ││                                                                                                                                                        │
│                                                            ││  ─── PLANNER ─── 10:20:17 ─────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  ─── 10:20:48 ────────────────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  I’ll use the `sase_plan` skill first, then inspect the startup/keymap flow enough to isolate why the notification panel opens without the `i` key.    │
│                                                            ││  After the plan is in place, I’ll make the smallest fix and verify it.                                                                                 │
│                                                            ││  ─── 10:21:01 ─────────────────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  I’ve loaded the project guidance and the plan skill. Next I’m tracing the `sase ace` startup path, notification panel widget, and keymap/config       │
│                                                            ││  handling to find what can open the panel without an explicit `i` key event.                                                                           │
│                                                            ││  ─── 10:22:05 ─────────────────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  The startup path doesn’t intentionally open notifications; it only initializes counts and polls/toasts later. I’m now checking raw key dispatch       │
│                                                            ││  and modal behavior, because this looks like a startup key event being interpreted as `show_notifications` rather than notification polling opening    │
│                                                            ││  the panel itself.                                                                                                                                     │
│                                                            ││  ─── 10:24:11 ─────────────────────────────────────                                                                                                ▆▆  │
│                                                            ││                                                                                                                                                        │
│                                                            ││  The leading root-cause candidate is the active Kitty graphics probe. It writes a terminal query before Textual owns stdin; the reply contains         │
│                                                            ││  `i=31337`, and if any reply bytes land after the short drain window, Textual can see `i` as a normal keybinding and open notifications. I’m           │
│                                                            ││  writing the plan now, then I’ll submit it with `sase plan` before changing code.                                                                      │
│                                                            ││  ─── CODER ─── 10:25:17 ───────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
│                                                            ││  ─── 10:25:27 ─────────────────────────────────────                                                                                                    │
│                                                            ││                                                                                                                                                        │
└────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────────── ○ files  ○ thinking ──────────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```