---
plan: sdd/tales/202605/telegram_launch_agents_disabled.md
---
  Can you help me add support to our Telegram integration for reading a SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED environment variable? If that environment variable is set (to any value), the Telegram integration should not launch agents in response to new Telegram messages from the user. This will be useful for cases where the user has multiple machines running sase and wants to be able to receive messages (e.g. plan approval messages, agent completion messages,  etc...) from all launched agents on all machines. In this case, the user will have to set SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED in order to avoid having each Telegram message he/she sends result in N agents being launched (one for each of the N machines running `sase axe` that have the sase-telegram plugin installed).

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `plugin`, `sase-telegram`)