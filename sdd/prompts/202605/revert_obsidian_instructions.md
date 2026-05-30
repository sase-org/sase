---
plan: sdd/tales/202605/revert_obsidian_instructions.md
---
 #fork:bpq Actually, can you revert these changes and add some new instructions to the ~/bob/AGENTS.md file instead? These instructions should tell the agent that the repo might already have uncommitted changes since it is actively synced by Obsidian Sync. The agent should also be instructed to commit any file changes that they make to files in the ~/bob/ directory before terminating using their `/sase_git_commit` skill. Use your /sase_git_commit skill to commit those changes to ~/bob/ when you are done. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `sase_git_commit`)