---
plan: sdd/plans/202604/bug_id_cli_option.md
---
Can you help me add a new `-B|--bug-id` option to the `sase commit` command that takes an integer bug ID as an argument?
This should allow users to explicitly set the bug ID without needing to set the `$SASE_BUG_ID` environment variable.
Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### Additional Requirements

- We shouldn't need to update the `/sase_git_commit` skills for this.
