---
plan: sdd/tales/202604/full_model_indicator.md
---
 It looks like we are truncating the model name in the new model indicator in the TUI (see the `sase ace` snapshot below). Can you help me stop doing this? Also, we should stop including the "Model " prefix in this indicator. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs (19)  │  Agents (2)  │  AXE (6 .2)                                                                                                                                  Model GEMINI(gemi...h-preview)  ■ IDLE  ✉ 1+0
 ChangeSpec: 19/19   +24X +20S                                  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 [group: by date (o)]   (auto-refresh in 6s)                    │ Search Query » project:bug OR project:bug_plans                                                                                                [9]   │
┌──────────────────────────────────────────────────────────────┐└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
│  ▌ Yesterday ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 CL    │┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  [!D] bug_roblox_buyer_block_v2_1 (http://cl/907825563)      ││                                                                                                                                                      │
│                                                              ││  ╭────────────────────────────────────────────────────── ~/.sase/projects/bug/bug.gp:1586 ──────────────────────────────────────────────────────╮    │
│  ▌ This Week ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8 CLs    ││  │                                                                                                                                              │    │
│  [!R] bug_rpc_exc (http://cl/906621704)                      ││  │  RUNNING:                                                                                                                                    │    │
│  [!D] bug_fix_miss_sponsor_1 (http://cl/906619110)           ││  │    #100 | 3760554 | ace(run)-260430_104832 | bug_roblox_buyer_block_v2_1                                                                     │    │
│  [D] bug_tapp_ob_1 (http://cl/906612824)                     ││  │    #101 | 3762670 | ace(run)-260430_104835 | bug_roblox_buyer_block_v2_1                                                                     │    │
│  [D] bug_clog_1 (http://cl/906610670)                        ││  │                                                                                                                                              │    │
│  [!D] bug_segment_error_2 (http://cl/906603282)              ││  │                                                                                                                                              │    │
│  [D] bug_segment_error_1 (http://cl/906601945)               ││  │  NAME: bug_roblox_buyer_block_v2_1                                                                                                           │    │
│  [D] bug_sync_point_error_1 (http://cl/906599548)            ││  │  DESCRIPTION:                                                                                                                                │    │
│  [!M] bug_pp_npe_sql (http://cl/903335367)                   ││  │    Create buyer block to allowlist GDA and DV3 seats for Roblox                                                                              │    │
│                                                              ││  │                                                                                                                                              │    │
│  ▌ Earlier ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  10 CLs    ││  │    This creates an F1 data change script to enable only GDA (AdWords) and                                                                    │    │
│  [!D] bug_pp_api_fix_1 (http://cl/904029100)                 ││  │    DV3 demand on Roblox traffic. It uses the known list of DV3 seats and GDA buyer network ID 1.                                             │    │
│  [!D] bug_arc_prod_filter_1 (http://cl/877388204)            ││  │                                                                                                                                              │    │
│  [!D] bug_pricing_and_pa_4 (http://cl/892384729)             ││  │    Test: None required.                                                                                                                      │    │
│  [!D] bug_fix_dev_1 (http://cl/897954458)                    ││  │  CL: http://cl/907825563                                                                                                                     │    │
│  [D] bug_no_pubmatic_cta_1 (http://cl/897175180)             ││  │  BUG: http://b/905262388                                                                                                                     │    │
│  [!M] bug_update_trafficking_paging (http://cl/890997109)    ││  │  STATUS: Draft                                                                                                                               │    │
│  [!D] bug_remove_target_platform_1 (http://cl/891400491)     ││  │  COMMITS:                                                                                                                                    │    │
│  [!R] bug_remove_creation_date_time (http://cl/891382800)    ││  │    (1) [run] Initial Commit  [folded: DIFF + PLAN]                                                                                           │    │
│  [!D] bug_csp_violate_ss__1 (http://cl/872924849)            ││  │        | CHAT: ~/.sase/chats/202604/bug-ace_run-260429_185107.md (13m45s)                                                                    │    │
│  [D] bug_pricing_and_pa_1 (http://cl/879839029)              ││  │    (2) [man] Fix IDs  [folded: DIFF]                                                                                                         │    │
│                                                              ││  │    (3) [man] Add comma                                                                                                                       │    │
│                                                              ││  │        | DIFF: ~/.sase/diffs/bug_roblox_buyer_block_v2_1-260429_201508.diff                                                                  │    │
│                                                              ││  │  HOOKS:                                                                                                                                      │    │
│                                                              ││  │    !$retired_mercurial_plugin_presubmit  [folded: PASSED: 1 | FAILED: 2]                                                                                  │    │
│                                                              ││  │        | (3) [260429_201533] FAILED (14s) - (!: Presubmit failed: SQL syntax error (unexpected 'AS') in                                      │    │
│                                                              ││  │  create-roblox-buyer-allowlist-fix.sql during dry run.)                                                                                      │    │
│                                                              ││  │    $retired_mercurial_plugin_lint  [folded: PASSED: 1 2 3]                                                                                                │    │
│                                                              ││  │  TIMESTAMPS:  [folded: 2]                                                                                                                    │    │
│                                                              ││  │    [260429_201522] COMMIT (3)                                                                                                                │    │
│                                                              ││  │                                                                                                                                              │    │
│                                                              ││  ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯    │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
│                                                              ││                                                                                                                                                      │
└──────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 COPY ! +snap  % raw  b bug  c CL#  n name  p spec  s snap                                                                                                                                              RUNNING   [*2]
```