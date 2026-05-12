---
plan: sdd/epics/202605/chop_output_coverage.md
---
 We recently made it easy to view lumberjack chop output from the AXE tab, but most chops don't output anything useful. Can you help me add good output to all of our chops (see the sase_athena.yml file in my chezmoi repo)? 

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)