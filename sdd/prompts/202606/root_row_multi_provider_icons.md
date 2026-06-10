---
plan: sdd/tales/202606/root_row_multi_provider_icons.md
---
 When a root entry is associated with child agent entries that use different LLM providers, we should show all of the associated LLM provider icons on the root agent row instead of just the icon associated with the first agent's provider. For example, in the `sase ace` snapshot below, the "51.f1" agent row should have the Claude icon and the Codex icon (in that order, since the claude model ran first). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.



### `sase ace` Snapshot
```
⭘                                                                                        sase ace (PID: 2917671)
  PRs  │  Agents  │  AXE                                                                                                                                Override CLAUDE(claude-fable-5) 286h55m  ■ IDLE  ✉ 0
 7 Agents [1 running · 6 done]   [siblings: 3 (~)]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 10 [R1 D6] ────────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                       │
│  │  ▎ 51 ───────────────────────────────────────────────  1 agent · 1 running    ││  Name: @51.f1                                                                                                         │
│  │  │  ▸ 51.f1 ─────────────────────────────────────────  1 agent · 1 running    ││  Project: sase                                                                                                        │
│  │  │  ≡ 🎭 ✏️ sase (TALE APPROVED) ×8 −5 @51.f1                     🏃‍♂️ 4m02s    ││  Workspace: #10                                                                                                       │
│  │  │    └─ 1/1--plan 🎭 ✏️ main (DONE) @51.f1--plan         10:00:49 · 3m25s    ││  Embedded Workflows: gh(gh_ref=sase), fork(name=51)                                                                   │
│  │  │    └─ 1/1--code 🤖 sase (TALE APPROVED) @51.f1--code             🏃‍♂️ 37s    ││  Model: CLAUDE(claude-fable-5)                                                                                        │
│  │  │    └─ 1g/1 🐚 ✏️ diff (DONE) ▼#gh                                          ││  VCS: GitHub                                                                                                          │
│                                                                                  ││  PID: 2957753                                                                                                         │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents    ││  Timestamps: START | 2026-06-10 09:57:14                                                                              │
│  │  🎭 ✏️ sase (TALE DONE) ×6 @54                           09:32:36 · 11m01s    ││              RUN   | 2026-06-10 09:57:24                                                                              │
│  │  🎭 ✏️ sase (TALE DONE) ×6 @53                           09:42:11 · 30m31s    ││              PLAN  | 2026-06-10 10:00:49                                                                              │
│  │  🤖 ✏️ sase (DONE) ×5 @52                                 09:02:02 · 7m56s    ││              CODE  | 2026-06-10 10:01:43                                                                              │
│  │  🎭 ✏️ sase (TALE DONE) ×6 @51                           09:11:58 · 15m23s    ││  Artifacts:                                                                                                           │
│  │  🎭 ✏️ sase (TALE DONE) ×6 @50                           09:21:01 · 22m28s    ││    • sdd/tales/202606/tui_perf_background_tasks.md                                                                    │
│  │  🤖 ✏️ sase (DONE) ×5 @4y                                 08:44:38 · 5m22s    ││                                                                                                                       │
│                                                                                  ││  ──────────────────────────────────────────────────                                                                   │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  MEMORY READS                                                                                                         │
│                                                                                  ││  1 reads · 1 files · last 09:58:46                                                                                    │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││    09:58:46  long/tui_perf.md  ↩ frontmatter                                                                          │
│                                                                                  ││              ↳ Planning an update to add background-task guidance for slow TUI work; need current                     │
│                                                                                  ││                content to integrate the new rule                                                                      │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  ──────────────────────────────────────────────────                                                                   │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  AGENT XPROMPT                                                                                                        │
│                                                                                  ││                                                                                                                   ▇▇  │
│                                                                                  ││  #gh:sase #fork:51 Can you now help me also mention the option of using background tasks (see recent commits that     │
│                                                                                  ││  moved agent cleanup and agent launches to background tasks) for slow work that would have otherwise blocked the      │
│                                                                                  ││  TUI? #plan                                                                                                           │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  ──────────────────────────────────────────────────                                                                   │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  AGENT PROMPT                                                                                                         │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  # Previous Conversation                                                                                              │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  **User:**                                                                                                            │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  @sdd/tales/202606/tui_perf_memory_migration.md                                                                       │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  The above plan has been reviewed and approved. Implement it now.                                                     │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  **Assistant:**                                                                                                   ▃▃  │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  I'll implement the approved migration plan. Let me start by looking at the files involved.                           │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  Since I'm editing a generated-skill source, the Tier 2 rules require reviewing `memory/long/generated_skills.md`     │
│                                                                                  ││  via the audited read skill first.                                                                                    │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  All file changes are in. Now installing deps (required in this ephemeral workspace) before regenerating the          │
│                                                                                  ││  skills.                                                                                                              │
│                                                                                  ││                                                                                                                       │
│                                                                                  ││  `sase skills init --force` is the current equivalent, and it runs the chezmoi apply step itself.                     │
│                                                                                  ││                                                                                                                       │
└──────────────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────── ● files [1/2]  ● tools ────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
```