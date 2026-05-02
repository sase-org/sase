---
plan: sdd/tales/202603/prompt_wrap_cursor_restore.md
---
Something is wrong with the auto-wrap functionality in the prompt input widget (see the `sase ace` snapshot below--I was
typing out `MUST` when this happened). Sometimes, the word/letter that was before my cursor winds up after the cursor
after the line gets wrapped / `prettier` is run on the prompt. Can you help me diagnose the root cause of this issue and
fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill.

### `sase ace` snapshot

```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (2)  │  AXE (6)                                                                                                                                                                            ■ IDLE  ✉ 2
 Agents: 1/1   [view: file]   (auto-refresh in 4s)
┌─────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  [agent] sase (RUNNING) (4 steps) @a    ││                                                                                                                                                                           │
│                                         ││  AGENT DETAILS                                                                                                                                                            │
│                                         ││                                                                                                                                                                           │
│                                         ││  Project: sase                                                                                                                                                            │
│                                         ││  Workspace: #101                                                                                                                                                          │
│                                         ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                                                      │
│                                         ││  Model: CLAUDE(opus)                                                                                                                                                      │
│                                         ││  VCS: GitHub                                                                                                                                                              │
│                                         ││  PID: 1829954                                                                                                                                                             │
│                                         ││  Name: @a                                                                                                                                                                 │
│                                         ││  Timestamps: BEGIN | 2026-03-26 14:14:24                                                                                                                                  │
│                                         ││                                                                                                                                                                           │
│                                         ││  ──────────────────────────────────────────────────                                                                                                                       │
│                                         ││                                                                                                                                                                           │
│                                         ││  AGENT XPROMPT                                                                                                                                                            │
│                                         ││                                                                                                                                                                           │
│                                         ││  #gh:sase Why is the "Agents" tab of the `sase ace` TUI showing "(1)" in the tab title when there is no agent running? Can you help me diagnose the root cause of this    │
│                                         ││  issue and fix it?                                                                                                                                                        │
│                                         ││                                                                                                                                                                           │
│                                         ││  ──────────────────────────────────────────────────                                                                                                                       │
│                                         ││                                                                                                                                                                           │
│                                         ││  AGENT PROMPT                                                                                                                                                             │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││  Why is the "Agents" tab of the `sase ace` TUI showing "(1)" in the tab title when there is no agent running? Can you                                                     │
│                                         ││  help me diagnose the root cause of this issue and fix it?                                                                                                                │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││  ──────────────────────────────────────────────────                                                                                                                       │
│                                         ││                                                                                                                                                                           │
│                                         ││  AGENT REPLY                                                                                                                                                              │
│                                         ││                                                                                                                                                                           │
│                                         ││  Waiting for agent response...                                                                                                                                            │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
│                                         ││                                                                                                                                                                           │
└─────────────────────────────────────────┘└─────────────────────────────────────────────────────────────────────────── ○ files  ○ thinking ───────────────────────────────────────────────────────────────────────────┘
┌─ Prompt ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 1  #gh:sase We start multiple agents under the same workflow when agents create plans or ask questions or when the user gives feedback on a plan. This works well mostly, but there is a problem with agent          │
│ 2  names.                                                                                                                                                                                                            │
│ 3                                                                                                                                                                                                                    │
│ 4  - We seem to try to give subsequent agents under the same workflow the same agent name as the original agent. This is NOT correct.                                                                                │
│ 5  - Instead, we should give the containing workflow the oringal name, and give each child agent the name `<name>.<N>`, where `<name>` is the original name and `<N>` is a positive integer which should start at    │
│ 6    1 and increment by 1 for every subsequent agent step.                                                                                                                                                           │
│ 7  - I'm not sure if we support naming workflow entries right now. So this might be something you need to flesh out. Keep in mind that, when a workflow only contains a single agent, the workflow and the agent     │
│ 8  UST  M                                                                                                                                                                                                            │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────  cancel ─┘

```
