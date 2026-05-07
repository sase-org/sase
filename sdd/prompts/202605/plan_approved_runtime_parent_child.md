---
plan: sdd/tales/202605/plan_approved_runtime_parent_child.md
---
 We recently have tried to fix the runtime for PLAN APPROVED agents, but we can't seem to get the main agent/workflow entry to keep incrementing while fixing the runtime of the child step of the same name (see the `sase ace` snapshot below). Can you help me diagnose the root cause of this issue and fix it? Review recent, related sase agent chats before deciding on your solution. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (2 x10)  │  AXE (8)                                                                                                                                                     CODEX(gpt-5.5)  ■ IDLE  ✉ 1+11
 Agents: 4/12   [view: collapsed]   [group: by date (o)]   (auto-refresh in 2s)
┌─ (untagged) · 14 ────────────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  11 agents · 2 running    ││                                                                                                                                          │
│  │  ▎ 11:00 ───────────────────────────────────  4 agents · 1 running    ││  AGENT DETAILS                                                                                                                           │
│  │  │  sase (RUNNING) ×6 @afk.code.r1.code.r1                  🏃‍♂️ 35s    ││                                                                                                                                          │
│  │  │  sase (PLAN DONE) ×6 @agh.plan                 11:13:06 · 1m24s    ││  Project: sase                                                                                                                           │
│  │  │  sase (PLAN DONE) ×6 @age.plan                 11:02:31 · 1m44s    ││  Workspace: #100                                                                                                                         │
│  │  │  sase (PLAN DONE) ×6 @aga.plan                 10:59:40 · 2m52s    ││  Embedded Workflows: gh(gh_ref=sase), resume(name=aga)                                                                                   │
│  │  ▎ 10:00 ───────────────────────────────────  7 agents · 1 running    ││  Model: CODEX(gpt-5.5)                                                                                                                   │
│  │  │  ≡ sase (PLAN APPROVED) ×8 −5 @aga.r1.plan  11:14:08 · 🏃‍♂️ 3m03s    ││  VCS: GitHub                                                                                                                             │
│  │  │    └─ 1/1.plan main (DONE) @aga.r1.plan        11:14:08 · 3m03s    ││  PID: 1366174                                                                                                                            │
│  │  │    └─ 1/1.code sase (RUNNING) @aga.r1.code             🏃‍♂️ 3m37s    ││  Name: @aga.r1.plan                                                                                                                      │
│  │  │    └─ 1g/1 diff (DONE) @aga.r1.plan ▼#gh                           ││  Waiting for: aga                                                                                                                        │
│  │  │  sase (PLAN DONE) ×6 @aft.plan                 10:43:16 · 1m17s    ││  Timestamps: WAIT  | 2026-05-07 10:58:26                                                                                                 │
│  │  │  sase (PLAN DONE) ×8 @afk.code.r1.plan         10:36:27 · 2m47s    ││              BEGIN | 2026-05-07 11:11:04                                                                                                 │
│  │  │  sase (PLAN DONE) ×6 @afr.plan                 10:30:15 · 2m01s    ││              PLAN  | 2026-05-07 11:14:08                                                                                                 │
│  │  │  sase (PLAN DONE) ×6 @aeu.plan                 10:24:44 · 1m53s    ││              CODE  | 2026-05-07 11:15:23                                                                                                 │
│  │  │  sase (PLAN DONE) ×6 @aed.plan                 10:24:34 · 4m17s    ││                                                                                                                                          │
│  │  │  sase (PLAN DONE) ×6 @afk.plan                 10:26:42 · 1m06s    ││  ──────────────────────────────────────────────────                                                                                      │
│                                                                          ││                                                                                                                                      ▃▃  │
│                                                                          ││  AGENT XPROMPT                                                                                                                           │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  #gh:sase #resume:aga %w:aga I thought we recently added support for completing xprompt skills which start with "/", but that doesn't    │
│                                                                          ││  seem to be working from the prompt input widget. Can you help me diagnose the root cause of this issue and fix it? #plan                │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  ──────────────────────────────────────────────────                                                                                      │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  AGENT PROMPT                                                                                                                            │
│                                                                          ││                                                                                                                                          │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  # Previous Conversation                                                                                                                 │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  **User:**                                                                                                                               │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  %model:gpt-5.5                                                                                                                          │
│                                                                          ││  #gh:sase @sdd/tales/202605/directive_completion.md                                                                                      │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  The above plan has been reviewed and approved. Implement it now.                                                                        │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  **Assistant:**                                                                                                                          │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  I’ll load the repo instructions and the approved directive, then trace the relevant code paths before editing. Once the target files    │
│                                                                          ││  are clear, I’ll make the changes and run the focused checks.                                                                            │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  The directive is a focused TUI completion change: add a pure directive completion engine, then thread it through the existing prompt    │
│                                                                          ││  completion mixin and panel rendering. I’m locating the current completion modules and tests now so the new behavior follows the         │
│                                                                          ││  existing acceptance/navigation path.                                                                                                    │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  I found the completion path. The important constraint from the directive is already true in the generic extractor: `%` is a             │
│                                                                          ││  delimiter, so I’ll add a separate `%` scanner and call it before the generic token scan.                                                │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  I’m going to add the directive completion module plus focused tests first, then patch the mixin and renderer. The existing              │
│                                                                          ││  `CompletionCandidate` metadata hook is enough for directive row hints, so this should stay small and avoid changing the acceptance      │
│                                                                          ││  machinery.                                                                                                                              │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  The first patch missed the exact surrounding lines in `_file_completion.py`, so I’m splitting the edits into smaller patches against    │
└──────────────────────────────────────────────────────────────────────────┘│  the current file.                                                                                                                       │
                                                                            │                                                                                                                                          │
┌─ #blog · 1 ──────────────────────────────────────────────────────────────┐│  The code and tests are in place. I’m running the new directive tests plus the adjacent prompt completion tests now; if the workspace    │
│  Yesterday ━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                           ││  dependencies are stale I’ll install before the full repo check.                                                                         │
│  │  ▎ 17:00 ─────────────────────────  1 agent                           ││                                                                                                                                          │
│  │  │  sase (DONE) @aea_2  May 6 17:09 · 1m19s                           ││                                                                                                                                          │
└──────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```