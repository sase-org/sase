---
plan: sdd/tales/202605/persist_default_artifacts.md
---
 The sdd/research/202605/last_workflow_set_status_script_infographic.png image artifact file doesn't exist because the workspace #100 was cleared by the next agent to run I think (see the `sase ace` snapshot below for context--figure out what the real issue is if this isn't t). We should be storing these artifacts somewhere globally (e.g. in ~/.sase/) and the artifacts panel should point to those file paths when the user tries to open them. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents  │  AXE                                                                                                                                                    Override CLAUDE(opus) 14h14m  ■ IDLE  ✉ 1+2
 25 Agents [1 running · 24 done]   [view: collapsed]   [group: by date (o)]   (auto-refresh in 6s)
┌─ (untagged) · 14 [R1 D13] ────────────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━  14 agents · 1 running                         ││                                                                                                                                 │
│  │  ▎ 20:00 ───────────────────────  5 agents · 1 running                         ││  AGENT DETAILS                                                                                                                  │
│  │  │  sase (RUNNING) ×4 @l6                       🏃‍♂️ 34s                         ││                                                                                                                                 │
│  │  │  sase (DONE) ×7 @l4.r1.r1          20:19:21 · 2m13s                         ││  Project: sase                                                                                                                  │
│  │  │  sase (DONE) ×7 @l4.r1             20:17:01 · 4m06s                         ││  Workspace: #100                                                                                                                │
│  │  │  sase (DONE) ×5 @l4                20:12:51 · 3m09s                         ││  Embedded Workflows: gh(gh_ref=sase), resume(name=l4.r1)                                                                        │
│  │  │  sase (DONE) ×7 @lx.r1.code.r1     20:10:13 · 5m48s                         ││  Model: CODEX(gpt-5.5)                                                                                                          │
│  │  ▎ 19:00 ───────────────────────────────────  9 agents                         ││  VCS: GitHub                                                                                                                    │
│  │  │  sase (DONE) ×7 @l3.r1.r1          19:48:46 · 2m04s                         ││  PID: 2184030                                                                                                                   │
│  │  │  sase (DONE) ×7 @l3.r1             19:46:35 · 5m37s                         ││  Name: @l4.r1.r1                                                                                                                │
│  │  │  sase (TALE DONE) ×8 @lx.r1.plan   19:46:01 · 7m58s                         ││  Waiting for: l4.r1                                                                                                             │
│  │  │  sase (DONE) ×5 @l3                19:40:47 · 5m08s                         ││  Timestamps: WAIT  | 2026-05-11 20:09:47                                                                                        │
│  │  │  sase (TALE DONE) ×6 @lx.plan     19:35:06 · 15m02s                         ││              BEGIN | 2026-05-11 20:17:08                                                                                        │
│  │  │  sase (TALE DONE) ×8 @lu.r1.plan   19:17:13 · 5m47s                         ││              END   | 2026-05-11 20:19:21                                                                                        │
│  │  │  sase (TALE DONE) ×6 @lv.plan      19:14:59 · 9m54s                         ││  ARTIFACTS:                                                                                                                     │
│  │  │  sase (TALE DONE) ×6 @lw.plan      19:12:01 · 4m43s                         ││    • sdd/research/202605/last_workflow_set_status_script_infographic.png                                                        │
│  │  │  sase (TALE DONE) ×6 @lu.plan     19:10:03 · 11m05s                         ││                                                                                                                                 │
│                                                                                   ││  ──────────────────────────────────────────────────                                                                             │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  AGENT XPROMPT                                                                                                                  │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  %w:l4.r1 #gh:sase #resume:l4.r1 #research/image %m:gpt-5.5                                                                     │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  ──────────────────────────────────────────────────                                                                         ▄▄  │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  AGENT PROMPT                                                                                                                   │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  # Previous Conversation                                                                                                        │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  **User:**                                                                                                                      │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  #gh:sase Can you do some research to help me reason about the best way to implement a solution that satisfies the below        │
│                                                                                   ││  prompt?                                                                                                                        │
│                                                                                   ││                                                                                                                                 │
│                                                                                   ││  ### THE PROMPT                                                                                                                 │
│                                                                                   ││  Can you help me write a script that finds the last set of GitHub Actions workflows to fully run on the master/main branch      │
└───────────────────────────────────────────────────────────────────────────────────┘│  and tells me whether or not all workflows passed? If any failed, the script should tell me which ones and give me a tail of    │
                                                                                     │  their error ourputs if possible. Store new research in a markdown file under the sdd/research/ directory. Organize research    │
┌─ #chop · 5 [D5] ──────────────────────────────────────────────────────────────────┐│  files in YYYYMM month                                                                                                          │
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agents    ││  subdirectories.                                                                                                                │
│  │  ▎ 19:00 ────────────────────────────────────────────────────────  5 agents    ││                                                                                                                                 │
│  │  │  sase (DONE) ×7 @refresh_docs.sase.d5dd0eb28c1f.polish  19:51:10 · 9m34s    ││  **Assistant:**                                                                                                                 │
│  │  │  sase (DONE) ×9 @audit_bugs.sase.d5dd0eb28c1f           19:42:14 · 8m02s    ││                                                                                                                                 │
│  │  │  sase (DONE) ×5 @refresh_docs.sase.d5dd0eb28c1f.update  19:41:33 · 8m13s    ││  I have enough context — gh CLI is available, repo uses three workflows (CI, Deploy Docs, Publish to PyPI), and there's a       │
│  │  │  [agent] audit_recent_bugs (DONE) ×3 @lz                   19:34:13 · 7s    ││  clear convention for the research file. Writing the research doc now.                                                          │
│  │  │  [agent] refresh_docs (DONE) ×3 @ly                       19:33:22 · 16s    ││                                                                                                                                 │
└───────────────────────────────────────────────────────────────────────────────────┘│  Wrote `sdd/research/202605/last_workflow_set_status_script.md`. Headlines:                                                     │
                                                                                     │                                                                                                                                 │
┌─ #sase-2x · 6 [D6] ───────────────────────────────────────────────────────────────┐│  - **Use `gh` CLI** (already installed). `gh run list --branch <b> --json …` for metadata, `gh run view <id> --log-failed`      │
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents                          ││  for the error tail — that flag returns *only* failed steps' output, which is exactly what you want and avoids downloading      │
│  │  ▎ 20:00 ──────────────────────────────────  2 agents                          ││  the full log zip.                                                                                                              │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2x     20:04:23 · 3m49s                          ││  - **"Last set" needs a definition.** Recommend grouping runs by `headSha` and walking newest→oldest until you find a SHA       │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2x.5  20:00:30 · 12m22s                          ││  where every triggered run is `completed` (no `in_progress`/`queued`). This naturally handles the fact that `Publish to         │
│  │  ▎ 19:00 ──────────────────────────────────  4 agents                          ││  PyPI` only fires on tag pushes, while `CI` and `Deploy Docs` fire on every master push.                                        │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2x.3  19:47:59 · 12m46s                          ││  - **Pass = `success` or `skipped`** (and arguably `neutral`); `cancelled` and `timed_out` count as failures.                   │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2x.2  19:35:11 · 21m53s                          ││  - **Default branch should be detected**, not hard-coded — `sase` uses `master` but most repos are `main`.                      │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2x.4  19:24:04 · 10m50s                          ││  - **Implement in Python** (stdlib + `subprocess`/`json`), ~150 lines, room to grow into structured output for sase ace.        │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-2x.1  19:13:08 · 21m21s                          ││                                                                                                                                 │
└───────────────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────── ● files [1/2]  ○ thinking ───────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```