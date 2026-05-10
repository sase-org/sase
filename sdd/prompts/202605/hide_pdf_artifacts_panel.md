---
plan: sdd/tales/202605/hide_pdf_artifacts_panel.md
---
 We shouldn't be showing PDF files in the artifacts panel (see the `sase ace` snapshot below). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (6 x9)  │  AXE (10)                                                                                                                                                      CODEX(gpt-5.5)  ■ IDLE  ✉ 2+2
 15 Agents [1 running · 5 waiting · 1 unread · 8 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 0s)
┌─ (untagged) · 3 [D3] ──────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││                                                                                                                                            │
│  │  sase (DONE) ×9 @audit_bugs.sase.c265ba72d00b   01:14:23 · 5m47s    ││  AGENT DETAILS                                                                                                                             │
│  │  sase (PLAN DONE) ×6 @er.plan                  01:13:16 · 10m26s    ││                                                                                                                                            │
│  │  sase (EPIC CREATED) ×6 @em.plan                01:12:59 · 9m02s    ││  Project: sase                                                                                                                             │
│                                                                        ││  Workspace: #104                                                                                                                           │
│                                                                        ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                       │
│                                                                        ││  Model: CODEX(gpt-5.5)                                                                                                                     │
│                                                                        ││  VCS: GitHub                                                                                                                               │
│                                                                        ││  PID: 3928132                                                                                                                              │
│                                                                        ││  Name: @em.plan                                                                                                                            │
│                                                                        ││  Timestamps: BEGIN | 2026-05-10 00:11:15                                                                                                   │
│                                                                        ││              PLAN  | 2026-05-10 00:13:23                                                                                                   │
│                                                                        ││              EPIC  | 2026-05-10 01:06:05                                                                                                   │
│                                                                        ││              END   | 2026-05-10 01:12:59                                                                                                   │
│                                                                        ││  DELTAS:                                                                                                                                   │
│                                                                        ││    ~ sdd/beads/config.json  ~1                                                                                                             │
│                                                                        ││    ~ sdd/beads/issues.jsonl  +6 ~667                                                                                                       │
│                                                                        ││    ~ sdd/epics/202605/png_only_visual_snapshots.md  +2                                                                                     │
│                                                                        ││  ARTIFACTS:                                                                                                                                │
│                                                                        ││    • sdd/epics/202605/png_only_visual_snapshots.md                                                                                         │
│                                                                      ╔════════════════════════════════════════════════════════════════════════╗                                                                      │
│                                                                      ║                                                                        ║                                                                      │
│                                                                      ║  Agent Artifacts  [3]                                                  ║                                                                      │
│                                                                      ║                                                                        ║                                                                      │
│                                                                      ║  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎  ║                                                                      │
│                                                                      ║  ▊ 1      Chat transcript  [chat]                                   ▎  ║                                                                      │
│                                                                      ║  ▊    ~/.sase/chats/202605/sase-ace_run-260510_001115.md            ▎  ║                                                                      │
│                                                                      ║  ▊ 2      png_only_visual_snapshots.md  [plan]                      ▎  ║ only supporting PNG snapshots? Add a few (3-5) useful PNG            │
│                                                                      ║  ▊    sdd/epics/202605/png_only_visual_snapshots.md                 ▎  ║                                                                      │
│                                                                      ║  ▊ 3      sdd__epics__202605__png_only_visual_snapshots.md.pdf      ▎  ║                                                                      │
│                                                                      ║  ▊ [pdf]                                                            ▎  ║                                                                      │
│                                                                      ║  ▊    ...05/markdown_pdfs/sdd__epics__202605__png_only_visual_snaps ▎  ║                                                                      │
│                                                                      ║  ▊ hots.md.pdf                                                      ▎  ║                                                                      │
│                                                                      ║  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎  ║                                                                      │
│                                                                      ║  ────────────────────────────────────────────────────────────────────  ║                                                                      │
└──────────────────────────────────────────────────────────────────────║                                                                        ║                                                                      │
                                                                       ║   key/enter: open  m: mark  A: open all  j/k: navigate  q/esc: close   ║                                                                      │
┌─ #sase-2o · 6 [U1 D5] ───────────────────────────────────────────────║                                                                        ║porting PNG snapshots? Add a few (3-5) useful PNG                     │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents       ╚════════════════════════════════════════════════════════════════════════╝                                                                      │
│  │  ▸ sase-2o ──────────────────────────────────────  6 agents         ││                                                                                                                                            │
│  │  ⚡ sase (PLAN DONE) ×6 @sase-2o.plan  01:15:05 · 🎉 15m27s         ││  This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep                   │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.5              00:59:20 · 15m         ││  in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` / `codex` /                   │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.4            00:42:44 · 8m09s         ││  `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before                        │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.3            00:44:12 · 9m39s         ││  making any file changes.                                                                                                                  │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.2            00:34:27 · 9m12s         ││                                                                                                                                            │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.1           00:25:07 · 12m21s         ││                                                                                                                                            │
└────────────────────────────────────────────────────────────────────────┘│  ──────────────────────────────────────────────────                                                                                        │
                                                                          │                                                                                                                                            │
┌─ #sase-2p · 6 [R1 W5] ─────────────────────────────────────────────────┐│  AGENT REPLY                                                                                                                               │
│  ▶ Running ━━━━━━━━━━━━━━━  1 agent · 1 running                        ││                                                                                                                                            │
│  │  ⚡ sase (RUNNING) ×4 ◆ @sase-2p.1  🏃‍♂️ 3m18s                        ││                                                                                                                                            │
│                                                                        ││  ─── PLANNER ─── 00:11:15 ─────────────────────────                                                                                        │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agents                       ││                                                                                                                                            │
│  │  ▸ sase-2p ───────────────────────  5 agents                        ││  ─── 00:11:36 ─────────────────────────────────────                                                                                        │
│  │  ⚡ sase (WAITING) ◆ @sase-2p                                       ││                                                                                                                                            │
│  │  ⚡ sase (WAITING) ◆ @sase-2p.5                                     ││  I’ll use the `sase_plan` skill first, then inspect the snapshot-related code and tests enough to split the work into independent          │
│  │  ⚡ sase (WAITING) ◆ @sase-2p.4                                     ││  phases. After that I’ll produce the plan without changing files.                                                                          │
│  │  ⚡ sase (WAITING) ◆ @sase-2p.3                                     ││  ─── 00:11:44 ─────────────────────────────────────                                                                                        │
│  │  ⚡ sase (WAITING) ◆ @sase-2p.2                                     ││                                                                                                                                            │
└────────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ─────────────────────────────────────────────────────────┘
 A artifacts  n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (9 done)                                                                                                         RUNNING



```