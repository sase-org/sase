---
plan: sdd/epics/202603/multi_agent_prompts.md
---
#gh:sase Can you create a plan using your /sase_plan skill for the following prompt:

### THE PROMPT YOU NEED TO CREATE A PLAN FOR

Can you help me add support for any sase agent prompt (ex: those started from the `sase ace` TUI or from `sase run` or
`sase run --daemon`) for triggering multiple agents from a single prompt?

- We will support this using three dashes (`---`) to separate each sase agent prompt.
- We should always run each agent in sequence. That doesn't mean that we have to wait for the next agent to run, unless
  the `%wait` directive is used, which brings me to my next point: We MUST wait long enough for the Nth agent to launch
  and be named before launching the N+1th agent. This way, for example, the`%wait` directive can be used without
  arguments in a sequence to have each agent wait for the last (if we wish).
- We should also add support for frontmatter in user prompts. These should follow the same rules our other local
  xprompts follow (ex: they MUST be used in the file they are defined in, their names MUST be preficed with `_`,
  etc...).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
