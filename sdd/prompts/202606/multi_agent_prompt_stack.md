---
plan: sdd/epics/202606/multi_agent_prompt_stack.md
---
 Can you help me add robust, beautiful support to the prompt input widget for multi-agent xprompts?

- These are defined only in markdown files currently and separate the different agent prompts using a line containing
  only `---`.
- We should start rendering prompts containing `---` lines as multiple, stacked prompt input widgets (use a pretty line
  in-between them), with the prompt the user is typing / can currently type placed at the very bottom.
- The user should be able to use the new `,j` / `,k` keymaps in the prompt input widget to navigate to/from different
  prompt input widgets in the stack.
- The user should be able to use the new `,J` and `,K` keymaps to move the currently selected prompt input widget
  down/up the stack, respectively.
- If the user presses `<enter>` the prompt in the current prompt input widget should be used to submit a single agent
  only. This prompt input widget should then be removed from the stack (i.e. should disappear).
- If the user presses `<shift+enter>`, however, then the entire stack of prompt input widgets should be submitted as a
  single multi-agent prompt (using the same rules that we follow for multi-agent xprompts defined in markdown files).
- The user should be able to trigger a new prompt input widget be added to the stack (causing the current prompt input
  widget to be pushed up the stack) using the new normal mode `-` keymap that you add to the prompt input widget OR by
  typing `---` anywhere in the prompt input widget (in insert mode).
- The user should be able to delete a prompt input widget from the stack by pressing `<ctrl+c>`, which should save the
  prompt in the current prompt input widget as a canceled agent prompt to prompt history and then remove the currently
  selected prompt input widget from the stack.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

