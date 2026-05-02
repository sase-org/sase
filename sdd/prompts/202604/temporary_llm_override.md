---
plan: sdd/epics/202604/temporary_llm_override.md
---
  Can you help me add a way to temporarily change the default sase LLM provider / model? We should add a new leader mode keymap for this. When the user uses this keymap, they should be prompted for a provider/model and a duration of time. The user should also be able to use this keymap to disable a current override (without the set previously using this keymap). I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 