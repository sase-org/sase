---
plan: sdd/epics/202605/remove_cross_workspace_bead_reads.md
---
 Can you help me remove all support from the `sase bead` command for reading beads across workspace directories? The source of all truth should be considered to be the current repo's sdd/beads/issues.jsonl file. This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

