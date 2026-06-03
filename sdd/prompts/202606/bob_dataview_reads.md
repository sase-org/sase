---
plan: sdd/epics/202606/bob_dataview_reads.md
---
 I want to be able to give the `#!sase/reads` (see the xprompts/reads.md file for context) xprompt markdown file
an Obsidian dataview query instead of a list of note files. The agent should then be able to use its (not yet created)
`/bob_dataview` skill to run the `bob dataview` command. This query would be a TABLE query that produces just the titles
and URLs of each AI reference note. Can you help me make this happen? I think we might need to migrate all of our AI
reference notes to individual files first (If this is necessary then just go ahead and do it), right?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

