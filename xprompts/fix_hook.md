---
name: fix_hook
input:
  - name: hook_command
    type: line
  - name: output_file
    type: path
  - name: cl_name
    type: word
    default: "null"
  - name: vcs_type
    type: word
    default: "hg"
---

{% if cl_name != "null" %}%{{ vcs_type }}:{{ cl_name }}

{% endif %}The command `{{ hook_command }}` is failing. The output of the last run can be found in the
@{{ output_file }} file. Can you help me fix this command by making the appropriate file changes? Verify that your fix
worked when you are done by re-running that command.

#propose
