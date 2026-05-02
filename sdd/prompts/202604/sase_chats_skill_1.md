---
plan: sdd/epics/202604/sase_chats_skill_1.md
---
  Can you help me add a new /sase_chats xprompt  skill that allows agents to easily access previous sase agent chat transcripts? See how the /sase_agent_status xprompt skill is implemented for inspiration. This skill should be invoked by agents when they are asked about previous agent chats.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 