---
plan: sdd/epics/202605/agents_starting_status.md
---
 Can you help me add a new STARTING agent row status on the "Agents" tab of the `sase ace` TUI? The goal of this status
is to distinguish between agents that are actually running and agent prompts that are still being processed, where we
don't know if we should be waiting on another agent, or waiting for a certain time, or if we should even run at all
(e.g. an xprompt validation error could prevent this).

- We should use this status instead of RUNNING for agents that have just started but aren't actually running yet. For
  example, we currently can go from the RUNNING status to the WAITING status. This should not be a valid transition in
  the new system, but going from STARTING to WAITING should be.
- We should also add a new "Starting" status to the agents tab that is used to group STARTING agents when the grouping
  strategy is "by status".
- We should update the BEGIN "Timestamps:" field in the agent metadata panel to START, since this is really when this
  timestamp gets added (not at launch time).
- We should also add a new RUN timestamps field that is equal to the time that the agent went from STARTING/WAITING to
  RUNNING. We should use this timestamp entry instead of START when calculating runtimes. In other words, anywhere we
  were using the BEGIN timestamp entry for runtime calculations before, we should start using the RUN timestamp entry
  now.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

