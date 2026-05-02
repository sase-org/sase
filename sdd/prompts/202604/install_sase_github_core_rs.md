---
plan: sdd/plans/202604/install_sase_github_core_rs.md
---
 I just got the following error when running the `install_sase_github` script (defined in my chezmoi repo). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
❯ acei -i
>>> Syncing /home/bryan/projects/github/sase-org/sase...
Already up to date.
>>> Syncing /home/bryan/projects/github/sase-org/sase-core...
Already up to date.
>>> Syncing /home/bryan/projects/github/sase-org/sase-github...
Already up to date.
>>> Syncing /home/bryan/projects/github/sase-org/sase-telegram...
Already up to date.
>>> Installing sase via uv tool...
  × No solution found when resolving dependencies:
  ╰─▶ Because sase-core-rs was not found in the package registry and sase==0.1.0 depends on sase-core-rs>=0.1.0,<0.2.0, we can conclude that sase==0.1.0 cannot be used.
      And because only sase==0.1.0 is available and you require sase, we can conclude that your requirements are unsatisfiable.
```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `sase-github`, `sase-telegram`)