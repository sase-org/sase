---
plan: sdd/tales/202605/xprompt_double_colon_parentheses.md
---
 I don't think using "::" with xprompts, which should accept all text from that point until the next xprompt that uses "::" or the end of the file as the next text argument, works when the text
after the "::" contains a "(". Namely, it looked like only the text after the "(" was passed along to the xprompt (which was src/sase/default_xprompts/research_swarm.md). Can you help me diagnose the root
cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
