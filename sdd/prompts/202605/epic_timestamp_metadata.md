---
plan: sdd/tales/202605/epic_timestamp_metadata.md
---
 When the user launches an agent to create an epic (e.g. by using the `E` keymap from the plan approval panel), no "EPIC" entry is added to the "Timestamps:" field in the agent metadata panel on
the "Agents" tab (see the `sase ace` snapshot below). Can you help me start doing this? See how we do this for the "PLAN" timestamp entries for context. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents (3 x1)  │  AXE (8)                                                                                                                                         Override CODEX(gpt-5.5) 31h53m  ■ IDLE  ✉ 1
 Agents: 3/4   [view: file]   [group: by project (o)]   (auto-refresh in 8s)
┌─ (untagged) · 4 ─────────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▌ sase ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents · 3 running    ││                                                                                                                                              │
│  │  sase (EPIC APPROVED) ×6 @sd.plan                        3m25s    ││  AGENT DETAILS                                                                                                                               │
│  │  sase (EPIC APPROVED) ×6 @mb.plan                        4m36s    ││                                                                                                                                              │
│  │  ▎ ma ──────────────────────────────────  2 agents · 1 running    ││  Project: sase                                                                                                                           ▅▅  │
│  │  │  sase (PLAN APPROVED) ×8 @ma.code.r1.plan             3m30s    ││  Workspace: #101                                                                                                                             │
│  │  │  sase (PLAN DONE) ×6 @ma.plan              12:11:07 · 8m26s    ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                         │
│                                                                      ││  Model: CODEX(gpt-5.5)                                                                                                                       │
│                                                                      ││  VCS: GitHub                                                                                                                                 │
│                                                                      ││  PID: 342493                                                                                                                                 │
│                                                                      ││  Name: @mb.plan                                                                                                                              │
│                                                                      ││  Timestamps: BEGIN | 2026-05-01 12:09:17                                                                                                     │
│                                                                      ││              PLAN  | 2026-05-01 12:13:06                                                                                                     │
│                                                                      ││                                                                                                                                              │
│                                                                      ││  ──────────────────────────────────────────────────                                                                                          │
│                                                                      ││                                                                                                                                              │
│                                                                      ││                                                                                                                                              │
│                                                                      │└──────────────────────────────────────────────────────────── ● files  ○ thinking ─────────────────────────────────────────────────────────────┘
│                                                                      │┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                      ││                                                                                                                                              │
│                                                                      ││  /home/bryan/.sase/plans/202605/rust_agent_launch_migration.md                                                                               │
│                                                                      ││                                                                                                                                              │
│                                                                      ││      1 # Rust-backed agent launch migration                                                                                                  │
│                                                                      ││      2                                                                                                                                       │
│                                                                      ││      3 ## Question answered                                                                                                                  │
│                                                                      ││      4                                                                                                                                       │
│                                                                      ││      5 Yes. The parts of agent launch that would benefit most from moving from Python into `../sase-core` are the                            │
│                                                                      ││      6 deterministic, pre-runtime pieces:                                                                                                    │
│                                                                      ││      7                                                                                                                                       │
│                                                                      ││      8 - RUNNING-field workspace allocation, claim, and transfer logic in `src/sase/running_field/_workspace.py` and                         │
│                                                                      ││      9   `src/sase/running_field/_operations.py`.                                                                                            │
│                                                                      ││     10 - Low-level launch preparation in `src/sase/agent/launcher.py`: prompt temp-file creation, output path derivation, env                │
│                                                                      ││     11   shaping, subprocess spawning, and post-spawn workspace claim/kill-on-failure behavior.                                              │
│                                                                      ││     12 - Fan-out planning in `src/sase/agent/multi_prompt_launcher.py`, `src/sase/agent/repeat_launcher.py`,                                 │
│                                                                      ││     13   `src/sase/xprompt/_directive_alt.py`, and the TUI launch mixins. This includes deterministic parsing of `%model`,                   │
│                                                                      ││     14   `%alt`, `%r`, `%wait`, multi-prompt separators, local-xprompt serialization metadata, unique timestamp allocation, and              │
│                                                                      ││     15   the current one-second sleeps between spawned agents.                                                                               │
│                                                                      ││     16                                                                                                                                       │
│                                                                      ││     17 The parts that should not move first are the Textual UI handlers, Python plugin hooks for VCS/workspace providers, and                │
│                                                                      ││     18 the actual agent runner/provider execution (`run_agent_runner.py`, Claude/Gemini/Codex provider code). Those remain                   │
│                                                                      ││     19 host/application logic. Rust should own the stable, deterministic backend contract that can be called from the TUI/CLI                │
│                                                                      ││     20 without duplicating parsing and mutation logic.                                                                                       │
│                                                                      ││     21                                                                                                                                       │
│                                                                      ││     22 ## Current launch shape                                                                                                               │
│                                                                      ││     23                                                                                                                                       │
│                                                                      ││     24 The single-agent TUI path already avoids blocking the Textual event loop by sending `_run_agent_launch_body()` through                │
│                                                                      ││     25 `asyncio.to_thread()`, but that worker still performs a long Python preflight before the agent appears:                               │
│                                                                      ││     26                                                                                                                                       │
│                                                                      ││     27 - Parse multi-prompt/frontmatter and possibly expand multi-agent xprompts.                                                            │
│                                                                      ││     28 - Resolve VCS refs, history, MRU, file references, workflow dispatch, `%wait`, `%model`, and `%r`.                                    │
│                                                                      ││     29 - Allocate workspace number by reading/parsing the RUNNING field.                                                                     │
│                                                                      ││     30 - Resolve workspace directory and clean non-main workspaces through provider/Python code.                                             │
│                                                                      ││     31 - Spawn a Python subprocess and then claim the workspace in the ProjectSpec file.                                                     │
│                                                                      ││     32                                                                                                                                       │
│                                                                      ││     33 The multi-agent paths are worse for total launch latency:                                                                             │
│                                                                      ││     34                                                                                                                                       │
│                                                                      ││     35 - Multi-model TUI launch sleeps one second between subagents.                                                                         │
│                                                                      ││     36 - Repeat launch sleeps one second between subagents.                                                                                  │
│                                                                      ││                                                                                                                                              │
│                                                                      ││    ▾ 282 more lines below                                                                                                                    │
│                                                                      ││                                                                                                                                              │
└──────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────── Lines 1-36 of 318 ──────────────────────────────────────────────────────────────┘
 COPY c chat  E file path  n name  p prompt  s snap                                                                                                                                                            RUNNING
```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `plugin`)