---
plan: sdd/tales/202603/pr_name_env_var.md
---
This agent (see the `sase ace` snapshot below) decided to use its own CL name despite the fact that we gave "foobar" as
the name argument for the embedded `#pr` xprompt workflow. Can you help me fix this using a new `$SASE_NAME` environment
variable in the pr.yml file's `environment` field that `sase_commit_stop_hook` uses to instruct the agent the name to
use? if the `#pr` workflow is used with the name argument, then we should tell the agent that the name MUST begin with
`<project>_` where `<project>` is the current project name (you should be able to figure out how to get that). Think
this through thoroughly and create a plan using your `/sase_plan` skill.

### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs (1)  │  Agents (x2)  │  AXE (4)                                                                                                                                                                               ✉ 2
 Agents: 1/3   [view: collapsed]   (auto-refresh in 7s)
┌─────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✘ [workflow] eval (DONE) (4 steps, 3 hidden) @b    ││                                                                                                                                                               │
│    └─ 1/1 ✘ [agent] main (DONE) @b                  ││  AGENT DETAILS                                                                                                                                                │
│  ✘ [agent] eval (DONE) (4 steps) @a                 ││                                                                                                                                                               │
│                                                     ││  Project: eval                                                                                                                                                │
│                                                     ││  Workspace: #100                                                                                                                                              │
│                                                     ││  Embedded Workflows: hg(name=eval), pr(name=foobar)                                                                                                           │
│                                                     ││  Model: GEMINI(gemini-3-flash-preview)                                                                                                                        │
│                                                     ││  VCS: Mercurial                                                                                                                                               │
│                                                     ││  PID: 3380564                                                                                                                                                 │
│                                                     ││  Name: @b                                                                                                                                                     │
│                                                     ││  Timestamps: BEGIN | 2026-03-25 16:26:35                                                                                                                      │
│                                                     ││              END   | 2026-03-25 16:28:02                                                                                                                      │
│                                                     ││                                                                                                                                                               │
│                                                     ││  ──────────────────────────────────────────────────                                                                                                           │
│                                                     ││                                                                                                                                                               │
│                                                     ││  AGENT PROMPT                                                                                                                                                 │
│                                                     ││                                                                                                                                                               │
│                                                     ││                                                                                                                                                               │
│                                                     ││  Can you help me add a new string 'foobar' field to the SizeSetting model class in the                                                                        │
│                                                     ││  contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart file? You should edit this file ONLY. Don't                                       │
│                                                     ││  worry about running tests or linters. Just make the file changes and then terminate.                                                                         │
│                                                     ││                                                                                                                                                               │
│                                                     ││  IMPORTANT: You should make the necessary file changes, but should NOT create a commit, branch, or PR / CL yourself.                                          │
│                                                     ││                                                                                                                                                               │
│                                                     ││                                                                                                                                                               │
│                                                     ││  ──────────────────────────────────────────────────                                                                                                           │
│                                                     ││                                                                                                                                                               │
│                                                     ││  AGENT CHAT                                                                                                                                                   │
│                                                     ││                                                                                                                                                               │
│                                                     ││                                                                                                                                                               │
│                                                     ││  # Chat History - ace-run                                                                                                                                     │
│                                                     ││                                                                                                                                                               │
│                                                     ││  **Timestamp:** 2026-03-25 16:28:02 EDT                                                                                                                       │
│                                                     ││                                                                                                                                                               │
│                                                     ││  ## Prompt                                                                                                                                                    │
│                                                     ││                                                                                                                                                               │
│                                                     ││  #hg:eval Can you help me add a new string 'foobar' field to the SizeSetting model class in the                                                               │
│                                                     ││  contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart file? You should edit this file ONLY. Don't                                       │
│                                                     ││  worry about running tests or linters. Just make the file changes and then terminate. #pr:foobar                                                              │
│                                                     ││                                                                                                                                                               │
│                                                     ││  ## Response                                                                                                                                                  │
│                                                     ││                                                                                                                                                               │
│                                                     ││  I will begin by reading the `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart` file to understand the current structure of the     │
│                                                     ││  `SizeSetting` class.                                                                                                                                         │
│                                                     ││  I'll read the file to identify the class definition and its current fields.                                                                                  │
│                                                     ││  I'll add the `foobar` field to the `SizeSetting` class, update the factory constructor, and set a default value in the `_postInitHook`.                      │
│                                                     ││  I have added the `foobar` string field to the `SizeSetting` class in `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart`,           │
│                                                     ││  including its getter, factory constructor parameter, and initialization in the `_postInitHook`.I will activate the `sase_hg_commit` skill to commit the      │
│                                                     ││  changes to `google3/contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart`.                                                             │
│                                                     ││  I'll run `hg status` and check for any in-progress beads to include in the commit.                                                                           │
│                                                     ││  I will commit the changes to `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart` with the message "Add 'foobar' string field to     │
│                                                     ││  SizeSetting model".                                                                                                                                          │
│                                                     ││  I'll check the `$SASE_COMMIT_METHOD` environment variable to determine if `create_pull_request` is being used and if a `name` field is required.             │
│                                                     ││  I'll commit the changes to `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart` using `sase commit` with the `name`                  │
│                                                     ││  "add_foobar_field".                                                                                                                                          │
│                                                     ││  I'll check `hg status` again to ensure the changes to `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart` have been successfully    │
│                                                     ││  committed.                                                                                                                                                   │
│                                                     ││  I've added the `foobar` string field to the `SizeSetting` model and successfully committed the changes.                                                      │
│                                                     ││                                                                                                                                                               │
│                                                     ││                                                                                                                                                               │
└─────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────────────── ○ files  ● thinking ─────────────────────────────────────────────────────────────────────┘
 COPY c chat  p prompt  s snap                                                                                                                                                                                 RUNNING
```
