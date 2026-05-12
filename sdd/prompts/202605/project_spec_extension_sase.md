---
plan: sdd/epics/202605/project_spec_extension_sase.md
---
 I want to change the `.gp` filename extension, which is likely referenced quite a bit in sase's codebase (including plugin repos and the sase-core repo), used for project specs to `.sase`. Can you help me make this change?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `plugin`, `sase-core`)