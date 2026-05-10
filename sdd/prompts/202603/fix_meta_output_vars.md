---
plan: sdd/tales/202603/fix_meta_output_vars.md
---
The `meta_` xprompt workflow step output variables are still broken. This agent (see the `sase ace` snapshot below)
created a CL and ChangeSpec properly, so I should see the new ChangeSpec / CL name in the the agent metadata panel on
the "Agents" tab of the `sase ace` TUI, but I do not. Can you help me diagnose the root cause of this issue and fix it?
This issue is occurring on another machine that uses the ../retired Mercurial plugin plugin. I've saved a `sase logs` logpack to the
~/tmp/260325_193911/ directory to help you figure this out. Think this through thoroughly and create a plan using your
`/sase_plan` skill.

### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs (1)  │  Agents (x6)  │  AXE (4)                                                                                                                                                                               ✉ 7
 Agents: 1/6   [view: collapsed]   (auto-refresh in 5s)
┌────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✘ [agent] eval (DONE) (4 steps) @g    ││                                                                                                                                                                            │
│  ✘ [agent] eval (DONE) (4 steps) @f    ││  AGENT DETAILS                                                                                                                                                             │
│  ✘ [agent] eval (DONE) (4 steps) @e    ││                                                                                                                                                                            │
│  ✘ [agent] eval (DONE) (4 steps) @d    ││  Project: eval                                                                                                                                                             │
│  ✘ [agent] eval (DONE) (4 steps) @b    ││  Workspace: #100                                                                                                                                                           │
│  ✘ [agent] eval (DONE) (4 steps) @a    ││  Embedded Workflows: hg(name=eval), pr(name=foobar)                                                                                                                        │
│                                        ││  Model: GEMINI(gemini-3-flash-preview)                                                                                                                                     │
│                                        ││  VCS: Mercurial                                                                                                                                                            │
│                                        ││  PID: 574132                                                                                                                                                               │
│                                        ││  Name: @g                                                                                                                                                                  │
│                                        ││  Timestamps: BEGIN | 2026-03-25 19:36:36                                                                                                                                   │
│                                        ││              END   | 2026-03-25 19:38:03                                                                                                                                   │
│                                        ││                                                                                                                                                                            │
│                                        ││  ──────────────────────────────────────────────────                                                                                                                        │
│                                        ││                                                                                                                                                                            │
│                                        ││  AGENT PROMPT                                                                                                                                                              │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││  Can you help me add a new string 'foobar' field to the SizeSetting model class in the                                                                                     │
│                                        ││  contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart file? You should edit this file ONLY. Don't                                                    │
│                                        ││  worry about running tests or linters. Just make the file changes and then terminate.                                                                                      │
│                                        ││                                                                                                                                                                            │
│                                        ││  IMPORTANT: You should make the necessary file changes, but should NOT create a commit, branch, or PR / CL yourself.                                                       │
│                                        ││  Exception: If a post-completion hook instructs you to commit, you MUST follow those instructions and commit.                                                              │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││  ──────────────────────────────────────────────────                                                                                                                        │
│                                        ││                                                                                                                                                                            │
│                                        ││  AGENT CHAT                                                                                                                                                                │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││  # Chat History - ace-run                                                                                                                                                  │
│                                        ││                                                                                                                                                                            │
│                                        ││  **Timestamp:** 2026-03-25 19:38:03 EDT                                                                                                                                    │
│                                        ││                                                                                                                                                                            │
│                                        ││  ## Prompt                                                                                                                                                                 │
│                                        ││                                                                                                                                                                            │
│                                        ││  #hg:eval Can you help me add a new string 'foobar' field to the SizeSetting model class in the                                                                            │
│                                        ││  contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart file? You should edit this file ONLY. Don't                                                    │
│                                        ││  worry about running tests or linters. Just make the file changes and then terminate. #pr:foobar                                                                           │
│                                        ││                                                                                                                                                                            │
│                                        ││  ## Response                                                                                                                                                               │
│                                        ││                                                                                                                                                                            │
│                                        ││  I will start by reading the `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart` file to understand the current implementation of the             │
│                                        ││  `SizeSetting` class.                                                                                                                                                      │
│                                        ││  I will now add the `foobar` field to the `SizeSetting` class, including the necessary annotations and doc comments.                                                       │
│                                        ││  I will now update the `SizeSetting` factory constructor to include the `foobar` field as a required parameter and pass it to the generated constructor.                   │
│                                        ││  I will now update the `_postInitHook` to initialize the `foobar` field with an empty string.                                                                              │
│                                        ││  I have added the `foobar` string field to the `SizeSetting` model class in `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart`, updated the      │
│                                        ││  factory constructor, and set an initial value in `_postInitHook`.                                                                                                         │
│                                        ││  I have added the `foobar` field to the `SizeSetting` model and successfully committed the changes with the name `eval_foobar` as requested.                               │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
│                                        ││                                                                                                                                                                            │
└────────────────────────────────────────┘└─────────────────────────────────────────────────────────────────────────── ○ files  ● thinking ────────────────────────────────────────────────────────────────────────────┘
 COPY c chat  p prompt  s snap                                                                                                                                                                                 RUNNING
```
