Can you help me design a #git / #gh solution for that enhances / obsoletes the previous solution described in the
plans/git_change_specs_v2.md file? This is a large piece of work, so split it up into phases. I'll let you decide how
many phases to create, but keep in mind that each phase will be completed by a distinct Claude Code instance.

- We should start using `git clone`s instead of worktrees for each workspace directory.
- This means that we can have `master` checked out in multiple directories.
- Our stop hook, which prompts the agent to commit changes, should handle the committing for us now and should be
  allowed to commit directly to master.
- This change completely obsoletes random branch names so make sure we remove all code related to those.
