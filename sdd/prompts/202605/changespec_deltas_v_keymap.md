---
plan: sdd/tales/202605/changespec_deltas_v_keymap.md
---
 Can you help me add support for the file entries in the ChangeSpec DELTAS field for the `v` keymap (see the `sase ace` snapshot below)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 ⭘                                                                                                     sase ace
  CLs (3)  │  Agents (1 x4)  │  AXE (6 .1)                                                                                                                                GEMINI(gemini-3-flash-preview)  ■ IDLE  ✉ 4+4
 ChangeSpec: 3/3   +28X +24S   c▸h▼m▸t▸d▼                      ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 [group: by date (o)]   (auto-refresh in 9s)                   │ Search Query » project:yserve                                                                                                                         │
┌─────────────────────────────────────────────────────────────┐└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
│  ▌ Today ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 CL    │┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▎ 16:00 ─────────────────────────────────────────  1 CL    ││                                                                                                                                                       │
│  [$R] yserve_routing_config (http://cl/905688169)  ●8 /8    ││  ╭──────────────────────────────────────────────────── ~/.sase/projects/yserve/yserve.gp:376 ────────────────────────────────────────────────────╮    │
│                                                             ││  │                                                                                                                                               │    │
│  ▌ Earlier ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 CLs    ││  │  RUNNING:                                                                                                                                     │    │
│  ▎ Apr 20-26 ────────────────────────────────────  2 CLs    ││  │    #100 | 1859941 | axe(crs)-critique-260429_163225 | yserve_dto_fixes                                                                        │    │
│  [!M] yserve_read_grow (http://cl/900318938)  /3            ││  │    #101 | 1859941 | hg-yserve_dto_fixes             | yserve_dto_fixes                                                                        │    │
│  [!D] yserve_write_grow_1 (http://cl/902880126)             ││  │    #102 | 3225857 | axe(hooks)-2                    | yserve_routing_config                                                                   │    │
│                                                             ││  │                                                                                                                                               │    │
│                                                             ││  │                                                                                                                                               │    │
│                                                             ││  │  NAME: yserve_routing_config                                                                                                                  │    │
│                                                             ││  │  DESCRIPTION:                                                                                                                                 │    │
│                                                             ││  │    Updates switching_config.textproto to enable shadow reads (READ_SHADOW_WIP) for newly supported YieldService methods and                   │    │
│                                                             ││  │    PQL tables.                                                                                                                                │    │
│                                                             ││  │  CL: http://cl/905688169                                                                                                                      │    │
│                                                             ││  │  BUG: http://b/350330301                                                                                                                      │    │
│                                                             ││  │  STATUS: Ready                                                                                                                                │    │
│                                                             ││  │  COMMITS:                                                                                                                                     │    │
│                                                             ││  │    (1) [run] Initial Commit  [folded: DIFF]                                                                                                   │    │
│                                                             ││  │        [1] | CHAT: ~/.sase/chats/202604/yserve_pql_parity-sase_commit-260425_193717.md (3s)                                                   │    │
│                                                             ││  │    (2) Fix YieldGroupPqlStubbyTest failure by correctly initializing empty buyerTypes  [+3 lines]                                             │    │
│                                                             ││  │        [2] | CHAT: ~/.sase/chats/202605/yserve_routing_config-ace_run-260505_153100.md (29m30s)                                               │    │
│                                                             ││  │        [3] | DIFF: ~/.sase/projects/yserve/artifacts/ace-run/20260505153100/commit_diff.diff                                                  │    │
│                                                             ││  │  DELTAS:                                                                                                                                      │    │
│                                                             ││  │    ~ java/com/google/ads/publisher/api/growbird/routing/config/test/switching_config.textproto                                                │    │
│                                                             ││  │    ~ java/com/google/ads/publisher/api/service/yieldpartner/oneplatform/common/YieldPartnerDtoConverter.java                                  │    │
│                                                             ││  │    ~ javatests/com/google/ads/publisher/api/service/yieldpartner/oneplatform/common/YieldPartnerDtoConverterTest.java                         │    │
│                                                             ││  │  HOOKS:                                                                                                                                       │    │
│                                                             ││  │    !$retired_mercurial_plugin_presubmit                                                                                                                    │    │
│                                                             ││  │        | [4] (2) [260505_160958] RUNNING - ($: 3235878)                                                                                       │    │
│                                                             ││  │    $retired_mercurial_plugin_lint                                                                                                                          │    │
│                                                             ││  │        | [5] (1) [260505_145452] PASSED (1s)                                                                                                  │    │
│                                                             ││  │        | [6] (2) [260505_160052] PASSED (4s)                                                                                                  │    │
│                                                             ││  │    //javatests/com/google/ads/publisher/api/service/yieldpartner/oneplatform/common:all                                                       │    │
│                                                             ││  │        | [7] (1) [260425_195417] PASSED (5s)                                                                                                  │    │
│                                                             ││  │        | [8] (2) [260505_160053] PASSED (1m23s)                                                                                               │    │
│                                                             ││  │  MENTORS:                                                                                                                                     │    │
│                                                             ││  │    (2) code[3/3]                                                                                                                              │    │
│                                                             ││  │        | [9] [260505_160232] code:code_quality - COMMENTED - (2m38s)                                                                          │    │
│                                                             ││  │        | [10] [260505_160233] code:complete - COMMENTED - (3m59s)                                                                             │    │
│                                                             ││  │        | [11] [260505_160234] code:bugs - COMMENTED - (3m47s)                                                                                 │    │
│                                                             ││  │  TIMESTAMPS:  [folded: 3]                                                                                                                     │    │
│                                                             ││  │    [260505_160030] COMMIT (2)                                                                                                                 │    │
│                                                             ││  │                                                                                                                                               │    │
│                                                             ││  ╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯    │
│                                                             ││                                                                                                                                                       │
│                                                             ││                                                                                                                                                       │
│                                                             ││                                                                                                                                                       │
│                                                             ││                                                                                                                                                       │
│                                                             ││                                                                                                                                                       │
│                                                             ││                                                                                                                                                       │
│                                                             ││                                                                                                                                                       │
│                                                             ││                                                                                                                                                       │
└─────────────────────────────────────────────────────────────┘│                                                                                                                                                       │
┌─────────────────────────────────────────────────────────────┐│                                                                                                                                                       │
│ ANCESTORS                                                   ││                                                                                                                                                       │
│   [<a] yserve_dto_fixes [S]                                 │└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
│   [<<] yserve_pql_parity [S]                                │┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                             ││ View:   1-5 or 3@ (@ to edit) or 3% (% to copy path)                                                                                           cancel │
└─────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 b rebase  d diff  M mail  n rename  R rewind  v files  w reword  W add tag  Y sync                                                                                                                     RUNNING   [*1]

 ^e End/Fill  ^d Scroll Down  ^u Clear to start  ^f Forward  ^b Backward  esc Cancel

### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `sase_commit`)