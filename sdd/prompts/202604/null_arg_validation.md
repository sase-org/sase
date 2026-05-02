---
plan: sdd/tales/202604/null_arg_validation.md
---
When we pass `null` to another xprompt within an xprompt workflow, that should indicate that we want to use the default
value for that argument. Instead, it looks like we currently fail validation (see the command output below). Can you
help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file
changes.

```
 bbugyi@bbugyi  ~/projects/github/sase-org/sase   master  sase run "#hg:yserve_batch_create_update #split"

╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────── Workflow Started ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   Workflow: split                                                                                                                                                                                                                                  │
│   Inputs: cl_name="yserve_batch_create_update", project_file="/usr/...                                                                                                                                                                             │
│   Steps: 5                                                                                                                                                                                                                                         │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Step 1/5: setup (bash)
----------------------

  Completed (6.07s)
  Output:
    cl_name: yserve_batch_create_update
    diff_path: /usr/local/google/home/bbugyi/projects/github/sase-org/sase/bb/sase/yserve_batch_create_update.diff
    bug: ''
    workspace_name: yserve
    default_parent: p4head
    has_children: 'false'
    parent_submitted: 'false'
    workspace_num: 100
    project_file: /usr/local/google/home/bbugyi/.sase/projects/yserve/yserve.gp
    should_release: true
    workflow_name: split-yserve_batch_create_update

Step 2/5: generate_spec (agent)
-------------------------------
❌ XPrompt '#split_spec_generator' argument error: Argument 'should_chain_cls' expects bool, got 'None'
```
