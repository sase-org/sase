---
plan: sdd/epics/202605/sase_notify_skill_1.md
---
 Can you help me add a new /sase_notify xprompt skill that agents can use to read sase notifications? This will be useful for prompts like "Can you help me fix the axe errors I just got a sase
notification about?". Review the existing /sase_agents_status, /sase_changespecs, and /sase_chats xprompt skills for inspiration before deciding on your solution.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `xprompt skill`)