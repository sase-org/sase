---
plan: sdd/tales/202603/commit_propose_entry_ids.md
---
It doesn't seem like new proposals (these are entries containing letters in a ChangeSpec COMMITS field) are getting
created by the `#propose` workflow (see the src/sase/xprompts/propose.yml file). See the `sase ace` snapshots below for
reference. Can you help me diagnose the root cause of this issue and fix it?

- Instead it seems to act just like the `#commit` workflow.
- On that note, I'm not sure if the `#commit` workflow adds a new (all nueric) COMMITS entry either. Can you check that
  and, if necessary, fix that too?
- The agent (seen in the 2nd `sase ace` snapshot below) also has a bad value for the `Proposal Id` field. It is
  currently `Proposal Id: http://cl/889496570`, where I want it to show `Proposal Id: (1a)`.

Think this through thoroughly and create a plan using your `/sase_plan` skill.

### `sase ace` Snapshot (the ChangeSpec that should have had the new `(1a)` proposal added to it)

```
⭘                                                                                                     sase ace
  CLs (1)  │  Agents (x7)  │  AXE (4)                                                                                                                                                                               ✉ 8
 ChangeSpec: 1/1   +29X   (auto-refresh in 8s)  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
┌──────────────────────────────────────────────┐│ Search Query » project:eval                                                                                                                                    [0]   │
│  [!D] eval_foobar_2 (http://cl/889496570)    │└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
│                                              │┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                              ││                                                                                                                                                                      │
│                                              ││  ╭───────────────────────────────────────────────────────────── ~/.sase/projects/eval/eval.gp:543 ──────────────────────────────────────────────────────────────╮    │
│                                              ││  │                                                                                                                                                              │    │
│                                              ││  │  NAME: eval_foobar_2                                                                                                                                         │    │
│                                              ││  │  DESCRIPTION:                                                                                                                                                │    │
│                                              ││  │    Add foobar field to SizeSetting model                                                                                                                     │    │
│                                              ││  │  CL: http://cl/889496570                                                                                                                                     │    │
│                                              ││  │  STATUS: Draft                                                                                                                                               │    │
│                                              ││  │  COMMITS:                                                                                                                                                    │    │
│                                              ││  │    (1) [run] Initial Commit                                                                                                                                  │    │
│                                              ││  │        | CHAT: ~/.sase/chats/eval_foobar-sase_commit-260325_193750.md (3s)                                                                                   │    │
│                                              ││  │        | DIFF: ~/.sase/diffs/eval_foobar-260325_193750.diff                                                                                                  │    │
│                                              ││  │  HOOKS:                                                                                                                                                      │    │
│                                              ││  │    !$retired_mercurial_plugin_presubmit                                                                                                                                   │    │
│                                              ││  │        | (1) [260325_193804] FAILED (6s) - (!: retired_mercurial_plugin_presubmit failed: size_setting.dart is out of date; sync or resolve required.)                    │    │
│                                              ││  │    $retired_mercurial_plugin_lint  [folded: PASSED: 1]                                                                                                                    │    │
│                                              ││  │                                                                                                                                                              │    │
│                                              ││  ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯    │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
└──────────────────────────────────────────────┘│                                                                                                                                                                      │
┌──────────────────────────────────────────────┐│                                                                                                                                                                      │
│ SIBLINGS (1 hidden)                          ││                                                                                                                                                                      │
│                                              ││                                                                                                                                                                      │
└──────────────────────────────────────────────┘└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 COPY ! +snap  % raw  b bug  c CL#  n name  p spec  s snap                                                                                                                                                     RUNNING
```

### `sase ace` Snapshot (the agent that should have created the new `(1a)` proposal on the `eval_foobar_2` ChangeSpec)

```
⭘                                                                                                     sase ace
  CLs (1)  │  Agents (1 x7)  │  AXE (4)                                                                                                                                                                             ✉ 8
 Agents: 1/8   [view: collapsed]   (auto-refresh in 1s)
┌──────────────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✘ [agent] eval_foobar_2 (DONE) (7 steps) @h             ││                                                                                                                                                          │
│  ✘ [agent] eval (DONE) (4 steps) @g                      ││  AGENT DETAILS                                                                                                                                           │
│  ✘ [agent] eval (DONE) (4 steps) @f                      ││                                                                                                                                                          │
│  ✘ [agent] eval (DONE) (4 steps) @e                      ││  ChangeSpec: eval_foobar_2 (http://cl/889496570)                                                                                                         │
│  ✘ [agent] eval (DONE) (4 steps) @d                      ││  Workspace: #100                                                                                                                                         │
│  ✘ [agent] eval (DONE) (4 steps) @b                      ││  Embedded Workflows: hg(name=eval_foobar_2), propose                                                                                                     │
│  ✘ [agent] eval (DONE) (4 steps) @a                      ││  Model: GEMINI(gemini-3-flash-preview)                                                                                                                   │
│  [agent] pat_line_chart_component (RUNNING) (3 steps)    ││  VCS: Mercurial                                                                                                                                          │
│                                                          ││  PID: 658707                                                                                                                                             │
│                                                          ││  Name: @h                                                                                                                                                │
│                                                          ││  Timestamps: BEGIN | 2026-03-25 19:47:16                                                                                                                 │
│                                                          ││              END   | 2026-03-25 19:52:26                                                                                                                 │
│                                                          ││                                                                                                                                                          │
│                                                          ││  Proposal Id: http://cl/889496570                                                                                                                        │
│                                                          ││  Commit Message: Add tests for SizeSetting foobar field and fix build issue by removing @OpField() from foobar as it's not in the proto yet.             │
│                                                          ││                                                                                                                                                          │
│                                                          ││  ──────────────────────────────────────────────────                                                                                                      │
│                                                          ││                                                                                                                                                          │
│                                                          ││  AGENT PROMPT                                                                                                                                            │
│                                                          ││                                                                                                                                                          │
│                                                          ││                                                                                                                                                          │
│                                                          ││  Can you add some tests for this CL?                                                                                                                     │
│                                                          ││                                                                                                                                                          │
│                                                          ││  IMPORTANT: You should make the necessary file changes, but should NOT create a commit, branch, or PR / CL yourself.                                     │
│                                                          ││  Exception: If a post-completion hook instructs you to commit, you MUST follow those instructions and commit. IMPORTANT:                             ▃▃  │
│                                                          ││  You should make the necessary file changes, but should NOT create/amend a CL.                                                                           │
│                                                          ││                                                                                                                                                          │
│                                                          ││  ### Context Files Related to this CL                                                                                                                    │
│                                                          ││                                                                                                                                                          │
│                                                          ││  - @.sase/xcmds/cl_changes-260325_194727.diff : Contains a diff of the changes made by the current CL.                                                   │
│                                                          ││  - @.sase/xcmds/cl_desc-260325_194726.txt : Contains the current CL's change description.                                                                │
│                                                          ││                                                                                                                                                          │
│                                                          ││                                                                                                                                                          │
│                                                          ││  ──────────────────────────────────────────────────                                                                                                      │
│                                                          ││                                                                                                                                                          │
│                                                          ││  AGENT CHAT                                                                                                                                              │
│                                                          ││                                                                                                                                                          │
│                                                          ││                                                                                                                                                          │
│                                                          ││  # Chat History - ace-run                                                                                                                                │
│                                                          ││                                                                                                                                                          │
│                                                          ││  **Timestamp:** 2026-03-25 19:52:26 EDT                                                                                                                  │
│                                                          ││                                                                                                                                                          │
│                                                          ││  ## Prompt                                                                                                                                               │
│                                                          ││                                                                                                                                                          │
│                                                          ││  #hg:eval_foobar_2 Can you add some tests for this CL? #propose                                                                                          │
│                                                          ││                                                                                                                                                          │
│                                                          ││  ## Response                                                                                                                                             │
│                                                          ││                                                                                                                                                          │
│                                                          ││  I will determine the current workspace type and locate the existing tests for the `SizeSetting` model.                                                  │
│                                                          ││  I will list the contents of the `size_setting/model` directory to find the tests.                                                                       │
│                                                          ││  I will read the `BUILD` file to identify any test targets.                                                                                              │
│                                                          ││  I will search for `size_setting_test.dart` in the entire codebase.                                                                                      │
│                                                          ││  I will search for `SizeSetting` in the entire codebase to find relevant tests.                                                                          │
│                                                          ││  I will check the contents of the `size_setting/service` directory to find relevant tests.                                                               │
│                                                          ││  I will search for tests for other models in the `size_setting` folder to see how they are tested.                                                       │
│                                                          ││  I will read `size_setting_test_constants.dart` to see if it needs updates.                                                                              │
│                                                          ││  I will read `size_setting_op_converter_test.dart` to see how to update the tests.                                                                       │
│                                                          ││  I will read `size_setting_op_converter.dart` to check the converter logic.                                                                              │
│                                                          ││  I will update `size_setting_test_constants.dart` to include the `foobar` field.I will update `size_setting_test_constants.dart` to include the          │
│                                                          ││                                                                                                                                                          │
└──────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────────────── ● files  ● thinking ───────────────────────────────────────────────────────────────────┘
 COPY c chat  p prompt  s snap                                                                                                                                                                                 RUNNING
```
