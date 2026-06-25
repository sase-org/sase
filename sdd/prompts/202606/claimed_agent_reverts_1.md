---
plan: sdd/tales/202606/claimed_agent_reverts_1.md
---
 When we revert agent commits (using the `,r` keymap on the agents tab), it seems like we use the same workspace directory that the agent ran on. This is unnecessary and error-prone (other agents can claim that workspace and make file changes to it, at which point we can no longer revert commits that our agent made to that workspace directory). Can you help me fix this by claiming a new workspace (and properly releasing it when you are done) for the reverts that we need to do? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
