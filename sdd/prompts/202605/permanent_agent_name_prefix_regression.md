---
plan: sdd/tales/202605/permanent_agent_name_prefix_regression.md
---
 Why does this agent have a YYmmdd prefix in its name (see the `sase ace` snapshot below)? Agent names are supposed to be permenant now. Review recent, related sase agent chats for context. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (1 x4)  │  AXE (8)                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 1+0
 Agents(5): 1 running · 0 waiting · 0 unread · 4 read   [view: collapsed]   [group: by status (o)]   (auto-refresh in 3s)                                 ▌
┌─ (untagged) · 2 ────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────▌ Plan ready for @b0: unread_agent_count_white.md           ─┐
│  ▲ Needs Attention ━━━━━━━━━━━━━━━━  1 agent · 1 awaiting       ││                                                                                      ▌                                                            │
│  │  sase (PLANNING) ×5 @b0            12:58:44 · 🙋 1m18s       ││  AGENT DETAILS                                                                                                                                    │
│                                                                 ││                                                                                                                                                   │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent       ││  Project: sase                                                                                                                                    │
│  │  sase (PLAN DONE) @260509.by.plan    12:56:09 · 10m29s       ││  Workspace: #100                                                                                                                                  │
│                                                                 ││  Embedded Workflows: gh(gh_ref=sase), resume(name=bv.r1)                                                                                          │
│                                                                 ││  Model: CODEX(gpt-5.5)                                                                                                                            │
│                                                                 ││  VCS: GitHub                                                                                                                                      │
│                                                                 ││  PID: 4104776                                                                                                                                     │
│                                                                 ││  Name: @260509.by.plan                                                                                                                            │
│                                                                 ││  Timestamps: BEGIN | 2026-05-09 12:41:56                                                                                                          │
│                                                                 ││              PLAN  | 2026-05-09 12:43:51                                                                                                          │
│                                                                 ││              CODE  | 2026-05-09 12:45:40                                                                                                          │
│                                                                 ││              END   | 2026-05-09 12:56:09                                                                                                          │
│                                                                 ││  DELTAS:                                                                                                                                          │
│                                                                 ││    ~ .github/workflows/ci.yml  +2 ~1                                                                                                              │
│                                                                 ││    ~ Justfile  +12                                                                                                                                │
│                                                                 ││    ~ docs/_headers  +4                                                                                                                            │
│                                                                 ││    ~ docs/images/bead-epic-work-infographic.prompt.md  +4                                                                                         │
│                                                                 ││    ~ docs/images/commit-workflow-infographic.prompt.md  +4                                                                                        │
│                                                                 ││    ~ docs/images/infographic-style-brief.md  +4                                                                                                   │
│                                                                 ││    ~ docs/images/rust-backend-boundary-infographic.prompt.md  +4                                                                                  │
│                                                                 ││    ~ docs/images/workflow-execution-infographic.prompt.md  +4                                                                                     │
│                                                                 ││    ~ docs/images/xprompt-resolution-infographic.prompt.md  +4                                                                                     │
│                                                                 ││    ~ docs/index.md  +10 ~1                                                                                                                        │
│                                                                 ││    + docs/stylesheets/pdf.css  +274                                                                                                               │
│                                                                 ││    + docs/templates/pdf/front.html.j2  +37                                                                                                        │
│                                                                 ││    + mkdocs-pdf.yml  +38                                                                                                                          │
│                                                                 ││    ~ pyproject.toml  +6                                                                                                                           │
│                                                                 ││    ~ sdd/tales/202605/sase_sh_pdf_handbook.md  ~1                                                                                                 │
│                                                                 ││    + tools/validate_docs_pdf  +101                                                                                                                │
│                                                                 ││  ARTIFACTS:                                                                                                                                       │
│                                                                 ││    • sdd/tales/202605/sase_sh_pdf_handbook.md                                                                                                     │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  Commit Message: feat: add downloadable docs PDF handbook                                                                                         │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  ──────────────────────────────────────────────────                                                                                               │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  AGENT XPROMPT                                                                                                                                    │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  %n:by #gh:sase #resume:bv.r1 Can you now help me implement this? Use previous research as inspiration but make the important design decisions    │
│                                                                 ││  yourself. #plan                                                                                                                                  │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  ──────────────────────────────────────────────────                                                                                               │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  AGENT PROMPT                                                                                                                                     │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││                                                                                                                                                   │
│                                                                 ││  # Previous Conversation                                                                                                                          │
│                                                                 ││                                                                                                                                                   │
└─────────────────────────────────────────────────────────────────┘│  **User:**                                                                                                                                        │
                                                                   │                                                                                                                                                   │
┌─ #blog · 3 ─────────────────────────────────────────────────────┐│  #gh:sase I want to start allowing users to download all of sase's documentation and blog articles as                                             │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││  a single, beautiful PDF from the sase.sh website. Can you do some research to help me decide on how I should implement                           │
│  │  ▎ 260507 ─────────────────────────────────────  3 agents    ││  this? Store new research in a markdown file under the sdd/research/ directory. Organize research files in YYYYMM month                           │
│  │  │  ▸ 260507.ajh ──────────────────────────────  3 agents    ││  subdirectories.                                                                                                                                  │
│  │  │  sase (DONE) ×5 @260507.ajh           May 7 17:21 · 6m    ││                                                                                                                                                   │
│  │  │  sase (DONE) ×7 @260507.ajh.r1.r1  May 7 17:35 · 6m35s    ││  **Assistant:**                                                                                                                                   │
│  │  │  sase (DONE) ×7 @260507.ajh.r1     May 7 17:28 · 6m51s    ││                                                                                                                                                   │
└─────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────── ● files [1/2]  ○ thinking ────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```