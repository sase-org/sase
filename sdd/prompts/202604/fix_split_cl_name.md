---
plan: sdd/tales/202604/fix_split_cl_name.md
---
Can you help me fix the `#split` xprompt workflow (defined in the ../retired Mercurial plugin repo)? See the command output below for
reference. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
bbugyi@bbugyi  ~/projects/github/sase-org/sase   master  sase run "#hg:yserve_batch_create_update #split"

╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────── Workflow Started ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   Workflow: split                                                                                                                                                                                                                                  │
│   Inputs: split_desc=None, chain=None                                                                                                                                                                                                              │
│   Steps: 6                                                                                                                                                                                                                                         │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Step 1/6: setup (bash)
----------------------
╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Failed ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   Workflow failed                                                                                                                                                                                                                                  │
│   Error: 'cl_name' is undefined                                                                                                                                                                                                                    │
│   Total duration: 0.03s                                                                                                                                                                                                                            │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Traceback (most recent call last):
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor.py", line 323, in execute
    success = self._execute_bash_step(step, step_state)
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_script.py", line 93, in _execute_bash_step
    rendered_command = render_template(step.bash, self.context)
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_utils.py", line 53, in render_template
    return jinja_template.render(merged)
           ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^
  File "/usr/local/google/home/bbugyi/.local/share/uv/tools/sase/lib/python3.13/site-packages/jinja2/environment.py", line 1295, in render
    self.environment.handle_exception()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/usr/local/google/home/bbugyi/.local/share/uv/tools/sase/lib/python3.13/site-packages/jinja2/environment.py", line 942, in handle_exception
    raise rewrite_traceback_stack(source=source)
  File "<template>", line 1, in top-level template code
jinja2.exceptions.UndefinedError: 'cl_name' is undefined

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/usr/local/google/home/bbugyi/.local/bin/sase", line 10, in <module>
    sys.exit(main())
             ~~~~^^
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/main/entry.py", line 21, in main
    handle_run_special_cases(args_after_run)
    ~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/main/query_handler/special_cases.py", line 158, in handle_run_special_cases
    _run_query(potential_query)
    ~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/main/query_handler/special_cases.py", line 46, in _run_query
    run_query(prompt)
    ~~~~~~~~~^^^^^^^^
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/main/query_handler/_query.py", line 279, in run_query
    raise workflow_error
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/main/query_handler/_query.py", line 229, in run_query
    result = execute_workflow(
        anon_workflow.name,
    ...<4 lines>...
        project=vcs_project,
    )
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_runner.py", line 503, in execute_workflow
    success = executor.execute()
  File "/usr/local/google/home/bbugyi/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor.py", line 379, in execute
    raise WorkflowExecutionError(
        f"Step '{step.name}' failed: {e}"
    ) from e
sase.xprompt.workflow_models.WorkflowExecutionError: Step 'setup' failed: 'cl_name' is undefined

```
