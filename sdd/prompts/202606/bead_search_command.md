---
plan: sdd/epics/202606/bead_search_command.md
---
 Can you help me create a new `sase bead search` command?

- This command should take a text query as an argument.
- The search should match any beads that contain that text anywhere.
- Make sure we support different output formats: json, bead name and short description only, full `sase bead show` output.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 