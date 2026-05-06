---
plan: sdd/tales/202605/agent_runtime_aggregation.md
---
 The main agent/workflow entries runtime should be the sum of the runtimes of all of the child agent steps. It doesn't look like that is currently the case (see the `sase ace` snapshot below). It
looks like we continue to increment that runtime when waiting for user feedback (e.g. HITL or when a plan is proposed and the agent entry has a PLANNING status) when the correct thing to do would be to
pause that runtime until the user approves the plan. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (8 x15)  │  AXE (8)                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 15
 Agents: 1/23   [view: collapsed]   [group: by status (o)]   (auto-refresh in 2s)
┌─ (untagged) · 11 ─────────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running          ││                                                                                                                                         │
│  │  ▎ afg ─────────────────────────────────  1 agent · 1 running          ││  AGENT DETAILS                                                                                                                          │
│  │  │  ▸ afg.plan ─────────────────────────  1 agent · 1 running          ││                                                                                                                                         │
│  │  │  ≡ sase (PLAN APPROVED) ×6 −3 @afg.plan           🏃‍♂️ 6m27s          ││  Project: sase                                                                                                                          │
│  │  │    └─ 1/1.plan main (DONE) @afg.plan      19:48:47 · 2m56s          ││  Workspace: #102                                                                                                                        │
│  │  │    └─ 1/1.code sase (RUNNING) @afg.code           🏃‍♂️ 3m05s          ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                    │
│  │  │    └─ 1e/1 diff (DONE) @afg.plan ▼#gh                               ││  Model: CODEX(gpt-5.5)                                                                                                                  │
│                                                                           ││  VCS: GitHub                                                                                                                            │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents         ││  PID: 2733497                                                                                                                           │
│  │  sase (WAITING) @aez                                                   ││  Name: @afg.plan                                                                                                                        │
│  │  ▎ aed ────────────────────────────────────────────  3 agents          ││  Timestamps: BEGIN | 2026-05-06 19:45:51                                                                                                │
│  │  │  sase (WAITING) @aed                                                ││              PLAN  | 2026-05-06 19:48:47                                                                                                │
│  │  │  ▸ aed.r1 ──────────────────────────────────────  2 agents          ││              CODE  | 2026-05-06 19:49:12                                                                                                │
│  │  │  sase (WAITING) @aed.r1                                             ││                                                                                                                                         │
│  │  │  sase (WAITING) @aed.r1.r1                                          ││  ──────────────────────────────────────────────────                                                                                     │
│                                                                           ││                                                                                                                                         │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents          ││  AGENT XPROMPT                                                                                                                          │
│  │  sase (PLAN DONE) ×6 @afe.plan               19:52:12 · 9m40s          ││                                                                                                                                         │
│  │  sase (PLAN DONE) ×6 @afc.plan              19:36:01 · 11m30s          ││  #gh:sase Can you help me add a new `,g` (group/ungroup) keymap to the "Agents" tab of the `sase ace` TUI? When this key is pressed     │
│  │  sase (PLAN DONE) ×7 @afb.plan              19:32:06 · 15m15s          ││  we should merge all dynamic agent panels together, put the agent tag name                                                              │
│                                                                           ││  in the appropriate agent entries (so we know which ones are tagged in this view), and group/sort them as if they were always apart     │
│                                                                           ││  of the same panel (using the current grouping strategy). If the user                                                                   │
│                                                                           ││  presses `,g` again, they should be split out into different panels again based on their tags and the tag names should be removed       │
│                                                                           ││  from the agent rows. #plan                                                                                                             │
│                                                                           ││                                                                                                                                         │
│                                                                           ││  ──────────────────────────────────────────────────                                                                                     │
└───────────────────────────────────────────────────────────────────────────┘│                                                                                                                                         │
                                                                             │  AGENT PROMPT                                                                                                                           │
┌─ @chop · 1 ───────────────────────────────────────────────────────────────┐│                                                                                                                                         │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                 ││                                                                                                                                         │
│  │  [agent] refresh_docs (DONE) ×7 @afd  19:41:12 · 7m53s                 ││  Can you help me add a new `,g` (group/ungroup) keymap to the "Agents" tab of the `sase ace` TUI? When this key is                      │
└───────────────────────────────────────────────────────────────────────────┘│  pressed we should merge all dynamic agent panels together, put the agent tag name in the appropriate agent entries (so                 │
                                                                             │  we know which ones are tagged in this view), and group/sort them as if they were always apart of the same panel (using                 │
┌─ @mobile · 1 ─────────────────────────────────────────────────────────────┐│  the current grouping strategy). If the user presses `,g` again, they should be split out into different panels again                   │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                                 ││  based on their tags and the tag names should be removed from the agent rows. Think this through thoroughly and create a                │
│  │  sase (DONE) ×5 @aeu  17:55:53 · 1m06s                                 ││  plan using your `/sase_plan` skill before making any file changes.                                                                     │
└───────────────────────────────────────────────────────────────────────────┘│                                                                                                                                         │
                                                                             │                                                                                                                                         │
┌─ @sase-26 · 13 ───────────────────────────────────────────────────────────┐│  ──────────────────────────────────────────────────                                                                                     │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                                         │
│  │  ⚡ sase (RUNNING) ×4 ◆ @sase-26.6                         🏃‍♂️ 2m12s    ││  AGENT REPLY                                                                                                                            │
│                                                                           ││                                                                                                                                         │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agent    ││                                                                                                                                         │
│  │  ▸ sase-26 ──────────────────────────────────────────────  2 agents    ││  ─── PLANNER ─── 19:45:51 ─────────────────────────                                                                                     │
│  │  ⚡ sase (WAITING) ◆ @sase-26                                          ││                                                                                                                                         │
│  │  ⚡E sase (WAITING) ◆ @sase-26.7.0                                     ││  ─── 19:46:10 ─────────────────────────────────────                                                                                     │
│                                                                           ││                                                                                                                                         │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  10 agents    ││  I’ll use the `sase_plan` skill first, as requested, and read the project’s core memory before touching implementation files. Then      │
│  │  ▎ sase-26 ─────────────────────────────────────────────  10 agents    ││  I’ll inspect the ACE TUI code enough to make the plan concrete.                                                                    ▂▂  │
│  │  │  ▸ sase-26.6 ────────────────────────────────────────  10 agents    ││  ─── 19:46:17 ─────────────────────────────────────                                                                                     │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.9              19:49:56 · 14m39s    ││                                                                                                                                         │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.6              19:05:42 · 10m33s    ││  The key constraint I’m carrying forward is that keymap/config updates need to stay in sync with `src/sase/default_config.yml`, and     │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.5              18:54:46 · 11m05s    ││  this looks presentation/TUI scoped unless inspection shows grouping logic is shared elsewhere. I’m locating the Agents tab, key        │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.3              19:34:52 · 53m55s    ││  handling, and panel/grouping code now.                                                                                                 │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.8              18:39:25 · 11m17s    ││  ─── 19:46:29 ─────────────────────────────────────                                                                                     │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.7              18:43:23 · 15m01s    ││                                                                                                                                         │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.4              18:41:47 · 13m17s    ││  I found the relevant areas: `agent_panels`, `agent_groups`, Agents tab display/actions, row rendering, keymap registry, and            │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.2              18:40:47 · 12m19s    ││  existing tests around grouping/panels. I’m narrowing the plan around those existing seams rather than inventing a new backend          │
│  │  │  ⚡ sase (DONE) ×5 ◆ @sase-26.6.1              18:28:02 · 17m18s    ││  concept.                                                                                                                               │
│  │  │  ⚡E sase (EPIC CREATED) ×6 @sase-26.6.0.plan  18:13:21 · 12m23s    ││                                                                                                                                         │
└───────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────── ● files  ○ thinking ──────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```