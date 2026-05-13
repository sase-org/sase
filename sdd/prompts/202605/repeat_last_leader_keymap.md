---
plan: sdd/epics/202605/repeat_last_leader_keymap.md
---
 Can you help me add a new `,,` (LEADER) keymap that re-runs the last run LEADER keymap? For example, I should
be able to use `,j` on the agents tab to jump to the most recently completed unread agent row and then use `,,`
repeatedly after that to continue jumping to the next unread agents until all of them are read. This should work with
ALL keymaps that start with `,`.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

