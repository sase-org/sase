---
plan: sdd/tales/202605/zorg_epic_linking.md
---
 The zorg-2 epic bead (see the `sase ace` snapshot below) should have been named zorg-1.1 since the agent should
have linked the epic bead to zorg-1 at the time of creation. Can you help me dig into what went wrong here and fix it
for next time? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (6 x2)  │  AXE (8)                                                                                                                                          Override CODEX(gpt-5.5) 4h53m  ■ IDLE  ✉ 1
 Agents: 6/8   [view: file]   [group: by status (o)]   (auto-refresh in 8s)
┌─ (untagged) · 8 ───────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                                                │
│  │  ⚡ zorg (RUNNING) ×4 ◆ zorg-2.1 @zorg-2.1               40s    ││  AGENT DETAILS                                                                                                                                 │
│                                                                    ││                                                                                                                                                │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agent    ││  Project: zorg                                                                                                                                 │
│  │  ▸ zorg-2 ────────────────────────────────────────  5 agents    ││  Workspace: #101                                                                                                                               │
│  │  ⚡ zorg (WAITING) ◆ zorg-2 @zorg-2                             ││  Embedded Workflows: gh(gh_ref=zorg)                                                                                                           │
│  │  ⚡ zorg (WAITING) ◆ zorg-2.5 @zorg-2.5                         ││  Model: CODEX(gpt-5.5)                                                                                                                         │
│  │  ⚡ zorg (WAITING) ◆ zorg-2.4 @zorg-2.4                         ││  VCS: GitHub                                                                                                                                   │
│  │  ⚡ zorg (WAITING) ◆ zorg-2.3 @zorg-2.3                         ││  Mode: ⚡ Auto-Approve                                                                                                                         │
│  │  ⚡ zorg (WAITING) ◆ zorg-2.2 @zorg-2.2                         ││  PID: 3401414                                                                                                                                  │
│                                                                    ││  Name: @zorg-2.1                                                                                                                               │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents    ││  Bead: zorg-2.1                                                                                                                                │
│  │  zorg (EPIC CREATED) ×6 @yd.plan            15:15:40 · 8m07s    ││  Timestamps: BEGIN | 2026-05-02 15:14:54                                                                                                       │
│  │  zorg (DONE) ×5 @xu                         15:00:55 · 3m12s    ││                                                                                                                                                │
│                                                                    ││  ──────────────────────────────────────────────────                                                                                            │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  AGENT XPROMPT                                                                                                                                 │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  #gh:zorg                                                                                                                                      │
│                                                                    ││  %name:zorg-2.1                                                                                                                                │
│                                                                    ││  %approve                                                                                                                                      │
│                                                                    ││  #bd/work_phase_bead:zorg-2.1                                                                                                                  │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  ──────────────────────────────────────────────────                                                                                            │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  AGENT PROMPT                                                                                                                                  │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  Can you complete the work for bead zorg-2.1? The bead has already been claimed for you (status=in_progress, assignee                          │
│                                                                    ││  set). Read its description and design file, do the work, commit, and close the bead. Do NOT close the parent epic. Do                         │
│                                                                    ││  NOT create new beads.                                                                                                                         │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  ──────────────────────────────────────────────────                                                                                            │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  AGENT REPLY                                                                                                                                   │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  ─── 15:15:07 ─────────────────────────────────────                                                                                            │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  I’ll use the bead workflow to inspect `zorg-2.1`, then the SASE commit workflow when the implementation is verified. I’ll keep the parent     │
│                                                                    ││  epic untouched and won’t create any new beads.                                                                                                │
│                                                                    ││  ─── 15:15:12 ─────────────────────────────────────                                                                                            │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  I’m reading the bead and current worktree state first so the implementation follows the recorded design and doesn’t step on unrelated         │
│                                                                    ││  edits.                                                                                                                                        │
│                                                                    ││  ─── 15:15:21 ─────────────────────────────────────                                                                                            │
│                                                                    ││                                                                                                                                                │
│                                                                    ││  `zorg-2.1` is the shared-spec phase under parent `zorg-2`; the bead description points into `../zorg`, so I’m checking the epic/design        │
│                                                                    ││  text and neighboring repo before editing.                                                                                                     │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
│                                                                    ││                                                                                                                                                │
└────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────── ○ files  ○ thinking ──────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```

### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `sase commit`, `commit workflow`)