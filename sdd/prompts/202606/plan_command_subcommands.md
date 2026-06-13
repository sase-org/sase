---
plan: sdd/epics/202606/plan_command_subcommands.md
---
 Can you help me improve the `sase plan` command?

- I want this command to start using subcommands.
- Migrate the existing functionality of this command to the `sase plan propose` command.
- Add a new `sase plan approve` command that allows the user to approve proposed plans.
- Add a new `sase plan list` (the default if `sase plan` is used with no subcommand) that shows all proposed plans, the
  10 most recently approved plans (across all projects), and the 10 most recently rejected plans (i.e. plans in
  ~/.sase/plans/ not represented by either of the prior two groups of plans). I want you to lead the design on this one. Just make sure it looks beautiful!
- Make sure you update the `/sase_plan` xprompt skill so future agents know to use the `sase plan propose` command
  instead of the `sase plan` command.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

