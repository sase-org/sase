---
plan: sdd/epics/202606/plugins_tab.md
---
 #fork:070 Can you now help me add a new "Plugins" tab in-between the "Settings" and "XPrompts" tabs?

- The user should be able to manage sase plugins from this tab in all the same ways that they can with the `sase plugin` command.
- To repeat, ALL functionality of the `sase plugin` command should be replicated in this tab in the nicest, TUI-compatiable way possible.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 