---
plan: sdd/epics/202606/prompt_history_tui.md
---
 Can you help me improve the prompt history functionality provided by the TUI's prompt input widget?

- We should stop sorting the prompt history based on what project / VCS xprompt workflow was used. Make sure to remove all references to this functionality and all logic that is only used to support this.
- We should stop using the hacky `.` syntax to trigger the prompt history panel. Instead the prompt input widget should support a new `<ctrl+.>` keymap that triggers this.
- The `<ctrl+.>` keymap should only be available when the prompt the user has typed in to the prompt input widget thus far consists of just one line of text.
- When the `<ctrl+.>` keymap is triggered, the prompt history panel's input bar should be populated with the first (and only) line of prompt text that existed in the prompt input widget at the time the keymap was triggered.
- Also, can you help me fix a (somewhat unrelated) bug where a prompt containing an invalid VCS xprompt workflow invocation (ex: `#gh:foobar` would cause a prompt failure since the "foobar" GitHub prject hasn't been registered / used with sase yet), does not save the prompt as a canceled prompt in prompt history. It is appropriate for these prompts to fail to launch agents, but we should ALWAYS store the prompt from failed agent launches (fix any other violations of this rule that you find).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

