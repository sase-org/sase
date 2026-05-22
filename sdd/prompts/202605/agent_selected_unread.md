---
plan: sdd/tales/202605/agent_selected_unread.md
---
 Currently, if an agent row is selected on the "Agents" tab of the `sase ace` TUI when it becomes unread, it doesn't show the checkmark until the user navigates to a different row. Can you help me make it so the checkmark shows immediately (even when that row is selected)? The agent row should be marked read if the user navigates back to that row somehow (e.g. by pressing `j` then `k` or by using the `,j` keymap). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
