---
plan: sdd/tales/202606/create_prompt_snippet_option.md
---
 Can you help me add a new `Create a new snippet...` option to the menu that pops up when the `gx` / `<ctrl+g>x` keymaps are used from the prompt input widget?

- When this option is chosen, the user should be prompted to select a valid sase YAML configuration file path.
- Once they select a YAML file, they should then be prompted for a name for the new snippet we are going to add to that file.
- Make sure that when we add the sase snippet to that configuration file, we make minimal edits to that file (e.g. preserve all comments and formatting).
- This should only appear as an option when there is only one prompt input widget since multi-agent prompts are not supported by snippets.
- If an existing snippet exists of the same name in the selected YAML configuration file, it should be overwritten.
- Make sure we display a useful toast to the user after creating the snippet.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
