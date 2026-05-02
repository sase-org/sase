---
plan: sdd/tales/202604/fix_ci_sase_core_rs_install.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
Using CPython 3.12.13
Creating virtual environment at: .venv
Activate with: .venv/bin/activate
  × No solution found when resolving dependencies:
  ╰─▶ Because sase-core-rs was not found in the package registry and
      sase==0.1.0 depends on sase-core-rs>=0.1.0,<0.2.0, we can conclude that
      sase==0.1.0 cannot be used.
      And because only sase[dev]==0.1.0 is available and you require
      sase[dev], we can conclude that your requirements are unsatisfiable.
error: Recipe `_setup` failed on line 19 with exit code 1
Error: Process completed with exit code 1.
```