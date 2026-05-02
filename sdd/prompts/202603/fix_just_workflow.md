---
plan: sdd/tales/202603/fix_just_workflow.md
---
The `#sase/fix_just` workflow is broken (see below). Can you help me diagnose the root cause of this issue and fix it?
Think this through thoroughly and create a plan using your `/sase_plan` skill.

```
❯ run "#gh:sase #sase/fix_just"

╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────── Workflow Started ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   Workflow: sase/fix_just                                                                                                                                                                                                                          │
│   Inputs: (none)                                                                                                                                                                                                                                   │
│   Steps: 6                                                                                                                                                                                                                                         │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Step 1/6: _just_fmt_check (bash)
--------------------------------

  Completed (0.22s)
  Output:
    success: false

Step 2/6: _just_lint (bash)
---------------------------

  Completed (2.12s)
  Output:
    success: true

Step 3/6: _just_test (bash)
---------------------------

  Completed (126.27s)
  Output:
    success: true

Step 4/6: fix_fmt (bash)
------------------------
  Condition: {{ not _just_fmt_check.success }} -> true
╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Failed ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   Workflow failed                                                                                                                                                                                                                                  │
│   Error: Bash step 'fix_fmt' failed: .venv/bin/ruff format src/ tests/                                                                                                                                                                             │
│ .venv/bin/ruff check --fix src/ tests/                                                                                                                                                                                                             │
│ prettier --write --prose-wrap=always --print-width=120 "**/*.md"                                                                                                                                                                                   │
│ git ls-files '*.yml' '*.yaml' | xargs keep-sorted                                                                                                                                                                                                  │
│ .venv/bin/ruff format src/ tests/                                                                                                                                                                                                                  │
│ .venv/bin/ruff check --fix src/ tests/                                                                                                                                                                                                             │
│ prettier --write --prose-wrap=always --print-width=120 "**/*.md"                                                                                                                                                                                   │
│   Total duration: 137.25s                                                                                                                                                                                                                          │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Traceback (most recent call last):
  File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor.py", line 323, in execute
    success = self._execute_bash_step(step, step_state)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor_steps_script.py", line 128, in _execute_bash_step
    raise WorkflowExecutionError(f"Bash step '{step.name}' failed: {error_msg}")
sase.xprompt.workflow_models.WorkflowExecutionError: Bash step 'fix_fmt' failed: .venv/bin/ruff format src/ tests/
.venv/bin/ruff check --fix src/ tests/
prettier --write --prose-wrap=always --print-width=120 "**/*.md"
git ls-files '*.yml' '*.yaml' | xargs keep-sorted
.venv/bin/ruff format src/ tests/
.venv/bin/ruff check --fix src/ tests/
prettier --write --prose-wrap=always --print-width=120 "**/*.md"

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/bryan/.pyenv/versions/3.12.11/bin/sase", line 6, in <module>
    sys.exit(main())
             ^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/entry.py", line 21, in main
    handle_run_special_cases(args_after_run)
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/query_handler/special_cases.py", line 158, in handle_run_special_cases
    _run_query(potential_query)
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/query_handler/special_cases.py", line 46, in _run_query
    run_query(prompt)
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/query_handler/_query.py", line 556, in run_query
    result = execute_workflow(
             ^^^^^^^^^^^^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_runner.py", line 508, in execute_workflow
    success = executor.execute()
              ^^^^^^^^^^^^^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/xprompt/workflow_executor.py", line 379, in execute
    raise WorkflowExecutionError(
sase.xprompt.workflow_models.WorkflowExecutionError: Step 'fix_fmt' failed: Bash step 'fix_fmt' failed: .venv/bin/ruff format src/ tests/
.venv/bin/ruff check --fix src/ tests/
prettier --write --prose-wrap=always --print-width=120 "**/*.md"
git ls-files '*.yml' '*.yaml' | xargs keep-sorted
.venv/bin/ruff format src/ tests/
.venv/bin/ruff check --fix src/ tests/
prettier --write --prose-wrap=always --print-width=120 "**/*.md"

```
