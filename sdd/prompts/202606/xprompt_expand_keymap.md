---
plan: sdd/epics/202606/xprompt_expand_keymap.md
---
 Can you help me add a new `<ctrl+i>` keymap to the "Select XPrompt" panel that is shown when `#@` is pressed in the prompt input widget?

- This keymap should expand the currently selected xprompt in the prompt input widget.
- Now that we support multiple prompt input widgets and an xprompt property panel, we should be able to expand most xprompts in the prompt input widget, but there might be some cases that won't work (xprompt YAML workflows, for example). In these cases, we should show an error to the user (without closing the panel).
- Make sure that this works even when there is already text in one or more prompt input widgets (think through all of the edge cases thoroughly).
- Make sure the user can undo this xprompt expansion using the `u` (undo) keymap.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 