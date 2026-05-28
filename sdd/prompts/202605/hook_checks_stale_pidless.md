---
plan: sdd/tales/202605/hook_checks_stale_pidless.md
---
 The `hook_checks` chop appears to be hung (see the `sase ace` snapshot below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                        sase ace (PID: 136725)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 6+4
┌────────────────────────────────────────────┐
│  ▌ [*] checks  1c                          │ [hooks / hook_checks]  │  ● running  │  When: 16:00:00 (405h ago)  │  Elapsed: 405h 55m 1s  │  Run 1/12  │  (auto-refresh in 6s)
│    └─ [✓] cl_submitted_checks              │───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
│    └─ [✓] stale_running_cleanup            │
│  ▌ [*] code_quality  5c                    │  partial
│    └─ [*] sase_recent_bug_audit            │
│    └─ [*] sase_recent_improvement_audit    │
│  ▌ [*] comments  5c                        │
│    └─ [✓] comment_checks                   │
│  ▌ [*] github_actions  1c                  │
│    └─ [✓] gh_actions_fix                   │
│  ▌ [*] hooks  43c                          │
│    └─ [●] hook_checks                      │
│    └─ [✓] mentor_checks                    │
│    └─ [✓] workflow_checks                  │
│    └─ [✓] pending_checks_poll              │
│    └─ [✓] comment_zombie_checks            │
│    └─ [✓] suffix_transforms                │
│    └─ [✓] orphan_cleanup                   │
│  ▌ [*] housekeeping  1c                    │
│    └─ [✓] error_digest                     │
│  ▌ [*] refresh_docs  5c                    │
│    └─ [*] sase_refresh_docs                │
│    └─ [*] sase_core_refresh_docs           │
│    └─ [*] sase_github_refresh_docs         │
│    └─ [*] sase_nvim_refresh_docs           │
│    └─ [*] sase_telegram_refresh_docs       │
│  ▌ [*] run_every  5c                       │
│    └─ [*] sase_pylimit_split               │
│    └─ [✓] sase_fix_just                    │
│  ▌ [*] telegram  38c                       │
│    └─ [✓] tg_inbound                       │
│    └─ [✓] tg_outbound                      │
│  ▌ [*] waits  25c                          │
│    └─ [●] wait_checks                      │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
└────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  o visible · O full · s snap                                                                                                                                                                 RUNNING
```