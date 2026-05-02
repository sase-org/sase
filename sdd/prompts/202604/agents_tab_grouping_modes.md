---
plan: sdd/epics/202604/agents_tab_grouping_modes.md
---
 Can you help me add a new keymap to the agents tab that changes the way that we group and sort agents in each of the agent group/tag panels? We should support two new sorting / grouping methods that this new key map
should cycle through: (1) sort and group by date (2) sort and group by priority/status (e.g. needs attention, running, failed, done).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 