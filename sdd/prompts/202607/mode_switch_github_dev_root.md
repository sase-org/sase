---
plan: sdd/tales/202607/mode_switch_github_dev_root.md
---
 When we switch from the PyPI version of sase to the dev version (using the `m` keymap on the "Updates" tab in the "SASE Admin Center" panel), we currently appear to store the GitHub repos in the ~/projects/git/ directory by default. Can you help me start storing them in the ~/projects/github/ directory instead? Also, we should use SSH-style remotes for these cloned repos (i.e. `git clone git@github.com:sase-org/sase.git` instead of `git clone https://github.com/sase-org/sase`).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  