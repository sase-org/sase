---
plan: sdd/tales/202605/tmux_agent_workspace_dir.md
---
 When I use the `t` keymap to attempt to open a new tmux window that `cd`s into this agent's workspace directory, which should be #10 (see the `sase ace` snapshot below), the primary workspace directory (~/projects/github/sase-org/sase/) is `cd`ed into instead. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                        sase ace (PID: 3512109)
  CLs  │  Agents  │  AXE                                                                                                                                                         CODEX(gpt-5.5)  ■ IDLE  ✉ 0
 32 Agents [1 running · 2 waiting · 29 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 6s)
┌─ (untagged) · 12 [D12] ──────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  12 agents        ││                                                                                                                                       │
│  │  🤖 sase (DONE) ×6 @auk               17:42:51 · 9m55s        ││  AGENT DETAILS                                                                                                                        │
│  │  🤖 sase (TALE DONE) ×6 @at2          15:25:49 · 7m47s        ││                                                                                                                                       │
│  │  🎭 home (PLAN DONE) ×8 @ars.r1  May 19 20:02 · 25m37s        ││  Project: sase                                                                                                                        │
│  │  🎭 home (DONE) ×5 @ars           May 19 19:43 · 3m37s        ││  Workspace: #10                                                                                                                       │
│  │  🤖 sase (TALE DONE) ×6 @aqr      May 19 11:44 · 5m56s        ││  Model: CODEX(gpt-5.5)                                                                                                                │
│  │  🤖 sase (TALE DONE) ×8 @ap5.r1  May 19 09:14 · 18m23s        ││  VCS: GitHub                                                                                                                          │
│  │  🤖 sase (TALE DONE) ×6 @ap5     May 19 08:12 · 16m24s        ││  Mode: ⚡ Auto-Approve                                                                                                                │
│  │  🎭 sase (PLAN DONE) ×9 @aj5     May 17 08:28 · 20m34s        ││  PID: 3732499                                                                                                                         │
│  │  🤖 sase (DONE) ×6 @aip.1.plan   May 16 20:25 · 13m17s        ││  Name: @sase-3s.5                                                                                                                     │
│  │  🎭 sase (DONE) ×5 @aaaaa           May 16 19:59 · 58s     ▅▅ ││  Bead: sase-3s.5                                                                                                                      │
│  │  ▸ aq2 ─────────────────────────────────────  2 agents        ││  Waiting for: sase-3s.4                                                                                                               │
└──────────────────────────────────────────────────────────────────┘│  Timestamps: WAIT  | 2026-05-20 17:42:12                                                                                              │
                                                                    │              RUN   | 2026-05-20 18:20:24                                                                                              │
┌─ #chop · 1 [D1] ─────────────────────────────────────────────────┐│                                                                                                                                       │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent    ││  ──────────────────────────────────────────────────                                                                                   │
└──────────────────────────────────────────────────────────────────┘│                                                                                                                                       │
                                                                    │  AGENT XPROMPT                                                                                                                        │
┌─ #read · 3 [D3] ─────────────────────────────────────────────────┐│                                                                                                                                       │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents             ││  #gh:sase                                                                                                                             │
│  │  ▸ aqa ────────────────────────────────  3 agents             ││  %name:sase-3s.5                                                                                                                      │
│  │  ♊ sase (DONE) ×5 @aqa.gem  May 19 09:13 · 1m50s             ││  %group:sase-3s                                                                                                                       │
│  │  🤖 sase (DONE) ×5 @aqa.cdx  May 19 09:17 · 5m24s          ▆▆ ││  %approve                                                                                                                             │
└──────────────────────────────────────────────────────────────────┘│  %w:sase-3s.4                                                                                                                         │
                                                                    │  #bd/work_phase_bead:sase-3s.5                                                                                                        │
┌─ #research · 3 [D3] ─────────────────────────────────────────────┐│                                                                                                                                       │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents            ││  ──────────────────────────────────────────────────                                                                                   │
│  │  ▎ aug ─────────────────────────────────  3 agents            ││                                                                                                                                       │
│  │  │  🤖 sase (DONE) ×5 @aug        17:10:25 · 6m02s         ▂▂ ││  AGENT PROMPT                                                                                                                         │
│  │  │  ▸ aug.r1 ───────────────────────────  2 agents            ││                                                                                                                                       │
└──────────────────────────────────────────────────────────────────┘│                                                                                                                                       │
                                                                    │  Can you complete the work for bead sase-3s.5? The bead has already been claimed for you (status=in_progress, assignee                │
┌─ #sase-3r · 6 [D6] ──────────────────────────────────────────────┐│  set). Read its description and design file, do the work, and close the bead. Do NOT close the parent epic. Do NOT create             │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents     ││  new beads.                                                                                                                           │
│  │  ▸ sase-3r ────────────────────────────────────  6 agents     ││                                                                                                                                       │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3r     May 16 21:48 · 8m18s     ││                                                                                                                                       │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3r.5  May 16 21:40 · 13m17s     ││  ──────────────────────────────────────────────────                                                                                   │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3r.4  May 16 21:26 · 11m09s     ││                                                                                                                                       │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3r.3  May 16 21:15 · 16m27s     ││  AGENT REPLY                                                                                                                          │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3r.2  May 16 20:58 · 11m19s  ▇▇ ││                                                                                                                                       │
└──────────────────────────────────────────────────────────────────┘│                                                                                                                                       │
                                                                    │  ─── 18:20:32 ─────────────────────────────────────                                                                                   │
┌─ #sase-3s · 7 [R1 W2 D4] ────────────────────────────────────────┐│                                                                                                                                       │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running      ││  I’ll read the bead workflow notes first, then inspect `sase-3s.5` and its referenced design so the implementation lines up with      │
│  │  ⚡ 🤖 sase (RUNNING) ×4 ◆ @sase-3s.5           🏃‍♂️ 2m57s      ││  the project’s tracking conventions.                                                                                                  │
│                                                                  ││  ─── 18:20:45 ─────────────────────────────────────                                                                                   │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents     ││                                                                                                                                       │
│  │  ▸ sase-3s ───────────────────────────────────  2 agents      ││  Using the `sase_beads` skill for the bead lifecycle. Next I’m loading the repository memory files that are marked as always          │
│  │  ⚡ 🤖 sase (WAITING) ◆ @sase-3s                              ││  relevant, then I’ll inspect the bead details.                                                                                        │
│  │  ⚡ 🤖 sase (WAITING) ◆ @sase-3s.6                            ││  ─── 18:20:53 ─────────────────────────────────────                                                                                   │
│                                                                  ││                                                                                                                                       │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents      ││  The phase bead is `in_progress`, depends on the closed phase 4, and blocks phase 6. Its own record doesn’t show a description or     │
│  │  ▸ sase-3s ───────────────────────────────────  4 agents      ││  design path, so I’m checking the parent epic for the implementation plan.                                                            │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3s.4      18:20:20 · 8m05s      ││  ─── 18:21:18 ─────────────────────────────────────                                                                                   │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3s.3      18:12:09 · 6m54s      ││                                                                                                                                       │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-3s.2     18:05:12 · 11m54s   ▇▇ ││                                                                                                                                       │
└──────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────── ● files [1/2]  ● tools ────────────────────────────────────────────────────────┘
 a epic  n name  N tag/untag  t tmux  T tmux (primary)  w edit wait  W new w/ wait  x kill  X cleanup (29 done)                                                                                     RUNNING


```