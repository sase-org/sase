---
plan: sdd/epics/202605/axe_tab_visual_redesign.md
---
 Can you help me make the AXE tab (see the `sase ace` snapshot below for what it looks like now) look WAY
better? 

- The entries in the left side-panel should NEVER wrap. Make that panel wider (dynmaically) if you need to.
- Lumberjack entries should be easily distinguishable from chop entries or user command entries.
- There should be good PNG snapshot tests that demonstrate all of this.
- When the output is knowable (e.g. we control the lumberjack output I think), it should have beautiful syntax
  highlighting.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents  │  AXE                                                                                                                                                    Override CLAUDE(opus) 14h23m  ■ IDLE  ✉ 1+0
┌─────────────────────────────────┐
│  [*] checks                     │ [checks / cl_submitted_checks]  │  ✓ success  │  When: 1m ago  │  Took: 6.3s  │  Exit: 0  │  Run 1/10  │  (auto-refresh in 2s)
│    └─ [✓]                       │─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
│  cl_submitted_checks            │
│    └─ [✓]                       │  * sase_stop_hook_dedup_fix_1: Started cl_submitted check
│  stale_running_cleanup          │  * sase_fix_plan_file__260329_190136: Started cl_submitted check
│  [*] code_quality               │  * sase_fix_branch_name_race__260329_191342: Started cl_submitted check
│    └─ [*]                       │  * sase_fix_rename_key_1: Started cl_submitted check
│  sase_recent_bug_audit          │  * sase_fix_rename_key__260330_090916: Started cl_submitted check
│    └─ [*]                       │  * sase_fix_timestamp_overwrite_2: Started cl_submitted check
│  sase_recent_improvement_aud    │  * sase_fix_timestamp_overwrite__260330_095043: Started cl_submitted check
│  it                             │  * sase_merge_plan_code_reply_1: Started cl_submitted check
│  [*] comments                   │  * sase_merge_plan_code_reply__260330_104916: Started cl_submitted check
│    └─ [✓] comment_checks        │  * sase_no_first_commit_timestamp_1: Started cl_submitted check
│  [*] github_actions             │  * sase_no_first_commit_timestamp__260330_115845: Started cl_submitted check
│    └─ [✓] gh_actions_fix        │  * sase_cap_z_keymaps_1__260330_121938: Started cl_submitted check
│  [*] hooks                      │  * sase_fix_commit_msg_var_2: Started cl_submitted check
│    └─ [✓] hook_checks           │  * sase_fix_commit_msg_var__260330_141151: Started cl_submitted check
│    └─ [✓] mentor_checks         │  * sase_fmt_plan_files_1: Started cl_submitted check
│    └─ [✓] workflow_checks       │  * sase_pinned_panel_1: Started cl_submitted check
│    └─ [✓]                       │  * sase_pinned_panel_2: Started cl_submitted check
│  pending_checks_poll            │  * sase_fix_extra_commits_1: Started cl_submitted check
│    └─ [✓]                       │  * sase_fix_extra_commits__260330_165800: Started cl_submitted check
│  comment_zombie_checks          │  * sase_pin_panel_2: Started cl_submitted check                                                                                                                                 ▃▃
│    └─ [✓] suffix_transforms     │  * sase_pin_panel__260330_172906: Started cl_submitted check
│    └─ [✓] orphan_cleanup        │  * sase_fast_agent__260330_202525: Started cl_submitted check
│  [*] housekeeping               │  * sase_better_pin_panel_1: Started cl_submitted check
│    └─ [✓] error_digest          │  * sase_better_pin_panel__260331_084905: Started cl_submitted check
│  [*] refresh_docs               │  * sase_better_pin_1: Started cl_submitted check
│    └─ [*] sase_refresh_docs     │  * sase_bg_cmd_out_1__260331_185041: Started cl_submitted check
│    └─ [·]                       │  * sase_approve_w_options_2: Started cl_submitted check
│  sase_core_refresh_docs         │  * sase_approve_w_options_1: Started cl_submitted check
│    └─ [·]                       │  * sase_piw_file_cmp_2: Started cl_submitted check
│  sase_github_refresh_docs       │  * sase_piw_file_cmp__260401_135313: Started cl_submitted check
│    └─ [·]                       │  * sase_search_md_format_1: Started cl_submitted check
│  sase_nvim_refresh_docs         │  * sase_search_md_format_2: Started cl_submitted check
│    └─ [·]                       │  * sase_search_md_format_4: Started cl_submitted check
│  sase_telegram_refresh_docs     │  * sase_search_md_format__260401_160740: Started cl_submitted check
│  [*] run_every                  │  * sase_big_v_key_1: Started cl_submitted check
│    └─ [*] sase_pylimit_split    │  * sase_big_v_key__260403_114115: Started cl_submitted check
│    └─ [*] sase_fix_just         │  * sase_fix_split_1: Started cl_submitted check
│  [*] telegram                   │  * sase_fix_split__260403_123223: Started cl_submitted check
│    └─ [✓] tg_inbound            │  * sase_fix_split_2: Started cl_submitted check
│    └─ [✓] tg_outbound           │  * sase_fix_split__260403_125504: Started cl_submitted check
│  [*] waits                      │  * sase_fix_codex_cs_names_1__260403_130909: Started cl_submitted check
│    └─ [✓] wait_checks           │  * sase_fix_agent_enter_1__260403_155214: Started cl_submitted check
│                                 │  * sase_fix_no_mentors_2: Started cl_submitted check
│                                 │  * sase_fix_no_mentors__260403_213426: Started cl_submitted check
│                                 │  * sase_fix_piw_freeze_2: Started cl_submitted check
│                                 │  * sase_fix_piw_freeze__260404_105932: Started cl_submitted check
│                                 │  * sase_fix_no_mentors_1__260404_150723: Started cl_submitted check
│                                 │  * sase_agent_tags_2: Started cl_submitted check
│                                 │  * sase_agent_tags_1: Started cl_submitted check
│                                 │  * sase_model_picker_1: Started cl_submitted check
│                                 │  * sase_model_picker__260408_174940: Started cl_submitted check
│                                 │  * sase_fix_codex_prs: Started cl_submitted check
│                                 │  * sase_fix_missing_chat_file_1__260413_191432: Started cl_submitted check
│                                 │  * sase_faster_tui_1__260415_165713: Started cl_submitted check
│                                 │  * sase_fast_refresh_1__260423_142540: Started cl_submitted check
│                                 │  Full cycle complete: 85 update(s)
│                                 │
└─────────────────────────────────┘
 COPY o visible  O full  s snap                                                                                                                                                                                RUNNING
```