---
plan: sdd/epics/202604/standalone_xprompt_bang_prefix.md
---
 Can you help me start requiring that standalong xprompt workflows be referenced using the `#!` prefix instead
of just `#`? See the @sdd/research/202604/standalone_workflow_xprompt_split.md research file for inspiration. Make sure
these standalone xprompt workflows remain supported by the special `#@` functionality (which will now need to insert an
extra `!` character when a standalong xprompt workflow is selected) provided by the TUI's prompt input widget and the
../sase-nvim repo.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `sase-nvim`)