---
plan: sdd/epics/202606/log_panel.md
---
 There are currently a lot of agent launch failure types that just send a toast with minimal information that then tells the user to "see the log", but there is no way to view "the log" from the TUI. Can you help me add a new `,L` keymap that works from any tab and shows "the log" (which should probably be a few different relevant logs)? Make sure to update these error messages accordingly and make sure that any agent launch / fanout failures are always logged to one of the files that is shown in this new "Log" panel.

I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 