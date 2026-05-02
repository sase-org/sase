---
plan: sdd/tales/202605/epic_phase_vcs_prompts.md
---
 It looks like phase agents (started by our epic integration) are being started from the home directory (see the `sase ace` snapshot below). Can you help me fix this by always embedding the proper
`#<vcs>:<project>` VCS xprompt workflow at the start of each phase/land bead's prompt? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (19 x8)  │  AXE (8)                                                                                                                                      Override CODEX(gpt-5.5) 31h18m  ■ IDLE  ✉ 3+8
 Agents: 13/27   [view: file]   [group: by status (o)]   (auto-refresh in 6s)
┌─ (untagged) · 27 ──────────────────────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agents · 5 running    ││                                                                                                                                        │
│  │  sase (RUNNING) ×4 @sl                                         4m41s    ││  AGENT DETAILS                                                                                                                         │
│  │  [✓] ⚡ ~ (RUNNING) ×2 ◆ sase-1r.1 @sase-1r.1                  5m58s    ││                                                                                                                                        │
│  │  sase (PLAN APPROVED) ×6 @sk.plan                              6m04s    ││  ChangeSpec: ~                                                                                                                         │
│  │  [✓] ⚡ ~ (RUNNING) ×2 ◆ redacted-plan-a.2 @redacted-plan-a.2                    42s    ││  Embedded Workflows: cd(cd_ref=~)                                                                                                      │
│  │  sase (PLAN APPROVED) ×9 @ma.code.r1.code.r1.plan             17m18s    ││  Model: CODEX(gpt-5.5)                                                                                                                 │
│                                                                            ││  Mode: ⚡ Auto-Approve                                                                                                                 │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  14 agent    ││  PID: 582529                                                                                                                           │
│  │  ▸ sase-1r ───────────────────────────────────────────────  9 agents    ││  Name: @sj                                                                                                                             │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r @sase-1r.land                             ││  Timestamps: BEGIN | 2026-05-01 12:43:10                                                                                               │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.9 @sase-1r.9                              ││              END   | 2026-05-01 12:45:05                                                                                               │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.8 @sase-1r.8                              ││                                                                                                                                        │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.7 @sase-1r.7                              ││  ──────────────────────────────────────────────────                                                                                    │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.6 @sase-1r.6                              ││                                                                                                                                        │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.5 @sase-1r.5                              ││  AGENT PROMPT                                                                                                                          │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.4 @sase-1r.4                              ││                                                                                                                                        │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.3 @sase-1r.3                              ││                                                                                                                                        │
│  │  [✓] ⚡ ~ (WAITING) ◆ sase-1r.2 @sase-1r.2                              ││  #gh:sase #!sase/pylimit_split                                                                                                         │
│  │  ▸ redacted-plan-a ───────────────────────────────────────────────  5 agents    ││                                                                                                                                        │
│  │  [✓] ⚡ ~ (WAITING) ◆ redacted-plan-a @redacted-plan-a.land                             ││                                                                                                                                        │
│  │  [✓] ⚡ ~ (WAITING) ◆ redacted-plan-a.6 @redacted-plan-a.6                              ││  ──────────────────────────────────────────────────                                                                                    │
│  │  [✓] ⚡ ~ (WAITING) ◆ redacted-plan-a.5 @redacted-plan-a.5                              ││                                                                                                                                        │
│  │  [✓] ⚡ ~ (WAITING) ◆ redacted-plan-a.4 @redacted-plan-a.4                              ││  AGENT CHAT                                                                                                                            │
│  │  [✓] ⚡ ~ (WAITING) ◆ redacted-plan-a.3 @redacted-plan-a.3                              ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8 agents    ││  ─── 12:43:24 ─────────────────────────────────────                                                                                    │
│  │  ⚡ ~ (DONE) ×2 @sj                                 12:45:05 · 1m55s    ││                                                                                                                                        │
│  │  ⚡ ~ (DONE) ×2 ◆ redacted-plan-a.1 @redacted-plan-a.1             12:49:58 · 12m49s    ││  I’ll first identify the repo and any local instructions for `sase/pylimit_split`, then I’ll trace the requested change before         │
│  │  sase (DONE) ×5 @sh                                 12:38:11 · 1m55s    ││  editing.                                                                                                                              │
│  │  sase (DONE) ×5 @sg                                 12:40:59 · 7m40s    ││  ─── 12:43:37 ─────────────────────────────────────                                                                                    │
│  │  sase (PLAN DONE) ×6 @si.plan                      12:35:24 · 11m01s    ││                                                                                                                                        │
│  │  sase (PLAN DONE) ×6 @sf.plan                      12:27:59 · 11m21s    ││  The prompt maps to the local `sase` GitHub checkout and a `pylimit_split` workflow. I found prior local history for that workflow,    │
│  │  ▸ ma ────────────────────────────────────────────────────  2 agents    ││  so I’m going into the repo now to see what it currently flags.                                                                        │
│  │  sase (PLAN DONE) ×8 @ma.code.r1.plan              12:25:16 · 14m06s    ││  ─── 12:44:12 ─────────────────────────────────────                                                                                    │
│  │  sase (PLAN DONE) ×6 @ma.plan                       12:11:07 · 8m26s    ││                                                                                                                                        │
│                                                                            ││  The primary checkout is `/home/bryan/projects/github/sase-org/sase`. It has one pre-existing modified bead file, and the current      │
│                                                                            ││  `pylimit_files` scan over `src` and `tests` produced no oversized files, so the split workflow appears to be a no-op right now.       │
│                                                                            ││  ─── 12:44:43 ─────────────────────────────────────                                                                                    │
│                                                                            ││                                                                                                                                        │
│                                                                            ││  The workflow is registered as the standalone `#!sase/pylimit_split` workflow and resolves to a single hidden Python step. Since       │
│                                                                            ││  the direct scan is empty, I’m going to run the workflow itself to confirm it reports `launched=0` rather than leaving the command     │
│                                                                            ││  unexecuted.                                                                                                                           │
│                                                                            ││  ─── 12:45:04 ─────────────────────────────────────                                                                                    │
│                                                                            ││                                                                                                                                        │
│                                                                            ││  Ran `sase run '#!sase/pylimit_split'` in `/home/bryan/projects/github/sase-org/sase`.                                                 │
│                                                                            ││                                                                                                                                        │
│                                                                            ││  Result: `launched: 0`. No split agents were needed.                                                                                   │
│                                                                            ││                                                                                                                                        │
│                                                                            ││  Verification: `just pylimit` passes for both `src` and `tests`; all Python files are within the 700-line info limit. No file          │
│                                                                            ││  changes were made.                                                                                                                    │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
│                                                                            ││                                                                                                                                        │
└────────────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────── ○ files  ○ thinking ──────────────────────────────────────────────────────────┘
 <enter> go to CL  e edit chat  N tag/untag  r resume  u unmark (16)  x kill/dismiss (16 marked)  X cleanup (8 done)                                                                                           RUNNING


```