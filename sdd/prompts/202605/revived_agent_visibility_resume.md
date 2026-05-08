---
plan: sdd/tales/202605/revived_agent_visibility_resume.md
---
 After revival, this agent (see the `sase ace` snapshot below) kept disappearing and then reappearing (I've
since re-dismissed it) from the agents tab. Also, when I tried to launch another agent using `resume:abb_3`, that agent
failed because it said that no agent of that name could be found. Can you help me diagnose the root cause of this issue
and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` snapshot

````
 ⭘                                                                                                     sase ace
  CLs  │  Agents (3 x9)  │  AXE (8)                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 1+3
 Agents: 12/12   [view: collapsed]   [group: by status (o)]   (auto-refresh in 6s)
┌─ (untagged) · 7 ──────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────▌                                                           ─┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                        ▌ CODEX(gpt-5.5) @amh completed: ace(run)-260508_130215      │
│  │  sase (PLAN APPROVED) ×6 @ami.plan             🏃‍♂️ 3m39s    ││  AGENT DETAILS                                                                         ▌                                                            │
│  │  sase (RUNNING) ×4 @amh.r1                        🏃‍♂️ 6s    ││                                                                                                                                                     │
│                                                               ││  Project: sase                                                                                                                                      │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agen    ││  Workspace: #100                                                                                                                                    │
│  │  sase (WAITING) @amh.r1.r1                                 ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                                │
│                                                               ││  Model: CODEX(gpt-5.5)                                                                                                                              │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents    ││  VCS: GitHub                                                                                                                                        │
│  │  sase (DONE) ×5 @amh                   13:08:06 · 5m51s    ││  PID: 3964034                                                                                                                                   ▅▅  │
│  │  sase (PLAN DONE) ×6 @amd.plan        12:56:19 · 12m01s    ││  Name: @abb_3                                                                                                                                       │
│  │  sase (PLAN DONE) ×6 @ame.plan        12:47:41 · 10m42s    ││  Timestamps: BEGIN | 2026-05-04 22:48:29                                                                                                            │
│  │  sase (DONE) @abb_3                 May 4 22:49 · 1m07s    ││              END   | 2026-05-04 22:49:36                                                                                                            │
│                                                               ││                                                                                                                                                     │
│                                                               ││  ──────────────────────────────────────────────────                                                                                                 │
│                                                               ││                                                                                                                                                     │
│                                                               ││  AGENT XPROMPT                                                                                                                                      │
│                                                               ││                                                                                                                                                     │
│                                                               ││  #gh:sase What do I need to do to install wkhtmltopdf on this machine? It doesn't look like I can install it with `apt-get install`.                │
│                                                               ││                                                                                                                                                     │
│                                                               ││  ──────────────────────────────────────────────────                                                                                                 │
│                                                               ││                                                                                                                                                     │
│                                                               ││  AGENT PROMPT                                                                                                                                       │
│                                                               ││                                                                                                                                                     │
│                                                               ││                                                                                                                                                     │
│                                                               ││  What do I need to do to install wkhtmltopdf on this machine? It doesn't look like I can install it with                                            │
│                                                               ││  `apt-get install`.                                                                                                                                 │
│                                                               ││                                                                                                                                                     │
│                                                               ││                                                                                                                                                     │
│                                                               ││  ──────────────────────────────────────────────────                                                                                                 │
│                                                               ││                                                                                                                                                     │
│                                                               ││  AGENT CHAT                                                                                                                                         │
│                                                               ││                                                                                                                                                     │
│                                                               ││                                                                                                                                                     │
│                                                               ││  ─── 22:48:44 ─────────────────────────────────────                                                                                                 │
│                                                               ││                                                                                                                                                     │
│                                                               ││  I’ll check the distro and package availability first, because `wkhtmltopdf` packaging depends heavily on Ubuntu/Debian release and                 │
│                                                               ││  architecture.                                                                                                                                      │
│                                                               ││  ─── 22:49:01 ─────────────────────────────────────                                                                                                 │
│                                                               ││                                                                                                                                                     │
│                                                               ││  This host is Debian 13 “trixie” on `amd64`, and the Debian repo has no `wkhtmltopdf` candidate for it. I’m checking the upstream `.deb`            │
│                                                               ││  dependency set now so the install advice is specific rather than generic.                                                                          │
│                                                               ││  ─── 22:49:35 ─────────────────────────────────────                                                                                                 │
│                                                               ││                                                                                                                                                     │
│                                                               ││  This machine is Debian 13 `trixie` on `amd64`. `wkhtmltopdf` has no Debian 13 apt candidate here, so `apt-get install wkhtmltopdf` will not        │
│                                                               ││  work.                                                                                                                                              │
│                                                               ││                                                                                                                                                     │
│                                                               ││  Use the upstream `wkhtmltox` Bookworm `.deb` from the archived wkhtmltopdf packaging releases:                                                     │
│                                                               ││                                                                                                                                                     │
│                                                               ││  ```bash                                                                                                                                            │
└───────────────────────────────────────────────────────────────┘│  cd /tmp                                                                                                                                            │
                                                                 │  wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb                                 │
┌─ #blog · 5 ───────────────────────────────────────────────────┐│  sudo apt-get update                                                                                                                                │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agents         ││  sudo apt-get install ./wkhtmltox_0.12.6.1-3.bookworm_amd64.deb                                                                                     │
│  │  sase (DONE) ×5 @ahu           May 7 11:51 · 1m25s         ││  wkhtmltopdf --version                                                                                                                              │
│  │  sase (DONE) @aea_2            May 6 17:09 · 1m19s         ││  ```                                                                                                                                                │
│  │  ▎ ajh ─────────────────────────────────  3 agents         ││                                                                                                                                                     │
│  │  │  sase (DONE) ×5 @ajh           May 7 17:21 · 6m         ││  I checked the package metadata and simulated the install on this host; apt accepts it on trixie. Use `apt-get install ./...deb`, not `dpkg -i`,    │
│  │  │  ▸ ajh.r1 ───────────────────────────  2 agents         ││  because apt will resolve dependencies correctly.                                                                                                   │
│  │  │  sase (DONE) ×7 @ajh.r1     May 7 17:28 · 6m51s         ││                                                                                                                                                     │
│  │  │  sase (DONE) ×7 @ajh.r1.r1  May 7 17:35 · 6m35s         ││                                                                                                                                                     │
└───────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────────── ○ files  ○ thinking ────────────────────────────────────────────────────────────────┘
 A artifacts  e edit chat  N tag/untag  r resume  t tmux  T tmux (primary)  x dismiss  X cleanup (9 done)                                                                                                      RUNNING


````