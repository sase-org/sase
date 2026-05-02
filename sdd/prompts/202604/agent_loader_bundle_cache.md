---
plan: sdd/plans/202604/agent_loader_bundle_cache.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
=========================== short test summary info ============================
FAILED tests/test_agent_loader_self_heal.py::test_load_agents_from_disk_includes_bundles_missing_from_index - AssertionError: assert [] == [Agent(agent_...t_history=[])]
  
  Right contains one more item: Agent(agent_type=<AgentType.WORKFLOW: 'workflow'>, cl_name='bundle_only', project_file='/tmp/projects/myproj/myproj.gp..._siblings=[], plan_times=[], code_time=None, feedback_times=[], questions_times=[], retry_times=[], attempt_history=[])
  
  Full diff:
  + []
  - [
  -     Agent(
  -         agent_type=<AgentType.WORKFLOW: 'workflow'>,
  -         cl_name='bundle_only',
  -         project_file='/tmp/projects/myproj/myproj.gp',
  -         status='DONE',
  -         start_time=datetime.datetime(2024, 1, 1, 12, 0),
  -         run_start_time=None,
  -         stop_time=None,
  -         workspace_num=None,
  -         workflow=None,
  -         hook_command=None,
  -         commit_entry_id=None,
  -         mentor_profile=None,
  -         mentor_name=None,
  -         reviewer=None,
  -         pid=None,
  -         raw_suffix='20240102120000',
  -         response_path=None,
  -         diff_path=None,
  -         extra_files=[],
  -         bug=None,
  -         cl_num=None,
  -         parent_workflow=None,
  -         parent_timestamp=None,
  -         step_name=None,
  -         step_type=None,
  -         step_source=None,
  -         step_output=None,
  -         step_index=None,
  -         total_steps=None,
  -         parent_step_index=None,
  -         parent_total_steps=None,
  -         is_hidden_step=False,
  -         appears_as_agent=False,
  -         is_anonymous=False,
  -         error_message=None,
  -         error_traceback=None,
  -         output_path=None,
  -         model=None,
  -         llm_provider=None,
  -         vcs_provider=None,
  -         agent_name=None,
  -         waiting_for=[],
  -         wait_duration=None,
  -         wait_until=None,
  -         artifacts_dir=None,
  -         embedded_workflow_name=None,
  -         is_pre_prompt_step=False,
  -         hidden=False,
  -         retry_count=0,
  -         max_retries=0,
  -         retry_next_at_epoch=None,
  -         retry_wait_seconds=0,
  -         using_fallback=False,
  -         fallback_model=None,
  -         retry_status=None,
  -         _from_changespec=False,
  -         approve=False,
  -         role_suffix=None,
  -         tag=None,
  -         followup_agents=[],
  -         retry_of_timestamp=None,
  -         retry_attempt=0,
  -         retry_chain_root_timestamp=None,
  -         retried_as_timestamp=None,
  -         retry_terminal=False,
  -         retry_error_category=None,
  -         retry_chain_siblings=[],
  -         plan_times=[],
  -         code_time=None,
  -         feedback_times=[],
  -         questions_times=[],
  -         retry_times=[],
  -         attempt_history=[],
  -     ),
  - ]
====== 1 failed, 5447 passed, 8 skipped, 15 warnings in 113.37s (0:01:53) ======
error: Recipe `test-cov` failed on line 113 with exit code 1
Error: Process completed with exit code 1.
```