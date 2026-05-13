---
plan: sdd/tales/202605/wait_timestamp_display.md
---
 When an agent had to wait to run because of the `%wait` directive, can we start using only the WAIT
"Timestamp:" field entry (in the agent metadata panel on the "Agents" tab of the `sase ace` TUI)? Currently we seem to
show both START and WAIT when waiting and then just START once the agent starts running (START continues to be visible
throughout the agent's lifecycle and WAIT is never visible again). Instead, we should start showing just WAIT when the
agent goes from START to WAIT and never show the START timestamp for that agent again (use WAIT instead).

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
