---
plan: sdd/epics/202605/resume_optional_name.md
---
 Can you help me make it so the `#resume` xprompt workflow's (see the src/sase/xprompts/resume.yml file) `name`
input optional?

- When not provided, we should default to using the name of the last launched agent.
- When used in a multi-prompt xprompt (i.e. an `*.md` file that contains multiple prompts separated by `---` lines) for
  any agent but the first, we should always default to using the name of the previous agent in that same markdown file
  regardless of race conditions (launching 3 multi-prompt workflows at the same time, for example, might cause a race
  condition if we don't enforce this constraint).
- Factor out the Python logic in the `resolve` step to a new `agent_chat_from_name` Python script.
- Add good tests for this new script.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

