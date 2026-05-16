---
plan: sdd/epics/202605/fast_agents_tab_disk_load.md
---
 Can you help me make the way we load agents from disk for the "Agents" tab of the `sase ace` TUI much faster?
Use the solution recommended in the sdd/research/202605/deep_ace_tui_perf_fix.md file to inspire your solution (call out
any differences in your solution that contradict with the research file).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 