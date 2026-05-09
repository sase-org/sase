---
plan: sdd/tales/202605/agents_count_header_format.md
---
 Can you help me change the form of the agent counts shown at the top of the the "Agents" tab of the `sase ace`
TUI? For example, in the below `sase ace` snapshot, we should change
`Agents(9): 1 running · 1 waiting · 0 unread · 7 read` to `9 Agents [1 running · 1 waiting · 0 unread · 7 read]`. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (2 x7)  │  AXE (8)                                                                                                                                                         CODEX(gpt-5.5)  ■ IDLE  ✉ 2
 Agents(9): 1 running · 1 waiting · 0 unread · 7 read   [view: file]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 6 ────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running     ││                                                                                                                                                   │
│  │  sase (PLAN APPROVED) ×6 @b3.plan               🏃‍♂️ 2m57s     ││  AGENT DETAILS                                                                                                                                    │
│                                                                 ││                                                                                                                                                   │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent    ││  Project: sase                                                                                                                                    │
│  │  sase (WAITING) @b3.r1                                       ││  Model: CLAUDE(opus)                                                                                                                              │
│                                                                 ││  VCS: GitHub                                                                                                                                      │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents     ││  PID: 107966                                                                                                                                      │
│  │  sase (PLAN DONE) ×8 @by.code.r1.plan   13:14:10 · 9m46s     ││  Name: @b3.r1                                                                                                                                     │
│  │  sase (PLAN DONE) ×6 @b1.plan          13:11:17 · 10m30s     ││  Waiting for: b3                                                                                                                                  │
│  │  sase (PLAN DONE) ×6 @b0.plan           13:02:57 · 4m25s     ││  Timestamps: WAIT  | 2026-05-09 13:17:09                                                                                                          │
│  │  sase (PLAN DONE) @260509.by.plan      12:56:09 · 10m29s     ││                                                                                                                                                   │
│                                                                 ││  ──────────────────────────────────────────────────                                                                                               │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  AGENT XPROMPT                                                                                                                                    │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  #gh:sase #resume:b3 %w:b3 Can you help me make sure the previous agent actually fixed this issue? Use `gh` to make sure the docs were            │
│                                                                 ││  deployed properly. %m:opus                                                                                                                       │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  ──────────────────────────────────────────────────                                                                                               │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  AGENT PROMPT                                                                                                                                     │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  No prompt file found.                                                                                                                            │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
└─────────────────────────────────────────────────────────────────┘│                                                                                                                                                   │
                                                                   │                                                                                                                                                   │
┌─ #blog · 3 ─────────────────────────────────────────────────────┐│                                                                                                                                                   │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││                                                                                                                                                   │
│  │  ▎ 260507 ─────────────────────────────────────  3 agents    ││                                                                                                                                                   │
│  │  │  ▸ 260507.ajh ──────────────────────────────  3 agents    ││                                                                                                                                                   │
│  │  │  sase (DONE) ×5 @260507.ajh           May 7 17:21 · 6m    ││                                                                                                                                                   │
│  │  │  sase (DONE) ×7 @260507.ajh.r1.r1  May 7 17:35 · 6m35s    ││                                                                                                                                                   │
│  │  │  sase (DONE) ×7 @260507.ajh.r1     May 7 17:28 · 6m51s    ││                                                                                                                                                   │
└─────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────────── ○ files  ○ thinking ───────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```