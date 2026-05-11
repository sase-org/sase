---
plan: sdd/epics/202605/axe_lumberjack_chop_sidebar.md
---
  I want to remove the axe sidebar entry on the AXE tab and instead start having lumberjacks as main entries that have chops as child entries.

- When a chop is selected, we should display the output from that chop's last run.
- The just should be able to use the <ctrl+n> / <ctrl+p> keymaps to see up to the last 10 run outputs.
- We should be careful to make sure that this does not degrade performance.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

