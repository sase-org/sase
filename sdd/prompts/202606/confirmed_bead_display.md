---
plan: sdd/tales/202606/confirmed_bead_display.md
---
 If we are not certain that a bead is associated with an agent's name, can we stop showing the bead icon in the agent list or the "Bead:" field in the agent metadata panel on the "Agents" tab of the `sase ace` TUI? We currently show it wrongly (i.e. when there is no bead that exists with an ID equal to the agent's name) a lot. Make sure these changes do not hurt performance at all and that we still show these when the bead definitely exists. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
