---
plan: sdd/tales/202605/artifact_tmux_zoom.md
---
 Can you help me add a new `z` keymap to the tmux pane that contains the artifact(s) chosen by the user (after using the `A` keymap)? This key map should zoom the tmux pane so it is the only one visible on the current tmux window and should then refresh the image (like the user pressed the `r` key). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- If the user presses `z` when the pane is already zoomed, we should unzoom the pane and refresh the image.