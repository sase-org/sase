---
plan: sdd/tales/202606/pyscripts_skip_nested_repos.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
---------- Validating scripts/tools directory structure... ----------
.venv/bin/python tools/pyscripts-260314
[Rule 1] Unused: sase-core/.github/scripts/check_cargo_version_edits.py is not referenced in sase-core/.github/
error: Recipe `_lint-pyscripts` failed on line 138 with exit code 1
error: Recipe `lint` failed on line 122 with exit code 1
Error: Process completed with exit code 1.
```