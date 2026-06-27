---
plan: sdd/tales/202606/memory_init_header_basename.md
---
 Can you help me have the `sase memory init` command start including the memory file basename only (for users, who would like transparency about how the file was generated) in the H3 headers that it generates for AGENTS.md files (and other agent provider files like CLAUDE.md)?

- We should include this name in parenthesis after the title parsed from the memory file (which should no longer be in parentheses).
- For example, `### memory/build_and_run.md (Build & Run Commands)` should be transformed into `### Build & Run Commands (build_and_run)`.
- When you're done, run the `sase memory init` command to apply your changes to the appropriate files. 

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 