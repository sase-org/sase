---
plan: sdd/tales/202605/agent_cleanup_tag_scope.md
---
 Something is wrong with the "Choose tag" option of the "Agent Cleanup" panel (triggered with the `X` keymap). We should only show tags that are present on the "Agents" tab currently and the same goes for agents that have those tags (we should only show ones that exist on the agents tab). Can you help me diagnose the root cause of this issue and fix it? See the `sase ace` snapshot below for an example of the issue I'm seeing. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (2 x14)  │  AXE (8)                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 11
 Agents: 2/16   [view: collapsed]   [group: by status (o)]   (auto-refresh in 7s)
┌─ (untagged) · 4 ───────────────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running              ││                                                                                                                                        │
│  │  sase (RUNNING) ×6 @260508.anx.code.r1              🏃‍♂️ 48s              ││  AGENT DETAILS                                                                                                                         │
│  │  sase (PLAN APPROVED) ×6 @c.plan                  🏃‍♂️ 5m37s              ││                                                                                                                                        │
│                                                                            ││  Project: sase                                                                                                                         │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents              ││  Workspace: #100                                                                                                                       │
│  │  ▸ 260508 ──────────────────────────────────────  2 agents              ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                   │
│  │  sase (EPIC CREATED) ×6 @260508.aoa.plan  20:09:05 · 7m10s              ││  Model: CODEX(gpt-5.5)                                                                                                                 │
│  │  sase (PLAN DONE) ×6 @260508.anx.plan     19:46:04 · 6m01s              ││  VCS: GitHub                                                                                                                           │
│                                                                            ││  PID: 393726                                                                                                                           │
│                                                                            ││  Name: @c.plan                                                                                                                         │
│                                                                            ││  Timestamps: BEGIN | 2026-05-08 21:50:30                                                                                               │
│                                                                            ││              PLAN  | 2026-05-08 21:52:03                                                                                               │
│                                                                            ││              CODE  | 2026-05-08 21:52:37                                                                                               │
│                                                                            ││  DELTAS:                                                                                                                               │
│                                                                            ││    ~ src/sase/ace/tui/actions/agents/_display_detail.py  +17                                                                           │
│                                                                            ││    ~ src/sase/ace/tui/widgets/agent_info_panel.py  +25                                                                                 │
│                                                                            ││    ~ tests/ace/tui/test_agent_panel_index_integration.py  +65                                                                          │
│                                                                            ││    ~ tests/ace/tui/widgets/test_agent_info_panel.py  +42                                                                               │
│                                                                      █▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█                                                                      │
│                                                                      █                                                                        █                                                                      │
│                                                                      █  Cleanup by Tag                                                        █                                                                      │
│                                                                      █  ┌──────────────────────────────────────────────────────────────────┐  █                                                                      │
│                                                                      █  │ @blog                                                            │  █                                                                      │
│                                                                      █  │    0 kill  3 dismiss  0 child cascade                            │  █                                                                      │
│                                                                      █  │ @chop                                                            │  █                                                                  ▄▄  │
│                                                                      █  │    0 kill  109 dismiss  0 child cascade                          │  █-refresh and group strategy) agent counts?                            │
│                                                                      █  │ @comedy                                                          │  █                                                                      │
│                                                                      █  │    0 kill  0 dismiss  0 child cascade                            │  █ ace` TUI is focused.                                                 │
│                                                                      █  │ @mobile                                                          │  █total # of agents.                                                    │
│                                                                      █  │    0 kill  0 dismiss  0 child cascade                            │  █                                                                      │
│                                                                      █  │ @read                                                            │  █                                                                      │
│                                                                      █  │    0 kill  0 dismiss  0 child cascade                            │  █                                                                      │
└──────────────────────────────────────────────────────────────────────█  │ @sase-24                                                         │  █                                                                      │
                                                                       █  │    0 kill  0 dismiss  0 child cascade                            │  █                                                                      │
┌─ #blog · 3 ──────────────────────────────────────────────────────────█  │ @sase-25                                                         │  █                                                                      │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents         █  │    0 kill  0 dismiss  0 child cascade                            │  █                                                                      │
│  │  ▎ 260507 ─────────────────────────────────────  3 agents         █  │ @sase-26                                                         │  █                                                                      │
│  │  │  ▸ 260507.ajh ──────────────────────────────  3 agents         █  │    0 kill  0 dismiss  0 child cascade                            │  █                                                                      │
│  │  │  sase (DONE) ×5 @260507.ajh           May 7 17:21 · 6m         █  └──────────────────────────────────────────────────────────────────┘  █and group strategy) agent counts?                                     │
│  │  │  sase (DONE) ×7 @260507.ajh.r1.r1  May 7 17:35 · 6m35s         █  enter choose  q close                                                 █                                                                      │
│  │  │  sase (DONE) ×7 @260507.ajh.r1     May 7 17:28 · 6m51s         █                                                                        █ ace` TUI is focused.                                                 │
└──────────────────────────────────────────────────────────────────────█▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█total # of agents.                                                    │
                                                                              │  - I want you to lead the design on this one. Just make sure it looks beautiful!                                                       │
┌─ #chop · 2 ────────────────────────────────────────────────────────────────┐│                                                                                                                                        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents    ││  Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.                         │
│  │  ▸ pysplit ───────────────────────────────────────────────  2 agents    ││                                                                                                                                        │
│  │  ⚡ sase (DONE) ×5 @pysplit.test_image_file_panels  19:35:08 · 7m08s    ││                                                                                                                                        │
│  │  ⚡ sase (DONE) ×5 @pysplit.test_artifact_viewer    19:27:55 · 5m58s    ││  ──────────────────────────────────────────────────                                                                                    │
└────────────────────────────────────────────────────────────────────────────┘│                                                                                                                                        │
                                                                              │  AGENT REPLY                                                                                                                           │
┌─ #sase-2e · 7 ─────────────────────────────────────────────────────────────┐│                                                                                                                                        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7 agents                      ││                                                                                                                                        │
│  │  ▸ sase-2e ─────────────────────────────  7 agents                      ││  ─── PLANNER ─── 21:50:30 ─────────────────────────                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2e     21:40:07 · 5m25s                      ││                                                                                                                                        │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2e.6  21:34:39 · 15m56s                      ││  ─── 21:50:49 ─────────────────────────────────────                                                                                ▁▁  │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2e.5  21:18:38 · 11m15s                      ││                                                                                                                                        │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2e.4  21:07:20 · 13m21s                      ││  I’ll use the `sase_plan` skill first, then inspect the TUI code and relevant project memory before touching files. After that I’ll    │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2e.3  20:53:50 · 15m07s                      ││  make the change and verify it with the repo’s normal checks.                                                                          │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2e.2  20:38:39 · 15m31s                      ││  ─── 21:50:56 ─────────────────────────────────────                                                                                    │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2e.1  20:23:00 · 14m48s                      ││                                                                                                                                        │
└───────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────── ● files [1/2]  ○ thinking ───────────────────────────────────────────────────────┘
 a approve  A artifacts  n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (14 done)                                                                                             RUNNING


```