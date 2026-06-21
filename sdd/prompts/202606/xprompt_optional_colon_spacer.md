---
plan: sdd/tales/202606/xprompt_optional_colon_spacer.md
---
 When an xprompt is auto-completed (e.g. using `#@`, `<ctrl+t>`, or auto-completion) in the prompt input widget or in nvim and the xprompt has only optional inputs, we insert the xprompt and then a space (e.g. `#foobar `). It is common in this case for the user to then want to specify an argument, at which point they type `<backspace>:`. Can you help me start auto-deleting the space when a colon is typed in this case? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 