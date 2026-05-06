---
plan: sdd/tales/202605/wait_requires_success_1.md
---
 If I kill an agent that another agent is waiting for (using the `%wait` directive), that waiting agent will be
launched. Can you help me change this so the agent keeps waiting until all agents it is waiting for complete
successfully? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- These waiting agents will not necessarily wait forever. If the user creates a new agent with a name matching the name of the agent the waiting agent is waiting for, then that agent's successful completion
should cause the waiting agent to launch.