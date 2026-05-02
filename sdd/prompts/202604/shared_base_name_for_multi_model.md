---
plan: sdd/plans/202604/shared_base_name_for_multi_model.md
---
 Can you help me start using the same base name for agents that are run using the same prompt that contained multiple `%model` directives (or one with multiple args)? For example, if `%m:gpt-5.5,opus` and `%n:foo` are both in
the prompt, then the codex agent should be named "foo.codex" and the claude agent should be named "foo.claude". This same form (`<name>.<llm>`) should be used when the name is auto-generated (i.e. not provided explicitly using the
`%name` directive). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
