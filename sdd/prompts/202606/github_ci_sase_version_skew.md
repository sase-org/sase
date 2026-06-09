---
plan: sdd/tales/202606/github_ci_sase_version_skew.md
---
 GitHub Actions is failing for sase-github with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

```
Run just lint
.venv/bin/ruff check src/ tests/
All checks passed!
.venv/bin/mypy
src/sase_github/plugin.py:108: error: "vcs_create_pull_request" undefined in superclass  [misc]
src/sase_github/workspace_plugin.py:718: error: Module "sase.ace.mail_ops" has no attribute "get_cl_description"; maybe "_get_cl_description"?  [attr-defined]
Found 2 errors in 2 files (checked 7 source files)
error: recipe `lint` failed on line 17 with exit code 1
Error: Process completed with exit code 1.
```