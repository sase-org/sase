---
plan: sdd/tales/202606/wait_time_keyword.md
---
  Can you help me migrate the `%time` directive's functionality to a new `time` keyword input for the `%wait` functionality?

- For example, `%time:5m` would become `%wait(time=5m)`.
- Also, add a new builtin `#t` xprompt that takes an input, say `<time>`, and has the contents that look like: `%wait(time=<time>)`. The goal with this new xprompt is to make sure it is still easy to use the current `%time` directive's functionality alone, but the `%wait` directive should be able to accept agent names as positional inputs and use the `time` keyword input at the same time.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 