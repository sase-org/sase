---
plan: sdd/tales/202605/agents_tab_agent_explosion.md
---
 Something weird is happening on the "Agents" tab of the `sase ace` TUI (see the `sase ace` snapshot below). I
am seeing WAY too many agents (I know I only should see ~30 right now). Can you help me diagnose the root cause of this
issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


%xprompts_enabled:false

### `sase ace` Snapshot

````
⭘                                                                                                     sase ace
  CLs  │  Agents (23 x8)  │  AXE (8)                                                                                                                                      Override CODEX(gpt-5.5) 30h25m  ■ IDLE  ✉ 2+7
 Agents: 4/31   [view: file]   [group: by status (o)]   (auto-refresh in 9s)                                                                              ▌
┌─ (untagged) · 870 ──────────────────────────────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────▌ Prompt input cancelled                                    ─┐
│  ▲ Needs Attention ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  46 agents · 46 awaiting    ││                                                          ▌                                                            │
│  │  sase (PLANNING) ×5 @su                                                         3m15s    ││  AGENT DETAILS                                                                                                        │
│  │  sase (PLANNING) ×5 @st                                                         4m51s    ││                                                                                                                       │
│  │  sase (FAILED) ×5                                                              18h48m ▁▁ ││  Project: sase                                                                                                        │
│  │  sase (FAILED) ×5 @dd.claude.code                                              70h24m    ││  Embedded Workflows: gh(gh_ref=sase)                                                                                  │
│  │  cy.2 (FAILED)                                                                 71h39m    ││  Model: CODEX(gpt-5.5)                                                                                                │
│  │  sase (FAILED) ×5 @bf.claude.code                                  Apr 27 10:40 · 30s    ││  VCS: GitHub                                                                                                          │
│  │  sase (FAILED) ×5 @ao.code                                      Apr 26 00:43 · 48m47s    ││  PID: 1084425                                                                                                         │
│  │  sase (FAILED) ×5 @m.code                                          Apr 25 17:47 · 14s    ││  Name: @st                                                                                                            │
│  │  sase (FAILED) ×5                                                             164h52m    ││  Timestamps: BEGIN | 2026-05-01 13:38:55                                                                              │
│  │  sase (FAILED) ×5                                                             213h50m    ││              PLAN  | 2026-05-01 13:41:06                                                                              │
│  │  sase (FAILED) ×5                                                             215h06m    ││                                                                                                                       │
│  │  sase (FAILED) ×5                                                             235h07m    ││  ──────────────────────────────────────────────────                                                                   │
│  │  sase (FAILED) ×5 @p.code                                        Apr 20 19:13 · 3m29s    ││                                                                                                                       │
│  │  sase (FAILED) ×7                                                             286h47m    ││  AGENT XPROMPT                                                                                                        │
│  │  sase (FAILED) ×7                                                             329h18m    ││                                                                                                                       │
│  │  sase (FAILED) ×7 ◆ j.2 @j.2                                     Apr 10 14:01 · 2m44s    ││  #gh:sase It looks like `sase axe` is not starting WAITING agents when the agents they were waiting for complete      │
│  │  sase (FAILED) ×7                                                             548h22m    ││  (see the `sase ace` snapshot below). Can you help me diagnose the root cause of this issue                           │
│  │  sase (FAILED) ×7                                                             548h23m    ││  and fix it? #plan                                                                                                    │
│  │  sase (FAILED) ×5 ◆ b.2 @b.2                                     Mar 29 19:14 · 5m40s    ││                                                                                                                       │
│  │  sase (FAILED) ×8                                                             787h07m    ││  ### `sase ace` Snapshot                                                                                              │
│  │  sase (FAILED) ×5 ◆ z.2 @z.2                                     Mar 29 18:28 · 1m19s    ││  ```                                                                                                                  │
│  │  sase (FAILED) ×5 ◆ t.2 @t.2                                       Mar 29 17:51 · 11s    ││  ⭘                                                                                                     sase ace       │
│  │  sase (FAILED) ×5 ◆ k.2 @k.2                                     Mar 27 02:34 · 8m06s    ││    CLs  │  Agents (19 x8)  │  AXE (8)                                                                                 │
│  │  sase (FAILED) ×5 ◆ a.2 @a.2                                    Mar 26 21:45 · 27m47s    ││  Override CODEX(gpt-5.5) 30h30m  ■ IDLE  ✉ 7                                                                          │
│  │  sase (FAILED) ×5 ◆ c.2 @c.2                                     Mar 26 19:20 · 2m08s    ││   Agents: 24/27   [view: file]   [group: by status (o)]   (auto-refresh in 2s)                                        │
│  │  sase (FAILED) ×5                                                  Mar 26 14:28 · 43s    ││  ┌─ (untagged) · 27                                                                                                   │
│  │  sase (FAILED) ×5                                                  Mar 25 15:54 · 12s    ││  ──────────────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────    │
│  │  sase (FAILED)                                                  Mar 25 15:53 · 27m52s    ││  ───────────────────────────────────────────────────────────────────────────────────┐                                 │
│  │  sase (FAILED) ×6                                                  Mar 20 10:58 · 47s    ││  │  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                  │
│  │  unknown (FAILED) ×4                                                         1010h54m    ││  │                                                                                                                    │
│  │  unknown (FAILED) ×4                                                         1010h55m    ││  │  │  sase (PLAN APPROVED) ×6 @ss.plan                                  2m26s    ││  AGENT DETAILS                   │
│  │  unknown (FAILED) ×4                                                         1075h06m    ││  │                                                                                                                    │
│  │  ▸ d ─────────────────────────────────────────────────────────  3 agents · 3 awaiting    ││  │  │  ⚡ sase (RUNNING) ×4 ◆ redacted-plan-b.3 @redacted-plan-b.3                       1m59s    ││                                  │
│  │  sase (FAILED) ×5 @d.code                                       Apr 25 09:55 · 14m10s    ││  │                                                                                                                    │
│  │  sase (FAILED) ×7 ◆ d.2 @d.2                                      Apr 4 10:23 · 1m26s    ││  │                                                                                ││  Project: sase                   │
│  │  sase (FAILED) ×7 ◆ d.3 @d.3                                      Apr 3 15:52 · 3m29s    ││  │                                                                                                                    │
│  │  ▸ f ─────────────────────────────────────────────────────────  2 agents · 2 awaiting    ││  │  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  17 agent    ││  Model: CODEX(gpt-5.5)           │
│  │  sase (FAILED) ×5 @f.code                                          Apr 20 13:24 · 23s    ││  │                                                                                                                    │
│  │  sase (FAILED) ×7 @f.code                                          Apr 14 23:33 · 19s    ││  │  │  sase (WAITING) @sr                                                         ││  VCS: GitHub                     │
│  │  ▸ h ─────────────────────────────────────────────────────────  3 agents · 3 awaiting    ││  │                                                                                                                    │
│  │  sase (FAILED) ×7 @h.code                                        Apr 17 22:16 · 2m05s    ││  │  │  ▸ sase-1r ───────────────────────────────────────────────────  8 agents    ││  Mode: ⚡ Auto-Approve           │
│  │  sase (FAILED) ×7 ◆ h.3 @h.3                                    Apr 12 20:13 · 12m35s    ││  │                                                                                                                    │
│  │  sase (FAILED) ×7 ◆ h.2 @h.2                                        Apr 7 22:03 · 40s    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r @sase-1r.land                                  ││  PID: 756923                     │
│  │  ▸ i ─────────────────────────────────────────────────────────  4 agents · 4 awaiting    ││  │                                                                                                                    │
│  │  sase (FAILED) ×7 ◆ i.3 @i.3                                       Apr 13 16:11 · 41s    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r.9 @sase-1r.9                                   ││  Name: @sase-1r.3                │
│  │  sase (FAILED) ×7 ◆ i.2 @i.2                                      Apr 8 19:00 · 5m58s    ││  │                                                                                                                    │
│  │  dotfiles (FAILED) ×5 ◆ i.2 @i.2                                 Mar 30 12:27 · 8m23s    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r.8 @sase-1r.8                                   ││  Bead: sase-1r.3                 │
│  │  sase (FAILED) ×5 ◆ i.2 @i.2                                        Mar 30 10:55 · 3m    ││  │                                                                                                                    │
│  │  ▸ r ─────────────────────────────────────────────────────────  2 agents · 2 awaiting    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r.7 @sase-1r.7                                   ││  Waiting for: sase-1r.2          │
│  │  sase (FAILED) ×5 @r.claude.code                                   Apr 25 18:25 · 24s    ││  │                                                                                                                    │
│  │  sase (FAILED) ×5 ◆ r.2 @r.2                                       Mar 29 17:42 · 22s    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r.6 @sase-1r.6                                   ││  Timestamps: WAIT  |             │
│                                                                                             ││  2026-05-01 13:04:00                                                                                           │      │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents · 6 running    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r.5 @sase-1r.5                                   ││                                  │
│  │  ⚡ ~ (RUNNING) ×2 @pysplit.test_agent_loader_status_overrides                    26s    ││  │                                                                                                                    │
│  │  ⚡ sase (RUNNING) ×4 ◆ redacted-plan-b.3 @redacted-plan-b.3                                    8m32s    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r.4 @sase-1r.4                                   ││                                  │
│  │  ⚡ sase (RUNNING) ×4 ◆ redacted-plan-a.4 @redacted-plan-a.4                                    2m51s    ││  ──────────────────────────────────────────────────                                                                   │
│  │  ⚡ sase (RUNNING) ×4 ◆ sase-1r.3 @sase-1r.3                                    4m40s    ││  │                                                                                                                    │
│  │  ▸ ss ─────────────────────────────────────────────────────────  2 agents · 2 running    ││  │  │  ⚡ sase (WAITING) ◆ sase-1r.3 @sase-1r.3                                   ││                                  │
│  │  sase (RUNNING) ×4 @ss.coder                                                    5m23s    ││                                                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────── ○ files  ○ thinking ─────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
````

%xprompts_enabled:true