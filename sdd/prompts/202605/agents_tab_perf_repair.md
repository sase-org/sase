---
plan: sdd/epics/202605/agents_tab_perf_repair.md
---
 Our recent attempts to optimize the way the TUI loads agent data (see the sase-3r bead and git commit
3a754e943685 for context) don't seem to have worked (run some useful `jq` commands against the
~/.sase/perf/tui_trace.jsonl file for proof). Also, the agents tab was broken badly by these changes (ex: lots of agents
that I know I haven't dismissed yet are not showing on the agents tab and the agents that are showing are not showing
child steps when I use the `l` keymap). Can you help me fix these performance issues for good and then run good E2E
tests (where you actually spin up `sase ace` on your own) to verify that the performance is fixed and that all of the
agents that should are showing on the agents tab (for example, I haven't dismissed any of the sase-3r phase agents yet,
so they should be showing on the agents tab)?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 