---
plan: sdd/epics/202605/agent_artifact_startup_perf.md
---
 It seems like the biggest performance bottleneck with sase is loading all of the agent artifacts. In
particular, starting up `sase ace` on a machine that has run many sase agents in the past takes much longer than
starting up a machine that has only ever run a few sase agents. Can you help me solve this performance problem without
sacrificing functionality? Review the research performed by previous agents in the
sdd/research/202605/agent_artifact_loading_startup.md file before deciding on your solution.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

