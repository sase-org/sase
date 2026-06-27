---
plan: sdd/tales/202606/xprompt_filter_digit_reservation.md
---
 When the "XPrompts" tab is opened using the `5` keymap on the "SASE Admin Center" panel in the TUI, the filter bar on that tab is automatically focused. This means if the user presses 1, for example, it goes to the filter bar instead of triggering the `1` keymap and focusing the first tab of the panel. Can you help me fix this by making it so the 0-9 keys are reserved (i.e. 1-5 are used to change tabs and 6-9 and 0 are reserved for future tabs) when the filter bar is empty after navigating to the "XPrompts" tab in order to focus the filter bar?

- The user should be able to type 0-9 digits into the filter bar, just not as the first character.
- The user should be able to press `<tab>` in the filter bar when they have already typed text in order to unfocus the filter bar so they can use the numeric keymaps to navigate to a different tab. This might work by default without you needing to change anything but I'm not sure.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
