---
plan: sdd/tales/202605/starting_to_running_row_latency.md
---
 When I launch a new sase agent, I see that the agent "starting" count increases pretty quickly, but it can take a while for the new agent to show as running. I think this likely has something to do with our tier 1 (fast) vs tier 2 (slow) agent reload paths. Can you help me fix this so that when an agent goes from STARTING to RUNNING/WAITING we immediately (or very soon after) add the corresponding agent entry to the agents tab? Make sure this doesn't hurt performance too much (it should ideally not cause any noticable performance degredation). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 