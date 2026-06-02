---
plan: sdd/tales/202606/zorg_live_artifact_cleanup.md
---
 I'm unable to delete the "zorg" project. Can you help me track down and delete these 5 live artifacts (see the `sase ace` snapshot below)? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                        sase ace (PID: 479914)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 1+1
 11 Agents [1 running · 10 done]   [view: file]   [group: by status (o)]   (auto-refresh in 3s)                                                ▌
┌─ (untagged) · 9 [R1 D8] ──────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────▌ Blocked: project 'zorg' has 5 live artifact marker(s);    ─┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running      ││                                                                             ▌ remove live work before deleting it                        │
│  │  🤖 sase (RUNNING) ×4 @2                       🏃‍♂️ 22s      ││  AGENT DETAILS                                                              ▌                                                            │
│                                                               ││                                                                                                                                          │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8 agents      ││  Name: @1                                                                                                                                │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @1       07:13:55 · 16m33s      ││  Project: sase                                                                                                                           │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @brd      06:45:45 · 6m26s      ││  Workspace: #10                                                                                                                          │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @brc     06:32:50 · 10m04s      ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                     │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @brb     06:40:18 · 20m09s      ││  Model: CODEX(gpt-5.5)                                                                                                                   │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bra     06:34:00 · 18╔══════════════════════════════════════════════════════════════════════════════════════════════╗                                                      │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bq9        06:19:20 ·║                                                                                              ║                                                      │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bq8   Jun 1 17:31 · 7║  Project Management                                                                          ║                                                      │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bq7  Jun 1 16:17 · 13║                                                                                              ║                                                      │
│                                                     ║  Filter: all  all:6 active:6 archived:0 closed:0  marked:0  Blocked: project 'zorg' has 5    ║                                                      │
│                                                     ║  live artifact marker(s); remove live work before deleting it                                ║                                                      │
│                                                     ║                                                                                              ║                                                      │
│                                                     ║  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎  ║──────────────────────────────────────────────────────┘
│                                                     ║  ▊  Type to filter projects...                                                            ▎  ║──────────────────────────────────────────────────────┐
│                                                     ║  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎  ║                                                      │
│                                                     ║                                                                                              ║                                                      │
│                                                     ║  ┌────────────────────────────────────────────────────────────────────────────────────────┐  ║                                                      │
│                                                     ║  │     .sase                     active   default  claims:0   launch:no   warnings:1  -   │  ║s/202606/project_management_edit_keymap_1.md          │
│                                                     ║  │     CV                        active   default  claims:0   launch:yes                  │  ║                                                      │
│                                                     ║  │ /home/bryan/projects/github/bbugyi200/CV                                               │  ║                                                      │
│                                                     ║  │     beads                     active   default  claims:0   launch:yes                  │  ║                                                      │
│                                                     ║  │ /home/bryan/projects/github/steveyegge/beads                                           │  ║                                                      │
│                                                     ║  │     bob-cli                   active   default  claims:0   launch:yes                  │  ║                                                      │
│                                                     ║  │ /home/bryan/projects/github/bbugyi200/bob-cli                                          │  ║                                                      │
│                                                     ║  │     sase                      active   default  claims:1   launch:yes                  │  ║                                                      │
│                                                     ║  │ /home/bryan/projects/github/sase-org/sase                                              │  ║                                                      │
│                                                     ║  │     zorg                      active   default  claims:0   launch:yes                  │  ║                                                      │
│                                                     ║  │ /home/bryan/projects/github/zettel-org/zorg                                            │  ║                                                      │
│                                                     ║  └────────────────────────────────────────────────────────────────────────────────────────┘  ║                                                      │
│                                                     ║                                                                                              ║e/ace/tui/modals/project_management_actions.py        │
│                                                     ║  ┌────────────────────────────────────────────────────────────────────────────────────────┐  ║                                                      │
│                                                     ║  │                                                                                        │  ║                                                      │
│                                                     ║  │  zorg  active (defaulted)                                                              │  ║                                                      │
│                                                     ║  │  Project file: /home/bryan/.sase/projects/zorg/zorg.gp                                 │  ║                                                      │
│                                                     ║  │  Workspace: /home/bryan/projects/github/zettel-org/zorg                                │  ║                                                      │
│                                                     ║  │  Active claims: 0    Launchable: yes                                                   │  ║                                                      │
│                                                     ║  │                                                                                        │  ║                                                      │
│                                                     ║  └────────────────────────────────────────────────────────────────────────────────────────┘  ║                                                      │
│                                                     ║                                                                                              ║                                                      │
│                                                     ║  ──────────────────────────────────────────────────────────────────────────────────────────  ║                                                      │
│                                                     ║                                                                                              ║                                                      │
│                                                     ║    j/k navigate  / filter  Tab state  Enter highlighted  m mark  u unmark all  e edit  a     ║                                                      │
│                                                     ║     activate  r archive  c close  Ctrl+D delete  F force after block  R reload  q close      ║                                                      │
│                                                     ║                                                                                              ║                                                      │
│                                                     ╚══════════════════════════════════════════════════════════════════════════════════════════════╝                                                      │
│                                                               ││     29 +from sase.ace.changespec.locking import acquire_edit_lock, release_edit_lock                                                     │
│                                                               ││     30 +from sase.ace.hints import build_editor_args                                                                                     │
└───────────────────────────────────────────────────────────────┘│     31  from sase.core.paths import sase_projects_dir                                                                                    │
                                                                 │     32  from sase.core.project_lifecycle_wire import ProjectRecordWire                                                                   │
┌─ #read · 2 [D2] ──────────────────────────────────────────────┐│     33  from sase.main.project_handler import ProjectLifecycleBlockedError                                                               │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents    ││     34 @@ -59,6 +65,50 @@ class ProjectManagementActionsMixin:                                                                           │
│  │  ▸ reads ────────────────────────────────────  2 agents    ││                                                                                                                                          │
│  │  🤖 sase (DONE) ×5 @reads.final-3  May 31 13:22 · 6m21s    ││    ▾ 369 more lines below                                                                                                                │
│  │  🤖 home (DONE) ×5 @reads.final-2  May 28 09:16 · 2m40s    ││                                                                                                                                          │
└───────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────── Lines 1-34 of 403 ────────────────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
 A artifacts · e edit chat · f fork · n name · N tag/untag · r retry · t tmux · T tmux (primary) · x dismiss · X cleanup (10 done)                                                                  RUNNING
```