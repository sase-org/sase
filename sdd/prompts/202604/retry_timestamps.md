---
plan: sdd/tales/202604/retry_timestamps.md
---
Can you help me add start logging a "RETRY" timestamp using the "Timestamps:" field in the agent metadata panel on the
"Agents" tab of the `sase ace` TUI that shows the time that the agent was retried? We should always add a new "RETRY"
timestamp when a new retry starts, which means it is possible for there to be multiple "RETRY" timestamps for a single
agent entry. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file
changes.
