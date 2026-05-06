---
plan: sdd/tales/202605/agents_group_ungroup_keymap.md
---
 Can you help me add a new `,g` (group/ungroup) keymap to the "Agents" tab of the `sase ace` TUI? When this key is pressed we should merge all dynamic agent panels together, put the agent tag name
in the appropriate agent entries (so we know which ones are tagged in this view), and group/sort them as if they were always apart of the same panel (using the current grouping strategy). If the user
presses `,g` again, they should be split out into different panels again based on their tags and the tag names should be removed from the agent rows. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
