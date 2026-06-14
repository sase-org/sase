---
plan: sdd/tales/202606/bulk_agent_revert.md
---
 We recently added support for the new `,r` keymap that reverts any commits associated with the selected agent
on the agents tab in the TUI. Can you help me add support for this keymap to be used to bulk revert all marked agents?

- We already support marking agents on the agents tab.
- Make sure that we revert all commits associated with all marked agents and do so in the appropriate order (newest
  commits get reverted first)
- Also, make sure that we have robust error handling support in the case of merge conflicts or other errors experienced
  when trying to revert a commit.
- Bulk reverts should also be atomic. In other words, in the case that any revert fails, we should abort / reverse all
  reverts from all marked agents.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
