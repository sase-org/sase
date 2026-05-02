---
plan: sdd/tales/202605/waiting_agents_stuck_maintenance.md
---
 It looks like `sase axe` is not starting WAITING agents when the agents they were waiting for complete (see the `sase ace` snapshot below). Can you help me diagnose the root cause of this issue
and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (19 x8)  │  AXE (8)                                                                                                                                        Override CODEX(gpt-5.5) 30h30m  ■ IDLE  ✉ 7
 Agents: 24/27   [view: file]   [group: by status (o)]   (auto-refresh in 2s)
┌─ (untagged) · 27 ──────────────────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                                                                    │
│  │  sase (PLAN APPROVED) ×6 @ss.plan                                  2m26s    ││  AGENT DETAILS                                                                                                                     │
│  │  ⚡ sase (RUNNING) ×4 ◆ redacted-plan-b.3 @redacted-plan-b.3                       1m59s    ││                                                                                                                                    │
│                                                                                ││  Project: sase                                                                                                                     │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  17 agent    ││  Model: CODEX(gpt-5.5)                                                                                                             │
│  │  sase (WAITING) @sr                                                         ││  VCS: GitHub                                                                                                                       │
│  │  ▸ sase-1r ───────────────────────────────────────────────────  8 agents    ││  Mode: ⚡ Auto-Approve                                                                                                             │
│  │  ⚡ sase (WAITING) ◆ sase-1r @sase-1r.land                                  ││  PID: 756923                                                                                                                       │
│  │  ⚡ sase (WAITING) ◆ sase-1r.9 @sase-1r.9                                   ││  Name: @sase-1r.3                                                                                                                  │
│  │  ⚡ sase (WAITING) ◆ sase-1r.8 @sase-1r.8                                   ││  Bead: sase-1r.3                                                                                                                   │
│  │  ⚡ sase (WAITING) ◆ sase-1r.7 @sase-1r.7                                   ││  Waiting for: sase-1r.2                                                                                                            │
│  │  ⚡ sase (WAITING) ◆ sase-1r.6 @sase-1r.6                                   ││  Timestamps: WAIT  | 2026-05-01 13:04:00                                                                                           │
│  │  ⚡ sase (WAITING) ◆ sase-1r.5 @sase-1r.5                                   ││                                                                                                                                    │
│  │  ⚡ sase (WAITING) ◆ sase-1r.4 @sase-1r.4                                   ││  ──────────────────────────────────────────────────                                                                                │
│  │  ⚡ sase (WAITING) ◆ sase-1r.3 @sase-1r.3                                   ││                                                                                                                                    │
│  │  ▸ redacted-plan-a ───────────────────────────────────────────────────  4 agents    ││  AGENT XPROMPT                                                                                                                     │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-a @redacted-plan-a.land                                  ││                                                                                                                                    │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-a.6 @redacted-plan-a.6                                   ││  #gh:sase                                                                                                                          │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-a.5 @redacted-plan-a.5                                   ││  %name:sase-1r.3                                                                                                                   │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-a.4 @redacted-plan-a.4                                   ││  %approve                                                                                                                          │
│  │  ▸ redacted-plan-b ───────────────────────────────────────────────────  4 agents    ││  %w:sase-1r.2                                                                                                                      │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-b @redacted-plan-b.land                                  ││  #bd/work_phase_bead:sase-1r.3                                                                                                     │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-b.6 @redacted-plan-b.6                                   ││                                                                                                                                    │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-b.5 @redacted-plan-b.5                                   ││  ──────────────────────────────────────────────────                                                                                │
│  │  ⚡ sase (WAITING) ◆ redacted-plan-b.4 @redacted-plan-b.4                                   ││                                                                                                                                    │
│                                                                                ││  AGENT PROMPT                                                                                                                      │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8 agents    ││                                                                                                                                    │
│  │  sase (DONE) ×5 @sh                                     13:26:22 · 1m58s    ││  No prompt file found.                                                                                                             │
│  │  sase (PLAN DONE) ×7 @ma.code.r1.code.r1.code.r1.plan   13:08:21 · 8m48s    ││                                                                                                                                    │
│  │  ▸ sase-1r ───────────────────────────────────────────────────  2 agents    ││                                                                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1r.2 @sase-1r.2              13:37:53 · 14m33s    ││                                                                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1r.1 @sase-1r.1              13:23:01 · 19m03s    ││                                                                                                                                    │
│  │  ▸ redacted-plan-a ───────────────────────────────────────────────────  2 agents    ││                                                                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ redacted-plan-a.3 @redacted-plan-a.3              13:36:14 · 15m35s    ││                                                                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ redacted-plan-a.2 @redacted-plan-a.2               13:20:31 · 9m51s    ││                                                                                                                                    │
│  │  ▸ redacted-plan-b ───────────────────────────────────────────────────  2 agents    ││                                                                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ redacted-plan-b.2 @redacted-plan-b.2               13:33:25 · 6m26s    ││                                                                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ redacted-plan-b.1 @redacted-plan-b.1              13:26:45 · 11m29s    ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
│                                                                                ││                                                                                                                                    │
└────────────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────── ○ files  ○ thinking ────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```