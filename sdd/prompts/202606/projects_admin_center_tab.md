---
plan: sdd/epics/202606/projects_admin_center_tab.md
---

 Can you help me get rid of the `,p` keymap and move the "Project Management" panel's functionality to the "SASE Admin Center" panel, which is triggered via the `#` keymap?

- This panel should be accessible via a new "Projects" tab that is to the right of the existing "Config" tab.
- Make sure we do not lose ANY of the functionality that the current "Project Management" tab offers (it should all be able to be replicated from this new "Projects" tab).
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 