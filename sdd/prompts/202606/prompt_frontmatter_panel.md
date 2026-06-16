---
plan: sdd/epics/202606/prompt_frontmatter_panel.md
---
  I am trying to bring the prompt input widget up to parity with xprompt markdown files.
We recently added support for multi-agent prompts to the prompt input widget with this goal in mind. Can you now help me
add support for the same frontmatter properties that xprompt markdown files support to the prompt input widget?

- This new panel (that shows what properties are set) should show above the top prompt input widget that is currently
  shown.
- The user should be able to trigger the creation of this new panel by typing `---` on a new line at the very start of
  the prompt in any prompt input widget.
- The user needs to be able to easily add, delete, and edit properties that are shown in this panel.
- We should make sure that we have particularly good support for local xprompts via the `xprompts` frontmatter field.
  For example, make sure that the `<ctrl+t>` and `<ctrl+l>` prompt input widget keymaps work for these xprompts the same
  as they would for normal xprompts.
- Also, if the `inputs` property is used, and any inputs without default values exist, then the user should be prompted
  for those input values (with great type validation and guidance for the user) after submitting the multi-agent prompt
  (e.g. by pressing `<ctrl-enter>`).
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 