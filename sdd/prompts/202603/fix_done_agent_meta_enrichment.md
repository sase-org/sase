---
plan: sdd/tales/202603/fix_done_agent_meta_enrichment.md
---
We finally got an agent (see the `sase ace` snapshot below) to create a CL and ChangeSpec of the correct name (see
recent, related git commits)! One problem: The CL URL and CL name for the newly created CL (it's fine if we just call
this PR like the github integration) are supposed to show in the agent metadata panel on the "Agents" tab of the
`sase ace` TUI, but they are not (hint: this is controlled by xprompt YAML workflow output variables if I recall). Can
you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your
`/sase_plan` skill.

### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs (1)  │  Agents (x5)  │  AXE (4)                                                                                                                                                                               ✉ 6
 Agents: 1/5   [view: collapsed]   (auto-refresh in 8s)
┌────────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✘ [agent] eval (DONE) (4 steps) @f    ││                                                                                                                                                                            │
│  ✘ [agent] eval (DONE) (4 steps) @e    ││  AGENT DETAILS                                                                                                                                                             │
│  ✘ [agent] eval (DONE) (4 steps) @d    ││                                                                                                                                                                            │
│  ✘ [agent] eval (DONE) (4 steps) @b    ││  Project: eval                                                                                                                                                             │
│  ✘ [agent] eval (DONE) (4 steps) @a    ││  Workspace: #100                                                                                                                                                           │
│                                        ││  Embedded Workflows: hg(name=eval), pr(name=foobar)                                                                                                                        │
│                                        ││  Model: GEMINI(gemini-3-flash-preview)                                                                                                                                     │
│                                        ││  VCS: Mercurial                                                                                                                                                            │
│                                        ││  PID: 130650                                                                                                                                                               │
│                                        ││  Name: @f                                                                                                                                                                  │
│                                        ││  Timestamps: BEGIN | 2026-03-25 18:33:46                                                                                                                                   │
│                                        ││              END   | 2026-03-25 18:35:19                                                                                                                                   │
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
│                                        ││  **Timestamp:** 2026-03-25 18:35:19 EDT                                                                                                                                    │
│                                        ││                                                                                                                                                                            │
│                                        ││  ## Prompt                                                                                                                                                                 │
│                                        ││                                                                                                                                                                            │
│                                        ││  #hg:eval Can you help me add a new string 'foobar' field to the SizeSetting model class in the                                                                            │
│                                        ││  contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart file? You should edit this file ONLY. Don't                                                    │
│                                        ││  worry about running tests or linters. Just make the file changes and then terminate. #pr:foobar                                                                           │
│                                        ││                                                                                                                                                                            │
│                                        ││  ## Response                                                                                                                                                               │
│                                        ││                                                                                                                                                                            │
│                                        ││  I will begin by reading the `size_setting.dart` file to understand the `SizeSetting` class structure and determine how to correctly add the `foobar` field.               │
│                                        ││  I will add the `foobar` field to the `SizeSetting` class, update its factory constructor, and include it in the `_postInitHook` for initialization.                       │
│                                        ││  I have added the `foobar` field to the `SizeSetting` model class in `contentads/drx/fe/client/exchange/size_setting/model/lib/size_setting.dart` and updated the          │
│                                        ││  factory constructor and initialization hook accordingly.I will activate the `sase_hg_commit` skill to retrieve the necessary instructions for committing my changes to    │
│                                        ││  the repository.                                                                                                                                                           │
│                                        ││  I will verify the workspace type and check for any active beads before committing the changes with the required `eval_foobar` name.                                       │
│                                        ││  I will check the workspace type using `mcp_CodeMind_get_current_workspace` to ensure I'm using the correct toolchain before proceeding with the commit.                   │
│                                        ││  I will run `hg status` to confirm the changes I've made before finalizing and executing the commit command.                                                               │
│                                        ││  I will now commit the changes with the required `eval_foobar` name and a descriptive message.                                                                             │
│                                        ││  I have successfully added the `foobar` field to the `SizeSetting` model and committed the changes under the required name `eval_foobar`.                                  │
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
