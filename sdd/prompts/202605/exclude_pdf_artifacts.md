---
plan: sdd/tales/202605/exclude_pdf_artifacts.md
---
 We should never include PDFs in the ARTIFACTS field (see the `sase ace` snapshot below for context). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (3 x4)  │  AXE (9)                                                                                                                                                         CODEX(gpt-5.5)  ■ IDLE  ✉ 0
 7 Agents [2 running · 1 waiting · 0 unread · 4 read]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 4s)
┌─ (untagged) · 4 ──────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                                                                                 │
│  │  sase (PLAN APPROVED) ×6 @cq.plan                  🏃‍♂️ 5m32s    ││  AGENT DETAILS                                                                                                                                  │
│  │  sase (PLAN APPROVED) ×8 @cg.code.r1.plan          🏃‍♂️ 9m34s    ││                                                                                                                                                 │
│                                                                   ││  Project: sase                                                                                                                                  │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agen    ││  Workspace: #100                                                                                                                                │
│  │  sase (WAITING) @cr                                            ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                            │
│                                                                   ││  Model: CODEX(gpt-5.5)                                                                                                                          │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent    ││  VCS: GitHub                                                                                                                                    │
│  │  sase (PLAN DONE) ×6 @co.plan              15:33:34 · 6m06s    ││  PID: 626638                                                                                                                                    │
│                                                                   ││  Name: @co.plan                                                                                                                                 │
│                                                                   ││  Timestamps: BEGIN | 2026-05-09 15:21:38                                                                                                        │
│                                                                   ││              PLAN  | 2026-05-09 15:23:19                                                                                                        │
│                                                                   ││              CODE  | 2026-05-09 15:29:09                                                                                                        │
│                                                                   ││              END   | 2026-05-09 15:33:34                                                                                                        │
│                                                                   ││  DELTAS:                                                                                                                                        │
│                                                                   ││    ~ sdd/tales/202605/remove_pdf_done_agent_rows.md  ~1                                                                                         │
│                                                                   ││    ~ src/sase/ace/tui/widgets/_agent_list_render_layout.py  ~4 -9                                                                               │
│                                                                   ││    ~ tests/test_ace_tui_widgets.py  +70 ~2                                                                                                      │
│                                                                   ││  ARTIFACTS:                                                                                                                                     │
│                                                                   ││    • sdd/tales/202605/remove_pdf_done_agent_rows.md                                                                                             │
│                                                                   ││    • ~/.sase/projects/sase/artifacts/ace-run/20260509152909/markdown_pdfs/sdd__tales__202605__remove_pdf_done_agent_rows.md.pdf                 │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  Commit Message: fix: suppress completed PDF activity in agent rows                                                                             │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  ──────────────────────────────────────────────────                                                                                             │
│                                                                   ││                                                                                                                                             ▄▄  │
│                                                                   ││  AGENT XPROMPT                                                                                                                                  │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  #gh:sase Can you help me remove the "PDFs done <N>/<M>" text from agent rows? I'm not sure how these got there #plan                           │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  ──────────────────────────────────────────────────                                                                                             │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  AGENT PROMPT                                                                                                                                   │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  Can you help me remove the "PDFs done <N>/<M>" text from agent rows? I'm not sure how these got there Think this through                       │
│                                                                   ││  thoroughly and create a plan using your `/sase_plan` skill before making any file changes.                                                     │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  ──────────────────────────────────────────────────                                                                                             │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  AGENT REPLY                                                                                                                                    │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  ─── PLANNER ─── 15:21:38 ─────────────────────────                                                                                             │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  ─── 15:22:02 ─────────────────────────────────────                                                                                             │
│                                                                   ││                                                                                                                                                 │
│                                                                   ││  I’ll use the `sase_plan` skill first, and I’ll inspect the relevant memory plus the UI code path before proposing changes. No file edits       │
│                                                                   ││  until the plan is in place.                                                                                                                    │
└───────────────────────────────────────────────────────────────────┘│  ─── 15:22:11 ─────────────────────────────────────                                                                                             │
                                                                     │                                                                                                                                                 │
┌─ #blog · 3 ───────────────────────────────────────────────────────┐│  I’ve got the plan workflow: first understand the source of the row text, then write and submit a standalone plan file with `sase plan`. I’m    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents      ││  searching the rendering and status code now so the plan is grounded in the actual code path.                                                   │
│  │  ▎ 260507 ─────────────────────────────────────  3 agents      ││  ─── 15:22:24 ─────────────────────────────────────                                                                                             │
│  │  │  ▸ 260507.ajh ──────────────────────────────  3 agents      ││                                                                                                                                                 │
│  │  │  sase (DONE) ×5 @260507.ajh           May 7 17:21 · 6m      ││  The text is coming from the Agents tab row renderer, not from the PDF generation code itself. I’m narrowing whether this is only a             │
│  │  │  sase (DONE) ×7 @260507.ajh.r1.r1  May 7 17:35 · 6m35s      ││  presentation suffix or also affects persisted activity metadata so the plan can avoid removing useful status data.                             │
│  │  │  sase (DONE) ×7 @260507.ajh.r1     May 7 17:28 · 6m51s      ││                                                                                                                                                 │
└───────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ───────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```