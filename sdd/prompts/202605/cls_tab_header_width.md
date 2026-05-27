---
plan: sdd/tales/202605/cls_tab_header_width.md
---
 The headers on the left side-panel of the the "CLs" tab of the `sase ace` TUI can sometimes be too long when there are ChangeSpec with long names that match the current ChangeSpec query (see the `sase ace` snapshot below). Can you help me fix this (the headers should only be, at most, as long as the left side-panel)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                        sase ace (PID: 223909)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 5+5
 ChangeSpec: 11/11   +68X +68S                                                  ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 [group: by date (o)]   (auto-refresh in 7s)                                    │ Search Query » project:sase                                                                                         [1]   │
┌──────────────────────────────────────────────────────────────────────────────┐└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
│  ▌ Yesterday                                                                 │┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    ││                                                                                                                           │
│  ━━━━━━  3 CLs                                                               ││  ╭──────────────────────────────────────── ~/.sase/projects/sase/sase.gp:626 ────────────────────────────────────────╮    │
│  ▎ 17:00                                                                     ││  │                                                                                                                   │    │
│  ────────────────────────────────────────────────────────────────────────    ││  │  RUNNING:                                                                                                         │    │
│  ───────────  1 CL                                                           ││  │    #12 | 2634372 | ace(run)-260521_184735 | sase                                                                  │    │
│  [D] sase_recent_improvement_audit_sase_2187718213c3_1                       ││  │    #14 |  721115 | ace(run)-260522_170702 | sase                                                                  │    │
│  (https://github.com/sase-org/sase/pull/134)                                 ││  │    #11 | 1924003 | ace(run)-260524_113924 | sase                                                                  │    │
│  ▎ 09:00                                                                     ││  │    #10 | 3255343 | ace(run)-260526_183546 | sase                                                                  │    │
│  ────────────────────────────────────────────────────────────────────────    ││  │                                                                                                                   │    │
│  ───────────  1 CL                                                           ││  │                                                                                                                   │    │
│  [D] sase_fix_just_tests_logs_1                                              ││  │  NAME: sase_recent_improvement_audit_sase_2187718213c3_1                                                          │    │
│  (https://github.com/sase-org/sase/pull/133)                                 ││  │  DESCRIPTION:                                                                                                     │    │
│  ▎ 05:00                                                                     ││  │    fix: harden memory and prompt edge cases                                                                       │    │
│  ────────────────────────────────────────────────────────────────────────    ││  │                                                                                                                   │    │
│  ───────────  1 CL                                                           ││  │    Avoid rewriting launch refs inside fenced code block variants and treat                                        │    │
│  [D] sase_fix_just_tests_followup_2                                          ││  │    invalid UTF-8 memory files like unreadable files when building memory                                          │    │
│  (https://github.com/sase-org/sase/pull/132)                                 ││  │    inventory stats.                                                                                               │    │
│                                                                              ││  │  PR: https://github.com/sase-org/sase/pull/134                                                                    │    │
│  ▌ This Week                                                                 ││  │  STATUS: Draft                                                                                                    │    │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    ││  │  COMMITS:                                                                                                         │    │
│  ━━━━━━  3 CLs                                                               ││  │    (1) [run] Initial Commit                                                                                       │    │
│  ▎ Mon May 25                                                                ││  │        | CHAT: ~/.sase/chats/202605/sase-ace_run-260526_172321.md (11m51s)                                        │    │
│  ────────────────────────────────────────────────────────────────────────    ││  │        | DIFF: ~/.sase/diffs/202605/sase_recent_improvement_audit_sase_2187718213c3-260526_173512.diff            │    │
│  ─────  2 CLs                                                                ││  │  DELTAS:  +0 ~4 (+44 ~12) -0 (4 files)                                                                            │    │
│  [D] sase_fix_just_tests_drift_paths_1                                       ││  │  HOOKS:                                                                                                           │    │
│  (https://github.com/sase-org/sase/pull/131)                                 ││  │    just lint                                                                                                      │    │
│  [D] sase_fix_just_tests_followup_1                                          ││  │    just test                                                                                                      │    │
│  (https://github.com/sase-org/sase/pull/130)                                 ││  │  TIMESTAMPS:                                                                                                      │    │
│  ▎ Sun May 24                                                                ││  │    [260526_173512] COMMIT (1)                                                                                     │    │
│  ────────────────────────────────────────────────────────────────────────    ││  │                                                                                                                   │    │
│  ──────  1 CL                                                                ││  ╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯    │
│  [D] sase_recent_bug_audit_sase_5ba2242b2f4c_1                               ││                                                                                                                           │
│  (https://github.com/sase-org/sase/pull/129)                                 ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
│  ▌ Earlier                                                                   ││                                                                                                                           │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    ││                                                                                                                           │
│  ━━━━━━━━  5 CLs                                                             ││                                                                                                                           │
│  ▎ May 11-17                                                                 ││                                                                                                                           │
│  ────────────────────────────────────────────────────────────────────────    ││                                                                                                                           │
│  ──────  5 CLs                                                               ││                                                                                                                           │
│  [D] sase_gha_fix_sase_org_sase_25977758272_a1_1                             ││                                                                                                                           │
│  (https://github.com/sase-org/sase/pull/121)                                 ││                                                                                                                           │
│  [D] sase_gha_fix_sase_org_sase_25975522255_a1_1                             ││                                                                                                                           │
│  (https://github.com/sase-org/sase/pull/120)                                 ││                                                                                                                           │
│  [D] sase_gha_fix_sase_org_sase_25973346430_a1_1                             ││                                                                                                                           │
│  (https://github.com/sase-org/sase/pull/118)                                 ││                                                                                                                           │
│  [D] sase_fix_just_tests_4 (https://github.com/sase-org/sase/pull/116)       ││                                                                                                                           │
│  [D] sase_fix_just_tests_3 (https://github.com/sase-org/sase/pull/115)       ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
│                                                                              ││                                                                                                                           │
└──────────────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  ! +snap · % raw · b bug · c CL# · n name · p spec · s snap                                                                                                                                  RUNNING
```