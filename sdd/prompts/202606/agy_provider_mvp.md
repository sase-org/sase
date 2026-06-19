---
plan: sdd/epics/202606/agy_provider_mvp.md
---
 #fork:research.t.final Can you help me make this migration and implement an ambitious MVP (try to support everything that claude and codex support) for the new Antigravity (`agy`) LLM provider? Remember that LLM provider support is supposed to be pluggable so try to add as little custom logic for anti-gravity to sase's code base as possible.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

