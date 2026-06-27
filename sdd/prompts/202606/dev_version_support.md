---
plan: sdd/epics/202606/dev_version_support.md
---
 Can you help me add support for editable / development versions (aka "dev" versions--ex: `0.5.0+285.g80d5c47c1`) to the `sase plugin list` command's output, the `sase update` command (which should be able to update to the latest dev version--if a dev version is already used) and the "Updates" tab in the TUI's "SASE Admin Center" panel?

- These versions are already supported for the `sase version` command.
- We should add support for dev versions to both the current and latest versions (only when the current version is an editable / development version) of each package (core and plugins).
- We should also add support for updating development versions of sase to both the `sase update` command and the "Updates" tab of the "SASE Admin Center" panel.
- Make sure to think through what it means to update a current dev version of sase and/or a sase plugin thoroughly and address all edge cases.
- We should automatically restart the TUI and restart axe (this is already supported by an option on the panel triggered by the `Q` keymap, so re-use that code/logic) after updating dev versions AND regular versions (so this change is slightly unrelated).
- See the ~/.sase/plans/202606/dev_version_updates.md and ~/.sase/plans/202606/dev_versions_updates.md plan files, which were created by other agents, for inspiration. These agents were given the same prompt as you, except for this bullet. Keep in mind that it is very possible that one plan is completely right and the other is completely wrong. It is also possible that the best answer is to integrate parts of both plans. Finally, it is possible that both of these agents missed something entirely.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

