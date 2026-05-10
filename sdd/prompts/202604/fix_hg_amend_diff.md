---
plan: sdd/tales/202604/fix_hg_amend_diff.md
---
When sase agents on another machine finish commiting to an existing PR, the diff that is shown in the file panel on the
"Agents" tab of the `sase ace` TUI shows the diff of the entire PR, instead of just that single commit like it should.
This machine uses the retired Mercurial plugin repo. Can you help me diagnose the root cause of this issue and fix it? Think this
through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### DYNAMIC MEMORY

- @.sase/memory/long-external-repos.md (matched: `retired Mercurial plugin`)
- @.sase/memory/long-tui-development.md (matched: `TUI`, `panel`)
