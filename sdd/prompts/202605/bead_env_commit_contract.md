---
plan: sdd/epics/202605/bead_env_commit_contract.md
---
  Currently, we leave it up to the agent whether it's going to associate a bead with a commit or not (using the `sase commit` command). Can we start using an environment variable that has the bead ID as its value and make it impossible for an agent to ever commit without having the bead associated (i.e. included in the commit message)?

- This means we can remove the --bead option.
- But it also means we will need the agent to close the bead.
- So make sure you update the commit stop hook to instruct the agent to close the bead (explicitly reference the bead ID) after committing (we should only include those instructions in the message if the environment variable is set).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `sase commit`)