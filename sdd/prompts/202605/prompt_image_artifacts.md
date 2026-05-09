---
plan: sdd/tales/202605/prompt_image_artifacts.md
---
 Can you help me include any image file path reference as an ARTIFACTS field entry in the agent metadata panel on the "Agents" tab of the `sase ace` TUI? This image file should also be viewable from the artifacts panel (triggered via the `A` keymap). For example, in the below `sase ace` snapshot, the ~/.sase/telegram/images/20260509_080052_AgACAgEAAxkB.jpg file path should have been added as an ARTIFACTS field entry. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (2 x10)  │  AXE (8)                                                                                                                                                        CODEX(gpt-5.5)  ■ IDLE  ✉ 7
 Agents: 0 unread · 2 running · 12 total   [view: collapsed]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 4 ────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running     ││                                                                                                                                                   │
│  │  sase (RUNNING) ×4 @ar                            🏃‍♂️ 52s     ││  AGENT DETAILS                                                                                                                                    │
│  │  sase (PLAN APPROVED) ×6 @ap.plan               🏃‍♂️ 8m08s     ││                                                                                                                                                   │
│                                                                 ││  Project: sase                                                                                                                                    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents     ││  Workspace: #101                                                                                                                                  │
│  │  ▸ ak ────────────────────────────────────────  2 agents     ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                              │
│  │  sase (PLAN DONE) ×8 @ak.code.r1.plan  03:52:44 · 11m09s     ││  Model: CODEX(gpt-5.5)                                                                                                                            │
│  │  sase (PLAN DONE) ×6 @ak.plan          03:32:26 · 14m50s     ││  VCS: GitHub                                                                                                                                      │
│                                                                 ││  PID: 2234600                                                                                                                                     │
│                                                                 ││  Name: @ar                                                                                                                                        │
│                                                                 ││  Timestamps: BEGIN | 2026-05-09 04:00:55                                                                                                          │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  ──────────────────────────────────────────────────                                                                                               │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  AGENT XPROMPT                                                                                                                                    │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  %n:ar The user sent an image via Telegram with the following caption:                                                                            │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  #gh:sase The new sase.sh landing page text doesn't look good. Can you help me make this look better? #plan                                       │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  The image has been saved to: /home/bryan/.sase/telegram/images/20260509_080052_AgACAgEAAxkB.jpg                                                  │
│                                                                 ││  Please read the image file and respond to the user's request.                                                                                    │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  ──────────────────────────────────────────────────                                                                                               │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  AGENT PROMPT                                                                                                                                     │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  The user sent an image via Telegram with the following caption:                                                                                  │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  The new sase.sh landing page text doesn't look good. Can you help me make this look better? Think this through                                   │
│                                                                 ││  thoroughly and create a plan using your `/sase_plan` skill before making any file changes.                                                       │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  The image has been saved to: /home/bryan/.sase/telegram/images/20260509_080052_AgACAgEAAxkB.jpg Please read the image                            │
│                                                                 ││  file and respond to the user's request.                                                                                                          │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  ──────────────────────────────────────────────────                                                                                               │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  AGENT REPLY                                                                                                                                      │
│                                                                 ││                                                                                                                                                   │
└─────────────────────────────────────────────────────────────────┘│                                                                                                                                                   │
                                                                   │  ─── 04:01:17 ─────────────────────────────────────                                                                                               │
┌─ #blog · 3 ─────────────────────────────────────────────────────┐│                                                                                                                                                   │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││  I’ll use the `sase_plan` skill first because you explicitly asked for a plan before edits. I’m also going to inspect the screenshot and the      │
│  │  ▎ 260507 ─────────────────────────────────────  3 agents    ││  local landing-page files so the plan is tied to the actual UI rather than guessing.                                                              │
│  │  │  ▸ 260507.ajh ──────────────────────────────  3 agents    ││                                                                                                                                                   │
│  │  │  sase (DONE) ×5 @260507.ajh           May 7 17:21 · 6m    ││                                                                                                                                                   │
│  │  │  sase (DONE) ×7 @260507.ajh.r1.r1  May 7 17:35 · 6m35s    ││                                                                                                                                                   │
│  │  │  sase (DONE) ×7 @260507.ajh.r1     May 7 17:28 · 6m51s    ││                                                                                                                                                   │
└─────────────────────────────────────────────────────────────────┘│                                                                                                                                                   │
                                                                   │                                                                                                                                                   │
┌─ #sase-2g · 5 ──────────────────────────────────────────────────┐│                                                                                                                                                   │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agents      ││                                                                                                                                                   │
│  │  ▸ sase-2g ──────────────────────────────────  5 agents      ││                                                                                                                                                   │
│  │  ⚡ sase (PLAN DONE) ×6 @sase-2g.plan  03:41:56 · 9m30s      ││                                                                                                                                                   │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2g.4           03:32:05 · 9m      ││                                                                                                                                                   │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2g.3        03:23:02 · 7m09s      ││                                                                                                                                                   │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2g.2        03:15:46 · 9m11s      ││                                                                                                                                                   │
│  │  ⚡ sase (DONE) ×5 ◆ @sase-2g.1        03:06:28 · 7m28s      ││                                                                                                                                                   │
└─────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```