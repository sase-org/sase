---
plan: sdd/plans/202604/fix_xprompt_cursor.md
---
Can you help me fix the sase-nvim plugin's (in the ../sase-nvim repo) `#@` xprompt completion? The problem: The popup
works great and the xprompt is inserted when the user hits `<enter>`, but the cursor, which should be at the end of the
xprompt that was inserted, is placed before the last letter of the xprompt instead (ex: `#fooba<CURSOR>r` instead of
`#foobar<CURSOR>`). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file
changes.
