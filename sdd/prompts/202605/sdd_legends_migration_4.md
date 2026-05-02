---
plan: sdd/epics/202605/sdd_legends_migration_4.md
---
  Can you help me migrate sase's SDD files to a new sdd/ directory and add support for "legends" to sase? We explored this a little bit in a research markdown file so find that and review it before deciding on your solution. 
Epics that are linked to legends should be created using the `--type epic(<legend_bead_id>)` option.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### Additional Requirements

- We should move existing epic plan files to sdd/epics/. We should also add a new "Legend" option to the plan approval panel, telegram plan approval messages, and Google chat plan approval messages.
- We should store normal (i.e. non-epic) plan files in the sdd/tales/ directory.
- Actually, let's just use `--type plan(<plan_file>,<legend_bead_id>)` to create epic beads that have a legend bead as a parent. No need for `--type epic`.
- We should NOT migrate the sdd/research/ directory.