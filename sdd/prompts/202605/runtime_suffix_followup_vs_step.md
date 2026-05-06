---
plan: sdd/tales/202605/runtime_suffix_followup_vs_step.md
---
 It looks like we made a mistake when implementing git commit 1e2faf4e40d9 (see the `sase ace` snapshot below for context). The `1/1.legend` step should have a live runtime, whereas the `main`
step should not. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (2)  │  AXE (8)                                                                                                                                                            CODEX(gpt-5.5)  ■ IDLE  ✉ 0
 Agents: 1/2   [view: collapsed]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 5 ─────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                                                                                      │
│  │  sase (RUNNING) ×6 @aed.r1.r1                    2m28s    ││  AGENT DETAILS                                                                                                                                       │
│  │  ▎ aee ──────────────────────────  1 agent · 1 running    ││                                                                                                                                                      │
│  │  │  ▸ aee.plan ──────────────────  1 agent · 1 running    ││  Project: sase                                                                                                                                       │
│  │  │  ≡ sase (LEGEND APPROVED) ×6 −3 @aee.plan    10m17s    ││  Workspace: #101                                                                                                                                     │
│  │  │    └─ 1/1.plan main (DONE) @aee.plan         10m05s    ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                                 │
│  │  │    └─ 1/1.legend sase (RUNNING) @aee.legend            ││  Model: CODEX(gpt-5.5)                                                                                                                               │
│  │  │    └─ 1e/1 diff (DONE) @aee.plan ▼#gh                  ││  VCS: GitHub                                                                                                                                         │
│                                                              ││  PID: 4004635                                                                                                                                        │
│                                                              ││  Name: @aee.legend                                                                                                                                   │
│                                                              ││  Timestamps: WAIT  | 2026-05-06 09:56:15                                                                                                             │
│                                                              ││              BEGIN | 2026-05-06 09:56:15                                                                                                             │
│                                                              ││                                                                                                                                                      │
│                                                              ││  ──────────────────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  AGENT PROMPT                                                                                                                                        │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││  Can you help me create a legend bead for the sdd/legends/202605/sase_mobile_mvp_legend.md plan file?                                                │
│                                                              ││                                                                                                                                                      │
│                                                              ││  First, read the legend plan file and count how many epics it proposes. Use that count as `<epic_count>` for the steps                               │
│                                                              ││  below.                                                                                                                                              │
│                                                              ││                                                                                                                                                      │
│                                                              ││  Create exactly one plan bead linked to the plan file using the `sase bead create` command's `--type plan(<plan_file>)`                              │
│                                                              ││  option, `--tier legend`, and `--epic-count <epic_count>`. Do not create phase beads or epic beads directly.                                         │
│                                                              ││                                                                                                                                                      │
│                                                              ││  Add the new bead ID to the plan file frontmatter as `legend_bead_id`, add `tier: legend`, and add                                                   │
│                                                              ││  `epic_count: <epic_count>`. Then commit the bead and plan-file metadata.                                                                            │
│                                                              ││                                                                                                                                                      │
│                                                              ││  After committing the legend bead metadata, run `sase bead work <legend_bead_id> --yes` (using the new legend bead's ID)                             │
│                                                              ││  to launch one epic-planning agent for each proposed epic and skip the launch confirmation prompt for this automated                                 │
│                                                              ││  kickoff.                                                                                                                                            │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││  ──────────────────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  AGENT REPLY                                                                                                                                         │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││  ─── 09:56:35 ─────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  I’ll use the SASE bead and commit skills here: first to follow the local bead workflow, then to commit via the required SASE commit path. I’m   ▄▄  │
│                                                              ││  going to load the repo memory and the relevant skill instructions before touching the plan file.                                                    │
│                                                              ││  ─── 09:56:44 ─────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  The bead workflow confirms this should be a single `legend` plan bead with an `epic_count`, and `sase bead work` is the right kickoff path. I’m     │
│                                                              ││  now reading the plan and current tree state so I can count epics and avoid mixing unrelated changes into the commit.                                │
│                                                              ││  ─── 09:56:52 ─────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  The plan proposes 7 epics, from “Host Gateway Foundation And Pairing” through “Background Delivery, Packaging, And End-To-End Hardening.” I’m       │
│                                                              ││  creating one legend-tier plan bead linked to the legend file with `--epic-count 7`.                                                                 │
│                                                              ││  ─── 09:57:01 ─────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  The new legend bead is `sase-26`. I’m adding the bead metadata into the legend plan frontmatter now, keeping the existing plan content              │
│                                                              ││  unchanged.                                                                                                                                          │
│                                                              ││  ─── 09:57:12 ─────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  Metadata is in place. Next I’m checking the exact file changes so the commit includes the new bead plus the plan frontmatter, and nothing           │
│                                                              ││  unrelated.                                                                                                                                          │
│                                                              ││                                                                                                                                                      │
└──────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ──────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```

### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `sase commit`)