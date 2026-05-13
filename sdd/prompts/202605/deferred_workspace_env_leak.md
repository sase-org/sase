---
plan: sdd/tales/202605/deferred_workspace_env_leak.md
---
 Agents keep failing with the following error:
```
RuntimeError: SASE_AGENT_DEFERRED_WORKSPACE=1 but 
extracted wait metadata is empty; refusing to continue in 
the placeholder workspace
```
Can you help me diagnose the root calls of this issue and fix it? Make sure that you identify the commit that introduced this bug so you are certain that you're changes do not introduce any regressions. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
