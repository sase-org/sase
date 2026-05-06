---
plan: sdd/tales/202605/dedup_feedback_timestamps.md
---
 It looks like the "FBACK" timestamps are duplicated (see the `sase ace` snapshot below). I only gave feedback
once, not twice. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (11 x6)  │  AXE (8)                                                                                                                                                      CODEX(gpt-5.5)  ■ IDLE  ✉ 9+6
 Agents: 1/17   [view: file]   [group: by status (o)]   (auto-refresh in 10s)
┌─ (untagged) · 6 ────────────────────────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running                                ││                                                                                                                           │
│  │  sase (PLAN APPROVED) ×7 @ado.plan              7m28s                                ││  AGENT DETAILS                                                                                                            │
│  │  sase (PLAN APPROVED) ×7 @adm.plan             13m50s                                ││                                                                                                                           │
│                                                                                         ││  Project: sase                                                                                                        ▇▇  │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                               ││  Workspace: #100                                                                                                          │
│  │  sase (WAITING) @adl                                                                 ││  Embedded Workflows: gh(gh_ref=sase)                                                                                      │
│                                                                                         ││  Model: CODEX(gpt-5.5)                                                                                                    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents                                ││  VCS: GitHub                                                                                                              │
│  │  sase (PLAN DONE) ×6 @adn.plan                 11m08s                                ││  PID: 1760038                                                                                                             │
│  │  ▎ adk ────────────────────────────────────  2 agents                                ││  Name: @ado.plan                                                                                                          │
│  │  │  ▸ adk.r1 ──────────────────────────────  2 agents                                ││  Timestamps: BEGIN | 2026-05-06 00:12:45                                                                                  │
│  │  │  sase (DONE) ×7 @adk.r1          May 5 23:59 · 10m                                ││              PLAN  | 2026-05-06 00:15:18                                                                                  │
│  │  │  sase (DONE) ×7 @adk.r1.r1        00:05:25 · 5m11s                                ││              FBACK | 2026-05-06 00:16:35                                                                                  │
│                                                                                         ││              FBACK | 2026-05-06 00:16:35                                                                                  │
│                                                                                         ││              PLAN  | 2026-05-06 00:19:33                                                                                  │
│                                                                                         ││                                                                                                                           │
│                                                                                         │└──────────────────────────────────────────────── ● files [2/2]  ○ thinking ────────────────────────────────────────────────┘
│                                                                                         │┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         ││                                                                                                                           │
│                                                                                         ││  /home/bryan/.sase/plans/202605/active_workflow_runtime_ticks.md                                                          │
│                                                                                         ││                                                                                                                           │
│                                                                                         ││     1 # Active Workflow Runtime Ticks                                                                                     │
│                                                                                         ││     2                                                                                                                     │
│                                                                                         ││     3 ## Context                                                                                                          │
│                                                                                         ││     4                                                                                                                     │
│                                                                                         ││     5 The Agents tab currently updates visible runtime suffixes once per second through                                   │
│                                                                                         ││     6 `AgentList.patch_active_runtime_rows()`. That path is intentionally cosmetic: it patches only visible rows and      │
│                                                                                         ││       falls                                                                                                               │
│                                                                                         ││     7 back to the next full refresh if a row cannot be patched in place.                                                  │
│                                                                                         ││     8                                                                                                                     │
│                                                                                         ││     9 The current eligibility predicate only treats direct active rows as ticking:                                        │
│                                                                                         ││    10                                                                                                                     │
│                                                                                         ││    11 - `RUNNING`                                                                                                         │
│                                                                                         ││    12 - `RETRYING`                                                                                                        │
│                                                                                         ││    13 - `WAITING` after `run_start_time`                                                                                  │
│                                                                                         ││    14                                                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘│    15 This misses parent entries whose displayed status is active because they contain an active follow-up/agent step.    │
┌─ @sase-42 · 11 ─────────────────────────────────────────────────────────────────────────┐│       The                                                                                                                 │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││    16 important cases are plan-chain parents such as `PLAN APPROVED`, `EPIC APPROVED`, `LEGEND APPROVED`, and             │
│  │  ▎ sase-42 ────────────────────────────────────────────────  2 agents · 2 running    ││    17 `PLAN COMMITTED`. Those parents are often loaded from a completed planner `done.json`, so they can have a fixed     │
│  │  │  ▸ sase-42.4 ───────────────────────────────────────────  2 agents · 2 running    ││    18 `stop_time`; simply adding their statuses to the patch predicate would still render the old finished planner        │
│  │  │  ⚡ sase (RUNNING) ×4 ◆ sase-42.4.4 @sase-42 @sase-42.4.4                   5m    ││       duration                                                                                                            │
│  │  │  ⚡ sase (RUNNING) ×4 ◆ sase-42.4.3 @sase-42 @sase-42.4.3                5m11s    ││    19 rather than a live active child runtime.                                                                            │
│                                                                                         ││    20                                                                                                                     │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agent    ││    21 ## Goal                                                                                                             │
│  │  sase (WAITING) @sase-42 @acw                                                        ││    22                                                                                                                     │
│  │  ▎ sase-42 ────────────────────────────────────────────────────────────  5 agents    ││    23 Make the Agents tab runtime suffix tick once per second for every visible agent/workflow row that has active        │
│  │  │  ⚡ sase (WAITING) ◆ sase-42 @sase-42 @sase-42                                    ││       running                                                                                                             │
│  │  │  ⚡E sase (WAITING) ◆ sase-42.6.0 @sase-42 @sase-42.6.0                           ││    24 work underneath it, including parent rows displayed as `PLAN APPROVED`, `EPIC APPROVED`, and related active         │
│  │  │  ⚡E sase (WAITING) ◆ sase-42.5.0 @sase-42 @sase-42.5.0                           ││       handoff                                                                                                             │
│  │  │  ▸ sase-42.4 ───────────────────────────────────────────────────────  2 agents    ││    25 states.                                                                                                             │
│  │  │  sase (WAITING) ◆ sase-42.4 @sase-42 @sase-42.4                                   ││    26                                                                                                                     │
│  │  │  ⚡ sase (WAITING) ◆ sase-42.4.6 @sase-42 @sase-42.4.6                            ││    27 ## Design                                                                                                           │
│                                                                                         ││    28                                                                                                                     │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││    29 Centralize the row-runtime semantics in `src/sase/ace/tui/models/agent_time.py` so the renderer, render cache,      │
│  │  ▎ sase-42 ────────────────────────────────────────────────────────────  3 agents    ││       and patch                                                                                                           │
│  │  │  ▸ sase-42.4 ───────────────────────────────────────────────────────  3 agents    ││    30 eligibility agree.                                                                                                  │
│  │  │  ⚡ sase (DONE) ×5 ◆ sase-42.4.2 @sase-42 @sase-42.4.2       00:14:59 · 10m39s    ││                                                                                                                           │
│  │  │  ⚡ sase (DONE) ×5 ◆ sase-42.4.5 @sase-42 @sase-42.4.5        00:04:01 · 8m41s    ││    ▾ 49 more lines below                                                                                                  │
│  │  │  ⚡E sase (EPIC CREATED) ×6 @sase-42 @sase-42.4.0.plan     May 5 23:56 · 6m55s    ││                                                                                                                           │
└─────────────────────────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────── Lines 1-30 of 79 ─────────────────────────────────────────────────────┘
 a approve  n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (6 done)                                                                                                           RUNNING
```