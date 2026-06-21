---
plan: sdd/tales/202606/prompt_search_char_targets.md
---
 We recently added support for the `/` and `?` keymaps in the prompt input widget to provide vim-inspired search functionality. This works well, but it looks like we broke our ability to use the `/` and `?` characters in text objects. For example, `dt/` no longer works to delete the text from the cursor to the first `/` character (the `/` character triggers the search input bar). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 