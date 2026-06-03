---
plan: sdd/epics/202606/sase_var_output_variables.md
---
 Can you help me create a new `/sase_var` xprompt slash command?

- This slash command should instruct agents how to use the new `sase var` command that you should create.
- This command is similar to the `sase artifact` command except that, instead of associating an entire file to the sase
  agent, `sase var` will be used to associate one or more key-value pairs with the sase agent.
- This will be used for / expected to support the following features:
  - All key-value pairs specified by an agent that ran the `sase var` command should be shown to the user in the agent
    metadata panel on the "Agents" tab of the `sase ace` TUI. Put these in a new "OUTPUT VARIABLES" section (above all
    other sections but below the fields shown at the top).
  - In multi-agent xprompt markdown files, all key-value pairs will be accessible to any agent defined in that file that
    is runs after the agent that ran the `sase var` command. The agent that ran the command will need to be named for
    this, so we can access the variables via the `<agent_name>.` jinja2 object variable / variable namespace. Any `-@`
    agent name suffix (which renders to `-<N>` for some positive integer `<N>`) should be removed from the agent name
    when converting to a jinja2 variable name (also, `-` should be converted to `_`).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

