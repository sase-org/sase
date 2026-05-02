---
plan: sdd/plans/202605/sdd_prompt_management.md
---
   Can you help me improve the way we manage SDD prompt files?

- Move sdd/specs/ to sdd/prompts/.
- Let's start adding a "prompt" frontmatter field to plans/, epics/, and legends/ plan files. The value of this field should be the file path for the prompt that was used to generate that file.
- Let's also start adding a "plan" field to the front matter of the prompt file that points to the file path of the plan/epic/ legend that this prompt was used to generate.
- Add a new `sase sdd validate` command (add some other useful sub commands to `sase sdd` too) that validates the front matter in these files. This command should be run by GitHub actions.
- These front matter fields should be added by sase code, NOT by agents.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

