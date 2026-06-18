---
plan: sdd/tales/202606/axe_orphan_stop.md
---
 It seems sometimes tests or agents maybe start `sase axe` in their own workspace directories and then it is impossible to stop those `sase axe` processes or start a new one from `sase ace`. See the below command output for context on this problem. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
❯ procs axe
 PID:▲   User  │ TTY CPU MEM CPU Time │ Command
               │     [%] [%]          │
 3945779 bryan │     0.0 0.3 00:00:10 │ /home/bryan/.local/share/uv/tools/sase/bin/python /home/bryan/projects/github/sase-org/sase/src/sase/axe/run_agent_runner.py sase /home/bryan/.sase/projects/sase/sas
 3964717 bryan │     0.0 0.3 00:00:09 │ /home/bryan/.local/share/uv/tools/sase/bin/python /home/bryan/projects/github/sase-org/sase/src/sase/axe/run_agent_runner.py sase /home/bryan/.sase/projects/sase/sas
 4039388 bryan │     0.0 0.1 00:00:00 │ /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/python /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/sase axe sta
 4039420 bryan │     0.0 0.1 00:00:00 │ /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/python /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/sase axe lum
 4039423 bryan │     0.0 0.1 00:00:00 │ /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/python /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/sase axe lum
 4039425 bryan │     0.0 0.1 00:00:00 │ /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/python /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/sase axe lum
 4039427 bryan │     0.0 0.1 00:00:00 │ /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/python /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/sase axe lum
 4039429 bryan │     0.0 0.1 00:00:00 │ /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/python /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/.venv/bin/sase axe lum

bryan in 🌐 athena in sase on  master is 📦 v0.3.0 via  v22.14.0 via 🐍 v3.10.18
❯ axe stop
Axe orchestrator is not running.
```