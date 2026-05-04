---
plan: sdd/tales/202605/epic_directive.md
---
 Can you help me add a new %epic directive?

- When this directive is used and the agent creates a plan using the /sase_plan skill, we should auto-approve it as an epic.
- This should work just like the agent proposed a sase plan and then the user approved it as an epic from the TUI or by pressing the "Epic" Telegram button, for example.
- We should also add support to the `a` keymap on the "Agents" tab of the `sase ace` TUI that allows us to specify that an agent's plan should be auto-approved as an epic even though it didn't include the
  %epic directive in its prompt.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
