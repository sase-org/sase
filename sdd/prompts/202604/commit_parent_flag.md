---
plan: sdd/tales/202604/commit_parent_flag.md
---
When `sase commit` is used with `-t create_pull_request` from a branch other than master/main, we should assume that the
PR associated with the current branch will be the parent of the new PR we create. We should therefore set the PARENT
ChangeSpec field appropriately for the new ChangeSpec, but it doesn't look like we set PARENT currently in this case (at
least its not working for child CLs created by the `#split` xprompt workflow--defined in the ../retired Mercurial plugin repo). Can
you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your
`/sase_plan` skill before making any file changes.
