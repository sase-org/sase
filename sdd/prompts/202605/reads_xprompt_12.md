---
plan: sdd/tales/202605/reads_xprompt_12.md
---
 Can you help me implement our first use-case for the recently implemented `foobar-@` syntax (see recent,
related git commits) by implementing a new xprompts/reads.md multi-agent xprompt that runs 3 agents, one gemini, one
claude, and one codex?

- Use the "bas.gem", "bas.cld", and "bas.cdx" sase agent chats as a reference for what I'm looking for with the first 3
  agents.
- These agents should search for new articles based on my prompt and should ensure I haven't read any of the recommended
  articles by reviewing my reference notes in the ~/org/ directory (the specific note files are specified in the
  prompt).
- A 4th agent, that waits for the other 3 to finish, should consolidate and rank the recommendations (based on which
  articles were referenced by multiple agents and based on the 4th agent's own judgement) from the previous agents. See
  the `wait_chats` jinja2 variable for an idea of how you can give this agent access to the first 3 agent chats.
- Make sure to verify this new multi-agent xprompt using the `sase run -d` command. I would like some new articles about
  agent memory (e.g. episodic, semantic, etc...) to read!

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
