---
plan: sdd/tales/202605/metadata_panel_dynamic_fields_header.md
---
 Can you help me add a nice header above dynamic fields that are shown on the agent metadata panel on the "Agents" tab of the `sase ace` TUI? For example, in the below `sase ace` snapshot, the header would go above the line starting with "Commit Message:". Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
  

### `sase ace` Snapshot
```
⭘                                                                                        sase ace (PID: 418255)
  CLs  │  Agents  │  AXE                                                                                                                                                                 CODEX(gpt-5.5)  ✉ 0
 19 Agents [2 running · 1 waiting · 16 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 13 [R1 D12] ───────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                                       │
│  │  🤖 sase (TALE APPROVED) ×6 @a64                  🏃‍♂️ 4m54s    ││  Project: sase                                                                                                                    ▂▂  │
│                                                                  ││  Workspace: #10                                                                                                                       │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  12 agents    ││  Model: CODEX(gpt-5.5)                                                                                                                │
│  │  🤖 sase (TALE DONE) ×6 @a6x              17:09:22 · 8m57s    ││  VCS: GitHub                                                                                                                          │
│  │  🤖 sase (TALE DONE) ×6 @a6w             16:53:03 · 10m57s    ││  PID: 394590                                                                                                                          │
│  │  🤖 sase (TALE DONE) ×6 @a6p             16:21:21 · 13m05s    ││  Name: @a6x                                                                                                                           │
│  │  🤖 sase (TALE DONE) ×6 @a6o                15:52:25 · 15m    ││  Timestamps: START | 2026-05-23 16:59:05                                                                                              │
│  │  🤖 sase (TALE DONE) ×7 @a6n             16:00:07 · 29m07s    ││              RUN   | 2026-05-23 16:59:10                                                                                              │
│  │  🤖 sase (TALE DONE) ×6 @a6m             16:05:54 · 28m53s    ││              PLAN  | 2026-05-23 17:01:47                                                                                              │
│  │  🤖 sase (TALE DONE) ×6 @a6l             15:42:12 · 13m56s    ││              CODE  | 2026-05-23 17:03:02                                                                                              │
│  │  🤖 sase (DONE) ×6 @a6g                  15:22:44 · 14m21s    ││              DONE  | 2026-05-23 17:09:22                                                                                              │
│  │  🎭 sase (TALE DONE) ×6 @a6e.1           14:57:22 · 35m31s    ││                                                                                                                                       │
│  │  ▎ sase-41 ─────────────────────────────────────  3 agents    ││  Commit Message: fix: align merged default mark-all-read keymap                                                                       │
│  │  │  ▸ sase-41.f1 ───────────────────────────────  3 agents    ││  New Commit: 96a895335                                                                                                                │
│  │  │  🤖 sase (DONE) ×5 @sase-41.f1         16:36:50 · 2m56s    ││                                                                                                                                       │
│  │  │  🤖 sase (DONE) ×5 @sase-41.f1.f1.f1   16:45:56 · 7m14s    ││  ──────────────────────────────────────────────────                                                                                   │
│  │  │  🎭 sase (DONE) ×5 @sase-41.f1.f1      16:38:36 · 1m37s    ││                                                                                                                                       │
│                                                                  ││  AGENT XPROMPT                                                                                                                        │
│                                                                  ││                                                                                                                                       │
│                                                                  ││  #gh:sase Can you help me start using `,u` as the trigger for the current `,U` keymap? #plan                                          │
│                                                                  ││                                                                                                                                       │
│                                                                  ││  ──────────────────────────────────────────────────                                                                               ▃▃  │
│                                                                  ││                                                                                                                                       │
│                                                                  ││  AGENT PROMPT                                                                                                                         │
│                                                                  ││                                                                                                                                       │
│                                                                  ││                                                                                                                                       │
│                                                                  ││  Can you help me start using `,u` as the trigger for the current `,U` keymap? Think this through thoroughly and create a              │
│                                                                  ││  plan using your `/sase_plan` skill before making any file changes.                                                                   │
│                                                                  ││                                                                                                                                       │
│                                                                  ││                                                                                                                                       │
│                                                                  ││  ──────────────────────────────────────────────────                                                                                   │
│                                                                  ││                                                                                                                                       │
│                                                                  ││  AGENT REPLY                                                                                                                          │
│                                                                  ││                                                                                                                                       │
│                                                                  ││                                                                                                                                       │
│                                                                  ││  ─── PLANNER ─── 16:59:10 ─────────────────────────                                                                                   │
│                                                                  ││                                                                                                                                       │
└──────────────────────────────────────────────────────────────────┘│  ─── 16:59:35 ─────────────────────────────────────                                                                                   │
                                                                    │                                                                                                                                       │
┌─ #read · 3 [D3] ─────────────────────────────────────────────────┐│  I’ll use the `sase_plan` skill first, then inspect the keymap path enough to produce a concrete plan before touching files. After    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents                 ││  that I’ll implement only if the plan points to a narrow, defensible change.                                                          │
│  │  ▸ a5h ────────────────────────────  3 agents                 ││  ─── 16:59:45 ─────────────────────────────────────                                                                                   │
│  │  ♊ sase (DONE) ×5 @a5h.gem  11:35:32 · 1m43s                 ││                                                                                                                                       │
│  │  🤖 sase (DONE) ×5 @a5h.cdx  11:37:20 · 3m35s                 ││  I’ve loaded the repo memory and the planning skill. The key warning for this task is that default keymap changes usually need        │
│  │  🎭 sase (DONE) ×5 @a5h.cld  11:34:56 · 1m17s                 ││  `src/sase/default_config.yml`, so I’m going to trace both default config and runtime keybinding resolution before writing the        │
└──────────────────────────────────────────────────────────────────┘│  plan file.                                                                                                                           │
                                                                    │  ─── 16:59:58 ─────────────────────────────────────                                                                                   │
┌─ #research · 3 [R1 W1 D1] ───────────────────────────────────────┐│                                                                                                                                       │
│  ▶ Running ━━━━━━━━━━━━━━━━━━  1 agent · 1 running               ││  The broad search shows the keymap system is centralized and already has tests around leader defaults. I’m narrowing now to the       │
│  │  🎭 sase (RUNNING) ×6 @a62.f1          🏃‍♂️ 2m38s               ││  exact `,U` action and checking whether `,u` is already occupied, because that decides whether this is an alias, a swap, or a         │
│                                                                  ││  conflict resolution.                                                                                                                 │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent              ││  ─── 17:01:02 ─────────────────────────────────────                                                                                   │
│  │  🤖 sase (WAITING) @a62.f1.f1                                 ││                                                                                                                                       │
│                                                                  ││  The source shows a real drift: the typed leader default and docs already say `,u`, but the packaged default config still sets        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent               ││  `mark_all_unread_done_agents_read: "U"`. That means a normal merged config can override the dataclass default back to `,U`, so       │
│  │  🤖 sase (DONE) ×5 @a62        17:36:20 · 9m15s               ││                                                                                                                                       │
└──────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────── ● files [1/2]  ● tools ────────────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
```