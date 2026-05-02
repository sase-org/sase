---
plan: sdd/plans/202604/tmux_empty_cls.md
---
Can you help me start supporting the `t` (tmux) keymap on the "CLs" tab of the `sase ace` TUI even when no ChangeSpec
match the current query?

- This will only work when there is one and only one `project:<project>` search query filter in the current query.
- When this is the case, and no ChangeSpecs match that query, then the `t` keymap should use a workspace directory
  corresponding with the `<project>` project (no branch checkout should occur, since we don't have a branch / ChangeSpec
  name).

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
