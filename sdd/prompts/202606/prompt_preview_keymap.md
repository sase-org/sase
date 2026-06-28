---
plan: sdd/tales/202606/prompt_preview_keymap.md
---
 Can you help me add support for a new `K` (preview) normal-mode keymap to the prompt input widget?

- This keymap should only do something when an xprompt, xprompt skill, or file path is selected. It should show a useful error in a toast otherwise. We should also provide a distinct error message if the xprompt/skill/vile path does not exist.
- When triggered, we should render a new panel in the TUI that allows the user to preview (with good syntax highlighting when possible) the contents of the currently selected xprompt / skill / file.
- Make sure the user is able to scroll through the file contents using the `<ctrl+d/u>` keymaps.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 