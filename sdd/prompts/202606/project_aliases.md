---
plan: sdd/epics/202606/project_aliases.md
---
 Can you help me add support for sase project aliases?

- This should be configured in project spec files.
- The user should be able to configure aliases from the "Project Management" panel in the TUI.
- The user should also be able to configure aliases using the `sase project` command.
- Aliases should be resolved very early in the xprompt lifecycle, so the user never actually sees them in any sase
  artifacts or output.
- When an alias `<alias>` is set for the `<prj>` project, then (assuming the GitHub VCS provider) `#gh:<alias>` should
  be resolved to `#gh:<prj>`.
- Let's set the `bob` alias for the existing `bob-cli` project as our first use-case.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

