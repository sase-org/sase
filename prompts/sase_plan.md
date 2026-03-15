Can you help me create a new `/sase_plan` Claude code skill that will replace claude's native plan-mode? The goal of
this change is to eventually standardize on a single, unified plan-mode process for all LLM provider types, but we will
start with just claude.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.

### Changes Required to CLAUDE.md and Claude LLM Provider

- TODO

### Planner/Coder `claude` Instances

- TODO

### `/sase_plan` Skill Requirements

- The skill should instruct claude to, after they understand the problem (possibly by asking the user questions---we
  already have support for this), made sufficient exploration, and finished the plan, to write the plan to a relative
  file named `sase_plan_<name>.md` where `<name>` is a good name (separated by underscores) selected by the agent.
- Finally, the skill should instruct claude to run the `sase_plan sase_plan_<name>.md` shell command, which should kill
  the agent (see next section).

### The `sase_plan` Script

- You will need to create a new script named `sase_plan` that will be used by the `/sase_plan` skill.
- The `sase_plan` script will be resoponsible for:
  - Killing the
