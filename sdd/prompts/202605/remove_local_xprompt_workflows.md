---
plan: sdd/epics/202605/remove_local_xprompt_workflows.md
---
 The local workflows defined in the sase_athena.yml file in my chezmoi repo are very hacky. Can you help me completely remove support for local workflows (e.g. xprompt workflows that are only available inside the `sase*.yml` file they are defined in)?

- We should move all existing local workflows from the sase_athena.yml file to this repo, defined in the xprompts/ directory.
- This might require some work on the main sase repo / sase-core since we need to make sure that embedding the `#gh:sase-org/sase` VCS xprompt workflow in the agent prompt is sufficient to ensure that the xprompt workflows in the xprompts/ directory are visible / usable.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `sase-core`)