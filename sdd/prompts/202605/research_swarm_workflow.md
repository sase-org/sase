---
plan: sdd/tales/202605/research_swarm_workflow.md
---
 Can you help me create an improved `research_swarm` xprompt workflow?

- Rename the current `research_swarm` xprompt workflow to `old_research_swarm`.
- I want this workflow to use the `foobar-@` syntax (see the xprompts/reads.md file for an example) to start 3 agents.
- The first two agents should use different models: gpt-5.5 for the first and opus for the 2nd. These agents should both
  have prompts similar to the first agent's prompt in the current `research_swarm` xprompt workflow.
- The 3rd agent should be told to verify, consolidate, and enhance (without unnecessarily increasing the length of) the
  research performed by the previous two agents. This agent should delete the two previously created research/ markdown
  files and create a new one containing this consolidated research.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
