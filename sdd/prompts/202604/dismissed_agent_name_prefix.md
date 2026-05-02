---
plan: sdd/epics/202604/dismissed_agent_name_prefix.md
---
 Can you help me start enforcing a constraint that all agents even dismissed ones that don't show in the TUI need to have an agent name?

- We will accomplish this by prepending "YYmmdd." to the agent name on dismissal, where "YYmmdd" is the date that the agent completed.
- We need to make sure to update all references to this agent name when we do that (ex: prompts that reference the name via the 'wait' directive or the 'resume' x prompt).
- This means that an agent name needs to be unique among all agents that are completed on the same day.
- if an agent is revived (using the 'R' keymap) the "YYmmdd." prefix should be stripped from its name.

 This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 