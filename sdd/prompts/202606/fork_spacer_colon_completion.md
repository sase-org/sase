---
plan: sdd/tales/202606/fork_spacer_colon_completion.md
---
  We recently added agent name completion to the `#fork` xprompt. We also auto-delete the space before the ":" if the user types ":" after selecting `#fork` from the xprompt completion menu in the prompt input widget. The agent name completion menu does not trigger in this case (the user has to type `<backspace>:` to get it to trigger). Can you help me fix this so the agent name completion menu is triggered after this space is deleted? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 