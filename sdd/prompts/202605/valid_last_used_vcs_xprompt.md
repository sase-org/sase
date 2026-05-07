---
plan: sdd/tales/202605/valid_last_used_vcs_xprompt.md
---
 We recently fixed the `@` keymap so invalid projects will now never be shown. Can you help me do the same for the last used VCS xprompt workflow (used by the `<space>` keymap)? This should prevent errors like those shown in the `sase ace` snapshot below. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (x9)  │  AXE (8)                                                                                                                                                          CODEX(gpt-5.5)  ■ IDLE  ✉ 11
 Agents: 1/9   [view: file]   [group: by status (o)]   (auto-refresh in 8s)                                                                               ▌
┌─ (untagged) · 6 ─────────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────▌ Saved @/<space> selection is stale: project file not      ─┐
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents                     ││                                                                             ▌ found for 'project'; cleared saved selection               │
│  │  sase (DONE) ×5 @aiq             16:44:21 · 8m38s                     ││  AGENT DETAILS                                                              ▌                                                            │
│  │  sase (PLAN DONE) ×6 @aia.plan  16:17:34 · 10m53s                     ││                                                                                                                                      ▂▂  │
│  │  sase (PLAN DONE) ×6 @ahz.plan   16:12:51 · 7m47s                     ││  Project: sase                                                                                                                           │
│  │  sase (PLAN DONE) ×6 @aje.plan  16:04:59 · 12m28s                     ││  Workspace: #100                                                                                                                         │
│  │  sase (PLAN DONE) ×6 @ajc.plan   15:59:17 · 8m32s                     ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                     │
│  │  sase (PLAN DONE) ×5 @aic.plan   12:22:53 · 4m12s                     ││  Model: CODEX(gpt-5.5)                                                                                                                   │
│                                                                          ││  VCS: GitHub                                                                                                                             │
│                                                                          ││  PID: 2880732                                                                                                                            │
│                                                                          ││  Name: @aiq                                                                                                                              │
│                                                                          ││  Timestamps: BEGIN | 2026-05-07 16:35:43                                                                                                 │
│                                                                          ││              END   | 2026-05-07 16:44:21                                                                                                 │
│                                                                          ││                                                                                                                                          │
│                                                                          ││  Commit Message: chore: use checked-in image notification fixture                                                                        │
│                                                                          ││                                                                                                                                          │
│                                                                          ││                                                                                                                                          │
│                                                                          │└────────────────────────────────────────────────────────── ● files  ○ thinking ───────────────────────────────────────────────────────────┘
│                                                                          │┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                          ││                                                                                                                                          │
│                                                                          ││  /tmp/sase-gh-p81Qq3.diff                                                                                                                │
│                                                                          ││                                                                                                                                          │
│                                                                          ││      1 diff --git a/tests/fixtures/notifications/test_image_notification.png                                                             │
│                                                                          ││        b/tests/fixtures/notifications/test_image_notification.png                                                                        │
│                                                                          ││      2 new file mode 100644                                                                                                              │
│                                                                          ││      3 index 00000000..4e2263d3                                                                                                          │
│                                                                          ││      4 Binary files /dev/null and b/tests/fixtures/notifications/test_image_notification.png differ                                      │
│                                                                          ││      5 diff --git a/tools/test_image_notification b/tools/test_image_notification                                                        │
│                                                                          ││      6 index 7dc9f053..625d007d 100755                                                                                                   │
│                                                                          ││      7 --- a/tools/test_image_notification                                                                                               │
│                                                                          ││      8 +++ b/tools/test_image_notification                                                                                               │
│                                                                          ││      9 @@ -1,30 +1,32 @@                                                                                                                 │
│                                                                          ││     10  #!/usr/bin/env python3                                                                                                           │
│                                                                          ││     11 -"""Create a SASE notification with a persistent test PNG attachment."""                                                          │
│                                                                          ││     12 +"""Create a SASE notification with a checked-in test PNG attachment."""                                                          │
│                                                                          ││     13                                                                                                                                   │
│                                                                          ││     14  from __future__ import annotations                                                                                               │
│                                                                          ││     15                                                                                                                                   │
│                                                                          ││     16  import json                                                                                                                      │
│                                                                          ││     17 -import struct                                                                                                                    │
│                                                                          ││     18  import subprocess                                                                                                                │
│                                                                          ││     19  import sys                                                                                                                       │
│                                                                          ││     20 -import zlib                                                                                                                      │
│                                                                          ││     21  from pathlib import Path                                                                                                         │
│                                                                          ││     22                                                                                                                                   │
│                                                                          ││     23                                                                                                                                   │
│                                                                          ││     24 -IMAGE_WIDTH = 96                                                                                                                 │
│                                                                          ││     25 -IMAGE_HEIGHT = 64                                                                                                                │
│                                                                          ││     26 -ASSET_DIR = Path.home() / ".sase" / "notifications" / "test_assets"                                                              │
│                                                                          ││     27 -IMAGE_PATH = ASSET_DIR / "notification_test_image.png"                                                                           │
└──────────────────────────────────────────────────────────────────────────┘│     28 +IMAGE_PATH = (                                                                                                                   │
                                                                            │     29 +    Path(__file__).resolve().parents[1]                                                                                          │
┌─ #blog · 2 ──────────────────────────────────────────────────────────────┐│     30 +    / "tests"                                                                                                                    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents                             ││     31 +    / "fixtures"                                                                                                                 │
│  │  sase (DONE) ×5 @ahu     11:51:02 · 1m25s                             ││     32 +    / "notifications"                                                                                                            │
│  │  sase (DONE) @aea_2   May 6 17:09 · 1m19s                             ││     33 +    / "test_image_notification.png"                                                                                              │
└──────────────────────────────────────────────────────────────────────────┘│     34 +)                                                                                                                                │
                                                                            │     35                                                                                                                                   │
┌─ #chop · 1 ──────────────────────────────────────────────────────────────┐│                                                                                                                                          │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent    ││    ▾ 67 more lines below                                                                                                                 │
│  │  ⚡ sase (DONE) ×5 @pysplit.test_xprompt_catalog  16:19:39 · 6m06s    ││                                                                                                                                          │
└──────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────── Lines 1-35 of 102 ────────────────────────────────────────────────────────────┘
 e edit chat  N tag/untag  r resume  t tmux  T tmux (primary)  x dismiss  X cleanup (9 done)                                                                                                                   RUNNING


```