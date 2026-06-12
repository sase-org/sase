---
plan: sdd/tales/202606/commit_tags.md
---
 Can you help me add more conventional commit message tags that the agent can use to the "Determine the commit tag" section of the src/sase/xprompts/skills/sase_git_commit.md file (which defines an xprompt skill)?

- Use your best judgement on which tags to add to the list.
- Make sure to give good instructions on when the agent should use each of these new tags (and improve the other tag descriptions if you can find objective improvements to make).
- Also, mention that the project might use a tool like release-please / release-plz for automated releases, so these tags are more than just cosmetic. Make sure to explicitly instruct the agent to use the `!` tag suffix and/or add a "BREAKING CHANGES:" line (use whatever standard release-please / release-plz use) to the commit message.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
 