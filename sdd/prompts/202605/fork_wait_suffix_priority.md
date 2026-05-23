---
plan: sdd/tales/202605/fork_wait_suffix_priority.md
---
 I think the root cause of this agent failure (see the `sase ace` snapshot below) is probably that we recently added support for the `.w<N>` suffix for agent's that use the `%wait` directive in their prompts, but we should always give priority to the `.f<N>` suffix when the `#fork` xprompt workflow is also found in the same agent prompt. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                        sase ace (PID: 910362)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 1+7
 34 Agents [2 running · 3 waiting · 1 failed · 8 unread · 21 done]   [siblings: 2 (~)]   [view: file]   [group: by status (o)]   (auto-refresh in 7s)
┌─ (untagged) · 15 [D15] ──────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  15 agents        ││                                                                                                                                   │
│  │  🤖 sase (DONE) ×8 @a62.f1.f2            18:10:52 · 12m42s        ││  AGENT DETAILS                                                                                                                    │
│  │  🎭 sase (TALE DONE) ×6 @a65              17:50:05 · 8m40s        ││                                                                                                                                   │
│  │  🤖 sase (TALE DONE) ×6 @a64             17:52:01 · 17m41s        ││  Project: sase                                                                                                                    │
│  │  🤖 sase (TALE DONE) ×6 @a6x              17:09:22 · 8m57s        ││  Workspace: #11                                                                                                                   │
│  │  🤖 sase (TALE DONE) ×6 @a6w             16:53:03 · 10m57s        ││  Model: CODEX(gpt-5.5)                                                                                                            │
│  │  🤖 sase (TALE DONE) ×6 @a6p             16:21:21 · 13m05s        ││  VCS: GitHub                                                                                                                      │
│  │  🤖 sase (TALE DONE) ×6 @a6o                15:52:25 · 15m        ││  PID: 1148672                                                                                                                     │
│  │  🤖 sase (TALE DONE) ×7 @a6n             16:00:07 · 29m07s        ││  Name: @a7f.f1.w1                                                                                                                 │
│  │  🤖 sase (TALE DONE) ×6 @a6m             16:05:54 · 28m53s        ││  Waiting for: a7f.f1                                                                                                              │
│  │  🤖 sase (TALE DONE) ×6 @a6l             15:42:12 · 13m56s        ││  Timestamps: WAIT  | 2026-05-23 19:08:42                                                                                          │
│  │  🤖 sase (DONE) ×6 @a6g                  15:22:44 · 14m21s        ││              RUN   | 2026-05-23 19:27:25                                                                                          │
│  │  🎭 sase (TALE DONE) ×6 @a6e.1           14:57:22 · 35m31s        ││              DONE  | 2026-05-23 19:27:34                                                                                          │
│  │  ▎ sase-41 ─────────────────────────────────────  3 agents        ││                                                                                                                                   │
└──────────────────────────────────────────────────────────────────────┘│  ERROR                                                                                                                            │
                                                                        │  Step 'main' failed: WorkflowExecutionError: Python step 'resolve' failed: Traceback (most recent call last):                     │
┌─ #chop · 1 [U1] ─────────────────────────────────────────────────────┐│    File "<string>", line 3, in <module>                                                                                           │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent    ││      main([name] if name else [])                                                                                                 │
└──────────────────────────────────────────────────────────────────────┘│      ~~~~^^^^^^^^^^^^^^^^^^^^^^^^                                                                                                 │
                                                                        │    File "/home/bryan/projects/github/sase-org/sase/src/sase/scripts/agent_chat_from_name.py", line 44, in main                    │
┌─ #read · 3 [D3] ─────────────────────────────────────────────────────┐│      print(json.dumps({"path": _resolve_agent_chat_path(args.name)}))                                                             │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents                     ││                                ~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^                                                                │
│  │  ▸ a5h ────────────────────────────  3 agents                  ▁▁ ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/scripts/agent_chat_from_name.py", line 36, in                         │
│  │  ♊ sase (DONE) ×5 @a5h.gem  11:35:32 · 1m43s                     ││  _resolve_agent_chat_path                                                                                                         │
└──────────────────────────────────────────────────────────────────────┘│      raise RuntimeError(f"No agent with chat history found for: {resolved_name}")                                                 │
                                                                        │  RuntimeError: No agent with chat history found for: a7g.f1.f1                                                                    │
┌─ #research · 9 [R1 W1 F1 U4 D3] ─────────────────────────────────────┐│                                                                                                                                   │
│  ✗ Failed ━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 failed            ││  ──────────────────────────────────────────────────                                                                               │
│  │  🤖 sase (FAILED) ×4 @a7f.f1.w1       19:27:34 · ❌ 8s            ││                                                                                                                                   │
│                                                                      ││  AGENT XPROMPT                                                                                                                    │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running            ││                                                                                                                                   │
│  │  🎭 sase (RUNNING) ×6 @a7g.f1                 🏃‍♂️ 8m27s            ││  %w %g:research #gh:sase #fork #research/image %m:gpt-5.5                                                                         │
│                                                                      ││                                                                                                                                   │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent           ││  ──────────────────────────────────────────────────                                                                               │
│  │  🤖 sase (WAITING) @a7g.f1.f1                                     ││                                                                                                                                   │
│                                                                      ││  AGENT PROMPT                                                                                                                     │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents            ││                                                                                                                                   │
│  │  🤖 sase (DONE) ×5 @a7g            19:19:44 · ✅ 9m40s            ││  No prompt file found.                                                                                                            │
│  │  ▎ a62 ─────────────────────────────────────  3 agents            ││                                                                                                                                   │
│  │  │  🤖 sase (DONE) ×5 @a62            17:36:20 · 9m15s            ││  Traceback (most recent call last):                                                                                               │
│  │  │  ▸ a62.f1 ───────────────────────────────  2 agents         ▄▄ ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor.py", line 330, in execute                   │
│  │  │  🎭 sase (DONE) ×7 @a62.f1         17:43:26 · 6m50s            ││      success = self._execute_prompt_step(step, step_state)                                                                        │
│  │  │  🤖 sase (DONE) ×7 @a62.f1.f1      17:46:43 · 3m06s            ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_prompt.py", line 205, in              │
└──────────────────────────────────────────────────────────────────────┘│  _execute_prompt_step                                                                                                         ▇▇  │
                                                                        │      self._expand_embedded_workflows_in_prompt(early.prompt)                                                                      │
┌─ #sase-42 · 6 [R1 W2 U3] ────────────────────────────────────────────┐│      ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^                                                                      │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running       ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_embedded_expand.py", line 212, in     │
│  │  ⚡ 🤖 sase (RUNNING) ×4 ◆ @sase-42.4             🏃‍♂️ 16m26s       ││  _expand_embedded_workflows_in_prompt                                                                                             │
│                                                                      ││      success = self._execute_embedded_workflow_steps(                                                                             │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents      ││          pre_steps,                                                                                                               │
│  │  ▸ sase-42 ──────────────────────────────────────  2 agents       ││      ...<5 lines>...                                                                                                              │
│  │  ⚡ 🤖 sase (WAITING) ◆ @sase-42                                  ││          embedded_workflow_name=p.name,                                                                                           │
│  │  ⚡ 🤖 sase (WAITING) ◆ @sase-42.5                                ││      )                                                                                                                            │
│                                                                      ││    File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_embedded.py", line 170, in            │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents       ││  _execute_embedded_workflow_steps                                                                                                 │
│  │  ▸ sase-42 ──────────────────────────────────────  3 agents    ▅▅ ││      success = self._execute_python_step(step, temp_state)                                                                        │
│  │  ⚡ 🤖 sase (DONE) ×5 ◆ @sase-42.3     19:11:44 · ✅ 15m42s       ││                                                                                                                                   │
└──────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────── ○ files  ○ tools ─────────────────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  c chat · n name · p prompt · s snap                                                                                                                                                         RUNNING
```