---
plan: sdd/tales/202607/zoom_panel_file_list.md
---
 The zoom panel file/panel list, which is navigated via the `<ctrl+n/p>` keymaps, has some problems.

- For one, it should be much clearer which files/panels are in the list and which one is currently active.
- Also, after the user presses `z` to activate the zoom panel, this list of files/panels should be fixed (we should load all of the files that are available at the moment). Right now, this list does seem to change sometimes after I press `<ctrl+n>` or `<ctrl+p>`.
- The `<ctrl+n/p>` keymaps should cycle to the very first/last files/panels in the list when the currently selected file/panel is the last/first in the list, respectively.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 

Can you help me fix these issues / make these improvements? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 