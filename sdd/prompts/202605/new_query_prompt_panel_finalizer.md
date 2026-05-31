---
plan: sdd/tales/202605/new_query_prompt_panel_finalizer.md
---
 Whey does the "New Query" (see src/sase/xprompts/fork.yml xprompt workflow for context) not show at the bottom
of the agent prompt for this agent (see the `sase ace` snapshot below)? Can you help me diagnose the root cause of this
issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

### `sase ace` Snapshot

```
⭘                                                                                        sase ace (PID: 856718)
  CLs  │  Agents  │  AXE                                                                                                                                                         CODEX(gpt-5.5)  ■ IDLE  ✉ 0
 14 Agents [1 running · 13 done]   [siblings: 3 (~)]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 3s)
┌─ (untagged) · 13 [R1 D12] ────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                                      │
│  │  🤖 sase (RUNNING) ×6 @bp6.f1.f1.f1                🏃‍♂️ 4m32s    ││  - Final marker sweep over `AGENTS.md src/sase/amd tests/main` found no matches.                                                     │
│                                                                   ││  - `git diff --check` passed.                                                                                                        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  12 agents    ││                                                                                                                                      │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bqa           11:45:45 · 15m12s    ││  Using `sase_git_commit` because the post-completion finalizer explicitly requires committing the session’s workspace changes.       │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bp8           11:29:47 · 16m48s    ││  I’ll inspect the status first so I only include the intended files.                                                                 │
│  │  🤖 ✏️ home (TALE DONE) ×6 @bp7            11:15:39 · 4m52s    ││                                                                                                                                      │
│  │  🤖 ✏️ home (TALE DONE) ×6 @bp5            10:42:22 · 6m46s    ││  The required workspace changes match the finalizer list, including the new internal parser file. I’m checking the diff now and      │
│  │  🤖 ✏️ home (TALE DONE) ×6 @bp4           09:40:53 · 10m49s    ││  I’ll leave the static `chezmoi` advisory alone unless it is clearly part of this same implementation.                               │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bp1           09:05:58 · 13m58s    ││                                                                                                                                      │
│  │  🤖 ✏️ sase (TALE DONE) ×6 @bpy            08:52:48 · 8m32s    ││  The static `chezmoi` diff is a separate home `AGENTS.md` regeneration and the approved plan only called out the checked-in root     │
│  │  ▎ bp6 ──────────────────────────────────────────  3 agents    ││  `AGENTS.md`, so I’m not committing that advisory change. I’m committing the main workspace implementation files now.                │
│  │  │  🤖 ✏️ sase (TALE DONE) ×6 @bp6        11:13:07 · 29m14s    ││                                                                                                                                      │
│  │  │  ▸ bp6.f1 ────────────────────────────────────  2 agents    ││  The commit wrapper completed and ran its precommit step. I’m verifying the main branch state now, including whether anything        │
│  │  │  🤖 ✏️ sase (TALE DONE) ×8 @bp6.f1      11:24:52 · 9m53s    ││  remains ahead or dirty.                                                                                                             │
│  │  │  🤖 ✏️ sase (TALE DONE) ×8 @bp6.f1.f1  11:42:55 · 16m54s    ││                                                                                                                                      │
│  │  ▸ bp9 ──────────────────────────────────────────  2 agents    ││  Committed the main workspace changes:                                                                                               │
│  │  🤖 ✏️ home (TALE DONE) ×8 @bp9.f1         11:39:48 · 3m41s    ││                                                                                                                                      │
│  │  🤖 ✏️ home (TALE DONE) ×6 @bp9            11:21:36 · 6m38s    ││  `2ede642f2 feat: remove AMD marker comments`                                                                                        │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  Main repo status is clean and not ahead of `origin/master`. I left the advisory `chezmoi/home/AGENTS.md` change uncommitted         │
│                                                                   ││  because it is outside the approved plan and not required by the finalizer.                                                          │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  ---                                                                                                                                 │
│                                                                   ││                                                                                                                                  ▁▁  │
│                                                                   ││  # New Query                                                                                                                         │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  Can you now help me change "Tier 3" to "Tier 2" in the AGENTS.md files? Update the `sase amd init` command's code                   │
│                                                                   ││  accordingly and then run the command. Think this through thoroughly and create a plan using your `/sase_plan` skill                 │
│                                                                   ││  before making any file changes.                                                                                                     │
│                                                                   ││                                                                                                                                      │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  --- Work So Far ---                                                                                                                 │
│                                                                   ││  Using `sase_plan` because you explicitly asked for a plan before edits. I’ll read its instructions and the relevant repo            │
│                                                                   ││  context, then I’ll produce the plan before touching files.                                                                          │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  I’m gathering the AMD wording surface now: the templates/renderer, tests, and existing `AGENTS.md` occurrences. I’ll also load      │
│                                                                   ││  the repo’s short memory files so the plan reflects local conventions.                                                               │
│                                                                   ││                                                                                                                                  ▁▁  │
│                                                                   ││  The search shows the visible label lives in `src/sase/amd/_memory.py`, the parser accepts only the old Tier 3 heading today, and    │
│                                                                   ││  focused tests assert the old wording. I’m reading those specific files next so the plan can name the exact edits and                │
│                                                                   ││  verification.                                                                                                                       │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  I found two generated surfaces that matter for the command in this environment: the project `AGENTS.md` and the configured          │
│                                                                   ││  chezmoi source `/home/bryan/.local/share/chezmoi/home/AGENTS.md`. The chezmoi file is already dirty from the prior                  │
│                                                                   ││  marker-removal run, so the plan will call that out and avoid reverting it.                                                          │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  The plan file is written. I’m submitting it through `sase plan` now, then I’ll proceed with implementation against that plan.       │
│                                                                   ││                                                                                                                                      │
│                                                                   ││  --- Commit Finalizer Pass 1 of 2 ---                                                                                                │
│                                                                   ││  Advisory uncommitted changes detected in static sibling repositories:                                                               │
│                                                                   ││  - static sibling repo chezmoi: /home/bryan/.local/share/chezmoi                                                                     │
│                                                                   ││    - home/AGENTS.md                                                                                                                  │
└───────────────────────────────────────────────────────────────────┘│                                                                                                                                      │
                                                                     │  Sibling repository commit instructions:                                                                                             │
┌─ #read · 1 [D1] ──────────────────────────────────────────────────┐│  A post-completion finalizer has detected uncommitted changes. First decide whether the listed uncommitted changes were made by      │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent        ││  you in this session. If you did NOT make these changes, ignore this warning for the session; it will not appear again. If you       │
│  │  🤖 home (DONE) ×5 @reads.final-2  May 28 09:16 · 2m40s        ││                                                                                                                                      │
└───────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────── ● files  ● tools ──────────────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
```