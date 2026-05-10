---
plan: sdd/epics/202605/remove_obsolete_plugin_repos.md
---
 The sase-2j epic bead has caused GitHub actions to fail because the retired chat plugin and retired Mercurial plugin repos cannot be accessed. That's fine because both of those repos are actually completely obsolete. Can you help me remove all references of those repos from this repo and all other non-obsolete plugin repos (and the sase-core repo)?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `plugin`, `retired Mercurial plugin`)