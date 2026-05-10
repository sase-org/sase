---
plan: sdd/epics/202605/lumberjack_quality_chops.md
---
  Can you help me add two new lumberjack chops?

- They should both be like the chop that refreshes docs in that they abort early if there haven't been at least 50 commits that have been made since the last time their agents ran.

- The first chop should look at all of the commits that have been made since the last time it ran and checked them for bugs. If it finds any it should fix them.
- The second job should be similar except for it should look for improvements it can make. Make sure you instruct this agent to only make changes if they are clear, objective wins. 
- Both of these agents should embed the 'pr' xprompt in their prompts.
- At least one of the implementation phases should cover extensive end-to-end testing using a fast model like sonnet.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 