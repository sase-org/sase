---
plan: sdd/plans/202604/fix_wait_agent_vcs_sync.md
---
 I have a feeling that when agents wait for other agents (using the `%wait` directive), they do not sync their VCS (e.g. run `git pull`) when they are eventually launched. This is important because the agents that the waiting
agent waited for could have pushed new commits to master. Can you help me confirm whether this is really and issue or not, diagnose the root cause if so, and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 