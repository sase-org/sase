---
plan: sdd/plans/202605/refresh_docs_config_workflow.md
---
 There is a problem with the 'refresh_docs' chops we recently added to my chezmoi repo (see the `sase ace`
snapshot below): The `sase/refresh_docs` xprompt is only defined in this repo. Can you help me factor out a
`refresh_docs` chop to the sase_athena.yml file in my chezmoi repo that the `SASE/REFRESH_DOCS` chop in this repo will
delegate to? This way sase's plugin repos can use this chop too. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (7 x11)  │  AXE (8)                                                                                                                                     Override CODEX(gpt-5.5) 43h7m  ■ IDLE  ✉ 10 ·1
 Agents: 1/18   [view: file]   [group: by status (o)]   (auto-refresh in 2s)
┌─ (untagged) · 18 ───────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                                                                           │
│  │  sase-org/sase-core (RUNNING) ×16 @nl                          9s    ││  AGENT DETAILS                                                                                                                            │
│  │  ⚡ sase (RUNNING) ◆ sase-1p.4 @sase-1p.4                   3m52s    ││                                                                                                                                           │
│                                                                         ││  ChangeSpec: sase-org/sase-core                                                                                                           │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agent    ││  Workspace: #100                                                                                                                          │
│  │  ▸ sase-1p ────────────────────────────────────────────  5 agents    ││  Embedded Workflows: gh(gh_ref=sase-org/sase-core)                                                                                        │
│  │  ⚡ sase (WAITING) ◆ sase-1p @sase-1p.land                           ││  Model: CODEX(gpt-5.5)                                                                                                                    │
│  │  ⚡ sase (WAITING) ◆ sase-1p.8 @sase-1p.8                            ││  VCS: GitHub                                                                                                                              │
│  │  ⚡ sase (WAITING) ◆ sase-1p.7 @sase-1p.7                            ││  PID: 1673521                                                                                                                             │
│  │  ⚡ sase (WAITING) ◆ sase-1p.6 @sase-1p.6                            ││  Name: @nl                                                                                                                                │
│  │  ⚡ sase (WAITING) ◆ sase-1p.5 @sase-1p.5                            ││  Timestamps: BEGIN | 2026-05-01 01:01:01                                                                                                  │
│                                                                         ││                                                                                                                                           │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  11 agents    ││  ──────────────────────────────────────────────────                                                                                       │
│  │  [agent] sase/refresh_docs (DONE) ×9 @nm            01:01:03 · 3s    ││                                                                                                                                           │
│  │  sase (EPIC CREATED) ×6 @ng.plan                 00:14:26 · 9m41s    ││  AGENT XPROMPT                                                                                                                            │
│  │  [agent] sase/refresh_docs (DONE) ×7 @mr         00:10:08 · 6m45s    ││                                                                                                                                           │
│  │  sase (DONE) ×7 @mq                             00:04:00 · 10m03s    ││  #gh:sase-org/sase-core #!sase/refresh_docs(project=sase-core, gh_ref=sase-org/sase-core, threshold=25)                                   │
│  │  sase (DONE) ×5 @mk                          Apr 30 23:53 · 6m03s    ││                                                                                                                                           │
│  │  sase (PLAN DONE) ×6 @mh.plan               Apr 30 23:44 · 10m05s    ││  ──────────────────────────────────────────────────                                                                                       │
│  │  sase (DONE) ×5 @mb                            Apr 30 23:20 · 33s    ││                                                                                                                                           │
│  │  sase (DONE) ×5 @ma                            Apr 30 23:19 · 58s    ││  AGENT PROMPT                                                                                                                             │
│  │  ▸ sase-1p ────────────────────────────────────────────  3 agents    ││                                                                                                                                           │
│  │  ⚡ sase (DONE) ◆ sase-1p.3 @sase-1p.3          00:57:06 · 16m34s    ││                                                                                                                                           │
│  │  ⚡ sase (DONE) ◆ sase-1p.2 @sase-1p.2          00:40:24 · 14m03s    ││  #!sase/refresh_docs(project=sase-core, gh_ref=sase-org/sase-core, threshold=25)                                                          │
│  │  ⚡ sase (DONE) ◆ sase-1p.1 @sase-1p.1             00:26:16 · 13m    ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││  ──────────────────────────────────────────────────                                                                                       │
│                                                                         ││                                                                                                                                           │
│                                                                         ││  AGENT REPLY                                                                                                                              │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││  ─── 01:01:15 ─────────────────────────────────────                                                                                       │
│                                                                         ││                                                                                                                                           │
│                                                                         ││  I’ll inspect the repo hooks and docs tooling to see how `sase/refresh_docs` is represented here, then run the matching workflow if it    │
│                                                                         ││  exists.                                                                                                                                  │
│                                                                         ││  ─── 01:01:23 ─────────────────────────────────────                                                                                       │
│                                                                         ││                                                                                                                                           │
│                                                                         ││  I don’t see a local `refresh_docs` script yet. The repo is small, so I’m checking the package metadata, current README, and git state    │
│                                                                         ││  before deciding whether this is a documentation drift check or a generated-doc refresh.                                                  │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
│                                                                         ││                                                                                                                                           │
└─────────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────── ○ files  ○ thinking ───────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `plugin`)