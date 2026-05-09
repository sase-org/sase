---
plan: sdd/tales/202605/docs_pdf_core_dependency.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
Run just docs-pdf-check
uv pip install --python .venv/bin/python --no-sources -e ".[docs-pdf]"
  × No solution found when resolving dependencies:
  ╰─▶ Because sase-core-rs was not found in the package registry and
      sase==0.1.0 depends on sase-core-rs>=0.1.1,<0.2.0, we can conclude that
      sase==0.1.0 cannot be used.
      And because only sase[docs-pdf]==0.1.0 is available and you
      require sase[docs-pdf], we can conclude that your requirements are
      unsatisfiable.
error: Recipe `docs-pdf-check` failed on line 170 with exit code 1
Error: Process completed with exit code 1.
```