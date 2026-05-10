---
plan: sdd/tales/202605/other_model_alias.md
---
 Can you help me add support for configuring an "other" model in sase.yml (update mine to configure opus in my chezmoi repo) that can be used via `%model:other`? This is meant to be an alternative / secondary model. Using `%m:other` instead of the model name explicitly allows for more generic multi-agent xprompts that will run a different model for each step depending on what default/other models you have configured at the time of agent launch. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)