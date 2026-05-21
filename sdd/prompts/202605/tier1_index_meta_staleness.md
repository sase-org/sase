---
plan: sdd/tales/202605/tier1_index_meta_staleness.md
---
 The tier 1 (fast) agent reload strategy doesn't seem to track the "Timestamps:" entries in the agent metadata
panel on the "Agents" tab of the `sase ace` TUI. The BAD `sase ace` snapshot below shows what I saw before using the
`,y` keymap to do a full refresh. The GOOD `sase ace` snapshot below (notice the PLAN timestamp entry) shows what I see
after the full refresh. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

### `sase ace` Snapshot (BAD)

````
⭘                                                                                        sase ace (PID: 588377)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 2+2
 14 Agents [2 stopped · 2 running · 10 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 0s)
┌─ (untagged) · 11 [S2 R2 D7] ─────────────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────▌                                                           ─┐
│  ▲ Stopped ━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 awaiting                         ││                                                      ▌ Copied: Snapshot                                           │
│  │  ▸ axe ───────────────────────────  2 agents · 2 awaiting                         ││  AGENT DETAILS                                       ▌                                                            │
│  │  🤖 sase (PLAN) ×5 @axe.cdx           13:41:11 · ✋ 1m33s                         ││                                                                                                                   │
│  │  🎭 sase (PLAN) ×5 @axe.cld           13:44:05 · ✋ 4m30s                         ││  Project: sase                                                                                                    │
│                                                                                      ││  Workspace: #13                                                                                                   │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running                         ││  Model: CLAUDE(opus)                                                                                              │
│  │  🤖 sase (RUNNING) ×6 @axh.cdx.r1                🏃‍♂️ 1m22s                         ││  VCS: GitHub                                                                                                      │
│  │  🎭 sase (TALE APPROVED) ×6 @axa.cld            🏃‍♂️ 12m26s                         ││  PID: 729466                                                                                                      │
│                                                                                      ││  Name: @axe.cld                                                                                                   │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7 agents                         ││  Timestamps: START | 2026-05-21 13:39:28                                                                      ▇▇  │
│  │  🤖 sase (TALE DONE) ×6 @aw9            13:50:28 · 14m30s                         ││              RUN   | 2026-05-21 13:39:34                                                                          │
│  │  ▸ axg ────────────────────────────────────────  2 agents                         ││                                                                                                                   │
│  │  🤖 sase (DONE) ×5 @axg.cdx              13:47:45 · 3m01s                         ││  ──────────────────────────────────────────────────                                                               │
│  │  🎭 sase (DONE) ×5 @axg.cld              13:51:11 · 6m26s                         ││                                                                                                                   │
│  │  ▸ axh ────────────────────────────────────────  2 agents                         ││  AGENT XPROMPT                                                                                                    │
│  │  🤖 sase (DONE) ×5 @axh.cdx              13:50:46 · 4m04s                         ││                                                                                                                   │
│  │  🎭 sase (DONE) ×5 @axh.cld              13:48:30 · 1m56s                         ││  %name:axe.cld                                                                                                    │
│  │  ▸ axi ────────────────────────────────────────  2 agents                         ││  #gh:sase I just approved a "tale" plan for this agent (see the `sase ace` snapshot below), so both the root      │
│  │  🤖 sase (DONE) ×5 @axi.cdx              13:55:11 · 4m21s                         ││  entry and the "1/1-code" child agent step entry should have a status of "TALE APPROVED" instead of "RUNNING".▂▂  │
│  │  🎭 sase (DONE) ×5 @axi.cld              13:52:22 · 1m35s                         ││  Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a     │
│                                                                                      ││  plan using your `/sase_plan` skill before making any file changes.                                               │
│                                                                                      ││   %model:opus                                                                                                     │
│                                                                                      ││                                                                                                                   │
│                                                                                      ││  ### `sase ace` Snapshot                                                                                          │
│                                                                                      ││  ```                                                                                                              │
│                                                                                      ││  ⭘                                                                                        sase ace (PID:          │
│                                                                                      ││  588377)                                                                                                          │
│                                                                                      ││    CLs  │  Agents  │  AXE                                                                                         │
│                                                                                      ││  CODEX(gpt-5.5)  ■ IDLE  ✉ 2                                                                                      │
│                                                                                      ││   5 Agents [3 running · 1 unread · 1 done]   [view: file]   [group: by status (o)]   (auto-refresh in 8s)         │
│                                                                                      ││  ┌─ (untagged) · 6 [R3]                                                                                           │
│                                                                                      ││  ───────────────────────────────────────────────────────────────────┐┌────────────────────────────────────────    │
│                                                                                      ││  ────────────────────────────────────────────────────────────────────────┐                                        │
│                                                                                      ││  │  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents · 3 running                       ││                     │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │  ▸ aw9 ──────────────────────────────────  1 agent · 1 running                       ││  AGENT DETAILS      │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │  🤖 sase (RUNNING) ×6 −3 @aw9                         🏃‍♂️ 2m24s                       ││                     │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │    └─ 1/1-plan 🤖 main (DONE) ◆ @aw9-plan     13:35:09 · 1m55s                       ││  Project: sase      │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │    └─ 1/1-code 🤖 sase (RUNNING) ◆ @aw9-code            🏃‍♂️ 28s                       ││  Workspace: #11     │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │    └─ 1e/1 🐚 diff (DONE) ▼#gh                                                       ││  Model:             │
│                                                                                      ││  CODEX(gpt-5.5)                                                                                         │         │
│                                                                                      ││  │  │  ▸ axa ─────────────────────────────────  2 agents · 2 running                       ││  VCS: GitHub        │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │  🤖 sase (RUNNING) ×4 @axa.cdx                        🏃‍♂️ 1m01s                       ││  PID: 678957        │
└──────────────────────────────────────────────────────────────────────────────────────┘│  │                                                                                                                │
                                                                                        │  │  │  🎭 sase (RUNNING) ×4 @axa.cld                        🏃‍♂️ 1m05s                       ││  Name: @aw9-code    │
┌─ #chop · 3 [D3] ─────────────────────────────────────────────────────────────────────┐│  │                                                                                                                │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││  │                                                                                         ││  Bead: aw9-code     │
│  │  🤖 sase (DONE) ×9 @audit_bugs.sase.d0898495aad1              13:48:21 · 9m35s    ││  │                                                                                                                │
│  │  ▎ refresh_docs ────────────────────────────────────────────────────  2 agents    ││  │                                                                                         ││  Timestamps:        │
│  │  │  ▸ refresh_docs.sase ────────────────────────────────────────────  2 agents    ││  START | 2026-05-21 13:37:53                                                                       │              │
│  │  │  🤖 sase (DONE) ×7 @refresh_docs.sase.942645d037e3.polish  13:35:27 · 6m48s    ││  │                                                                                         ││              RUN    │
│  │  │  🤖 sase (DONE) ×5 @refresh_docs.sase.942645d037e3.update  13:28:32 · 7m08s    ││                                                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────── ○ files  ● tools ─────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
````

### `sase ace` Snapshot (GOOD)

````
⭘                                                                                        sase ace (PID: 588377)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 2+2
 14 Agents [2 stopped · 2 running · 10 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 11 [S2 R2 D7] ─────────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▲ Stopped ━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 awaiting                         ││                                                                                                                   │
│  │  ▸ axe ───────────────────────────  2 agents · 2 awaiting                         ││  AGENT DETAILS                                                                                                    │
│  │  🤖 sase (PLAN) ×5 @axe.cdx           13:41:11 · ✋ 1m33s                         ││                                                                                                                   │
│  │  🎭 sase (PLAN) ×5 @axe.cld           13:44:05 · ✋ 4m30s                         ││  Project: sase                                                                                                    │
│                                                                                      ││  Workspace: #13                                                                                                   │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running                         ││  Model: CLAUDE(opus)                                                                                              │
│  │  🤖 sase (RUNNING) ×6 @axh.cdx.r1                🏃‍♂️ 1m17s                         ││  VCS: GitHub                                                                                                      │
│  │  🎭 sase (TALE APPROVED) ×6 @axa.cld            🏃‍♂️ 12m21s                         ││  PID: 729466                                                                                                      │
│                                                                                      ││  Name: @axe.cld                                                                                                   │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7 agents                         ││  Timestamps: START | 2026-05-21 13:39:28                                                                      ▇▇  │
│  │  🤖 sase (TALE DONE) ×6 @aw9            13:50:28 · 14m30s                         ││              RUN   | 2026-05-21 13:39:34                                                                          │
│  │  ▸ axg ────────────────────────────────────────  2 agents                         ││              PLAN  | 2026-05-21 13:44:05                                                                          │
│  │  🤖 sase (DONE) ×5 @axg.cdx              13:47:45 · 3m01s                         ││                                                                                                                   │
│  │  🎭 sase (DONE) ×5 @axg.cld              13:51:11 · 6m26s                         ││  ──────────────────────────────────────────────────                                                               │
│  │  ▸ axh ────────────────────────────────────────  2 agents                         ││                                                                                                                   │
│  │  🤖 sase (DONE) ×5 @axh.cdx              13:50:46 · 4m04s                         ││  AGENT XPROMPT                                                                                                    │
│  │  🎭 sase (DONE) ×5 @axh.cld              13:48:30 · 1m56s                         ││                                                                                                                   │
│  │  ▸ axi ────────────────────────────────────────  2 agents                         ││  %name:axe.cld                                                                                                    │
│  │  🤖 sase (DONE) ×5 @axi.cdx              13:55:11 · 4m21s                         ││  #gh:sase I just approved a "tale" plan for this agent (see the `sase ace` snapshot below), so both the root  ▂▂  │
│  │  🎭 sase (DONE) ×5 @axi.cld              13:52:22 · 1m35s                         ││  entry and the "1/1-code" child agent step entry should have a status of "TALE APPROVED" instead of "RUNNING".    │
│                                                                                      ││  Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a     │
│                                                                                      ││  plan using your `/sase_plan` skill before making any file changes.                                               │
│                                                                                      ││   %model:opus                                                                                                     │
│                                                                                      ││                                                                                                                   │
│                                                                                      ││  ### `sase ace` Snapshot                                                                                          │
│                                                                                      ││  ```                                                                                                              │
│                                                                                      ││  ⭘                                                                                        sase ace (PID:          │
│                                                                                      ││  588377)                                                                                                          │
│                                                                                      ││    CLs  │  Agents  │  AXE                                                                                         │
│                                                                                      ││  CODEX(gpt-5.5)  ■ IDLE  ✉ 2                                                                                      │
│                                                                                      ││   5 Agents [3 running · 1 unread · 1 done]   [view: file]   [group: by status (o)]   (auto-refresh in 8s)         │
│                                                                                      ││  ┌─ (untagged) · 6 [R3]                                                                                           │
│                                                                                      ││  ───────────────────────────────────────────────────────────────────┐┌────────────────────────────────────────    │
│                                                                                      ││  ────────────────────────────────────────────────────────────────────────┐                                        │
│                                                                                      ││  │  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents · 3 running                       ││                     │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │  ▸ aw9 ──────────────────────────────────  1 agent · 1 running                       ││  AGENT DETAILS      │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │  🤖 sase (RUNNING) ×6 −3 @aw9                         🏃‍♂️ 2m24s                       ││                     │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │    └─ 1/1-plan 🤖 main (DONE) ◆ @aw9-plan     13:35:09 · 1m55s                       ││  Project: sase      │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │    └─ 1/1-code 🤖 sase (RUNNING) ◆ @aw9-code            🏃‍♂️ 28s                       ││  Workspace: #11     │
│                                                                                      ││  │                                                                                                                │
│                                                                                      ││  │  │    └─ 1e/1 🐚 diff (DONE) ▼#gh                                                       ││  Model:             │
│                                                                                      ││  CODEX(gpt-5.5)                                                                                         │         │
│                                                                                      ││  │  │  ▸ axa ─────────────────────────────────  2 agents · 2 running                       ││  VCS: GitHub        │
│                                                                                      ││  │                                                                                                                │
└──────────────────────────────────────────────────────────────────────────────────────┘│  │  │  🤖 sase (RUNNING) ×4 @axa.cdx                        🏃‍♂️ 1m01s                       ││  PID: 678957        │
                                                                                        │  │                                                                                                                │
┌─ #chop · 3 [D3] ─────────────────────────────────────────────────────────────────────┐│  │  │  🎭 sase (RUNNING) ×4 @axa.cld                        🏃‍♂️ 1m05s                       ││  Name: @aw9-code    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││  │                                                                                                                │
│  │  🤖 sase (DONE) ×9 @audit_bugs.sase.d0898495aad1              13:48:21 · 9m35s    ││  │                                                                                         ││  Bead: aw9-code     │
│  │  ▎ refresh_docs ────────────────────────────────────────────────────  2 agents    ││  │                                                                                                                │
│  │  │  ▸ refresh_docs.sase ────────────────────────────────────────────  2 agents    ││  │                                                                                         ││  Timestamps:        │
│  │  │  🤖 sase (DONE) ×7 @refresh_docs.sase.942645d037e3.polish  13:35:27 · 6m48s    ││  START | 2026-05-21 13:37:53                                                                       │              │
│  │  │  🤖 sase (DONE) ×5 @refresh_docs.sase.942645d037e3.update  13:28:32 · 7m08s    ││                                                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────── ○ files  ● tools ─────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
````