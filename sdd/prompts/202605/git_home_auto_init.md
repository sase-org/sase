---
plan: sdd/tales/202605/git_home_auto_init.md
---
 The `#git` VCS xprompt workflow is supposed to initialize the bare git repo if it doesn't exist yet. Can you help me fix this (see the `sase ace` snapshot below)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                                     sase ace
  CLs  │  Agents  │  AXE                                                                                                                                                                    CODEX(gpt-5.5)  ■ IDLE  ✉ 0
 11 Agents [2 running · 2 waiting · 2 failed · 5 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 3s)
┌─ (untagged) · 5 [R1 W1 F2 D1] ─────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✗ Failed ━━━━━━━━━━  2 agents · 2 failed                      ││                                                                                                                                                    │
│  │  🐼 . (FAILED) ×1                                           ││  AGENT DETAILS                                                                                                                                     │
│  │  🐼 home (FAILED) ×1                                        ││                                                                                                                                                    │
│                                                                ││  ChangeSpec: home                                                                                                                                  │
│  ▶ Running ━━━━━━━━━  1 agent · 1 running                      ││  Workspace: #10                                                                                                                                    │
│  │  🤖 sase (RUNNING) ×4 @qc     🏃‍♂️ 3m04s                      ││  Model: QWEN(qwen3-coder-flash)                                                                                                                    │
│                                                                ││  VCS: GitHub                                                                                                                                       │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━  1 agent                     ││  PID: 3067443                                                                                                                                      │
│  │  🎭 sase (WAITING) @qc.r1                                   ││  Timestamps: BEGIN | 2026-05-12 14:22:25                                                                                                           │
│                                                                ││                                                                                                                                                    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━  1 agent                      ││  ERROR                                                                                                                                             │
│  │  🐼 . (DONE) ×2                                             ││  Step 'main' failed: WorkflowExecutionError: Python step 'setup' failed: Traceback (most recent call last):                                        │
│                                                                ││    File "<string>", line 2, in <module>                                                                                                            │
│                                                                ││      main(                                                                                                                                         │
│                                                                ││      ~~~~^                                                                                                                                         │
│                                                                ││          git_ref="home",                                                                                                                           │
│                                                                ││          ^^^^^^^^^^^^^^^                                                                                                                           │
│                                                                ││      ...<2 lines>...                                                                                                                               │
│                                                                ││          workflow_label=None,                                                                                                                      │
│                                                                ││          ^^^^^^^^^^^^^^^^^^^^                                                                                                                      │
│                                                                ││      )                                                                                                                                             │
│                                                                ││      ^                                                                                                                                             │
│                                                                ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/scripts/git_setup.py", line 24, in main                                                │
│                                                                ││      resolved = resolve_git_ref(git_ref)                                                                                                           │
│                                                                ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/workspace_provider/plugins/bare_git_ref.py", line 184, in resolve_git_ref              │
│                                                                ││      raise _home_project_setup_error("BARE_REPO_DIR is not set")                                                                                   │
│                                                                ││  ValueError: Default bare-git project 'home' is not ready: BARE_REPO_DIR is not set. Run `sase init-git home --existing <bare-repo> --clone-dir    │
│                                                                ││  <checkout-dir>` so #git:home points at the intended home/dotfiles repository, or use `#cd:~` for a direct home-directory run with no VCS          │
│                                                                ││  workspace.                                                                                                                                        │
│                                                                ││                                                                                                                                                    │
│                                                                ││  ──────────────────────────────────────────────────                                                                                                │
│                                                                ││                                                                                                                                                    │
│                                                                ││  AGENT XPROMPT                                                                                                                                     │
│                                                                ││                                                                                                                                                    │
│                                                                ││  %model:qwen/qwen3-coder-flash #git:home Describe this repo in three concise bullets.                                                              │
│                                                                ││                                                                                                                                                    │
│                                                                ││  ──────────────────────────────────────────────────                                                                                                │
│                                                                ││                                                                                                                                                    │
│                                                                ││  AGENT PROMPT                                                                                                                                      │
│                                                                ││                                                                                                                                                    │
│                                                                ││  No prompt file found.                                                                                                                             │
│                                                                ││                                                                                                                                                ▃▃  │
│                                                                ││  Traceback (most recent call last):                                                                                                                │
│                                                                ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor.py", line 325, in execute                                    │
└────────────────────────────────────────────────────────────────┘│      success = self._execute_prompt_step(step, step_state)                                                                                         │
                                                                  │    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_prompt.py", line 205, in _execute_prompt_step          │
┌─ #sase-36 · 6 [R1 W1 D4] ──────────────────────────────────────┐│      self._expand_embedded_workflows_in_prompt(early.prompt)                                                                                       │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││      ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^                                                                                       │
│  │  ⚡ 🤖 sase (RUNNING) ×4 ◆ @sase-36.5             🏃‍♂️ 13m    ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_embedded_expand.py", line 212, in                      │
│                                                                ││  _expand_embedded_workflows_in_prompt                                                                                                              │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agen    ││      success = self._execute_embedded_workflow_steps(                                                                                              │
│  │  ⚡ 🤖 sase (WAITING) ◆ @sase-36                            ││          pre_steps,                                                                                                                                │
│                                                                ││      ...<5 lines>...                                                                                                                               │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents    ││          embedded_workflow_name=p.name,                                                                                                            │
│  │  ▸ sase-36 ───────────────────────────────────  4 agents    ││      )                                                                                                                                             │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-36.4     14:06:58 · 10m28s    ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_embedded.py", line 170, in                             │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-36.3      14:02:25 · 5m56s    ││  _execute_embedded_workflow_steps                                                                                                                  │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-36.2     14:10:17 · 13m49s    ││      success = self._execute_python_step(step, temp_state)                                                                                         │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-36.1     14:09:39 · 13m12s    ││                                                                                                                                                    │
└────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────────── ○ files  ○ thinking ────────────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```