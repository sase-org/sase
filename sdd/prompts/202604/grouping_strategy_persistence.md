---
plan: sdd/tales/202604/grouping_strategy_persistence.md
---
 Can you help me start saving the new grouping strategy to disk every time the `o`/`O` keymaps are used?

- When the `sase ace` command is run, we should read the last grouping strategy from disk and use that.
- The CLs tab and the Agents tab should save separate grouping strategies to disk.
- Make sure that when we save to disk, we do so in an async way that does not block the TUI at all.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 