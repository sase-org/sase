---
plan: sdd/epics/202607/dynamic_agent_families_v2.md
---
  Can you help me implement v2 of dynamic agent families?

- See the "Recommended v2 shape (staged)" section of the sdd/research/202607/dynamic_agent_families_v1_v2_design.md file for context.
- Review the recently completed work related to the sase-5f epic bead to get a better idea of what work has already been completed for v1.
- In case you need even more context: the sase-5f epic bead was created by the last agent in the "0b" sase agent hood ("0b.f1.f1").

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

  