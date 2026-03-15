Can you help me create a new `/sase_plan` Claude code skill that will replace claude's native plan-mode? The goal of
this change is to eventually standardize on a single, unified plan-mode process for all LLM provider types, but we will
start with just claude.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.

### Changes Required to CLAUDE.md and Claude LLM Provider

- We should completely disable claude's ability to use its native plan-mode or ask questions.
- We will need to give CLAUDE.md clear instructions on two things: (1) It does NOT have access to plan mode; it should
  use the `/sase_plan` skill instead. (2) It does NOT have access to ask questions the normal way and should instead
  make use of the `sase questions` command. It doesn't need to know about the `sase plan` command, as that will be used
  by the skill itself.

### A New `claude` Instance for ALL the Things

- When a plan is proposed via the `sase plan` command, we will start killing the current `claude` instance. If the plan
  is approved by the user (or auto-approve is enabled) then a new agent will be created in the same workflow (see below
  bullet). We will also kill the current agent when `sase questions` is used by an agent to ask the user one or more
  questions and then create a new agent to with the same prompt but with a "Questions and Answers" H3 section added to
  the bottom. These will also be in the same workflow (and will be shown as steps in the "Agents" tab).
- These new agents will be dynamically created within the current agent workflow (this creates a multi-agent workflow,
  so it should be displayed as such in the "Agents" tab of the `sase ace` TUI) and each workflow step should have the
  same number as the original agent but should be given a suffix name that indicates what role it played. For example,
  an agent that would have shown as `1/1 ✘ [agent] main (RUNNING)` when viewing workflow steps would, after proposing a
  plan, would be shown as `1/1.plan ✘ [agent] main (DONE)`.

### `/sase_plan` Skill Requirements

- The skill should instruct claude to, after they understand the problem, made sufficient exploration, and finished the
  plan, to write the plan to a relative file named `sase_plan_<name>.md` where `<name>` is a good name (separated by
  underscores) selected by the agent.
- Finally, the skill should instruct claude to run the `sase plan sase_plan_<name>.md` shell command, which should kill
  the agent (see next section).

### The NEW `sase plan` Subcommand

- You will need to create a new `sase plan` subcommand that will be used by the `/sase_plan` skill.
- The `sase plan` command will be resoponsible for:
  - Killing the current agent that proposed the plan. I'm not sure of the best way to do this, but I would recommend
    always injecting an agent's name as a `SASE_AGENT_NAME` environment variable when running the `claude` command and
    then using that to find and kill the agent when `sase plan` is run.
  - Triggering the plan notification in the same way that claude code's hooks currently (you should remove these hooks
    from the chezmoi repo) do for plans.

### The NEW `sase questions` Subcommand

- You will also need to create a new `sase questions` subcommand that will allow claude to ask the user questions from
  the command-line.
- We MUST support all of the same functionality that claude's native question/answer system does (e.g. multiple
  questions, recommended answers, custom answers, etc.---see how we display these in the notification popup in the TUI;
  I want to keep this exactly the same as the current experience).
- The `sase questions` command will be resoponsible for:
  - Killing the current agent that asked the question(s).
  - Triggering the question notification in the same way that claude code's hooks currently (you should remove these
    hooks from the chezmoi repo) do for questions.
