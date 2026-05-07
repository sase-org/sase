---
plan: sdd/tales/202605/workspace_allocation_retry.md
---
 It seems we sometimes fail to assign an available sase workspace to an agent when launching and continue to launch it anyway. This is not correct. We should continue retrying to find an available workspace until we find one (or exceed some max retry count--in which case the agent should fail with a good error message). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
