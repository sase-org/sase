---
plan: sdd/tales/202605/agent_header_file_hints.md
---
 Do you see how, in the below `sase ace` snapshot, ~/.sase/plans/202605/wait_requires_success.md doesn't have a hint next to it despite the fact that I had just used the `v` keymap? Can you help
me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (8 x13)  │  AXE (8)                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 14
 Agents: 3/21   [view: collapsed]   [group: by date (o)]   (auto-refresh in 2s)
┌─ (untagged) · 6 ──────────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents                   ││                                                                                                                                         │
│  │  ▎ 19:00 ─────────────────────────────────  3 agents                   ││  AGENT DETAILS                                                                                                                          │
│  │  │  sase (PLAN DONE) ×6 @afc.plan  19:36:01 · 11m30s                   ││                                                                                                                                         │
│  │  │  sase (PLAN DONE) ×7 @afb.plan  19:32:06 · 15m15s                   ││  Project: sase                                                                                                                          │
│  │  │  sase (WAITING) @aez                                                ││  Workspace: #101                                                                                                                        │
│  │  ▎ 12:00 ─────────────────────────────────  3 agents                   ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                    │
│  │  │  sase (WAITING) @aed.r1.r1                                          ││  Model: CODEX(gpt-5.5)                                                                                                                  │
│  │  │  sase (WAITING) @aed.r1                                             ││  VCS: GitHub                                                                                                                            │
│  │  │  sase (WAITING) @aed                                                ││  PID: 2571006                                                                                                                           │
│                                                                           ││  Name: @afb.plan                                                                                                                        │
│                                                                           ││  Timestamps: BEGIN | 2026-05-06 19:16:51                                                                                                │
│                                                                           ││              PLAN  | 2026-05-06 19:19:27                                                                                                │
│                                                                           ││              FBACK | 2026-05-06 19:21:24 | ~/.sase/plans/202605/wait_requires_success.md                                                │
│                                                                           ││              PLAN  | 2026-05-06 19:23:56                                                                                                │
│                                                                           ││              CODE  | 2026-05-06 19:25:23                                                                                                │
│                                                                           ││              END   | 2026-05-06 19:32:06                                                                                                │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  Commit Message: fix: require successful wait dependencies                                                                              │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  ──────────────────────────────────────────────────                                                                                 ▇▇  │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  AGENT XPROMPT                                                                                                                          │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  #gh:sase If I kill an agent that another agent is waiting for (using the `%wait` directive), that waiting agent will be                │
│                                                                           ││  launched. Can you help me change this so the agent keeps waiting until all agents it is waiting for complete                           │
│                                                                           ││  successfully? #plan                                                                                                                    │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  ──────────────────────────────────────────────────                                                                                     │
└───────────────────────────────────────────────────────────────────────────┘│                                                                                                                                         │
                                                                             │  AGENT PROMPT                                                                                                                           │
┌─ @chop · 1 ───────────────────────────────────────────────────────────────┐│                                                                                                                                         │
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent              ││  If I kill an agent that another agent is waiting for (using the `%wait` directive), that waiting agent will be launched.               │
│  │  ▎ 19:00 ───────────────────────────────────────  1 agent              ││  Can you help me change this so the agent keeps waiting until all agents it is waiting for complete successfully? Think                 │
│  │  │  [agent] refresh_docs (DONE) ×7 @afd  19:41:12 · 7m53s              ││  this through thoroughly and create a plan using your `[1] /sase_plan` skill before making any file changes.                            │
└───────────────────────────────────────────────────────────────────────────┘│                                                                                                                                         │
                                                                             │                                                                                                                                         │
┌─ @mobile · 1 ─────────────────────────────────────────────────────────────┐│  ──────────────────────────────────────────────────                                                                                     │
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                              ││                                                                                                                                         │
│  │  ▎ 17:00 ───────────────────────  1 agent                              ││  AGENT REPLY                                                                                                                            │
│  │  │  sase (DONE) ×5 @aeu  17:55:53 · 1m06s                              ││                                                                                                                                         │
└───────────────────────────────────────────────────────────────────────────┘│  ─── PLANNER ─── 19:16:51 ─────────────────────────                                                                                     │
                                                                             │  ─── 19:17:10 ─────────────────────────────────────                                                                                     │
┌─ @sase-26 · 13 ───────────────────────────────────────────────────────────┐│  I’ll use the `sase_plan` skill as requested, then inspect the relevant scheduling/wait code and memory before drafting the plan. No    │
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  13 agents · 1 running    ││  file changes until the plan is in place.                                                                                               │
│  │  ▎ 19:00 ────────────────────────────────────────────────  2 agents    ││                                                                                                                                         │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.3              19:34:52 · 53m55s    ││  ─── 19:17:17 ─────────────────────────────────────                                                                                     │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.6              19:05:42 · 10m33s    ││  The plan skill only requires a written plan file plus `sase plan`. I’m now tracing `%wait` parsing and launch behavior so the plan     │
│  │  ▎ 18:00 ────────────────────────────────────  9 agents · 1 running    ││  addresses the actual lifecycle path rather than guessing from names.                                                                   │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.5              18:54:46 · 11m05s    ││                                                                                                                                         │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.7              18:43:23 · 15m01s    ││  ─── 19:17:37 ─────────────────────────────────────                                                                                     │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.4              18:41:47 · 13m17s    ││  The main runner waits on a `ready.json` marker, and that marker is produced outside the runner by a “wait checks” chop script. I’m     │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.2              18:40:47 · 12m19s    ││  reading that producer next, because the fix likely belongs where dependency success is decided rather than where the waiter merely     │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.8              18:39:25 · 11m17s    ││  polls.                                                                                                                                 │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.1              18:28:02 · 17m18s    ││                                                                                                                                         │
│  │  │  ⚡E sase (EPIC CREATED) ×6 @sase-26.6.0.plan  18:13:21 · 12m23s    ││  ─── 19:18:17 ─────────────────────────────────────                                                                                     │
│  │  │  ⚡ sase (WAITING) ◆ @sase-26.6                                     ││  The bug is shaping up as a semantic mismatch: `wait_checks` treats “has any done marker” as dependency satisfaction, while agent       │
│  │  │  ⚡ sase (RUNNING) ×4 ◆ @sase-26.6.9                    🏃‍♂️ 6m20s    ││                                                                                                                                         │
│  │  ▎ 09:00 ────────────────────────────────────────────────  2 agents    │└─────────────────────────────────────────────────────── ● files [1/2]  ○ thinking ───────────────────────────────────────────────────────┘
│  │  │  ⚡ sase (WAITING) ◆ @sase-26                                       │┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  │  │  ⚡E sase (WAITING) ◆ @sase-26.7.0                                  ││ View:   1-5 or 3@ (@ to edit) or 3% (% to copy path)                                                                             cancel │
└───────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (13 done)                                                                                                                     RUNNING

 ^e End/Fill  ^d Scroll Down  ^u Clear to start  ^f Forward  ^b Backward  esc Cancel

```