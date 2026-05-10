---
plan: sdd/tales/202604/parent_p4head_leak.md
---
The `sase commit` command just created a ChangeSpec with a PARENT field value of "p4head". This is a sentinel value used
by the hg VCS (see the ../retired Mercurial plugin repo) that represents the main branch of the repo (this should be "main" or
"master" for the git/GitHub VCSes). We should never set PARENT to this value. Can you help me diagnose the root cause of
this issue and fix it? Make sure everything is appropriately VCS-agnostic. Think this through thoroughly and create a
plan using your `/sase_plan` skill before making any file changes.

### DYNAMIC MEMORY

- @.sase/memory/long-external-repos.md (matched: `retired Mercurial plugin`)
- @.sase/memory/long-generated-skills.md (matched: `sase commit`)
