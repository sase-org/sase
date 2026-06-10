---
plan: sdd/epics/202606/worker_model.md
---
 Can you help me add a brand new concept of a secondary default model to SASE?

- This will be the LLM provider model that is used for secondary tasks like phase agents that are working phases of an
  epic.
- These should be configurable (e.g. in a sase.yml file), but should be optional. If not provided the current default
  model or override model, if one is set, should be used in its place.
- The model override panel in the TUI should also support overriding the secondary default model.
- Configure my secondary default model (think of a better name for this) in the sase.yml file in my chezmoi repo to use
  the `codex/gpt-5.5` model.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

