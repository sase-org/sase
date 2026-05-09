---
plan: sdd/epics/202605/pyvision_external_repos.md
---
 Can you help me add support to pyvision (defined in my chezmoi repo) for checking for references in external
repos? Once pyvision has the necessary functionality you should completely obsolete and remove the
legacy public API whitelist file and remove all old whitelist pyvision pragmas in this repo in favor of pragmas
of the form `# pyvision: <uri_of_external_repo>`.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)
