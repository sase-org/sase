---
name: fix_hook
description: Fix a failing hook command using its captured output file.
tags: fix_hook
input:
  - name: hook_command
    type: line
    description: Hook command that is currently failing.
  - name: output_file
    type: path
    description: File containing the most recent failing command output.
  - name: cl_name
    type: word
    default: "null"
    description: Optional ChangeSpec or PR name to attach to the fix workflow.
  - name: vcs_type
    type: word
    description: Registered workspace directive prefix to use for the ChangeSpec or PR.
---

{% if cl_name != "null" %}#{{ vcs_type }}({{ cl_name }}, workflow_label="fix_hook")

{% endif %}The command {{ "\x60" }}{{ hook_command }}{{ "\x60" }} is failing. The output of the last run can be found in
the @{{ output_file }} file. Can you help me fix this command by making the appropriate file changes? Verify that your
fix worked when you are done by re-running that command.

#propose
