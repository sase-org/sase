---
plan: sdd/tales/202605/agent_name_prefix_grouping.md
---
 Can you help me add a level 2 group/heading (using the a distinct heading---see how other grouping strategies
handle 3 grouping levels) for agent name prefices? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


- Let's start treating everything before the 2nd period in an agent name (assuming >1 agents share this pattern) as this
  group's key.
- For example, in the below `sase ace` snapshot, all agents with names starting with `sase-42.2.` should be in the same
  group, which is a sub-group of the existing `sase-42` group. The same goes for all agents with names starting with
  `sase-42.1.`.

### `sase ace` snapshot

```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (6 x24)  │  AXE (8)                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 24
 Agents: 28/30   [view: file]   [group: by status (o)]   (auto-refresh in 3s)
┌─ (untagged) · 8 ────────────────────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8 agents          ││                                                                                                                               │
│  │  sase (PLAN DONE) ×6 @adc.plan                         22:22:24 · 9m50s          ││  AGENT DETAILS                                                                                                                │
│  │  sase (PLAN DONE) ×6 @ada.plan                        22:07:17 · 10m58s          ││                                                                                                                               │
│  │  sase (PLAN DONE) ×6 @acz.plan                         22:00:21 · 9m58s          ││  Project: sase                                                                                                                │
│  │  sase (PLAN DONE) ×6 @acy.plan                         21:45:28 · 9m47s          ││  Workspace: #100                                                                                                              │
│  │  sase (PLAN DONE) ×6 @aco.plan                         21:42:28 · 7m48s          ││  Embedded Workflows: gh(gh_ref=sase)                                                                                          │
│  │  ▸ pysplit ──────────────────────────────────────────────────  3 agents          ││  Model: CODEX(gpt-5.5)                                                                                                        │
│  │  ⚡ sase (DONE) ×5 @pysplit.test_init_skills_handler   22:11:50 · 2m52s          ││  VCS: GitHub                                                                                                                  │
│  │  ⚡ sase (DONE) ×5 @pysplit.test_artifact_cli          22:08:55 · 6m25s          ││  Mode: ⚡ Epic Auto-Approve                                                                                                   │
│  │  ⚡ sase (DONE) ×5 @pysplit.artifact_panel_renderers   22:02:14 · 4m13s          ││  PID: 517040                                                                                                                  │
│                                                                                     ││  Name: @sase-42.3.0                                                                                                           │
│                                                                                     ││  Bead: sase-42.3.0                                                                                                            │
│                                                                                     ││  Waiting for: sase-42.2                                                                                                       │
│                                                                                     ││  Timestamps: WAIT  | 2026-05-05 20:01:20                                                                                      │
│                                                                                     ││              BEGIN | 2026-05-05 22:22:41                                                                                      │
│                                                                                     ││                                                                                                                               │
│                                                                                     ││  ──────────────────────────────────────────────────                                                                           │
│                                                                                     ││                                                                                                                               │
│                                                                                     ││  AGENT XPROMPT                                                                                                                │
│                                                                                     ││                                                                                                                               │
│                                                                                     ││  #gh:sase                                                                                                                     │
│                                                                                     ││  %name:sase-42.3.0                                                                                                            │
│                                                                                     ││  %epic                                                                                                                        │
│                                                                                     ││  %w:sase-42.2                                                                                                                 │
│                                                                                     ││  Can you help me implement epic #3 from the legend plan in the sdd/epics/202605/legend_bead_integration.md file? #epic     │
│                                                                                     ││  Keep in mind that this epic will be split into phases and worked by separate agents after approval.                          │
│                                                                                     ││                                                                                                                               │
│                                                                                     ││  ──────────────────────────────────────────────────                                                                           │
│                                                                                     ││                                                                                                                               │
└─────────────────────────────────────────────────────────────────────────────────────┘│  AGENT PROMPT                                                                                                                 │
┌─ @sase-42 · 22 ─────────────────────────────────────────────────────────────────────┐│                                                                                                                               │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                               │
│  │  ⚡E sase (RUNNING) ×4 ◆ sase-42.3.0 @sase-42 @sase-42.3.0                39s    ││  Can you help me implement epic #3 from the legend plan in the sdd/epics/202605/legend_bead_integration.md file? This      │
│                                                                                     ││  is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep in        │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agent    ││  mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` / `codex`           │
│  │  sase (WAITING) @sase-42 @acw                                                    ││  command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.      │
│  │  ▸ sase-42 ────────────────────────────────────────────────────────  4 agents    ││                                                                                                                               │
│  │  ⚡ sase (WAITING) ◆ sase-42 @sase-42 @sase-42                                   ││  Keep in mind that this epic will be split into phases and worked by separate agents after approval.                          │
│  │  ⚡E sase (WAITING) ◆ sase-42.6.0 @sase-42 @sase-42.6.0                          ││                                                                                                                               │
│  │  ⚡E sase (WAITING) ◆ sase-42.5.0 @sase-42 @sase-42.5.0                          ││                                                                                                                               │
│  │  ⚡E sase (WAITING) ◆ sase-42.4.0 @sase-42 @sase-42.4.0                          ││  ──────────────────────────────────────────────────                                                                           │
│                                                                                     ││                                                                                                                               │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  16 agents    ││  AGENT REPLY                                                                                                                  │
│  │  ▸ sase-42 ───────────────────────────────────────────────────────  16 agents    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.2 @sase-42 @sase-42.2           22:22:30 · 6m31s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.2.6 @sase-42 @sase-42.2.6       22:15:49 · 8m36s    ││  ─── 22:22:53 ─────────────────────────────────────                                                                           │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.2.5 @sase-42 @sase-42.2.5      22:07:04 · 14m20s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.2.4 @sase-42 @sase-42.2.4      21:52:41 · 12m43s    ││  I’ll use the `sase_plan` skill and read the repository’s short-term memory plus the legend file before drafting anything.    │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.2.3 @sase-42 @sase-42.2.3      21:39:48 · 12m12s    ││  I’m treating this as planning only: no implementation file changes until the phase plan is approved.                         │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.2.2 @sase-42 @sase-42.2.2       21:27:26 · 7m43s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.2.1 @sase-42 @sase-42.2.1       21:19:17 · 8m12s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.1 @sase-42 @sase-42.1           21:03:38 · 5m21s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.1.6 @sase-42 @sase-42.1.6       20:58:06 · 4m50s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.1.5 @sase-42 @sase-42.1.5       20:52:52 · 8m14s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.1.3 @sase-42 @sase-42.1.3       20:44:20 · 9m37s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.1.4 @sase-42 @sase-42.1.4       20:29:19 · 8m31s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.1.2 @sase-42 @sase-42.1.2      20:34:35 · 13m37s    ││                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-42.1.1 @sase-42 @sase-42.1.1      20:20:37 · 13m08s    ││                                                                                                                               │
│  │  ⚡E sase (EPIC CREATED) ×6 @sase-42 @sase-42.2.0.plan       21:13:24 · 9m31s    ││                                                                                                                               │
│  │  ⚡E sase (EPIC CREATED) ×6 @sase-42 @sase-42.1.0.plan       20:10:24 · 9m06s    ││                                                                                                                               │
└─────────────────────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────── ○ files  ○ thinking ─────────────────────────────────────────────────────┘
 a unapprove  n name  N tag/untag  t tmux  T tmux (primary)  w edit wait  W new w/ wait  x kill  X cleanup (24 done)                                                                                           RUNNING


```