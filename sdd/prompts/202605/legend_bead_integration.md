---
plan: sdd/epics/202605/legend_bead_integration.md
---
 Can you help me improve sase's legend bead integration? 

- I want the integration to launch an agent with a name of the form `<prj>-<M>.<N>.0`, which use a prompt like the
  `sase ace` snapshot below, for each epic proposed by the legend plan file.
- These agents should (unlike the `sase ace` snapshot below) include the new `%epic` directive in their prompts so the
  plans they create get approved as epics automatically.
- All of these agents except for the first, should wait for the agent that lands the previous epic.
- These agents shouldn't be created until the agent that uses the `#bd/new_legend` xprompt (which will need updating)
  runs the `sase bead work <legend_bead_id>` command.
- The `#bd/new_legend` agent will also need specify the number of epics that need creation (we should add support for
  legend beads to store this count), so the legend integration knows how many agents to launch.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (17 x3)  │  AXE (8)                                                                                                                                        Override CODEX(gpt-5.5) 7h6m  ■ IDLE  ✉ 1+3
 Agents: 17/20   [view: file]   [group: by status (o)]   (auto-refresh in 3s)
┌─ (untagged) · 20 ──────────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents · 4 running    ││                                                                                                                                            │
│  │  sase (PLAN APPROVED) ×6 @zx.plan                          4m48s    ││  AGENT DETAILS                                                                                                                             │
│  │  zorg (RUNNING) ×6 @zw.r1.r1                               1m25s    ││                                                                                                                                            │
│  │  ⚡ sase (RUNNING) ×4 ◆ sase-20.2 @sase-20.2                 38s    ││  Project: zorg                                                                                                                             │
│  │  ⚡ zorg (RUNNING) ×4 ◆ zorg-7.1.3 @zorg-7.1.3                6s    ││  Model: CODEX(gpt-5.5)                                                                                                                     │
│                                                                        ││  VCS: GitHub                                                                                                                               │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  13 agent    ││  PID: 1290730                                                                                                                              │
│  │  ▸ sase-20 ───────────────────────────────────────────  6 agents    ││  Name: @zorg-7.5.0                                                                                                                         │
│  │  ⚡ sase (WAITING) ◆ sase-20 @sase-20                               ││  Bead: zorg-7.5.0                                                                                                                          │
│  │  ⚡ sase (WAITING) ◆ sase-20.7 @sase-20.7                           ││  Waiting for: zorg-7.4                                                                                                                     │
│  │  ⚡ sase (WAITING) ◆ sase-20.6 @sase-20.6                           ││  Timestamps: WAIT  | 2026-05-04 12:56:27                                                                                                   │
│  │  ⚡ sase (WAITING) ◆ sase-20.5 @sase-20.5                           ││                                                                                                                                            │
│  │  ⚡ sase (WAITING) ◆ sase-20.4 @sase-20.4                           ││  ──────────────────────────────────────────────────                                                                                        │
│  │  ⚡ sase (WAITING) ◆ sase-20.3 @sase-20.3                           ││                                                                                                                                            │
│  │  ▸ zorg-7 ────────────────────────────────────────────  7 agents    ││  AGENT XPROMPT                                                                                                                             │
│  │  ⚡ zorg (WAITING) ◆ zorg-7.1 @zorg-7.1                             ││                                                                                                                                            │
│  │  ⚡ zorg (WAITING) ◆ zorg-7.1.5 @zorg-7.1.5                         ││  #gh:zorg %w:zorg-7.4 Can you help me implement epic #28 from the roadmap in the                                                           │
│  │  ⚡ zorg (WAITING) ◆ zorg-7.1.4 @zorg-7.1.4                         ││  sdd/legends/202605/zorg_dash_visual_refresh_1.md file? #epic Keep in mind that the phases listed in the                                   │
│  │  zorg (WAITING) ◆ zorg-7.5.0 @zorg-7.5.0                            ││  sdd/legends/202605/zorg_dash_visual_refresh_1.md file are only suggestions (you should make the final call on what                        │
│  │  zorg (WAITING) ◆ zorg-7.4.0 @zorg-7.4.0                            ││  phases to create). %n:zorg-7.5.0                                                                                                          │
│  │  zorg (WAITING) ◆ zorg-7.3.0 @zorg-7.3.0                            ││                                                                                                                                            │
│  │  zorg (WAITING) ◆ zorg-7.2.0 @zorg-7.2.0                            ││  ──────────────────────────────────────────────────                                                                                        │
│                                                                        ││                                                                                                                                            │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││  AGENT PROMPT                                                                                                                              │
│  │  ⚡ sase (DONE) ×5 ◆ sase-20.1 @sase-20.1       13:12:05 · 8m42s    ││                                                                                                                                            │
│  │  zorg (DONE) ×7 @zw.r1                          13:14:36 · 6m27s    ││  No prompt file found.                                                                                                                     │
│  │  ⚡ zorg (DONE) ×5 ◆ zorg-7.1.2 @zorg-7.1.2     13:11:25 · 5m37s    ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
│                                                                        ││                                                                                                                                            │
└────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────── ○ files  ○ thinking ────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```