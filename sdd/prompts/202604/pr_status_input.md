---
plan: sdd/plans/202604/pr_status_input.md
---
Can you help me add a new 'status' input argument to the `#pr` xprompt workflow (see the src/sase/xprompts/pr.yml file)?
Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

- This argument should accept a (case insensitive) string that matches either "wip", "draft", or "ready" (defaults to
  "draft").
- This argument should control the STATUS field value of the ChangeSpec that is created by this workflow.
