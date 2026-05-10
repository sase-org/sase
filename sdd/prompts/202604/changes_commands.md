---
plan: sdd/epics/202604/changes_commands.md
---
  Can you help me add a new /changes Telegram slash command that lists all (not submitted, archived or reverted) ChangeSpecs as copy buttons which copies the appropriate VCS xprompt workflow tag (ex: #hg:foobar)?

- The slash command should support an optional argument which should be a project name. If this is given we should only show ChangeSpecs from that project. 
- We also need to add a .changes dot command to the retired chat plugin repo that works the same way. 

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

