---
plan: sdd/epics/202606/model_alias_configuration_migration.md
---
 #fork:0am Can you now help me remove our existing `default_model` and `worker_models` configuration fields in favor of defining special model aliases that are used by default / by the agents that are launched with the `#coder` xprompt, respectively?

- We should remove any special support we currently have for the `other` or `worker` model aliases. These are no longer relevant.
- These model aliases should be of the form `<provider>_coder` (ex: `claude_coder`, `codex_coder`, `agy_coder`, etc...).
- For a plan that was created using the Claude provider, for example, the `%m:@claude_coder` directive should be included in the `#coder` agent's prompt.
- A model alias should be able to reference other model aliases using the `@<alias_name>` syntax.
- If the `<provider>_coder` model alias is not defined, it should default to using a reference to the  `@coder` model alias, which itself should default to `@default` if it has not been explicitly configured.
- The `default` model alias is special in that it should be used by default if no explicit `%model` directive is used in the prompt. This is what will replace our `default_model` config field.
- We should also define the special `epic_creator`, `epic_lander`, and `phase_worker` aliases. These should default to `@default` and should be used for the agent that are launched to create epics, land epics, and work epic phases, respectively.
- Make sure you properly update the sase.yml file in my chezmoi repo.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

