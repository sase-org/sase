---
plan: sdd/epics/202605/tier1_agent_index_upkeep.md
---
 Can you help me find any instances where we should be updating the tier 1 agent index but are not currently
doing so? Update the code accordingly so the tier 1 agent index is kept up-to-date. We keep dealing with bugs related to
this, so dig deep / look hard! Make sure to review the ~/.sase/plans/202605/tier1_agent_index_lifecycle.md and
~/.sase/plans/202605/tier1_index_upsert_gaps.md plan files, which are plans created by other agents to fix the same
problem, before deciding on your solution.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

