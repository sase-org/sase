---
plan: sdd/tales/202605/refresh_docs_validation.md
---
 Can you help me diagnose the root cause of this issue and fix it (see the `sase ace` snapshot below)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (5 x24)  │  AXE (9)                                                                                                                                                     CODEX(gpt-5.5)  ■ IDLE  ✉ 4+17
 29 Agents [3 hitl · 1 running · 1 waiting · 1 failed · 16 unread · 7 done]   [view: collapsed]   [group: by project (o)]   (auto-refresh in 1s)
┌─ (untagged) · 17 [H3 F1 U7 D6] ────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▌ sase ━━━━━━━━━━━━━━━━━━━━━━━━  17 agents · 1 failed · 3 awaiting    ││                                                                                                                                            │
│  │  [agent] refresh_docs (FAILED) @en                 00:15:00 · 4s    ││  WORKFLOW DETAILS                                                                                                                          │
│  │  sase (PLANNING) ×5 @em                      00:13:23 · 🙋 2m08s    ││                                                                                                                                            │
│  │  sase (EPIC CREATED) ×6 @el.plan             00:13:21 · 🎉 8m45s    ││  Workflow: refresh_docs                                                                                                                    │
│  │  sase (PLANNING) ×5 @eh                      23:56:45 · 🙋 3m51s    ││  ChangeSpec: sase                                                                                                                          │
│  │  sase (PLAN DONE) ×7 @ee.plan               23:33:32 · 🎉 11m43s    ││  Workspace: #103                                                                                                                           │
│  │  sase (DONE) ×5 @ed                            23:11:07 · 🎉 11s    ││  Model: CODEX(gpt-5.5)                                                                                                                     │
│  │  sase (PLAN DONE) ×6 @ec.plan               23:14:57 · 🎉 17m50s    ││  VCS: GitHub                                                                                                                               │
│  │  sase (PLAN DONE) ×6 @eb.plan               May 9 22:55 · 11m49s    ││  Status: FAILED                                                                                                                            │
│  │  sase (PLAN DONE) ×6 @ea.plan                   22:48:16 · 6m13s    ││  Timestamps: BEGIN | 2026-05-10 00:14:56                                                                                                   │
│  │  sase (PLAN DONE) ×6 @d9.plan                   22:42:50 · 5m50s    ││              END   | 2026-05-10 00:15:00                                                                                                   │
│  │  sase (PLAN DONE) ×6 @d7.plan                  22:39:37 · 10m55s    ││  PID: 3945239                                                                                                                              │
│  │  ▎ d6 ────────────────────────────────────────────────  2 agents    ││                                                                                                                                            │
│  │  │  sase (PLAN DONE) ×8 @d6.code.r1.plan     May 9 22:37 · 3m54s    ││  ERROR                                                                                                                                     │
│  │  │  sase (PLAN DONE) ×6 @d6.plan             May 9 22:26 · 5m42s    ││  Workflow 'refresh_docs' validation failed:                                                                                                │
│  │  ▎ ej ───────────────────────────────────  2 agents · 1 awaiting    ││    - Step 'launch_docs_agents' has output 'launched' but is never referenced                                                               │
│  │  │  sase (EPIC CREATED) ×6 @ej.cdx.plan      00:01:24 · 🎉 7m43s    ││                                                                                                                                            │
│  │  │  sase (PLANNING) ×5 @ej.cld            May 9 23:57 · 🙋 4m33s    ││  Traceback (most recent call last):                                                                                                        │
│  │  ▎ ek ────────────────────────────────────────────────  2 agents    ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/axe/run_agent_runner.py", line 305, in main                                    │
│  │  │  sase (DONE) ×7 @ek.r1                 May 9 23:53 · 🎉 2m04s    ││      exec_result = run_execution_loop(ctx, prompt)                                                                                         │
│  │  │  sase (DONE) ×5 @ek                    May 9 23:48 · 🎉 2m06s    ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/axe/run_agent_exec.py", line 574, in run_execution_loop                        │
│                                                                        ││      result = execute_workflow(                                                                                                            │
│                                                                        ││          anon_workflow.name,                                                                                                               │
│                                                                        ││      ...<5 lines>...                                                                                                                       │
│                                                                        ││          project=_resolve_workflow_project(ctx),                                                                                           │
│                                                                        ││      )                                                                                                                                     │
│                                                                        ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_runner.py", line 463, in execute_workflow                     │
│                                                                        ││      validate_workflow(workflow)                                                                                                           │
│                                                                        ││      ~~~~~~~~~~~~~~~~~^^^^^^^^^^                                                                                                           │
│                                                                        ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_validator.py", line 93, in validate_workflow                  │
│                                                                        ││      raise WorkflowValidationError(error_msg.rstrip())                                                                                     │
│                                                                        ││  sase.xprompt.workflow_models.WorkflowValidationError: Workflow 'refresh_docs' validation failed:                                          │
│                                                                        ││    - Step 'launch_docs_agents' has output 'launched' but is never referenced                                                               │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││  ──────────────────────────────────────────────────                                                                                        │
│                                                                        ││                                                                                                                                            │
└────────────────────────────────────────────────────────────────────────┘│  WORKFLOW STEPS                                                                                                                            │
                                                                          │                                                                                                                                            │
┌─ #sase-2n · 6 [U5 D1] ─────────────────────────────────────────────────┐│                                                                                                                                            │
│  ▌ sase ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents            ││  Error: Workflow 'refresh_docs' validation failed:                                                                                         │
│  │  ▎ sase-2n ───────────────────────────────────  6 agents            ││    - Step 'launch_docs_agents' has output 'launched' but is never referenced                                                               │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2n        00:30:55 · 7m10s            ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2n.5      00:23:35 · 🎉 2m            ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2n.4  00:21:30 · 🎉 10m39s            ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2n.3   00:10:45 · 🎉 3m50s            ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2n.2   00:06:46 · 🎉 3m31s            ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2n.1   00:03:10 · 🎉 4m31s            ││                                                                                                                                            │
└────────────────────────────────────────────────────────────────────────┘│                                                                                                                                            │
                                                                          │                                                                                                                                            │
┌─ #sase-2o · 6 [R1 W1 U4] ──────────────────────────────────────────────┐│                                                                                                                                            │
│  ▌ sase ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents · 1 running         ││                                                                                                                                            │
│  │  ▎ sase-2o ──────────────────────────  6 agents · 1 running         ││                                                                                                                                            │
│  │  │  ⚡ sase (WAITING) ◆ @sase-2o                                    ││                                                                                                                                            │
│  │  │  ⚡ sase (RUNNING) ×4 ◆ @sase-2o.5              🏃‍♂️ 3m48s         ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.4      00:42:44 · 🎉 8m09s         ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.3      00:44:12 · 🎉 9m39s         ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.2      00:34:27 · 🎉 9m12s         ││                                                                                                                                            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2o.1     00:25:07 · 🎉 12m21s         ││                                                                                                                                            │
└────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────────── ● files [1/2] ───────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```