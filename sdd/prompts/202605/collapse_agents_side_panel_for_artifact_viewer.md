---
plan: sdd/tales/202605/collapse_agents_side_panel_for_artifact_viewer.md
---
 Can you help me make it so we collapse the agent side panel on the "Agents" tab of the `sase ace` TUI when the artifact viewer is visible in a tmux pane? This makes sense because we should be focused on the current agent (navigating to another agent row would be confusing so disable that until the artifact viewer is closed--inform the user with a toast why they can't if they try). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
