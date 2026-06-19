---
plan: sdd/epics/202606/prompt_search_command.md
---
 Can you help me create a new `sase prompt search` command that works a lot like the `sase bead search` command but for sase prompts (both repo-specific sdd/ prompts, which should be prioritized and prompts that are local to this machine, which are stored elsewhere)?

- Make sure that we support all of the same formats types as the `sase bead search` command, with just as high (or ideally, higher) quality output.
- We should support filtering by date and should support other useful filter types (you should decide which filter types we should support).
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 