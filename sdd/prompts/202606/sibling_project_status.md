---
plan: sdd/tales/202606/sibling_project_status.md
---
  Can you help me start supporting a new "sibling" status for projects (see the recent work related
to the "Project Management" panel in the TUI for context)?

- The `sase workspace open` command should be updated to work with unknown projects when those projects are configured
  as sibling repos.
- This command should create the projects (and necessary project files) if necessary when it is run, but the project
  should be given a state of "sibling" in this case. We should assume the same VCS is being used with the same
  organization (ex: we should assume "sase-org" for all sibling repos configured in this repo's sase.yml file).
- Projects with a state of "sibling" should not be shown to the user when using the `@` keymap in the TUI (only active
  projects should be shown).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
