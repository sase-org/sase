---
plan: sdd/epics/202605/agents_tab_unread_badge_1.md
---
 Now that we don't send agent completion notifications to the TUI (see epic bead sase-2t) we should start
highlighting the "Agents" tab title yellow when a new agent completes and the "Agents" tab is not currently focused.

- We should also append `(<new_unread_count>)` to the agents tab title where `<new_unread_count>` is the number of agent
  rows that have completed (and thus been marked as unread) since the last time the agents tab was focused.
- This should also work when the user first starts `sase ace`. In other words, for example, if the "Agents" tab is not
  automatically selected and there are 2 unread notifications, then the tab title should be "Agents(2)" and it should be
  highlighted yellow.
- Make sure we add good PNG snapshot tests for this functionality.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

  