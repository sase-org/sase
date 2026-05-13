---
plan: sdd/tales/202605/agent_tier_merge_watermark.md
---
 #resume:t7.cdx.code.r1.code This is still happening (see the `sase ace` snapshot below). Can you help me diagnose the root cause of this issue and (finally) fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
  
### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents  │  AXE                                                                                                                                                                    CODEX(gpt-5.5)  ■ IDLE  ✉ 0
 2 Agents [2 running]   [view: file]   [group: by status (o)]   (auto-refresh in 8s)                                                                      ▌
┌─ (untagged) · 2 [R2] ─────────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────▌ Killed workflow (PID 860060)                              ─┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running                   ││                                                                            ▌                                                            │
│  │  [agent] 🤖 sase (RUNNING) @t8.cdx.code.r1    🏃‍♂️ 58s                   ││  AGENT DETAILS                                                                                                                          │
│  │  [agent] 🎭 sase (RUNNING) @t9.cld          🏃‍♂️ 8m48s                   ││                                                                                                                                         │
│                                                                           ││  Project: sase                                                                                                                          │
│                                                                           ││  Workspace: #100                                                                                                                        │
│                                                                           ││  Embedded Workflows: gh(gh_ref=sase), resume(name=t8.cdx.code)                                                                          │
│                                                                           ││  Model: CODEX(gpt-5.5)                                                                                                                  │
│                                                                           ││  VCS: GitHub                                                                                                                            │
│                                                                           ││  PID: 849273                                                                                                                            │
│                                                                           ││  Name: @t8.cdx.code.r1                                                                                                                  │
│                                                                           ││  Waiting for: t8.cdx.code                                                                                                               │
│                                                                           ││  Timestamps: START | 2026-05-13 10:26:29                                                                                                │
│                                                                           ││              RUN   | 2026-05-13 10:28:26                                                                                                │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  ──────────────────────────────────────────────────                                                                                     │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  AGENT XPROMPT                                                                                                                          │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  #gh:sase #resume:t8.cdx.code %w:t8.cdx.code Can you help me review the ~/.sase/plans/202605/bead_fast_path_vc_mode.md                  │
│                                                                           ││  plan file, which was produced to fix this same problem, and evaluate if any of the recommendations are still relevant?                 │
│                                                                           ││  If so, can you please create a /sase_plan to implement them.                                                                           │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  ──────────────────────────────────────────────────                                                                                     │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  AGENT PROMPT                                                                                                                           │
│                                                                           ││                                                                                                                                         │
│                                                                           ││                                                                                                                                     ▃▃  │
│                                                                           ││  # Previous Conversation                                                                                                                │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  **User:**                                                                                                                              │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  %model:gpt-5.5                                                                                                                         │
│                                                                           ││  #gh:sase @sdd/tales/202605/bead_closed_list_fix.md                                                                                     │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  The above plan has been reviewed and approved. Implement it now.                                                                       │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  **Assistant:**                                                                                                                         │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  I’ll read the approved plan and the repo’s short-term memory first, then inspect the relevant code paths before making edits.          │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  The worktree is clean. I found both the approved tale and its prompt; I’m loading the memory files plus the plan now so the            │
│                                                                           ││  implementation stays aligned with local conventions.                                                                                   │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  The plan targets the fast-path resolver only, with a focused regression around mixed current and primary stores. I’m going to read     │
│                                                                           ││  that resolver, the normal bead CLI location helper, and the existing fast-path tests before editing.                                   │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  The mismatch is exactly where the plan says: the fast path returns `primary/.sase/sdd/beads` before it ever checks for `cwd`’s         │
│                                                                           ││  `sdd/beads`. I’ll adjust that ordering and add the regression test for the mixed-store scenario.                                       │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  I’m making a small resolver change: when a project match is found, it will check the current checkout’s `sdd/beads` first, then        │
│                                                                           ││  fall back to the primary non-VC store, then the primary VC store. The write-command guard remains unchanged because it still keys      │
│                                                                           ││  off the resolved directory kind.                                                                                                       │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  The code and regression test are in place. I’m checking the diff, then I’ll run the focused fast-path test file before broader         │
│                                                                           ││  verification.                                                                                                                          │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  The focused pytest run hit the known stale-workspace problem from the memory note: imports are resolving from an uninstalled tree      │
│                                                                           ││  (`sase.ace.tui` is missing on the package object during test setup). I’m running `just install` now, then I’ll rerun the focused       │
│                                                                           ││                                                                                                                                         │
└───────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────── ○ files  ○ thinking ──────────────────────────────────────────────────────────┘
 / edit query                                                                                                                                                                                                  RUNNING


```

### Additional Requirements

- There are agent rows that are missing from the above snapshot. They disappeared for a few seconds and then came back. This seems to happen most often after killing or launching agents.