---
plan: sdd/epics/202606/generalized_agent_name_at_templates.md
---
 Can you help me generalize, improve, and increase the scope of the `-@` suffix that we support for sase agent
names?

- I want to start making `@` allowed anywhere in an agent name. In which case, it should mean the same thing it does
  today (the first `<X>` such that the agent name is untaken after `@` is replaced with `<X>` is used to replace `@`).
- But instead of `<X>` being a positive integer, we should start using the same alphanumeric sequence that we do for
  auto-generated agent names (start with `0-9` and then `a-z`).
- It is important that we use the same alphnumeric sequence for `@` that we do for auto-generated agent names because we
  should start implementing these auto-generated agent names using the same exact logic. Namely, we should start
  injecting `%n:@` into the prompt (or a variation like `@.cld`, for multi-model prompts--I'm not sure how those are
  handled currently, but I think they probably need to be considered for this work).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

