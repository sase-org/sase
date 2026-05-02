---
plan: sdd/plans/202603/fix_workflow_input_defaults.md
---
Can you look into the "sase_refresh_docs" chop that is defined in the chezmoi repo? It's supposed to run every hour and
if there were 10 or more commits since the last time the agent ran then run an agent with the 'sase/docs' xprompt. I'm
pretty sure I've made 10 commits today and I don't think that the docs have been refreshed yet. Think this through
thoroughly and create a plan using your `/sase_plan` skill.
