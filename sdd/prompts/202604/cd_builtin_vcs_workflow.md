---
plan: sdd/epics/202604/cd_builtin_vcs_workflow.md
---
  Can you help me add a new #cd built-in VCS xprompt workflow?

- This VCS workflow should be the simplest of them all and not use version control at all. 
- it will just CD into the appropriate directory (given it an argument instead of a project)
- we should also migrate our existing home mode (when no VCS workflow is embedded) to be implemented by defaulting to #cd:~

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

