---
plan: sdd/tales/202607/unified_model_aliases.md
---
 We recently added descriptions to the model aliases shown in the "Models" panel in the TUI by adding support for a new `custom_model_aliases` config field (see recent, related git commits). As far as the new config schema goes though, can you help me use a single `model_aliases` config field with two subfields, `builtin` and `custom`, instead? Also, the description for the currently selected model alias (builtin or custom) should always be shown somewhere in the "Models" panel, so there should be no need for the `d` (describe) keymap.

Can you help me fix these issues / make these improvements? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 