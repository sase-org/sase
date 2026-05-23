---
plan: sdd/tales/202605/init_check_memory_false_positives.md
---
 It looks like the `sase init --check` command omits false positives for sase's memory files (see output below). Can you help me diagnose the root cause of this issue and fix it? Also, can you add a `-c` short option for the `--check` option? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
❯ sase init memory
init memory: initialized memory
  project memory target: /home/bryan/projects/github/sase-org/sase/memory/short/sase.md
  home memory target: /home/bryan/.local/share/chezmoi/home/memory/short/sase.md
  global config source: /home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml
🔄 Running precommit command: just fix
init memory: nothing to commit in /home/bryan/projects/github/sase-org/sase

bryan in 🌐 athena in sase on  master is 📦 v0.1.0 via  v22.14.0 via 🐍 v3.10.18 took 3s
❯ sase init --check
SASE initialization check

Up to date:
  ok   init sdd     SDD README files and directory map are current
  ok   init skills  provider skill files are current

Needs attention:
  run  init memory  update 2 memory files and provider shims
    - update    memory/short/sase.md  generated SASE memory
    - update    memory/README.md  memory README
```