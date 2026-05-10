---
plan: sdd/epics/202605/bead_model_routing.md
---
 Can you help me add support to sase beads for specifying which model should work (for phase agents) or land (for epic/legend agents) the bead? Make sure to update the appropriate xprompt skill. This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `xprompt skill`)