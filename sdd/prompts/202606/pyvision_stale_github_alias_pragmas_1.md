---
plan: sdd/tales/202606/pyvision_stale_github_alias_pragmas_1.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
---------- Validating scripts/tools directory structure... ----------
.venv/bin/python tools/pyscripts-260619
All scripts/ and tools/ directories are valid!

---------- Checking for unused Python definitions... ----------
BD_COMMAND=tools/sase_bead .venv/bin/python tools/pyvision-260608 src/sase
Error: pyvision pragma in src/sase/project_aliases.py:243: external repository 'https://github.com/sase-org/sase-github.git' does not reference symbol 'allocate_project_alias'
Error: pyvision pragma in src/sase/project_aliases.py:479: external repository 'https://github.com/sase-org/sase-github.git' does not reference symbol 'ensure_project_alias_locked'
error: Recipe `_lint-pyvision` failed on line 144 with exit code 1
error: Recipe `lint` failed on line 126 with exit code 1
Error: Process completed with exit code 1.
```

### Additional Requirements

- It seems like the sase-github repo is also experiencing related Github actions failures.