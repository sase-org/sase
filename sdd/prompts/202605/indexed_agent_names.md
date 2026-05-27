---
plan: sdd/epics/202605/indexed_agent_names.md
---
 I want to be able to start naming and referring to agents using an input argument of `foobar-@` for the
`n`/`name` directive and `foobar-@` as an input argument the `w`/`wait` directive and `#resume`.

- In the case of the `name` directive the agent should be named `foobar-<N>`, where `<N>` is the first positive integer
  such that the agent name `foobar-<N>` is untaken / available.
- In the case of `%w` / `#resume`, `foobar-@` should resolve to `foobar-<M>`, where `<M>` is the highest positive
  integer such that a sase agent named `foobar-<M>` exists.
- This should allow me to name and refer to agents by name in multi-agent prompts (i.e. prompts split by `---` that
  trigger multiple agent launches).
- Make sure that the code quality is high and that this feature is reliable.

Can you help me implement this? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

