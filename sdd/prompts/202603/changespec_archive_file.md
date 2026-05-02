---
plan: sdd/plans/202603/changespec_archive_file.md
---
Can you help me start moving ChangeSpec to from the `~/.sase/projects/<project>/<project>.gp` file to the
`~/.sase/projects/<project>/<project>-archive.gp file when the status is changed to any one of the following?:
Submitted, Archived, Reverted?

- We should make sure to move them back to the original file if we ever change the status back to a status other than
  one of those listed.
- We should start reading the `<project>.gp` file AND the `<project>-archive.gp` file for all projects instead of just
  the former.
- Make sure you cover EVERY possible scenario where a ChangeSpec's STATUS field value might change.

Think this through thoroughly and create a plan using your `/sase_plan` skill.
