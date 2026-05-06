---
plan: sdd/tales/202605/cross_panel_agent_jump.md
---
 The appostrophe ("'") keymap doesn't jump to the selected hint when it is not in the same agent panel. In the below `sase ace` snapshot, for example, when I press "3", nothing happens (I should
jump to the agent entry next to he "[3]" hint). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (13 x26)  │  AXE (8)                                                                                                                                                    CODEX(gpt-5.5)  ■ IDLE  ✉ 9+26
 Agents: 4/39   [view: file]   [group: by status (o)]   (auto-refresh in 4s)
┌─ (untagged) · 4 ───────────────────────────────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running                                    ││                                                                                                                        │
│  │  [1] sase (RUNNING) ×4 @adm                      55s                                    ││  AGENT DETAILS                                                                                                         │
│  │  [2] sase (RUNNING) ×6 @adk.r1.r1              3m07s                                    ││                                                                                                                        │
│                                                                                            ││  Project: sase                                                                                                         │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                                   ││  Model: CODEX(gpt-5.5)                                                                                                 │
│  │  [3] sase (WAITING) @adl                                                                ││  VCS: GitHub                                                                                                           │
│                                                                                            ││  Mode: ⚡ Auto-Approve                                                                                                 │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                                    ││  PID: 1661651                                                                                                          │
│  │  [4] sase (DONE) ×7 @adk.r1        May 5 23:59 · 10m                                    ││  Name: @sase-42.4.4                                                                                                    │
│                                                                                            ││  Bead: sase-42.4.4 - Thread optional artifact indicators through Agent list update, panel slicing, formatting,         │
│                                                                                            ││  render cache keys, panel width/height behavior, workflow rows, tag panels, and patch rendering using the shared       │
│                                                                                            ││  renderer while preserving highlight-only j/k refresh behavior.                                                        │
└────────────────────────────────────────────────────────────────────────────────────────────┘│  Waiting for: sase-42.4.2                                                                                              │
┌─ @sase-42 · 35 ────────────────────────────────────────────────────────────────────────────┐│  Timestamps: WAIT  | 2026-05-05 23:55:23                                                                               │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                        │
│  │  [5] ⚡ sase (RUNNING) ×4 ◆ sase-42.4.5 @sase-42 @sase-42.4.5                  8m01s    ││  ──────────────────────────────────────────────────                                                                    │
│                                                                                            ││                                                                                                                        │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  9 agent    ││  AGENT XPROMPT                                                                                                         │
│  │  [6] sase (WAITING) @sase-42 @acw                                                       ││                                                                                                                        │
│  │  ▎ sase-42 ───────────────────────────────────────────────────────────────  8 agents    ││  #gh:sase                                                                                                              │
│  │  │  [7] ⚡ sase (WAITING) ◆ sase-42 @sase-42 @sase-42                                   ││  %name:sase-42.4.4                                                                                                     │
│  │  │  [8] ⚡E sase (WAITING) ◆ sase-42.6.0 @sase-42 @sase-42.6.0                          ││  %tag:sase-42                                                                                                          │
│  │  │  [9] ⚡E sase (WAITING) ◆ sase-42.5.0 @sase-42 @sase-42.5.0                          ││  %approve                                                                                                              │
│  │  │  ▸ sase-42.4 ──────────────────────────────────────────────────────────  5 agents    ││  %w:sase-42.4.2                                                                                                        │
│  │  │  [0] sase (WAITING) ◆ sase-42.4 @sase-42 @sase-42.4                                  ││  #bd/work_phase_bead:sase-42.4.4                                                                                       │
│  │  │  [a] ⚡ sase (WAITING) ◆ sase-42.4.6 @sase-42 @sase-42.4.6                           ││                                                                                                                        │
│  │  │  [b] ⚡ sase (WAITING) ◆ sase-42.4.4 @sase-42 @sase-42.4.4                           ││  ──────────────────────────────────────────────────                                                                    │
│  │  │  [c] ⚡ sase (WAITING) ◆ sase-42.4.3 @sase-42 @sase-42.4.3                           ││                                                                                                                        │
│  │  │  [d] ⚡ sase (WAITING) ◆ sase-42.4.2 @sase-42 @sase-42.4.2                           ││  AGENT PROMPT                                                                                                          │
│                                                                                            ││                                                                                                                        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  25 agents    ││  No prompt file found.                                                                                                 │
│  │  ▎ sase-42 ──────────────────────────────────────────────────────────────  25 agents    ││                                                                                                                        │
│  │  │  [e] ⚡E sase (EPIC CREATED) ×6 @sase-42 @sase-42.4.0.plan    May 5 23:56 · 6m55s    ││                                                                                                                        │
│  │  │  ▸ sase-42.1 ──────────────────────────────────────────────────────────  8 agents    ││                                                                                                                        │
│  │  │  [f] ⚡ sase (DONE) ×5 ◆ sase-42.1 @sase-42 @sase-42.1        May 5 21:03 · 5m21s    ││                                                                                                                        │
│  │  │  [g] ⚡ sase (DONE) ×5 ◆ sase-42.1.6 @sase-42 @sase-42.1.6    May 5 20:58 · 4m50s    ││                                                                                                                        │
│  │  │  [h] ⚡ sase (DONE) ×5 ◆ sase-42.1.5 @sase-42 @sase-42.1.5    May 5 20:52 · 8m14s    ││                                                                                                                        │
│  │  │  [i] ⚡ sase (DONE) ×5 ◆ sase-42.1.3 @sase-42 @sase-42.1.3    May 5 20:44 · 9m37s    ││                                                                                                                        │
│  │  │  [j] ⚡ sase (DONE) ×5 ◆ sase-42.1.4 @sase-42 @sase-42.1.4    May 5 20:29 · 8m31s    ││                                                                                                                        │
│  │  │  [k] ⚡ sase (DONE) ×5 ◆ sase-42.1.2 @sase-42 @sase-42.1.2   May 5 20:34 · 13m37s    ││                                                                                                                        │
│  │  │  [l] ⚡ sase (DONE) ×5 ◆ sase-42.1.1 @sase-42 @sase-42.1.1   May 5 20:20 · 13m08s    ││                                                                                                                        │
│  │  │  [m] ⚡E sase (EPIC CREATED) ×6 @sase-42 @sase-42.1.0.plan    May 5 20:10 · 9m06s    ││                                                                                                                        │
│  │  │  ▸ sase-42.2 ──────────────────────────────────────────────────────────  8 agents    ││                                                                                                                        │
│  │  │  [n] ⚡ sase (DONE) ×5 ◆ sase-42.2 @sase-42 @sase-42.2        May 5 22:22 · 6m31s    ││                                                                                                                        │
│  │  │  [o] ⚡ sase (DONE) ×5 ◆ sase-42.2.6 @sase-42 @sase-42.2.6    May 5 22:15 · 8m36s    ││                                                                                                                        │
│  │  │  [p] ⚡ sase (DONE) ×5 ◆ sase-42.2.5 @sase-42 @sase-42.2.5   May 5 22:07 · 14m20s    ││                                                                                                                        │
│  │  │  [q] ⚡ sase (DONE) ×5 ◆ sase-42.2.4 @sase-42 @sase-42.2.4   May 5 21:52 · 12m43s    ││                                                                                                                        │
│  │  │  [r] ⚡ sase (DONE) ×5 ◆ sase-42.2.3 @sase-42 @sase-42.2.3   May 5 21:39 · 12m12s    ││                                                                                                                        │
│  │  │  [s] ⚡ sase (DONE) ×5 ◆ sase-42.2.2 @sase-42 @sase-42.2.2    May 5 21:27 · 7m43s    ││                                                                                                                        │
│  │  │  [t] ⚡ sase (DONE) ×5 ◆ sase-42.2.1 @sase-42 @sase-42.2.1    May 5 21:19 · 8m12s    ││                                                                                                                        │
│  │  │  [u] ⚡E sase (EPIC CREATED) ×6 @sase-42 @sase-42.2.0.plan    May 5 21:13 · 9m31s    ││                                                                                                                        │
│  │  │  ▸ sase-42.3 ──────────────────────────────────────────────────────────  8 agents    ││                                                                                                                        │
│  │  │  [v] sase (DONE) ×5 ◆ sase-42.3 @sase-42 @sase-42.3           May 5 23:49 · 5m36s    ││                                                                                                                        │
│  │  │  [w] ⚡ sase (DONE) ×5 ◆ sase-42.3.6 @sase-42 @sase-42.3.6   May 5 23:43 · 12m37s    ││                                                                                                                        │
│  │  │  [x] ⚡ sase (DONE) ×5 ◆ sase-42.3.5 @sase-42 @sase-42.3.5    May 5 23:30 · 6m05s    ││                                                                                                                        │
│  │  │  [y] ⚡ sase (DONE) ×5 ◆ sase-42.3.4 @sase-42 @sase-42.3.4    May 5 23:24 · 7m16s    ││                                                                                                                        │
│  │  │  [z] ⚡ sase (DONE) ×5 ◆ sase-42.3.3 @sase-42 @sase-42.3.3    May 5 23:16 · 9m51s    ││                                                                                                                        │
│  │  │  [A] ⚡ sase (DONE) ×5 ◆ sase-42.3.2 @sase-42 @sase-42.3.2    May 5 23:06 · 9m26s    ││                                                                                                                        │
│  │  │  [B] ⚡ sase (DONE) ×5 ◆ sase-42.3.1 @sase-42 @sase-42.3.1   May 5 22:57 · 10m34s    ││                                                                                                                        │
│  │  │  [C] ⚡E sase (EPIC CREATED) ×6 @sase-42 @sase-42.3.0.plan    May 5 22:30 · 7m45s    ││                                                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────── ○ files  ○ thinking ──────────────────────────────────────────────────┘
 a epic  n name  N tag/untag  w edit wait  W new w/ wait  x kill  X cleanup (26 done)                                                                                                                          RUNNING


```