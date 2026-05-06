---
plan: sdd/tales/202605/agents_tab_non_agent_step_runtimes.md
---
 We seem to show runtimes for non-agent steps on the "Agents" tab of the `sase ace` TUI. We should only show
runtimes for agent/workflow entries and agent steps (see the "setup", "prepare", and "checkout" steps in the `sase ace`
snapshot below--we shouldn't show runtimes for any of those). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (3 x15)  │  AXE (8)                                                                                                                                                    CODEX(gpt-5.5)  ■ IDLE  ✉ 10+15
 Agents: 3/18   [view: collapsed]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 9 ──────────────────────────────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  9 agents            ││                                                                                                                     │
│  │  sase (EPIC CREATED) ×6 @adw.plan  art ?                      02:59:58 · 15m17s            ││  AGENT DETAILS                                                                                                      │
│  │  sase (PLAN DONE) ×8 @adv.plan  art ?                         01:47:43 · 19m25s            ││                                                                                                                     │
│  │  sase (PLAN DONE) ×6 @adu.plan  art ?                          01:28:16 · 6m54s            ││  Step: setup                                                                                                        │
│  │  sase (PLAN DONE) ×6 @adq.plan  art ?                          00:52:06 · 7m32s            ││  Workspace: #100                                                                                                    │
│  │  sase (PLAN DONE) ×6 @adk.plan  art ?                          00:32:50 · 7m07s            ││  Workflow: tmp_260506_032629                                                                                        │
│  │  sase (PLAN DONE) ×7 @ado.plan  art ?                         00:27:22 · 14m37s            ││  Model: CODEX(gpt-5.5)                                                                                              │
│  │  ▸ pysplit ──────────────────────────────────────────────────────────  3 agents            ││  VCS: GitHub                                                                                                        │
│  │  ⚡ sase (DONE) ×5 @pysplit.test_artifact_panel_modal  art ?  01:28:27 · 13m11s            ││  Mode: ⚡ Auto-Approve                                                                                              │
│  │  ⚡ sase (DONE) ×5 @pysplit.artifact_panel_state  art ?        01:15:09 · 6m45s            ││  Name: @sase-25.7                                                                                                   │
│  │  ⚡ sase (DONE) ×5 @pysplit.artifact_panel_modal  art ?        01:08:14 · 8m29s            ││  Bead: sase-25.7 - Remove only the historical SDD and bead metadata surface for the sase-23 and sase-24 families    │
│                                                                                               ││  after implementation cleanup.                                                                                      │
│                                                                                               ││  Waiting for: sase-25.2, sase-25.3, sase-25.4, sase-25.5, sase-25.6                                                 │
│                                                                                               ││  Timestamps: WAIT  | 2026-05-06 02:58:46                                                                            │
│                                                                                               ││              BEGIN | 2026-05-06 03:26:24                                                                            │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││  ──────────────────────────────────────────────────                                                                 │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││  PYTHON CODE                                                                                                        │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││  from sase_github.scripts.gh_setup import main                                                                      │
│                                                                                               ││  main(                                                                                                              │
│                                                                                               ││      gh_ref={{ gh_ref | tojson }},                                                                                  │
│                                                                                               ││      n={{ n | tojson }},                                                                                            │
│                                                                                               ││      release={{ release | tojson }},                                                                                │
│                                                                                               ││      workflow_label={{ workflow_label | tojson }},                                                                  │
│                                                                                               ││  )                                                                                                                  │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││  ──────────────────────────────────────────────────                                                                 │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││  STEP OUTPUT                                                                                                        │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││                                                                                                                     │
│                                                                                               ││  {                                                                                                                  │
└───────────────────────────────────────────────────────────────────────────────────────────────┘│    "checkout_target": "origin/master",                                                                              │
┌─ @sase-25 · 13 ───────────────────────────────────────────────────────────────────────────────┐│    "meta_workspace": "100",                                                                                         │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││    "primary_workspace_dir": "/home/bryan/projects/github/sase-org/sase/",                                           │
│  │  ▎ sase-25 ───────────────────────────────────────────────────────  1 agent · 1 running    ││    "project_file": "/home/bryan/.sase/projects/sase/sase.gp",                                                       │
│  │  │  ▸ sase-25.7 ──────────────────────────────────────────────────  1 agent · 1 running    ││    "project_name": "sase",                                                                                          │
│  │  │  ⚡ ≡ sase (RUNNING) ×4 +3 ◆ sase-25.7 @sase-25 @sase-25.7  art ?              7m06s    ││    "should_release": false,                                                                                         │
│  │  │  ⚡   └─ 1/1 main (RUNNING) ◆ sase-25.7 @sase-25.7  art ?                      7m06s    ││    "workflow_name": "gh-sase",                                                                                      │
│  │  │  ⚡   └─ 1a/1 setup (DONE) ◆ sase-25.7 @sase-25.7 ▲#gh  art ?                  7m01s    ││    "workspace_dir": "/home/bryan/projects/github/sase-org/sase_100/",                                               │
│  │  │  ⚡   └─ 1b/1 prepare (DONE) ◆ sase-25.7 @sase-25.7 ▲#gh  art ?                7m01s    ││    "workspace_num": 100                                                                                             │
│  │  │  ⚡   └─ 1c/1 checkout (DONE) ◆ sase-25.7 @sase-25.7 ▲#gh  art ?               7m01s    ││  }                                                                                                                  │
│                                                                                               ││                                                                                                                     │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agent    ││                                                                                                                     │
│  │  ▸ sase-25 ──────────────────────────────────────────────────────────────────  2 agents    ││                                                                                                                     │
│  │  sase (WAITING) ◆ sase-25 @sase-25 @sase-25  art ?                                         ││                                                                                                                     │
│  │  ⚡ sase (WAITING) ◆ sase-25.8 @sase-25 @sase-25.8  art ?                                  ││                                                                                                                     │
│                                                                                               ││                                                                                                                     │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents    ││                                                                                                                     │
│  │  ▸ sase-25 ──────────────────────────────────────────────────────────────────  6 agents    ││                                                                                                                     │
│  │  ⚡ sase (DONE) ×5 ◆ sase-25.6 @sase-25 @sase-25.6  art ?              03:11:44 · 6m05s    ││                                                                                                                     │
│  │  ⚡ sase (DONE) ×5 ◆ sase-25.5 @sase-25 @sase-25.5  art ?             03:20:22 · 14m37s    ││                                                                                                                     │
│  │  ⚡ sase (DONE) ×5 ◆ sase-25.4 @sase-25 @sase-25.4  art ?             03:26:18 · 20m22s    ││                                                                                                                     │
│  │  ⚡ sase (DONE) ×5 ◆ sase-25.3 @sase-25 @sase-25.3  art ?              03:13:14 · 7m36s    ││                                                                                                                     │
│  │  ⚡ sase (DONE) ×5 ◆ sase-25.2 @sase-25 @sase-25.2  art ?             03:17:44 · 11m56s    ││                                                                                                                     │
│  │  ⚡ sase (DONE) ×5 ◆ sase-25.1 @sase-25 @sase-25.1  art ?              03:05:35 · 6m55s    ││                                                                                                                     │
└───────────────────────────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────── ● files ──────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```