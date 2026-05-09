---
plan: sdd/epics/202605/plan_approval_custom_model_picker.md
---
 Can you help me migrate the `A` (options) keymap on the plan approval TUI modal to `c` (custom) and make some
improvements to it?

- I should be able to decide between Approve, Tale, Epic, and Legend. This will obsolete the toggle that let's us
  specify whether we commit the plan or not.
- We should improve the model picker substantially:
  - Add a new "'" appostrophe keymap and emulate how this keymap works on other panels.
  - Add an input bar so the user can filter the list of models and providers.
- Give each provider and its models a unique and beautiful styling.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

