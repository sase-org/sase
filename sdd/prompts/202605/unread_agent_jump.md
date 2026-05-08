---
plan: sdd/tales/202605/unread_agent_jump.md
---
 When I use the `,j` keymap, I'm getting a "No unread completed agents" error message (see the `sase ace` snapshot below) even though there is clearly one unread agent row (the agent named "anj.plan"). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (x21)  │  AXE (8)                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 1+16
 Agents: 7/21   [view: file]   [group: by status (o)]   (auto-refresh in 4s)                                                                              ▌
┌─ (untagged) · 15 ──────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────▌ No unread completed agents                                ─┐
│  ✗ Failed ━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 failed           ││                                                                                       ▌                                                            │
│  │  sase (FAILED) ×5 @ani              16:23:56 · 5s           ││  AGENT DETAILS                                                                                                                                     │
│                                                                ││                                                                                                                                                ▆▆  │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  14 agents           ││  Project: sase                                                                                                                                     │
│  │  sase (PLAN DONE) ×6 @anj.plan   16:34:35 · 🎉 7m           ││  Workspace: #102                                                                                                                                   │
│  │  sase (PLAN DONE) ×6 @ang.plan   16:05:59 · 4m28s           ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                               │
│  │  sase (PLAN DONE) ×6 @ane.plan   16:00:15 · 7m19s           ││  Model: CODEX(gpt-5.5)                                                                                                                             │
│  │  sase (PLAN DONE) ×6 @anc.plan   15:49:19 · 6m22s           ││  VCS: GitHub                                                                                                                                       │
│  │  sase (PLAN DONE) ×6 @anb.plan  15:50:24 · 10m30s           ││  PID: 3022106                                                                                                                                      │
│  │  sase (PLAN DONE) ×6 @ana.plan   15:43:32 · 5m11s           ││  Name: @anc.plan                                                                                                                                   │
│  │  sase (DONE) ×5 @amz             15:23:33 · 1m03s           ││  Timestamps: BEGIN | 2026-05-08 15:41:35                                                                                                           │
│  │  ~ (DONE) ×2 @amy                  15:20:42 · 14s           ││              PLAN  | 2026-05-08 15:43:19                                                                                                           │
│  │  sase (DONE) ×5 @amx             15:23:05 · 2m39s           ││              CODE  | 2026-05-08 15:44:41                                                                                                           │
│  │  sase (PLAN DONE) ×8 @amt.plan  14:37:56 · 10m27s           ││              END   | 2026-05-08 15:49:19                                                                                                           │
│  │  sase (DONE) ×5 @ams             14:26:15 · 5m50s           ││  DELTAS:                                                                                                                                           │
│  │  sase (PLAN DONE) ×6 @amq.plan  14:21:52 · 13m37s           ││                                                                                                                                                    │
│  │  sase (PLAN DONE) ×6 @amp.plan      14:05:47 · 5m           │└──────────────────────────────────────────────────────────── ● files [1/2]  ○ thinking ─────────────────────────────────────────────────────────────┘
│  │  sase (PLAN DONE) ×6 @amo.plan   14:05:40 · 7m19s           │┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                ││                                                                                                                                                    │
│                                                                ││  /tmp/sase-gh-9hPeUn.diff                                                                                                                          │
│                                                                ││                                                                                                                                                    │
│                                                                ││      1 diff --git a/sdd/tales/202605/artifact_viewer_file_path_header.md b/sdd/tales/202605/artifact_viewer_file_path_header.md                    │
│                                                                ││      2 index 43351aa6..7c50a404 100644                                                                                                             │
│                                                                ││      3 --- a/sdd/tales/202605/artifact_viewer_file_path_header.md                                                                                  │
│                                                                ││      4 +++ b/sdd/tales/202605/artifact_viewer_file_path_header.md                                                                                  │
│                                                                ││      5 @@ -1,6 +1,6 @@                                                                                                                             │
│                                                                ││      6  ---                                                                                                                                        │
│                                                                ││      7  create_time: 2026-05-08 15:44:33                                                                                                           │
│                                                                ││      8 -status: wip                                                                                                                                │
│                                                                ││      9 +status: done                                                                                                                               │
│                                                                ││     10  prompt: sdd/prompts/202605/artifact_viewer_file_path_header.md                                                                             │
│                                                                ││     11  ---                                                                                                                                        │
│                                                                ││     12  # Artifact Viewer File Path Header Plan                                                                                                    │
│                                                                ││     13 diff --git a/src/sase/ace/tui/graphics/viewer.py b/src/sase/ace/tui/graphics/viewer.py                                                      │
│                                                                ││     14 index 51ec179c..399d604c 100644                                                                                                             │
│                                                                ││     15 --- a/src/sase/ace/tui/graphics/viewer.py                                                                                                   │
│                                                                ││     16 +++ b/src/sase/ace/tui/graphics/viewer.py                                                                                                   │
│                                                                ││     17 @@ -17,6 +17,10 @@ from dataclasses import dataclass                                                                                        │
│                                                                ││     18  from pathlib import Path                                                                                                                   │
│                                                                ││     19  from typing import Any, Literal, Protocol                                                                                                  │
│                                                                ││     20                                                                                                                                             │
│                                                                ││     21 +from rich.console import Console                                                                                                           │
│                                                                ││     22 +from rich.panel import Panel                                                                                                               │
│                                                                ││     23 +from rich.text import Text                                                                                                                 │
└────────────────────────────────────────────────────────────────┘│     24 +                                                                                                                                           │
                                                                  │     25  from sase.attachments.markdown_pdf import PDF_ENGINES, render_markdown_pdf                                                                 │
┌─ #blog · 4 ────────────────────────────────────────────────────┐│     26                                                                                                                                             │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents          ││     27  from .images import is_supported_image_path                                                                                                │
│  │  sase (DONE) ×5 @ahu           May 7 11:51 · 1m25s          ││     28 @@ -490,6 +494,13 @@ def run_artifact_sequence_loop(                                                                                        │
│  │  ▎ ajh ─────────────────────────────────  3 agents          ││     29              return _PageLoopResult(returncode=1)                                                                                           │
│  │  │  sase (DONE) ×5 @ajh           May 7 17:21 · 6m          ││     30                                                                                                                                             │
│  │  │  ▸ ajh.r1 ───────────────────────────  2 agents          ││     31          _clear_terminal(run)                                                                                                               │
│  │  │  sase (DONE) ×7 @ajh.r1     May 7 17:28 · 6m51s          ││     32 +        _print_artifact_header(                                                                                                            │
│  │  │  sase (DONE) ×7 @ajh.r1.r1  May 7 17:35 · 6m35s          ││     33 +            specs[artifact_index],                                                                                                         │
└────────────────────────────────────────────────────────────────┘│     34 +            page_index=page_index,                                                                                                         │
                                                                  │     35 +            page_count=len(pages),                                                                                                         │
┌─ #chop · 2 ────────────────────────────────────────────────────┐│     36 +            artifact_index=artifact_index,                                                                                                 │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents    ││                                                                                                                                                    │
│  │  ⚡ sase (DONE) ×5 @pysplit.viewer      16:27:55 · 7m35s    ││    ▾ 146 more lines below                                                                                                                          │
│  │  [agent] sase/fix_just (DONE) ×8 @anf  16:07:19 · 13m11s    ││                                                                                                                                                    │
└────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────────── Lines 1-36 of 182 ─────────────────────────────────────────────────────────────────┘
 A artifacts  n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (21 done)                                                                                                        RUNNING


```