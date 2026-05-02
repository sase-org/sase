---
plan: sdd/plans/202604/fix_ci_inline_snapshot_xdist.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
---------- Running pytest with coverage... ----------
.venv/bin/pytest -n auto --dist=loadfile --cov=src/sase --cov-branch --cov-report=term-missing:skip-covered --cov-report=html --cov-report=xml --cov-fail-under=50 --inline-snapshot=short-report
ERROR: --inline-snapshot=short-report cannot be combined with xdist
```