---
plan: sdd/tales/202605/plan_step_runtime_1.md
---
 We recently fixed the runtime for "PLAN APPROVED" agent/workflow entries, but there is a problem (see the `sase ace` snapshot below). Namely, the child agent step (the child named `afk.code.r1.plan` in the `sase ace` snapshot below) should only show the runtime for that agent step (which is calculated as PLAN - BEGIN in this case). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (2 x6)  │  AXE (8)                                                                                                                                                         CODEX(gpt-5.5)  ■ IDLE  ✉ 7
 Agents: 4/8   [view: file]   [group: by status (o)]   (auto-refresh in 3s)
┌─ (untagged) · 11 ─────────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                                         │
│  │  sase (RUNNING) ×4 @aga                                    🏃‍♂️ 2m15s    ││  AGENT DETAILS                                                                                                                          │
│                                                                           ││                                                                                                                                         │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agen    ││  Project: sase                                                                                                                          │
│  │  sase (WAITING) @aga.r1                                                ││  Workspace: #100                                                                                                                        │
│                                                                           ││  Embedded Workflows: gh(gh_ref=sase), resume(name=afk.code)                                                                             │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents    ││  Model: CODEX(gpt-5.5)                                                                                                                  │
│  │  sase (PLAN DONE) ×6 @aft.plan                     10:50:35 · 8m36s    ││  VCS: GitHub                                                                                                                            │
│  │  sase (PLAN DONE) ×6 @afr.plan                     10:36:46 · 8m32s    ││  PID: 1229601                                                                                                                           │
│  │  sase (PLAN DONE) ×6 @aeu.plan                     10:32:28 · 9m37s    ││  Name: @afk.code.r1.plan                                                                                                                │
│  │  sase (PLAN DONE) ×6 @aed.plan                    10:31:26 · 11m09s    ││  Timestamps: BEGIN | 2026-05-07 10:33:40                                                                                                │
│  │  ▎ afk ──────────────────────────────────────────────────  2 agents    ││              PLAN  | 2026-05-07 10:36:27                                                                                                │
│  │  │  sase (PLAN DONE) ×6 @afk.plan                  10:30:48 · 5m12s    ││              CODE  | 2026-05-07 10:40:12                                                                                                │
│  │  │  ▸ afk.code ───────────────────────────────────────────  1 agent    ││              END   | 2026-05-07 10:47:20                                                                                                │
│  │  │  ≡ sase (PLAN DONE) ×8 −5 @afk.code.r1.plan    10:47:20 · 13m40s    ││                                                                                                                                         │
│  │  │    └─ 1/1.plan main (DONE) @afk.code.r1.plan   10:47:20 · 13m40s    ││                                                                                                                                         │
│  │  │    └─ 1/1.code sase (DONE) @afk.code.r1.code    10:47:20 · 7m08s    │└─────────────────────────────────────────────────────── ● files [1/2]  ○ thinking ───────────────────────────────────────────────────────┘
│  │  │    └─ 1g/1 diff (DONE) @afk.code.r1.plan ▼#gh                       │┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                           ││                                                                                                                                         │
│                                                                           ││  /tmp/sase-gh-leGDJi.diff                                                                                                               │
│                                                                           ││                                                                                                                                         │
│                                                                           ││      1 diff --git a/sdd/tales/202605/tmux_kitty_image_notifications.md b/sdd/tales/202605/tmux_kitty_image_notifications.md             │
│                                                                           ││      2 index f1ea352f..a71980b5 100644                                                                                                  │
│                                                                           ││      3 --- a/sdd/tales/202605/tmux_kitty_image_notifications.md                                                                         │
│                                                                           ││      4 +++ b/sdd/tales/202605/tmux_kitty_image_notifications.md                                                                         │
│                                                                           ││      5 @@ -1,6 +1,6 @@                                                                                                                  │
│                                                                           ││      6  ---                                                                                                                             │
│                                                                           ││      7  create_time: 2026-05-07 10:40:04                                                                                                │
│                                                                           ││      8 -status: wip                                                                                                                     │
│                                                                           ││      9 +status: done                                                                                                                    │
│                                                                           ││     10  prompt: sdd/prompts/202605/tmux_kitty_image_notifications.md                                                                    │
│                                                                           ││     11  ---                                                                                                                             │
│                                                                           ││     12  # Fix Blurry Notification Image Previews in tmux                                                                                │
│                                                                           ││     13 diff --git a/src/sase/ace/tui/graphics/capability.py b/src/sase/ace/tui/graphics/capability.py                                   │
│                                                                           ││     14 index ac0d9edb..c74b636b 100644                                                                                                  │
│                                                                           ││     15 --- a/src/sase/ace/tui/graphics/capability.py                                                                                    │
│                                                                           ││     16 +++ b/src/sase/ace/tui/graphics/capability.py                                                                                    │
│                                                                           ││     17 @@ -10,6 +10,7 @@ from __future__ import annotations                                                                             │
│                                                                           ││     18  import fcntl                                                                                                                    │
│                                                                           ││     19  import os                                                                                                                       │
│                                                                           ││     20  import select                                                                                                                   │
│                                                                           ││     21 +import subprocess                                                                                                               │
│                                                                           ││     22  import termios                                                                                                                  │
│                                                                           ││     23  import time                                                                                                                     │
│                                                                           ││     24  import tty                                                                                                                      │
│                                                                           ││     25 @@ -59,6 +60,13 @@ class GraphicsCapability:                                                                                     │
│                                                                           ││     26                                                                                                                                  │
│                                                                           ││     27  ProbeFunc = Callable[[PassthroughMode, float], bool]                                                                            │
│                                                                           ││     28  _PROBE_REPLY_DRAIN_TIMEOUT = 0.02                                                                                               │
│                                                                           ││     29 +_TMUX_QUERY_TIMEOUT = 0.08                                                                                                      │
│                                                                           ││     30 +                                                                                                                                │
│                                                                           ││     31 +                                                                                                                                │
│                                                                           ││     32 +@dataclass(frozen=True)                                                                                                         │
│                                                                           ││     33 +class _TmuxMetadata:                                                                                                            │
│                                                                           ││     34 +    terminal: str | None                                                                                                        │
│                                                                           ││     35 +    allow_passthrough: str | None                                                                                               │
│                                                                           ││     36                                                                                                                                  │
│                                                                           ││                                                                                                                                         │
│                                                                           ││    ▾ 378 more lines below                                                                                                               │
│                                                                           ││                                                                                                                                         │
└───────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────── Lines 1-36 of 414 ───────────────────────────────────────────────────────────┘
 COPY c chat  E file path  n name  p prompt  s snap                                                                                                                                                            RUNNING
```