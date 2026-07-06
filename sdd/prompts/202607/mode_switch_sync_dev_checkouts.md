---
plan: sdd/tales/202607/mode_switch_sync_dev_checkouts.md
---
 When the `m` (switch) keymap is used on the "Updates" tab of the "SASE Admin Center" panel to switch from the
PyPI versions of installed sase packages to the corresponding dev/editable versions of those packages, we should be
making sure to sync every one of those sase repos with the corresponding master branch (e.g. by running the `git pull`
command in that repo directory or something similar). I don't believe we're currently doing this. Can you help me
confirm my suspicion, diagnose the root cause of this issue, and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  