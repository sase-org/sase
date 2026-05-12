---
plan: sdd/epics/202605/agent_completion_notification_unread_contract.md
---
 There was a lot of hackery around the agent completion notifications in the TUI committed today (see recent, related git commits). Can you help me revert most of that and, instead, just go back to sending the notifications to the TUI and making the unread status in agent rows on the agent tab one-to-one with wehther the corresponding notification is dismissed or not (i.e. if the agent is read, the notification should have been dismissed, and vice-versa)? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 

- NOTE: We should keep the new highlighting of unread agent counts.