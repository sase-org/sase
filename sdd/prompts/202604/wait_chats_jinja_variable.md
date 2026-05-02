---
plan: sdd/tales/202604/wait_chats_jinja_variable.md
---
 Can you help me inject a new `wait_chats` jinja2 variable into agent prompts when those agent prompts contain `%w`/`%wait` directive(s) that wait for other agents? This variable's value should be a list of a ~/.sase/chats/
file paths that correspond with the chat transcripts of the agents that this agent waited for. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
