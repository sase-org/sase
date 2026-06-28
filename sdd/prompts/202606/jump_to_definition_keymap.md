---
plan: sdd/tales/202606/jump_to_definition_keymap.md
---
  Can you help me add support for a new `<ctrl+]>` normal-mode keymap to the prompt input widget?

- This keymap should act as a "jump-to-definition" for xprompts, xprompt skills, and file paths.
- This keymap should only do something when an xprompt, xprompt skill, or file path is selected. It should show a useful error in a toast otherwise. We should also provide a distinct error message if the xprompt/skill/file path does not exist.
- When triggered, we should render a new pop-up panel that offers the user the following options, which should be selectable by the user via a single keypress:
  - Open a new vertical tmux pane that launches the user's editor with the appropriate file path. Only show this option when the TUI is running inside of a TMUX session.
  - Open the target file in the user's editor in this pane (i.e. use the same process as the TUI).
  - Load the xprompt / xprompt skill in the prompt input widget after first stashing all prompt input widget prompts (and xprompt properties in the xprompt property panel, if any) as a bundled prompt stash. This option should only be available when a xprompt/xprompt skill is currently selected. If an xprompt defined in a YAML is selected, we should not show this option since we cannot load YAML xprompt workflows in the prompt input widget.
-  Add special support to vim / nvim for jumping to the correct corresponding line number and column number when the file is opened if appropriate (only shown if running in a TMUX session--otherwise, don't show this menu and default to the next option) for both of these options.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 