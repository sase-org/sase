---
plan: sdd/epics/202606/plugin_catalog.md
---
 Can you help me add a new `sase plugin list` command and a new `sase plugin show <plugin_name>` command?

- The list command should show a listing of all of the sase plugins that exist, using the GitHub `sase-plugin` repo topic to figure that out (all sase plugin repos, internal and external, are expected to have this GitHub topic).
- I've already applied the `sase-plugin` GitHub topic to the sase-org/sase-github and sase-org/sase-telegram repos.
- We should cache this list (so we don't need to run slow `gh` commands every time we run the `sase plugin list` command, for example) but provide an option to the user that allows them to refresh the cache (i.e. not use it and update it with fresh data).
- The list command should clearly indicate which plugins were installed and which plugins have which GitHub topics. We should also provide a short description of each plugin somehow. Also, it should be clear whether the plugin is builtin (in the sase-org GitHub organization) or community-provided (with a warning for community-provided plugins).
- The `sase plugin show <plugin_name>` command should show a detailed view of the plugin specified by `<plugin_name>`.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 