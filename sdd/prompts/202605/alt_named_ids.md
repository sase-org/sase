---
plan: sdd/epics/202605/alt_named_ids.md
---
 Currently, we name agents that were started with the same prompt but run against different models (e.g. by using multiple `%m` directives) with the same `<name>.<id>` prefix. Can you help me
start doing this for all alternations (i.e. prompts that use the `%alt` directive--which is what `%model` uses under-the-hood when multiple model args are provided)?

- The user should be able to start using named arguments to `%alt` (or the `%` short-hand) to specify what `<id>` should be.
- Use `<N>` for `<id>` (where `<N>` is the first available positive integer) when named arguments are not used.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

