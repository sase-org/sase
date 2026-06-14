---
plan: sdd/tales/202606/agent_context_memory_skills_panel.md
---
 We already show what memory files an agent has read in the metadata panel in the TUI. Can you help me support
also showing all of the xprompt skills that were used by that agent?

- Instead of creating a new section to the metadata panel for this, we should create a new section (pick a good name for
  this section) that has two sub-sections: "MEMORY" (which is where the "MEMORY READS" section should be migrated to)
  and "SKILLS" (which is where we should show what xprompt skills the agent used).
- Make sure this works for all LLM providers (i.e. claude, codex, gemini, qwen, and opencode).
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 