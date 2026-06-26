---
plan: sdd/epics/202606/sase_update_and_plugin_install.md
---
 Can you help me add a new `sase update` command?

- This command will assume that sase was installed via the `uv tool install sase` command or some variant of it. We should check for this and crash with a good error message if it doesn't seem to be the case.
- This command should delegate to `uv tool upgrade` (or some equivalent--you should figure out how all of this will work) to update sase and any installed sase plugins.
- This command should have excellent, useful, concise, and beautiful output.
- We should also add a new `sase plugin install <plugin>` command and a new `sase plugin update <plugin>` command that install/update the target `<plugin>`. Make sure that plugin packages that we install get injected into the same environment as `sase`.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 