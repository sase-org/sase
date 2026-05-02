---
plan: sdd/tales/202604/wait_duration.md
---
Can you help me add support to the `%wait` directive for duration arguments of the form `XhYmZs` (we should support
short-forms like `5m` too)? When an argument that looks like this is used, we will treat it as the amount of time we
should wait before running the agent. Think this through thoroughly and create a plan using your `/sase_plan` skill
before making any file changes.
