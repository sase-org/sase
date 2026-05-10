---
plan: sdd/tales/202604/fix_mentor_profiles_loading.md
---
The MENTORS ChangeSpec field is not being added to the below ChangeSpec by `sase axe` (running on another machine). Can
you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your
`/sase_plan` skill before making any file changes.

### ChangeSpec

```
NAME: yserve_platform_param
DESCRIPTION:
  Map platform and parameters in YieldPartnerSettingsDtoConverter

  - Removed `parameters` and `platform` from `ignore` in `YieldPartnerSettingsDtoConverter` and implemented manual mapping for `parameters`.
  - Created `YieldParameterDtoConverter` to map `YieldParameterDto` to `YieldPartnerSettings.YieldParameter`.
  - Handled integer-to-long type discrepancy for `helpTooltipId`.
  - Added missing dependencies in `BUILD`.
CL: http://cl/894598392
BUG: http://b/350330301
STATUS: Ready
COMMITS:
  (1) [run] Initial Commit
      | CHAT: ~/.sase/chats/yserve-ace_run-260404_122046.md (31m9s)
      | DIFF: ~/.sase/diffs/yserve_null-260404_125153.diff
      | PLAN: /google/src/cloud/bbugyi/yserve/google3/.sase/sdd/tales/202604/yserve_converters.md
HOOKS:
  !$retired_mercurial_plugin_presubmit
      | (1) [260404_150308] FAILED (5m15s) - (!: Presubmit failed with 1 target failure in xfp_api.exchange.)
  $retired_mercurial_plugin_lint
      | (1) [260404_150309] PASSED (4s)
TIMESTAMPS:
  [260404_125155] COMMIT (1)
  [260404_135312] STATUS Draft -> Ready
  [260404_150255] REWORD tag "BUG"
```

### `sase ace` Snapshot (that shows 'hooks' lumberjack logs)

```
⭘                                                                                                                    sase ace
  CLs (4)  │  Agents (1 x1 +1)  │  AXE (4 .1)                                                                                                                                                                                                     ✉ 1
┌─────────────────────────────────┐
│  [*] sase axe                   │ [hooks] (3/4)  │  RUNNING  │  PID: 4028375  │  Interval: 1s  │  Cycles: 44  │  Chops: 8  │  (auto-refresh in 7s)
│    └─ [*] checks                │───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
│    └─ [*] comments              │
│    └─ [*] hooks                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│    └─ [*] housekeeping          │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'bug_update_trafficking_paging'
│  ◌ [*] xpad                     │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'bug_update_trafficking_paging'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'bug_remove_creation_date_time'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'bug_remove_creation_date_time'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'fixit_float_date_label'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'fixit_float_date_label'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'fixit_date_pick_star'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'fixit_date_pick_star'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'foobar_pokemon'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'foobar_pokemon'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_1'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_1'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_2'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_2'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_3'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_3'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_4'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_4'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_5'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_5'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_6'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_6'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_7'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_7'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_8'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_8'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_9'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_9'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'pat_ui_integration'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'pat_ui_integration'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'pat_fix_pg_view_details'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'pat_fix_pg_view_details'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_1'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_1'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_2'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_2'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_3'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_3'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_4'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_4'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_5'                                                                                                                            ▃▃
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_5'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'feat-x_6'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'feat-x_6'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'yserve_batch_proto'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'yserve_batch_proto'
│                                 │  [2026-04-04 16:06:02] [hooks] Phase 2: 0 mentor profile(s) loaded from config
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 profile(s) loaded for 'yserve_platform_param'
│                                 │  [2026-04-04 16:06:02] [hooks] Mentor matching: 0 new profiles matched for 'yserve_platform_param'
└─────────────────────────────────┘
 COPY o visible  O full  s snap                                                                                                                                                                                                       RUNNING   [*1]
```
