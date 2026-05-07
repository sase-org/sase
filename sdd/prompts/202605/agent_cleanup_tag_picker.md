---
plan: sdd/tales/202605/agent_cleanup_tag_picker.md
---
 When we use the `X` keymap on the "Agents" tab of the `sase ace` TUI and press `t` to select an agent tag group to target for killing/dismissing, it looks like we show a lot of tags that are not currently represented on the tab (i.e. no agents are tagged using that tag). See the `sase ace` snapshot below for an example. Can you help me fix this so we only show tags that are used by >=1 agent on the agents tab? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (2 x24)  │  AXE (8)                                                                                                                                                     CODEX(gpt-5.5)  ■ IDLE  ✉ 1+21
 Agents: 1/26   [view: collapsed]   [group: by status (o)]   (auto-refresh in 6s)
┌─ (untagged) · 17 ────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▲ Needs Attention ━━━━━━━━━━━━━━━━  1 agent · 1 awaiting    ││                                                                                                                                                      │
│  │  sase (PLANNING) ×5 ◆ @aij.2          13:50:28 · 3m45s    ││  AGENT DETAILS                                                                                                                                       │
│                                                              ││                                                                                                                                                      │
│  ✗ Failed ━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 failed    ││  Project: sase                                                                                                                                       │
│  │  sase (FAILED) @aij                                       ││  Workspace: #101                                                                                                                                     │
│  │  sase (FAILED) @aij_2                                     ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                                 │
│                                                              ││  Model: CODEX(gpt-5.5)                                                                                                                           ▁▁  │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││  VCS: GitHub                                                                                                                                         │
│  │  sase (RUNNING) ×5 ◆ @aii.1           12:49:51 · 2m22s    ││  PID: 2009364                                                                                                                                        │
│                                                              ││  Name: @aij.2                                                                                                                                        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  13 agents    ││  Bead: aij.2                                                                                                                                         │
│  │  sase (PLAN DONE) ×6 @aij.1.plan     14:04:44 · 15m50s    ││  Waiting for: sase-2b                                                                                                                                │
│  │  sase (EPIC CREATED) ×6 @aii.2.plan   12:58:29 · 8m46s    ││  Timestamps: WAIT  | 2026-05-07 13:05:03                                                                                                             │
│  │  sase (PLAN DONE) ×6 @aig.plan       12:56:16 · 12m15s    ││              BEGIN | 2026-05-07 13:46:43                                                                                                             │
│  │  sase (DONE) ×5 @aif                  12:43:01 · 1m20s    ││              PLAN  | 2026-05-07 13:50:28                                                                                                             │
│  │  sase (PLAN DONE) ×6 @aie.plan        12:46:36 · 7m45s    ││                                                                                                                                                      │
│  │  sase (PLAN DONE) ×6 @aic.plan        12:22:53 · 5m15s    ││  ──────────────────────────────────────────────────                                                                                                  │
│  │  sase (DONE) ×5 @ahz                  12:16:26 · 4m37s    ││                                                                                                                                                      │
│  │  sase (PLAN DONE) ×6 @ahv.plan       12:09:44 · 18m09s    ││  AGENT XPROMPT                                                                                                                                       │
│  │  sase (PLAN DONE) ×6 @ahy.plan        11:52:40 · 6m06s    ││                                                                                                                                                      │
│  │  sase (PLAN DONE) ×6 @ahw.plan       11:59:56 · 14m36s    ││  %name:aij.2                                                                                                                                         │
│  │  ▎ aia ─────────────────────────────────────  3 agents    ││  #gh:sase %w:sase-2b It doesn't look like the LSP server that we recently implemented for xprompts ingests xprompts that are defined by plug-in      │
│  │  │  sase (DONE) ×5 @aia               12:16:31 · 7m25s    ││  repos. For example, my editor keeps complaining that 'gh' is not a valid xprompt. Can you help me fix this? #epic                                   │
│  │  │  ▸ aia.r1 ───────────────────────────────  2 agents    ││                                                                                                                                                      │
│  │  │  sase (DONE) ×7 @aia.r1            12:24:28 · 7m52s    ││  ──────────────────────────────────────────────────                                                                                                  │
│  │  │  sase (DONE) ×7 @aia.r1.r1         12:28:48 · 4m16s    ││                                                                                                                                                      │
│                                                              ││  AGENT PROMPT                                                                                                                                        │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││  It doesn't look like the LSP server that we recently implemented for xprompts ingests xprompts that are defined by                                  │
│                                                              ││  plug-in repos. For example, my editor keeps complaining that 'gh' is not a valid xprompt. Can you help me fix this? This                            │
│                                                              ││  is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep in                               │
│                                                              ││  mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` / `codex` /                                │
│                                                              ││  `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before                                  │
│                                                              ││  making any file changes.                                                                                                                            │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││  ──────────────────────────────────────────────────                                                                                                  │
│                                                              ││                                                                                                                                                      │
│                                                              ││  AGENT REPLY                                                                                                                                         │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
└──────────────────────────────────────────────────────────────┘│  ─── 13:47:01 ─────────────────────────────────────                                                                                                  │
                                                                │                                                                                                                                                      │
┌─ #blog · 2 ──────────────────────────────────────────────────┐│  I’ll use the `sase_plan` skill as requested and first gather the repo context around the LSP/xprompt/plugin boundary, without editing files.        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents                 ││  ─── 13:47:11 ─────────────────────────────────────                                                                                                  │
│  │  sase (DONE) ×5 @ahu     11:51:02 · 1m25s                 ││                                                                                                                                                      │
│  │  sase (DONE) @aea_2   May 6 17:09 · 1m19s                 ││  The plan skill only requires a submitted plan file, so I’m going to inspect the LSP implementation, xprompt loading path, and the plugin-repo       │
└──────────────────────────────────────────────────────────────┘│  memory before writing that handoff artifact.                                                                                                        │
                                                                │  ─── 13:47:28 ─────────────────────────────────────                                                                                                  │
┌─ #sase-2b · 7 ───────────────────────────────────────────────┐│                                                                                                                                                      │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7 agents      ││  The Python loaders already have plugin hooks for normal CLI/TUI xprompt discovery. The likely gap is that the Rust LSP receives only                │
│  │  ▸ sase-2b ───────────────────────────────  7 agents      ││  package/default config paths through env vars and has no plugin catalog input yet, so I’m checking both sides of that boundary now.                 │
│  │  ✦ ⚡ sase (DONE) ×5 ◆ @sase-2b     13:46:37 · 6m12s      ││  ─── 13:47:39 ─────────────────────────────────────                                                                                                  │
│  │  ✦ ⚡ sase (DONE) ×5 ◆ @sase-2b.6   13:40:23 · 6m47s      ││                                                                                                                                                      │
│  │  ✦ ⚡ sase (DONE) ×5 ◆ @sase-2b.5   13:28:52 · 4m16s      ││  The existing LSP plans confirm this is a cross-repo boundary issue: Python owns plugin discovery, while the Rust LSP consumes a catalog             │
│  │  ✦ ⚡ sase (DONE) ×5 ◆ @sase-2b.4   13:33:30 · 8m57s      ││  contract. I’m checking the current Rust catalog and server code so the phase plan targets the real implementation instead of guessing from old  ▅▅  │
│  │  ✦ ⚡ sase (DONE) ×5 ◆ @sase-2b.3   13:24:25 · 4m47s      ││  SDD notes.                                                                                                                                          │
│  │  ✦ ⚡ sase (DONE) ×5 ◆ @sase-2b.2   13:19:31 · 5m08s      ││  ─── 13:48:24 ─────────────────────────────────────                                                                                                  │
│  │  ✦ ⚡ sase (DONE) ×5 ◆ @sase-2b.1  13:14:13 · 16m52s      ││                                                                                                                                                      │
└──────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────────── ○ files  ○ thinking ─────────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `plugin`)