---
plan: sdd/epics/202604/chop_agent_visibility_and_pylimit_split.md
---
 Can you help me improve the way that chops (see those configured in the sase_athena.yml file in my chezmoi repo) run agents?
- Namely, I want these agents to stop being hidden. Also, agents should be run in such a way that it is identical to running the agent via the `sase run -d` command.
- For the `sase_pylimit_split` chop, in particular, each agent except the first should contain a `%wait` directive that makes it wait until the previous agent completes.
- I think we have a `sase_pylimit_split` script defined somewhere on this machine. That should be deleted since we should use the `#sase/pylimit_split` xprompt workflow (see the xprompts/pylimit_split.yml file) to run this chop.
- We should be able to completely get rid of the "gate" functionality (currently only used by the `sase_pylimit_split` chop).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)