---
plan: sdd/tales/202606/agent_name_namespace_templates.md
---
 We recently generalized the concept of using `@` with the `%name` directive (see the sase-4g epic bead for
details). When `%n:foo.@.bar` is used, for example, the agent's name will be `foo.<X>.bar`, where `<X>` is the first
alphanumeric sequence such that `foo.<X>.bar` is a unique agent name. Can you help me make some changes to this logic?
Namely:

- When the `@` is placed somewhere to the left of a period, we should treat that period (the first one found to the left
  of the `@`) as the end of a namespace (`foo.@` in our example) and then choose the first available `foo.<X>.bar` such
  that the `foo.<X>` namespace is unused (i.e. no agent is named `foo.<X>` and no agent's name starts with `foo.<X>`).
- The `@` symbols found in agent names in a single xprompt markdown file should be generated all at once. This will
  allow for the agents in the src/sase/default_xprompts/research_swarm.md xprompt, for example, to all use the same
  `research.<X>.` prefix (which should be unique everytime the `research_swarm` xprompt is used).
- Similarly, all agents launched from a multi-model sase agent prompt (ex: if `gpt-5.5` and `opus` were both given to
  the `%model` directive) should have the same `<X>.` namespace, but no other agents before these were launched should
  have been named `<X>` or had a name that started with `<X>.`.
- If `@` is not placed to the left of a period, for example `foo-@` or `@` (which is used for auto-generated agent
  names), then the entire agent name is treated as a namespace. In that case, we should assign the agent the first
  `foo-<X>` / `<X>` name such that no other agents has been named `foo-<X>` / `<X>` and no other agent has had a name
  that starts with `foo-<X>.` / `<X>.`.
- Make sure this doesn't slow down agent launches / agent name allocation too much.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
