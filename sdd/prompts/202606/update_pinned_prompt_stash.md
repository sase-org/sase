---
plan: sdd/tales/202606/update_pinned_prompt_stash.md
---
 Yesterday we added support for pinned prompt stashes. Can you now help me add the new `gS` (normal mode) and `<ctrl+g>S` (insert mode) keymaps to the prompt input widget?

- These keymaps will be used to update a pinned prompt stash using the prompt in the current prompt input widget.
- If there is only one pinned prompt stash, we should update that one automatically.
- Otherwise we should show a prompt to the user and allow them to select which pinned prompts to update with a single key press.
- Make sure we send a nice toast to the user to let them know what pinned prompt stash entry got updated.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 