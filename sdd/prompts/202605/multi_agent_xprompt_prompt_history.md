---
plan: sdd/tales/202605/multi_agent_xprompt_prompt_history.md
---
 When I launch multiple agents using a multi-agent xprompt (a prompt that contains one or more `---` lines), it seems like we don't save the prompt to history. Instead, we save each individual agent prompt (used for each agent launched during the multi-agent prompt fanout) to history. Can you help me make it so these individual agent prompt are NOT saved to prompt history and save the original multi-prompt xprompt to prompt history instead? For example, when I use the `#!research_swarm` xprompt, the exact prompt that it was embedded in should be saved to prompt history, NOT the 3 prompts corresponding to the 3 agents that this multi-agent xprompt will launch.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
