---
plan: sdd/tales/202605/artifact_panel_single_plan.md
---
 Can you help me fix the artifact panel so we never show multiple plan entries? In the below `sase ace` snapshot, for example, we should only show one instead of two and its path should be relative (i.e. sdd/tales/202605/unread_plan_done_jump.md). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (3 x19)  │  AXE (8)                                                                                                                                                     CODEX(gpt-5.5)  ■ IDLE  ✉ 2+15
 Agents: 3/22   [view: collapsed]   [group: by status (o)]   (auto-refresh in 8s)
┌─ (untagged) · 18 ─────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▲ Needs Attention ━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 awaiting    ││                                                                                                                                             │
│  │  sase (PLANNING) ×5 @ani                    17:12:51 · 🙋 1m32s    ││  AGENT DETAILS                                                                                                                              │
│                                                                       ││                                                                                                                                             │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││  Project: sase                                                                                                                              │
│  │  sase (PLAN APPROVED) ×8 @anl.code.r1.plan             🏃‍♂️ 5m39s    ││  Workspace: #100                                                                                                                            │
│                                                                       ││  Embedded Workflows: gh(gh_ref=sase), resume(name=anl.code)                                                                                 │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agen    ││  Model: CODEX(gpt-5.5)                                                                                                                      │
│  │  sase (WAITING) @anf                                               ││  VCS: GitHub                                                                                                                                │
│                                                                       ││  PID: 3365565                                                                                                                               │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  15 agents    ││  Name: @anl.code.r1.plan                                                                                                                    │
│  │  sase (PLAN DONE) ×6 @anl.plan                 17:03:32 · 7m50s    ││  Timestamps: BEGIN | 2026-05-08 17:07:18                                                                                                    │
│  │  sase (PLAN DONE) ×6 @anj.plan                    16:34:35 · 7m    ││              PLAN  | 2026-05-08 17:09:24                                                                                                    │
│  │  sase (PLAN DONE) ×6 @ang.plan                 16:05:59 · 4m28s    ││              CODE  | 2026-05-08 17:09:59                                                                                                    │
│  │  sase (PLAN DONE) ×6 @ane.plan                 16:00:15 · 7m19s    ││  DELTAS:                                                                                                                                    │
│  │  sase (PLAN DONE) ×6 @anc.plan                 15:49:19 · 6m22s    ││    ~ src/sase/ace/tui/actions/agents/_core.py  +8 ~3                                                                                        │
│  │  sase (PLAN DONE) ×6 @anb.plan                15:50:24 · 10m30s    ││    ~ src/sase/ace/tui/commands/context.py  +2 ~2                                                                                            │
│  │  sase (PLAN DONE) ×6 @ana.plan                 15:43:32 · 5m11s    ││    ~ tests/ace/tui/test_agent_unread_indicator.py  +18 ~2                                                                                   │
│  │  sase (DONE) ×5 @amz                           15:23:33 · 1m03s    ││    ~ tests/test_command_palette_wiring.py  +19 ~1                                                                                           │
│  │  ~ (DONE) ×2 @amy                                15:20:42 · 14s    ││  ARTIFACTS:                                                                                                                                 │
│  │  sase (DONE) ×5 @amx                           15:23:05 · 2m39s    ││    ~ sdd/tales/202605/unread_plan_done_jump.md                                                                                              │
│  │  sase (PLAN DONE) ×8 @amt.plan                14:37:56 · 10m27s   ╔════════════════════════════════════════════════════════════════════════╗                                                                  ▇▇  │
│  │  sase (DONE) ×5 @ams                           14:26:15 · 5m50s   ║                                                                        ║                                                                      │
│  │  sase (PLAN DONE) ×6 @amq.plan                14:21:52 · 13m37s   ║  Agent Artifacts  [3]                                                  ║                                                                      │
│  │  sase (PLAN DONE) ×6 @amp.plan                    14:05:47 · 5m   ║                                                                        ║                                                                      │
│  │  sase (PLAN DONE) ×6 @amo.plan                 14:05:40 · 7m19s   ║  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎  ║                                                                      │
│                                                                      ║  ▊ 1      Chat transcript  [chat]                                   ▎  ║x this issue. It looks like this is working for                       │
│                                                                      ║  ▊    ~/.sase/chats/202605/sase-ace_run-anl_code_r1_plan-260508_170 ▎  ║#plan                                                                 │
│                                                                      ║  ▊ 718.md                                                           ▎  ║                                                                      │
│                                                                      ║  ▊ 2      unread_plan_done_jump.md  [plan]                          ▎  ║                                                                      │
│                                                                      ║  ▊    ~/.sase/plans/202605/unread_plan_done_jump.md                 ▎  ║                                                                      │
│                                                                      ║  ▊ 3      unread_plan_done_jump.md  [plan]                          ▎  ║                                                                      │
│                                                                      ║  ▊    ...ts/github/sase-org/sase_100/sdd/tales/202605/unread_plan_d ▎  ║                                                                      │
│                                                                      ║  ▊ one_jump.md                                                      ▎  ║                                                                      │
│                                                                      ║  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎  ║                                                                      │
│                                                                      ║  ────────────────────────────────────────────────────────────────────  ║                                                                      │
│                                                                      ║                                                                        ║                                                                      │
│                                                                      ║   key/enter: open  m: mark  A: open all  j/k: navigate  q/esc: close   ║                                                                      │
│                                                                      ║                                                                        ║                                                                      │
│                                                                      ╚════════════════════════════════════════════════════════════════════════╝                                                                      │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  The above plan has been reviewed and approved. Implement it now.                                                                           │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  **Assistant:**                                                                                                                             │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  I’ll read the approved plan and the repo guidance first, then trace the affected code paths before editing.                                │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  The plan is scoped to the Agents TUI navigation layer and matching regression tests. I’m checking the local package notes and the          │
│                                                                       ││  existing unread-indicator tests so the patch follows the current panel model.                                                              │
│                                                                       ││                                                                                                                                             │
│                                                                       ││  The existing jump method sorts unread terminal rows by completion time and wraps from the current selected agent, but it only asks the     │
└───────────────────────────────────────────────────────────────────────┘│  focused panel for visible rows. I’m going to keep that ordering and change only the candidate source and refresh behavior around           │
                                                                         │  cross-panel jumps.                                                                                                                         │
┌─ #blog · 4 ───────────────────────────────────────────────────────────┐│                                                                                                                                             │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents                 ││  I’m editing `_core.py` now: adding a small panel lookup helper, building visible unread candidates from every rendered panel, and          │
│  │  sase (DONE) ×5 @ahu           May 7 11:51 · 1m25s                 ││  forcing a full list refresh when panel focus changes.                                                                                      │
│  │  ▎ ajh ─────────────────────────────────  3 agents                 ││                                                                                                                                             │
│  │  │  sase (DONE) ×5 @ajh           May 7 17:21 · 6m                 ││  The regression harness now has an opt-in panel group so older single-list tests still exercise the fallback path. I’m running the          │
│  │  │  ▸ ajh.r1 ───────────────────────────  2 agents                 ││  focused unread and keymap suites next.                                                                                                     │
│  │  │  sase (DONE) ×7 @ajh.r1     May 7 17:28 · 6m51s                 ││                                                                                                                                             │
│  │  │  sase (DONE) ×7 @ajh.r1.r1  May 7 17:35 · 6m35s                 ││                                                                                                                                             │
└───────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ─────────────────────────────────────────────────────────┘
 a approve  A artifacts  n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (19 done)                                                                                             RUNNING


```