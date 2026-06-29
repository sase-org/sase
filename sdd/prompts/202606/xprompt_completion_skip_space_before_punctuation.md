---
plan: sdd/tales/202606/xprompt_completion_skip_space_before_punctuation.md
---
 When auto-completing xprompts in the prompt input widget after the user selects an xprompt using the prompt input widget's completion menu, if the xprompt has no required arguments, we insert a space after the xprompt (ex: `#foo `). Can you help me make it so we only do this when the next character after the xprompt is not punctuation (ex: `)`, `.`, `!`, etc...)? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 