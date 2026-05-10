---
plan: sdd/tales/202605/refresh_docs_polish_daemon_agents.md
---
 Can you help me update the sase_refresh_docs lumberjack chop to run a 2nd agent that polishes the changes the previous agent made with an eye for accuracy (i.e. Is this a correct description of our system?) and clarity (i.e. Would a new user understand these changes?)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- Instead of running these agents as a part of the xprompt workflow, we should run them as daemon agents (the pylimit chop does something similar).