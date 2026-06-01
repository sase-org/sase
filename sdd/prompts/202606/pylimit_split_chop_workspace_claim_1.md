---
plan: sdd/tales/202606/pylimit_split_chop_workspace_claim_1.md
---
 Can you help me fix the `sase_pylimit_split` chop (see the `sase ace` snapshot below)? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.


### `sase ace` Snapshot
```
⭘                                                                                        sase ace (PID: 726523)
  CLs  │  Agents  │  AXE                                                                                                                                                       CODEX(gpt-5.5)  ■ IDLE  ✉ 3+2
┌────────────────────────────────────────────┐
│  ▌ [*] checks  4c                          │ [run_every / sase_pylimit_split]  │  ✗ failure  │  When: 10:05:01 (34m ago)  │  Took: 8.8s  │  Run 1/10  │  (auto-refresh in 2s)
│    └─ [✓] cl_submitted_checks              │───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
│    └─ [✓] stale_running_cleanup            │
│  ▌ [*] code_quality  19c                   │          env=subprocess_env,
│    └─ [*] sase_recent_bug_audit            │          claim_callback=_claim_spawned_child,
│    └─ [*] sase_recent_improvement_audit    │      )
│  ▌ [*] comments  18c                       │    File "/home/bryan/projects/github/sase-org/sase/src/sase/core/agent_launch_facade.py", line 61, in spawn_prepared_agent_process
│    └─ [✓] comment_checks                   │      binding(
│  ▌ [*] github_actions  4c                  │      ~~~~~~~^
│    └─ [✓] gh_actions_fix                   │          agent_launch_wire_to_json_dict(prepared),
│  ▌ [*] hooks  141c                         │          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
│    └─ [✓] hook_checks                      │          {str(key): str(value) for key, value in env.items()},
│    └─ [✓] mentor_checks                    │          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
│    └─ [✓] workflow_checks                  │          claim_callback,
│    └─ [✓] pending_checks_poll              │          ^^^^^^^^^^^^^^^
│    └─ [✓] comment_zombie_checks            │      )
│    └─ [✓] suffix_transforms                │      ^                                                                                                                                                    ▄▄
│    └─ [✓] orphan_cleanup                   │    File "/home/bryan/projects/github/sase-org/sase/src/sase/agent/launch_spawn.py", line 237, in _claim_spawned_child
│  ▌ [*] housekeeping  1c                    │      return _claim_or_prepare_home_project(pid)
│    └─ [✓] error_digest                     │    File "/home/bryan/projects/github/sase-org/sase/src/sase/agent/launch_spawn.py", line 273, in _claim_or_prepare_home_project
│  ▌ [*] memory  4c                          │      raise WorkspaceClaimError(
│    └─ [✓] memory_episodes                  │      ...<3 lines>...
│  ▌ [*] refresh_docs  19c                   │      )
│    └─ [*] sase_refresh_docs                │  sase.running_field._model.WorkspaceClaimError: Failed to claim workspace #10: workspace #10 is already claimed
│    └─ [*] sase_core_refresh_docs           │
│    └─ [*] sase_github_refresh_docs         │  The above exception was the direct cause of the following exception:
│    └─ [*] sase_nvim_refresh_docs           │
│    └─ [*] sase_telegram_refresh_docs       │  Traceback (most recent call last):
│  ▌ [*] run_every  19c                      │    File "/home/bryan/projects/github/sase-org/sase/src/sase/axe/chop_runner_agent.py", line 109, in run_agent_chop_once
│    └─ [!] sase_pylimit_split               │      result = launch_agent_from_cwd_fn(chop.agent, extra_env=extra_env)
│    └─ [✓] sase_fix_just                    │    File "/home/bryan/projects/github/sase-org/sase/src/sase/agent/launch_cwd.py", line 539, in launch_agent_from_cwd
│  ▌ [*] telegram  143c                      │      results = launch_agents_from_cwd(
│    └─ [✓] tg_inbound                       │          query,
│    └─ [✓] tg_outbound                      │      ...<2 lines>...
│  ▌ [*] waits  98c                          │          timestamp=timestamp,
│    └─ [✓] wait_checks                      │      )
│                                            │    File "/home/bryan/projects/github/sase-org/sase/src/sase/agent/launch_cwd.py", line 506, in launch_agents_from_cwd
│                                            │      execution = execute_launch_plan(
│                                            │          plan_fake_fanout("single", [query]),
│                                            │      ...<15 lines>...
│                                            │          allow_hyphenated_names=_internal_agent_name_bypass_for_launch(extra_env),
│                                            │      )
│                                            │    File "/home/bryan/projects/github/sase-org/sase/src/sase/agent/launch_executor.py", line 99, in execute_launch_plan
│                                            │      request, result = spawn_slot_with_workspace_retry(
│                                            │                        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
│                                            │          slot=slot,
│                                            │          ^^^^^^^^^^
│                                            │      ...<5 lines>...
│                                            │          spawn=spawn_fn,
│                                            │          ^^^^^^^^^^^^^^^
│                                            │      )
│                                            │      ^
│                                            │    File "/home/bryan/projects/github/sase-org/sase/src/sase/agent/launch_executor_workspace.py", line 91, in spawn_slot_with_workspace_retry
│                                            │      raise WorkspaceClaimError(
│                                            │      ...<3 lines>...
│                                            │      ) from last_error
│                                            │  sase.running_field._model.WorkspaceClaimError: Failed to claim an available workspace for sase after 6 attempts: Failed to claim workspace #10: workspace
│                                            │  #10 is already claimed
└────────────────────────────────────────────┘
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  COPY  o visible · O full · s snap                                                                                                                                                                 RUNNING
```