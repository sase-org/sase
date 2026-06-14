---
plan: sdd/tales/202606/agent_family_context_1.md
---
 I don't think that we currently surface memory reads (or logged xprompt skills probably) from any other agent but the first in the agent family (e.g. the "plan" agent when the agent proposes a sase plan) in the agent metadata panel on the "Agents" tab of the `sase ace` TUI. Can you help me fix this?

- Make sure it is clear which agent in the family (e.g. "plan", "coder", "q", etc...) was responsible for the memory read / xprompt skill use.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
