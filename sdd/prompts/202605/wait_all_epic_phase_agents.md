---
plan: sdd/tales/202605/wait_all_epic_phase_agents.md
---
  Our epic integration currently creates an agent that lands the epic. This agent currently waits for the final phase agent to complete. The problem is that sometimes multiple phase agents are running at the same time and the final phase agent finishes before some of the others. Can you help me start having the landing agent wait for all phase agents to complete instead of just the final phase agent? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
