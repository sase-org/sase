---
plan: sdd/epics/202605/agents_tab_full_refresh_elimination.md
---
 We recently added a tier 1 (fast way) path for refreshing the agents tab on the TUI (see the sase-3s epic bead
for context), but we still seem to need to do a full refresh often. I would like to make full refreshes, which are VERY
slow, almost NEVER needed for the agent entries that we show on the agents tab. Can you help me implement a solution for
this? Review the research performed by previous agents, contained in the
sdd/research/202605/agents_tab_full_refresh_elimination.md file, for inspiration before deciding on your solution.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

