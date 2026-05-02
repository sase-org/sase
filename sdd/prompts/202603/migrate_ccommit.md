---
plan: sdd/epics/202603/migrate_ccommit.md
---
Can you help me integrate all functionality from the `/commit` skill and ccommit scripts into our new unified
commit/propose/pr workflows?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance. Make sure each phase of the plan explicitly
tells the agent to use the `sase_git_commit` or `ccommit` (depending on the phase) scripts directly to commit their
changes when they finish validating their work.

### DESIGN DECISIONS

I asked another agent to flesh out any design decisions that I needed to make. The agent's response can be found in the
sdd/research/202603/migrate_ccommit_prompt_critique.md file, which also contains my decisions (in "DECISIONS" sections).
