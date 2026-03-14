---
status: done
---

Can you help me add support two new prompt directives?: `%wait:<name>` and `%name:<name>`.

- The single `<name>` input argument supported by both is meant to represent the name of an agent.
- When the `%name:<name>` directive is included in an agent's prompt, that agent will me named `<name>`.
- When the `%wait:<name>` directive is included in an agent's prompt, that agent will not start executing until an agent
  with the name `<name>` has completed its execution (i.e. reached a "DONE" status in the `sase ace` TUI).
- We can use a lumberjack to coordinate this work. Either create a new lumberjack or use an existing one, you decide.
- We should support multiple `%wait:<name>` directives in a single prompt.
- We should support naming an agent with a name after it has already started executing by selecting the agent the
  "Agents" tab of the `sase ace` TUI and using a new keymap (e.g. `n`) to trigger a prompt that allows the user to input
  a name for that agent.

This is a large piece of work that should be split into phases (parallel if possible). I'll let you decide how many
phases to create, but keep in mind that each phase will be completed by a distinct `claude` instance.
