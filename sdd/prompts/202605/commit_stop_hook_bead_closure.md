---
plan: sdd/tales/202605/commit_stop_hook_bead_closure.md
---
   #resume:sase-2d I just realized that the commit stop hook should be instructing the agent to close the bead before it uses its commit skill (and only if the detected file changes were made by that agent). Otherwise the bead closure wouldn't be committed. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `commit skill`)