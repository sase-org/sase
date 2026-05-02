---
plan: sdd/tales/202604/fix_ci_tools.md
---
Can you help me fix this GitHub Actions error in my chezmoi repo? It looks like we are not setting up the GitHub Actions
environment correctly. We probably have other commands we need to install as well, so make sure to look for those too.
Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
---------- Running llscheck linter on Lua files... ----------
llscheck --checklevel Hint ./home/dot_config/nvim
sh: 1: llscheck: not found
error: Recipe `lint-lua` failed on line 72 with exit code 127
```
