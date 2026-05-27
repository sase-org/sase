---
plan: sdd/epics/202605/agent_group_revival.md
---
 I want to add a new `S` keymap to the TUI's agents tab that dismisses (never kills) all marked agents) and saves them for easy revival later.

- These agents should be revivable as a group from the new revival panel that we should start using for the `R` keymap.
- This new panel should show all (up to 20 with an option to load more) saved agent groups which the user should be able to select and preview.
- The final entry in the new panel should trigger a custom revival search panel, which should be equivalent to the current panel that is triggered by the `R` keymap before this change.
- I want you to lead the design on this one. Just make sure it looks beautiful! 

Can you help me implement this? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

