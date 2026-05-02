---
plan: sdd/tales/202603/fix_non_primary_sdd_path_resolution.md
---
I just used the `c` (commit) option to commit a plan file on a remote machine for a project that does not have
`sdd.version_controlled` set. The plan was saved to the
/google/src/cloud/bbugyi/pat_102/google3/.sase/sdd/tales/deal_check_line_chart.md file on that machine. The agent ran on
workspace #102, so /google/src/cloud/bbugyi/pat_102/google3/ was its working directory. The problem, however, is that
the .sase/sdd/ directory should NEVER be created / written for non-primary workspaces. When `sdd.version_controlled` is
not set, we should always copy plans to the <primary_workspace>/.sase/sdd/tales/ (in this case, the plan file should
have been copied to /google/src/cloud/bbugyi/pat/google3/.sase/sdd/tales/deal_check_line_chart.md). Can you help me
diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your
`/sase_plan` skill.
