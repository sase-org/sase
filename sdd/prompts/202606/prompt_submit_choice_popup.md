---
plan: sdd/tales/202606/prompt_submit_choice_popup.md
---
  Can you help me start triggering a new popup panel that gives the user a selection of (triggered with a single keypress) options when they press `<enter>` in the prompt input widget and multiple prompt input widget are visible?

- Currently, we just launch an agent using the prompt in the selected prompt input widget in this case.
- We should add a new `<ctrl+shift+s>` keymap to the prompt input widget when there are multiple prompt input widgets shown to replicate the old behavior of `<enter>` (described in the above bullet).
- This new panel should have options to submit all prompts as a multi-agent xprompt (what the existing `<ctrl+s>` keymap already does) and to submit just the current prompt (what the new `<ctrl+shift+s>` keymap should do).
- I want you to lead the design on this one. Just make sure it looks beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 