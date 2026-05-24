---
plan: sdd/epics/202605/notification_tags.md
---
 Can you help me add support for sase notification tags?

- Senders should be able to specify custom tags (ex: 'foobar').
- Each tag should be given a separate tab in the TUI's notificatino panel. I want you to lead the design on this one. Just make sure it looks beautiful!
- We should start marking successful agent completion notifications with the 'done' tag as our first use-case (these are the notifications that get auto-dismissed when the corresponding agent row on the agents tab goes from unread to read).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

