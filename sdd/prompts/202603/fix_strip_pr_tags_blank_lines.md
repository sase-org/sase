---
plan: sdd/tales/202603/fix_strip_pr_tags_blank_lines.md
---
Why is BUG attached to this new ChangeSpec that I created on another machine? No PR tags should be included in the
DESCRIPTION field value for ChangeSpecs. Can you help me diagnose the root cause of this issue and fix it? Think this
through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### The Actual CL Descrition

```
[bug] Update DRX UI Style Guide with guidance for `late` and `late final` fields.

Added `Public late final`, `Private late final`, `Public late`, and `Private late` to the "Order fields and functions of classes" section. Updated the "DO" example to reflect the new field placement.

AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT
BUG=483686843
R=startblock
MARKDOWN=true
STARTBLOCK_AUTOSUBMIT=yes
WANT_LGTM=all
```

### `sase ace` Snapshot

```
⭘                                                                                                                    sase ace
  CLs (6)  │  Agents (2 x21)  │  AXE (4)                                                                                                                                                                                                         ✉ 36
 ChangeSpec: 6/6   +10X +12S   (auto-refresh in 4s)                   ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
┌────────────────────────────────────────────────────────────────────┐│ Search Query » project:bug                                                                                                                                             [9]   │
│  [!D] bug_csp_violate_ss__1 (http://cl/872924849)                  │└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
│  [!M] bug_class_brand (http://cl/875934898)                        │┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  [!D] bug_arc_prod_filter_1 (http://cl/877388204)                  ││                                                                                                                                                                              │
│  [D] bug_pricing_and_pa_1 (http://cl/879839029)                    ││  ╭────────────────────────────────────────────────────────────────── ~/.sase/projects/bug/bug.gp:1017 ──────────────────────────────────────────────────────────────────╮    │
│  [M] bug_update_trafficking_paging (http://cl/890997109)  ✓3 /4    ││  │                                                                                                                                                                      │    │
│  [$D] bug_drx_ui_style_late_fields_1 (http://cl/891378544)         ││  │  RUNNING:                                                                                                                                                            │    │
│                                                                    ││  │    #100 | 2724961 | ace(run)-260329_163856 | bug                                                                                                                     │    │
│                                                                    ││  │    #101 | 2780026 | ace(run)-260329_164318 | bug                                                                                                                     │    │
│                                                                    ││  │    #103 | 2893789 | axe(hooks)-1           | bug_drx_ui_style_late_fields_1                                                                                          │    │
│                                                                    ││  │                                                                                                                                                                      │    │
│                                                                    ││  │                                                                                                                                                                      │    │
│                                                                    ││  │  NAME: bug_drx_ui_style_late_fields_1                                                                                                                                │    │
│                                                                    ││  │  DESCRIPTION:                                                                                                                                                        │    │
│                                                                    ││  │    Update DRX UI Style Guide with guidance for `late` and `late final` fields.                                                                                       │    │
│                                                                    ││  │                                                                                                                                                                      │    │
│                                                                    ││  │    Added `Public late final`, `Private late final`, `Public late`, and `Private late` to the "Order fields and functions of classes" section. Updated the "DO"       │    │
│                                                                    ││  │  example to reflect the new field placement.                                                                                                                         │    │
│                                                                    ││  │                                                                                                                                                                      │    │
│                                                                    ││  │    BUG=483686843                                                                                                                                                     │    │
│                                                                    ││  │  CL: http://cl/891378544                                                                                                                                             │    │
│                                                                    ││  │  STATUS: Draft                                                                                                                                                       │    │
│                                                                    ││  │  COMMITS:                                                                                                                                                            │    │
│                                                                    ││  │    (1) [run] Initial Commit                                                                                                                                          │    │
│                                                                    ││  │        | CHAT: ~/.sase/chats/bug-ace_run-260329_164439.md (9m25s)                                                                                                    │    │
│                                                                    ││  │        | DIFF: ~/.sase/diffs/bug_drx_ui_style_late_fields-260329_165400.diff                                                                                         │    │
│                                                                    ││  │  HOOKS:                                                                                                                                                              │    │
│                                                                    ││  │    !$retired_mercurial_plugin_presubmit  [folded: PASSED: 1]                                                                                                                      │    │
│                                                                    ││  │    $retired_mercurial_plugin_lint                                                                                                                                                 │    │
│                                                                    ││  │        | (1) [260329_165417] RUNNING - ($: 2898078)                                                                                                                  │    │
│                                                                    ││  │                                                                                                                                                                      │    │
│                                                                    ││  ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯    │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
│                                                                    ││                                                                                                                                                                              │
└────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 COPY ! +snap  % raw  b bug  c CL#  n name  p spec  s snap                                                                                                                                                                                   RUNNING
```
