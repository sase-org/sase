---
plan: sdd/plans/202605/known_project_xprompt_launch.md
---
 It looks like local xprompt workflow resolution (from the VCS xprompt workflow---`#gh:sase` in the `sase ace` snapshot below) is broken again. Can you help me diagnose the root cause of this
issue and (finally) fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (4 x8)  │  AXE (8)                                                                                                                                       Override CODEX(gpt-5.5) 26h34m  ■ IDLE  ✉ 6+7
 Agents: 2/12   [view: collapsed]   [group: by status (o)]   (auto-refresh in 1s)
┌─ (untagged) · 12 ─────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✗ Failed ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 failed    ││                                                                                                                                             │
│  │  [agent] sase/fix_just (FAILED) ×4                          59s    ││  AGENT DETAILS                                                                                                                              │
│                                                                       ││                                                                                                                                             │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││  Project: home                                                                                                                              │
│  │  home (RUNNING) @tt                                       2m45s    ││  Model: CODEX(gpt-5.5)                                                                                                                      │
│  │  ⚡ sase (RUNNING) ×4 ◆ sase-1u.6 @sase-1u.6                23s    ││  PID: 2507250                                                                                                                               │
│                                                                       ││  Name: @tt                                                                                                                                  │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agent    ││  Timestamps: BEGIN | 2026-05-01 17:31:52                                                                                                    │
│  │  ▸ sase-1u ──────────────────────────────────────────  2 agents    ││                                                                                                                                             │
│  │  ⚡ sase (WAITING) ◆ sase-1u.8 @sase-1u.8                          ││  ──────────────────────────────────────────────────                                                                                         │
│  │  ⚡ sase (WAITING) ◆ sase-1u @sase-1u.land                         ││                                                                                                                                             │
│                                                                       ││  AGENT XPROMPT                                                                                                                              │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7 agents    ││                                                                                                                                             │
│  │  sase (PLAN DONE) ×6 @ui.plan                  17:31:13 · 6m27s    ││  #gh:sase #!sase/fix_just                                                                                                                   │
│  │  ▸ sase-1u ──────────────────────────────────────────  6 agents    ││                                                                                                                                             │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1u.5 @sase-1u.5     17:34:05 · 10m33s    ││  ──────────────────────────────────────────────────                                                                                         │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1u.7 @sase-1u.7     17:15:42 · 17m20s    ││                                                                                                                                             │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1u.4 @sase-1u.4     17:23:30 · 25m03s    ││  AGENT PROMPT                                                                                                                               │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1u.3 @sase-1u.3     16:58:18 · 13m10s    ││                                                                                                                                             │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1u.2 @sase-1u.2      16:44:54 · 9m44s    ││                                                                                                                                             │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1u.1 @sase-1u.1     16:35:01 · 14m34s    ││  #gh:sase #!sase/fix_just                                                                                                                   │
│                                                                       ││                                                                                                                                             │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  ──────────────────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  AGENT REPLY                                                                                                                                │
│                                                                       ││                                                                                                                                             │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  ─── 17:32:06 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  I’ll inspect the workspace and the SASE project context first, then identify what `fix_just` is asking me to change.                       │
│                                                                       ││  ─── 17:32:13 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  I found the SASE tooling and cached project paths under `/home/bryan/projects/github`. I’m switching into the likely repository now and    │
│                                                                       ││  checking its local state before touching anything.                                                                                         │
│                                                                       ││  ─── 17:32:21 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  `#!sase/fix_just` looks like a SASE xprompt/workflow name rather than a plain file. I’m asking the local SASE CLI to expand it so I can    │
│                                                                       ││  follow the intended task instead of guessing from filenames.                                                                               │
│                                                                       ││  ─── 17:32:29 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  I found an existing implementation plan for this exact task at `plans/202603/fix_just_workflow.md`. I’m reading that plus the workflow     │
│                                                                       ││  and related tests before editing.                                                                                                          │
│                                                                       ││  ─── 17:32:40 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  The workflow file already has the March fix applied: it stages changes, escapes the backticks, and rebases before pushing. I’m going to    │
│                                                                       ││  run the same gates the workflow would run now, then fix whatever is actually failing in this workspace.                                    │
│                                                                       ││  ─── 17:32:51 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  A direct `sase xprompt explain '#!sase/fix_just'` fails with “Unknown workflow,” so the current issue is discovery/invocation, not the     │
│                                                                       ││  old `fix_fmt` shell body. I found a newer plan for exactly that failure and am reading the loader path now.                                │
│                                                                       ││  ─── 17:33:13 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                         ▁▁  │
│                                                                       ││  The installed code already contains the project-workspace fallback and the regression tests from the May plan. The workflow resolves       │
│                                                                       ││  when addressed as `sase/fix_just`; I’m checking the run path and then I’ll execute/verify the workflow behavior itself.                    │
│                                                                       ││  ─── 17:33:29 ─────────────────────────────────────                                                                                         │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  The targeted test run failed only because I invoked the system `pytest`, which does not have this repo’s dependencies (`rich`). I’m        │
│                                                                       ││  switching to the repo venv and running the focused regressions there.                                                                      │
│                                                                       ││                                                                                                                                             │
└───────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────── ○ files  ○ thinking ────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```