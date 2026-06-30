---
plan: sdd/epics/202606/models_panel.md
---
 Can you help me migrate the "Model Override" panel (triggered by the `,m` keymap) to a new more general-purpose "Models" panel?

- This panel should allow the user to view and modify all currently configured model aliases.
- Any changes to model aliases should be committed and pushed (after the user confirms via a y/n panel). Make sure this feature supports the `use_chezmoi: true` configuration field (set when the user uses chezmoi to manage their dotfiles).
- We should also allow any model alias to be overridden for a user-specified period of time (use the same interfaces that we already use for this use-case, but extend it to work with all model aliases instead of just the default).
- When the default model is overridden, we should illustrate this fact the way that we do now in the TUI.
- Any other model alias override, however, needs to be represented in a different, concise, and uniform way in the TUI.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 