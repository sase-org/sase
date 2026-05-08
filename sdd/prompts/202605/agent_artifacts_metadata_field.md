---
plan: sdd/tales/202605/agent_artifacts_metadata_field.md
---
 When we implemented the artifact panel epic (see recent, related git commits), we messed up the user
requirements for the "ARTIFACTS" field in the agent metadata panel on the "Agents" tab of the `sase ace` TUI. Namely:

- This field should be shown below the DELTAS field.
- This field should have entries which look just like the DELTAS field except for that they do not have indicators that
  show how many lines were added/removed/modified by the agent.
- An artifact is only added as an entry to this field if it is a plan file that was proposed by the agent (use a
  ~/.sase/plans/ path if the plan file was not committed to version-control; otherwise, use a relative path) OR the
  artifact was linked to this agent using the `sase artifact create` command.
- The file paths displayed as ARTIFACTS field entries should support the `v` keymap, so the user can view them, copy
  their paths, etc...

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
