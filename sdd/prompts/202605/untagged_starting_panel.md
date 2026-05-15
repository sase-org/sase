---
plan: sdd/tales/202605/untagged_starting_panel.md
---
 Currently, we start showing the untagged agent panel when there are agents that are starting (i.e. when the "starting" agent count is shown), even when that panel is empty. This is not correct. We shouldn't show the untagged panel until the agent row is shown and, even then, it should only show if that agent row is actually supposed to be rendered in the untagged panel (i.e. it doesn't belong to a different agent group). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
