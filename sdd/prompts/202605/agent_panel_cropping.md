---
plan: sdd/tales/202605/agent_panel_cropping.md
---
 There is no agent shown in the `#chop` dynamic agent panel (see the `sase ace` snapshot below). Also, the `(untagged)` panel should only be cropped (i.e. have a scrollbar) when it would take up more than half of the available height (otherwise, crop the other agent panels if necessary, but don't crop the `(untagged)` agent panel). Can you help me implement this change? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                        sase ace (PID: 816564)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 5+3
 31 Agents [2 running · 29 done]   [siblings: 1 (~)]   [view: file]   [group: by status (o)]   (auto-refresh in 6s)
┌─ (untagged) · 3 [R1 D2] ─────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━  1 agent · 1 running             ││                                                                                                                                           │
│  │  🤖 sase (RUNNING) ×4 @bj3              🏃‍♂️ 7s             ││  AGENT DETAILS                                                                                                                            │
│                                                              ││                                                                                                                                           │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents          ▃▃ ││  Project: sase                                                                                                                            │
│  │  ▸ bjn ────────────────────────────  2 agents             ││  Workspace: #13                                                                                                                           │
└──────────────────────────────────────────────────────────────┘│  Model: CODEX(gpt-5.5)                                                                                                                    │
                                                                │  VCS: GitHub                                                                                                                              │
┌─ #chop · 1 [R1] ─────────────────────────────────────────────┐│  PID: 3448070                                                                                                                             │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││  Name: @bhv.f1.f1                                                                                                                         │
└──────────────────────────────────────────────────────────────┘│  Waiting for: bhv.f1                                                                                                                      │
                                                                │  Timestamps: WAIT  | 2026-05-26 19:22:22                                                                                                  │
┌─ #read · 6 [D6] ─────────────────────────────────────────────┐│              RUN   | 2026-05-26 19:35:30                                                                                                  │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents         ││              DONE  | 2026-05-26 19:38:48                                                                                              ▇▇  │
│  │  ▸ bar ────────────────────────────────  3 agents         ││                                                                                                                                           │
│  │  ♊ sase (DONE) ×5 @bar.gem  May 24 13:55 · 1m03s         ││  STEP METADATA                                                                                                                            │
│  │  🤖 sase (DONE) ×5 @bar.cdx  May 24 13:58 · 3m36s         ││                                                                                                                                           │
│  │  🎭 sase (DONE) ×5 @bar.cld  May 24 13:57 · 2m30s         ││  Commit Message: chore: add SASE episodes research infographic                                                                            │
│  │  ▸ bas ────────────────────────────────  3 agents      ▄▄ ││  New Commit: 3130706ad                                                                                                                    │
│  │  ♊ sase (DONE) ×5 @bas.gem  May 24 13:59 · 1m30s         ││                                                                                                                                           │
└──────────────────────────────────────────────────────────────┘│  ──────────────────────────────────────────────────                                                                                       │
                                                                │                                                                                                                                           │
┌─ #research · 21 [D21] ───────────────────────────────────────┐│  AGENT XPROMPT                                                                                                                            │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  21 agents    ││                                                                                                                                           │
│  │  ▎ bh0 ─────────────────────────────────────  2 agents    ││  %w:bhv.f1 %g:research #gh:sase #fork:bhv.f1 #research/image %m:gpt-5.5                                                                   │
│  │  │  ▸ bh0.f1 ───────────────────────────────  2 agents    ││                                                                                                                                           │
│  │  │  🎭 sase (DONE) ×7 @bh0.f1     May 26 19:56 · 6m14s    ││  ──────────────────────────────────────────────────                                                                                       │
│  │  │  🤖 sase (DONE) ×7 @bh0.f1.f1  May 26 19:59 · 3m23s    ││                                                                                                                                           │
│  │  ▎ bhb ─────────────────────────────────────  2 agents    ││  AGENT PROMPT                                                                                                                             │
│  │  │  ▸ bhb.f1 ───────────────────────────────  2 agents    ││                                                                                                                                           │
│  │  │  🎭 sase (DONE) ×7 @bhb.f1     May 26 17:04 · 4m20s    ││                                                                                                                                           │
│  │  │  🤖 sase (DONE) ×7 @bhb.f1.f1  May 26 17:08 · 3m59s    ││  # Previous Conversation                                                                                                                  │
│  │  ▎ bhd ─────────────────────────────────────  2 agents    ││                                                                                                                                           │
│  │  │  ▸ bhd.f1 ───────────────────────────────  2 agents    ││  **User:**                                                                                                                                │
│  │  │  🎭 home (DONE) ×7 @bhd.f1     May 26 17:19 · 5m50s    ││                                                                                                                                           │
│  │  │  🤖 home (DONE) ×7 @bhd.f1.f1  May 26 17:23 · 3m53s    ││  %g:research #gh:sase Can you do some research with the goal of guiding a new user through how they should use sase episodes (see the     │
│  │  ▎ bhe ─────────────────────────────────────  2 agents    ││  sase-45 epic bead for context)? Store new research in a markdown file under the sdd/research/ directory. Organize research files in      │
│  │  │  ▸ bhe.f1 ───────────────────────────────  2 agents    ││  YYYYMM month                                                                                                                             │
│  │  │  🎭 sase (DONE) ×7 @bhe.f1     May 26 17:36 · 3m56s    ││  subdirectories.                                                                                                                          │
│  │  │  🤖 sase (DONE) ×7 @bhe.f1.f1  May 26 17:40 · 3m53s    ││                                                                                                                                           │
│  │  ▎ bhu ─────────────────────────────────────  2 agents    ││  **Assistant:**                                                                                                                           │
│  │  │  ▸ bhu.f1 ───────────────────────────────  2 agents    ││                                                                                                                                           │
│  │  │  🎭 sase (DONE) ×7 @bhu.f1     May 26 19:34 · 4m17s    ││  I’ll use the SASE bead guidance first, then inspect the repo/docs around episodes and write a dated research note under                  │
│  │  │  🤖 sase (DONE) ×7 @bhu.f1.f1  May 26 19:38 · 3m52s    ││  `sdd/research/`.                                                                                                                         │
│  │  ▎ bhv ─────────────────────────────────────  2 agents    ││                                                                                                                                           │
│  │  │  ▸ bhv.f1 ───────────────────────────────  2 agents    ││  I’ve loaded the bead command rules. Next I’m pulling the epic details, project memory, and existing research/docs so the output          │
│  │  │  🎭 sase (DONE) ×7 @bhv.f1     May 26 19:35 · 5m59s    ││  matches the local SASE vocabulary instead of inventing a guide in isolation.                                                             │
│  │  │  🤖 sase (DONE) ×7 @bhv.f1.f1  May 26 19:38 · 3m17s    ││                                                                                                                                           │
│  │  ▎ bia ─────────────────────────────────────  3 agents    ││  The epic is specifically scoped to `sase memory episodes`, project-local storage under `~/.sase/projects/<project>/episodes/`, and       │
│  │  │  🤖 home (DONE) ×5 @bia        May 26 20:56 · 5m10s    ││  deterministic evidence-linked lessons. I’m checking the current implementation and older episode research now so the new note can        │
│  │  │  ▸ bia.f1 ───────────────────────────────  2 agents    ││  distinguish “what exists now” from “what should be taught to new users.”                                                                 │
│  │  │  🎭 home (DONE) ×7 @bia.f1     May 26 21:02 · 5m32s    ││                                                                                                                                           │
│  │  │  🤖 home (DONE) ×7 @bia.f1.f1  May 26 21:07 · 5m01s    ││  I have enough context to write the research note. The important current-state finding is that this checkout has Phase 1 episode          │
│  │  ▎ bjt ─────────────────────────────────────  3 agents    ││  wire/schema code, but `sase memory episodes` is not yet registered in the CLI; the guide should be framed as user guidance for the       │
│  │  │  🤖 sase (DONE) ×5 @bjt           08:03:18 · 10m19s    ││  sase-45 MVP as it lands, with today’s command examples clearly marked as target commands.                                                │
│  │  │  ▸ bjt.f1 ───────────────────────────────  2 agents ▄▄ ││                                                                                                                                           │
│  │  │  🎭 sase (DONE) ×7 @bjt.f1         08:09:07 · 5m43s    ││  I’m adding a single markdown research file in the existing `202605` research folder. It will capture the new-user mental model,          │
│  │  │  🤖 sase (DONE) ×7 @bjt.f1.f1      08:18:34 · 9m14s    ││  recommended first-run flow, CLI copy, safety rules, and doc/UX recommendations without touching memory files.                            │
│  │  ▎ bju ─────────────────────────────────────  3 agents    ││                                                                                                                                           │
└──────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────── ○ files  ● tools ─────────────────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
```