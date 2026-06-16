---
plan: sdd/tales/202606/hide_terminalized_abandoned_agents.md
---
 We made a change yesterday that seemed to break how we populate agents on the agents tab in the TUI. Namely
there are 197 agents in the chop agent group (i.e. are rendered in the `#chop` dynamic agent panel on the left) that I
know have been dismissed before that are showing on the agents tab. I've tried dismissing these all from the TUI but
that doesn't seem to work.

Can you help me diagnose the root cause of this issue and fix it? Make sure you verify your fix by running the `sase ace --tmux` command to launch the TUI in a tmux pane and then capturing the contents of that pane to verify the agents I'm talking about no longer show on the agents tab. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 