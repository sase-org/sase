---
plan: sdd/plans/202603/timestamps_field.md
---
Can you help me add a new TIMESTAMPS ChangeSpec field that tracks timestamps of the form `YYYY-MM-DD HH:MM:SS` for the
following events in a ChangeSpec's life?: Each COMMITS entry's creation, successful syncs (e.g. using the `Y` keymap),
rewords (e.g. the `w` or `W` keymaps--make sure to indicate which type of reword occurred somehow), all STATUS field
value changes.

- No TIMESTAMPS entries should be shown when the ChangeSpec is fully folded. Only COMMITS creation TIMESTAMPS entries
  should be shown when partially unfolded. All should be shown when fully unfolded.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last
  but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
