---
plan: sdd/tales/202606/prompt_pyvision_cleanup.md
---
 GitHub Actions is failing with the below error. Can you help me fix this in the appropriate way (either remove these symbols, make them private, or add a `# pyvision:` pragma to ignore them)? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

```
┌───────────────────────────────────────────────────────┐
│                RUNNING: just pyvision                 │
└───────────────────────────────────────────────────────┘
BD_COMMAND=tools/sase_bead .venv/bin/python tools/pyvision-260608 src/sase 
Unused public functions/classes. Make these private if they are used only within the file they are defined. If the functions/classes are completely unused, you should delete them:
  PromptAmbiguousError in src/sase/history/prompt.py
  PromptNotFoundError in src/sase/history/prompt.py
  compute_prompt_id in src/sase/history/prompt.py
error: Recipe `pyvision` failed on line 317 with exit code 1
Error: Process completed with exit code 1.
```