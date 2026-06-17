---
plan: sdd/epics/202606/prompt_g_prefix_keymaps.md
---
 We've been changing the keymaps for the prompt input widget a lot this morning (see recent, related git commits), but I think I've finally thought this through and understand what I want the UX to look like. Can you help me implement these new requirements?

- I want to migrate a lot of the recently added keymaps to use new keymaps that use the "g" prefix. As a part of this migration, we will migrate all of the "," preficed prompt input widget keymaps to new "g" preficed keymaps. We should thus remove the recently added "," hints widget that is shown above the prompt input widget. Instead let's implement the same thing for the "g" prefix (hints that the user sees)!
- The current `J`/`K` normal mode keymaps should be migrated to `gj` and `gk`. We should restore the old (vim-inspired) functionality of the `J` keymap.
- The current down/up arrow keymaps should be migrated to `gJ` and `gK`.
- The current `<ctrl+->` and `<ctrl+shift+=>` keymaps should be migrated to `g-` and `g=`. The `,f` keymap, which is now redundant since the `g=` keymap should handle the same functionality, should be completely removed. Make sure that the `g=` keymap navigates back to the previously active prompt input widget when the `g=` keymap is used but the xprompt property panel is already active (i.e. make sure that `g=` deactivates the xprompt property panel too).
- The `,s`; `,S`; and `,P` keymaps should be migrated to `gs`, `gS`, and `gP`, resepctively. We should also only make the `gP` keymap available when a prompt input widget is active (currently, the `,P` keymap is always available). Also, we should add a new `gp` keymap that populates the prompt input widget(s) with the chosen prompt from the stash, but does NOT delete that prompt from the stash.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

