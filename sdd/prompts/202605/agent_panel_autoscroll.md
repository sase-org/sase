---
plan: sdd/tales/202605/agent_panel_autoscroll.md
---
 Can you help me enable auto-scroll for the dynamic agent panels shown on the left in the the "Agents" tab of the `sase ace` TUI? For example, in the below `sase ace` snapshot, the selected agent row is currently not visible. I would like to make that impossible by automatically scrolling that panel down when the user hits `j` to view a (at the time of keypress) hidden agent row. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (37 x7)  │  AXE (9)                                                                                                                                                        CODEX(gpt-5.5)  ■ IDLE  ✉ 1
 44 Agents [6 running · 31 waiting · 0 unread · 7 read]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 2s)
┌─ (untagged) · 6 ──────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents · 3 running    ││                                                                                                                                                 │
│  │  sase (PLAN APPROVED) ×6                           🏃‍♂️ 1m47s    ││  AGENT DETAILS                                                                                                                                  │
│  │  sase (PLAN APPROVED) ×6 @cr.plan                  🏃‍♂️ 5m12s    ││                                                                                                                                                 │
│  │  sase (PLAN APPROVED) ×8 @cg.code.r1.plan         🏃‍♂️ 20m34s    ││  Project: sase                                                                                                                                  │
│                                                                   ││  Workspace: #103                                                                                                                                │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents ▄▄ ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                            │
│  │  sase (PLAN DONE) ×6 @cs.plan              15:46:29 · 6m42s    ││  Model: CODEX(gpt-5.5)                                                                                                                          │
└───────────────────────────────────────────────────────────────────┘│  VCS: GitHub                                                                                                                                    │
                                                                     │  PID: 667834                                                                                                                                    │
┌─ #blog · 3 ───────────────────────────────────────────────────────┐│  Name: @cq.plan                                                                                                                                 │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents      ││  Timestamps: BEGIN | 2026-05-09 15:31:25                                                                                                        │
│  │  ▎ 260507 ─────────────────────────────────────  3 agents      ││              PLAN  | 2026-05-09 15:33:28                                                                                                        │
│  │  │  ▸ 260507.ajh ──────────────────────────────  3 agents      ││              CODE  | 2026-05-09 15:35:07                                                                                                        │
│  │  │  sase (DONE) ×5 @260507.ajh           May 7 17:21 · 6m      ││              END   | 2026-05-09 15:42:01                                                                                                        │
│  │  │  sase (DONE) ×7 @260507.ajh.r1.r1  May 7 17:35 · 6m35s   ▆▆ ││  DELTAS:                                                                                                                                        │
└───────────────────────────────────────────────────────────────────┘│    ~ sdd/tales/202605/agents_asking_count.md  ~1                                                                                                │
                                                                     │    ~ src/sase/ace/tui/actions/agents/_display_detail.py  +14 ~3                                                                                 │
┌─ #sase-2i · 35 ───────────────────────────────────────────────────┐│    ~ src/sase/ace/tui/widgets/_agent_list_render_layout.py  +1 ~2                                                                               │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━  3 agents · 3 running           ││    ~ src/sase/ace/tui/widgets/agent_info_panel.py  +13 ~1                                                                                       │
│  │  ▸ sase-2i ───────────────────  3 agents · 3 running           ││    ~ src/sase/agent/status_buckets.py  +12                                                                                                  ▂▂  │
│  │  ⚡ sase (RUNNING) ×4 ◆ @sase-2i.6          🏃‍♂️ 1m12s           ││    ~ tests/ace/tui/test_agent_panel_index_integration.py  +25 ~6                                                                                │
│  │  ⚡ sase (RUNNING) ×4 ◆ @sase-2i.2          🏃‍♂️ 5m56s           ││    ~ tests/ace/tui/test_startup_loading_indicators.py  ~1                                                                                       │
│  │  ⚡ sase (RUNNING) ×4  @sase-2i.1          🏃‍♂️ 5m58s           ││    ~ tests/ace/tui/widgets/test_agent_info_panel.py  +7 ~14                                                                                     │
│                                                                   ││  ARTIFACTS:                                                                                                                                     │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  31 agents          ││    • sdd/tales/202605/agents_asking_count.md                                                                                                    │
│  │  ▸ sase-2i ──────────────────────────────  31 agents           ││    • ~/.sase/projects/sase/artifacts/ace-run/20260509153507/markdown_pdfs/sdd__tales__202605__agents_asking_count.md.pdf                        │
│  │  ⚡ sase (WAITING) ◆ @sase-2i                                  ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.34                               ││  Commit Message: feat: show asking count in agents tab                                                                                          │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.33                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.32                               ││  ──────────────────────────────────────────────────                                                                                             │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.31                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.30                               ││  AGENT XPROMPT                                                                                                                                  │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.29                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.28                               ││  #gh:sase Can you help me add a new agent count to the top of the the "Agents" tab of the `sase ace` TUI? This count should be named            │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.27                               ││  "asking" and it should include any agent that is currently waiting for human input (e.g. PLANNING). We already use a special icon to the       │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.26                               ││  left of the runtime in the agent row to visually mark these agents. #plan                                                                      │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.25                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.24                               ││  ──────────────────────────────────────────────────                                                                                             │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.23                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.22                               ││  AGENT PROMPT                                                                                                                                   │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.21                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.20                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.19                               ││  Can you help me add a new agent count to the top of the the "Agents" tab of the `sase ace` TUI? This count should be                           │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.18                               ││  named "asking" and it should include any agent that is currently waiting for human input (e.g. PLANNING). We already use                       │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.17                               ││  a special icon to the left of the runtime in the agent row to visually mark these agents. Think this through thoroughly                        │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.16                               ││  and create a plan using your `/sase_plan` skill before making any file changes.                                                                │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.15                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.14                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.13                               ││  ──────────────────────────────────────────────────                                                                                             │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.12                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.11                               ││  AGENT REPLY                                                                                                                                    │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.10                               ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.9                                ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.8                                ││  ─── PLANNER ─── 15:31:25 ─────────────────────────                                                                                             │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.7                                ││                                                                                                                                                 │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.5                                ││  ─── 15:31:45 ─────────────────────────────────────                                                                                             │
│  │  ⚡ sase (WAITING) ◆ @sase-2i.4                                ││                                                                                                                                                 │
│                                                                   ││  I’ll use the `sase_plan` skill first as requested, then inspect the TUI code and related agent status logic before proposing the               │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent        ▇▇ ││                                                                                                                                                 │
└───────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ───────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```