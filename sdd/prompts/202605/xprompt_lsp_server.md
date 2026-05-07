---
plan: sdd/epics/202605/xprompt_lsp_server.md
---
    I want to minimize the logic in the sase-nvim plugin, give it even better functionality (e.g. add directive completion and jump-to-def), and make it easier for other editors to add support for xprompts by factoring out as much of the logic as possible to a new LSP server that we define in sase-core. Can you help me implement this? Review the recently created research markdown file that's related to this for context.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `plugin`, `sase-nvim`)