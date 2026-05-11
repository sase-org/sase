---
plan: sdd/epics/202605/notification_filters_1.md
---
 We currently send notifications every time an agent completes. This is correct and necessary for our Telegram
integration, where we genuinely want to see these. For the TUI, however, it creates way too much notification noise. Can
you help me start suppressing these notifications in the TUI only by adding support for user-configured notification
filters?

- The user should be able to specify the client (e.g. TUI, Telegram, Mobile, etc...) and the notification type they want
  to suppress.
- We should add default configuration to this repo's default_config.yml file that suppresses agent completion messages
  for the TUI only.
- We should be able to remove the recently added logic that dismisses these notifications when an agent (on the Agents
  tab) is marked as read (i.e. when a user selects an agent row that is marked as unread). This was meant to reduce the
  number of these notifications the user had to dismiss manually, which won't be a problem anymore.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 