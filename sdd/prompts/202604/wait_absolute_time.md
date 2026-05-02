---
plan: sdd/plans/202604/wait_absolute_time.md
---
Can you help me add support for new HHMM and yymmdd/HHMM time and datetime formats, respectively, to the `%w` directive?
This is meant to compliment the recently added duration format. When this format is used, we should wait until that time
has passed before running the agent. Make sure to add good TUI support as well so the user knows which agents are
waiting and for when. I want you to lead the design on this one. Make sure you design this feature so it is intuitive,
reliable, and (last but not least) beautiful! Think this through thoroughly and create a plan using your `/sase_plan`
skill before making any file changes.
