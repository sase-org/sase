---
plan: sdd/tales/202605/xprompt_space_encoding.md
---
 Can you help me fix this agent launch failure which happened on a different machine (see the `sase ace` snapshot below)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                         sase ace (PID: 67407)
  CLs  │  Agents  │  AXE                                                                                                                                                                 CLAUDE(opus)  ✉ 3+0
 1 Agents [1 failed · 1 unread]   [view: file]   [group: by project (o)]   (auto-refresh in 5s)                                                ▌
┌─ (untagged) · 1 [F1 U1] ─────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────▌ Axe: CLAUDE(opus) @f failed: ace(run)-260523_152938       ─┐
│  ▌ sase ━━━━━━━━━━━━━━━━  1 agent · 1 failed             ││                                                                                  ▌                                                            │
│  │  🎭 sase (FAILED) ×1 @f  15:29:40 · ❌ 0s             ││  AGENT DETAILS                                                                                                                                │
│                                                          ││                                                                                                                                               │
│                                                          ││  Project: sase                                                                                                                                │
│                                                          ││  Workspace: #10                                                                                                                               │
│                                                          ││  Model: CLAUDE(opus)                                                                                                                          │
│                                                          ││  VCS: GitHub                                                                                                                                  │
│                                                          ││  PID: 69575                                                                                                                                   │
│                                                          ││  Name: @f                                                                                                                                     │
│                                                          ││  Timestamps: START | 2026-05-23 15:29:38                                                                                                      │
│                                                          ││              RUN   | 2026-05-23 15:29:39                                                                                                      │
│                                                          ││              DONE  | 2026-05-23 15:29:40                                                                                                      │
│                                                          ││                                                                                                                                               │
│                                                          ││  ERROR                                                                                                                                        │
│                                                          ││  Step 'main' failed: WorkflowExecutionError: Python step 'setup' output validation failed: At workspace_dir: expected path (no spaces),       │
│                                                          ││  got '/Users/bbugyi/Library/Application Support/sase/wor...'                                                                                  │
│                                                          ││                                                                                                                                               │
│                                                          ││  ──────────────────────────────────────────────────                                                                                           │
│                                                          ││                                                                                                                                               │
│                                                          ││  AGENT XPROMPT                                                                                                                                │
│                                                          ││                                                                                                                                               │
│                                                          ││  #gh:sase My display brightness on this MacBook constantly gets automatically dimmed. Can you adjust whatever setting you need to on this     │
│                                                          ││  system to stop that from happening? #plan                                                                                                    │
│                                                          ││                                                                                                                                               │
│                                                          ││  ──────────────────────────────────────────────────                                                                                           │
│                                                          ││                                                                                                                                               │
│                                                          ││  AGENT PROMPT                                                                                                                                 │
│                                                          ││                                                                                                                                               │
│                                                          ││  No prompt file found.                                                                                                                        │
│                                                          ││                                                                                                                                               │
│                                                          ││  Traceback (most recent call last):                                                                                                           │
│                                                          ││    File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor.py", line 330, in execute                             │
│                                                          ││      success = self._execute_prompt_step(step, step_state)                                                                                    │
│                                                          ││                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^                                                                                    │
│                                                          ││    File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_prompt.py", line 205, in                        │
│                                                          ││  _execute_prompt_step                                                                                                                         │
│                                                          ││      self._expand_embedded_workflows_in_prompt(early.prompt)                                                                                  │
│                                                          ││    File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_embedded_expand.py", line 212, in               │
│                                                          ││  _expand_embedded_workflows_in_prompt                                                                                                         │
│                                                          ││      success = self._execute_embedded_workflow_steps(                                                                                         │
│                                                          ││                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^                                                                                         │
│                                                          ││    File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_embedded.py", line 170, in                      │
│                                                          ││  _execute_embedded_workflow_steps                                                                                                             │
│                                                          ││      success = self._execute_python_step(step, temp_state)                                                                                    │
│                                                          ││                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^                                                                                    │
│                                                          ││    File "/Users/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_script.py", line 328, in                        │
│                                                          ││  _execute_python_step                                                                                                                         │
│                                                          ││      raise WorkflowExecutionError(                                                                                                            │
│                                                          ││  sase.xprompt.workflow_models.WorkflowExecutionError: Python step 'setup' output validation failed: At workspace_dir: expected path (no       │
│                                                          ││  spaces), got '/Users/bbugyi/Library/Application Support/sase/wor...'                                                                         │
│                                                          ││                                                                                                                                               │
│                                                          ││                                                                                                                                               │
│                                                          ││                                                                                                                                               │
│                                                          ││                                                                                                                                               │
│                                                          ││                                                                                                                                               │
│                                                          ││                                                                                                                                               │
│                                                          ││                                                                                                                                               │
│                                                          ││                                                                                                                                               │
└──────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────────── ○ files  ○ tools ───────────────────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
```

### Additional Requirements

- xprompt arguments should not support spaces so we will need to implement some kind of character substitution (we could, for example, replace `+` with ` ` internally) for that.