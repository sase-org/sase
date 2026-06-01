---
plan: sdd/epics/202606/project_lifecycle_cli_tui.md
---
 #fork:research_swarm.final-26 Can you help me implement the command line interface and TUI changes necessary to support active/archived/closed projects? See the research markdown file we just created for context and inspiration. Make sure that a global keymap (e.g. `,P`) is added that opens a panel that allows the user to view all active/archived/closed projects. This panel should support filtering based on state and should make it easy for the user to change a project's state from the TUI.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

