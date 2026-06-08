---
plan: sdd/tales/202605/github_actions_home_init.md
---
 Can you help me fix this GitHub Actions failure? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
┌───────────────────────────────────────────────────────┐
│                RUNNING: just lint                     │
└───────────────────────────────────────────────────────┘
[setup] Linking keep-sorted from PATH into .venv/bin/keep-sorted.

---------- Checking keep-sorted blocks in YAML files... ----------
git ls-files '*.yml' '*.yaml' | xargs .venv/bin/keep-sorted --mode lint

---------- Running ruff linter on Python files... ----------
.venv/bin/ruff check src/ tests/
All checks passed!

---------- Running mypy type checker... ----------
.venv/bin/mypy
Success: no issues found in 1157 source files

---------- Validating scripts/tools directory structure... ----------
.venv/bin/python tools/pyscripts-260314
All scripts/ and tools/ directories are valid!

---------- Checking for unused Python definitions... ----------
BD_COMMAND=tools/sase_bead .venv/bin/python tools/pyvision-260608 src/sase
All public/private classes/functions are used properly!

---------- Running SASE validation... ----------
.venv/bin/sase validate
SASE validation
  fail   init --check
  ok     sdd validate

init --check failed (exit 1)
stdout:
SASE initialization check

Up to date:
  ok   init amd     agent markdown documents are current
  ok   init sdd     SDD README files and directory map are current

Needs attention:
  run  init memory  create 7 memory files and provider shims
    - create    ~/memory/short/sase.md  generated SASE memory
    - create    ~/memory/README.md  memory README
    - create    ~/AGENTS.md  agent instruction file
    ... 4 more actions
  run  init skills  create 62 provider skill files
    - create    ~/.claude/skills/sase_agents_status/SKILL.md  claude/sase_agents_status
    - create    ~/.codex/skills/sase_agents_status/SKILL.md  codex/sase_agents_status
    - create    ~/.gemini/skills/sase_agents_status/SKILL.md  gemini/sase_agents_status
    ... 59 more actions

Warnings:
  init skills: init skills: prettier not found on PATH; output may not match chezmoi CI formatting
error: Recipe `validate` failed on line 278 with exit code 1
error: Recipe `lint` failed on line 124 with exit code 1
Error: Process completed with exit code 1.
```

### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `SKILL.md`)