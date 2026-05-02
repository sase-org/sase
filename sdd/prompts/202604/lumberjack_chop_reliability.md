---
plan: sdd/tales/202604/lumberjack_chop_reliability.md
---
I'm pretty sure that right now if the cumulative runtime of every chop script is greater than the interval configured
for the lumberjack, then we wind up skipping some chop scripts at the end. Can you help me fix this so we always
reliably run all chop strips within a lumberjack? Think this through thoroughly and create a plan using your
`/sase_plan` skill before making any file changes.
