---
plan: sdd/epics/202605/agents_tab_completion_notification_dismissal.md
---
 We currently dismiss agent completion notifications from the TUI when the corresponding agent is either marked
as unread or dismissed from the agents tab. Can you help me start dismissing ALL agent completion notifications as soon
as the user navigates to the agents tab or, if the user is already on the agents tab, the next time there is some kind
of user activity (e.g. `j`/`k` agent row navigation)? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 