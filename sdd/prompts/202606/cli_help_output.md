---
plan: sdd/tales/202606/cli_help_output.md
---
 Can you help me make some improvements to sase's command line help output?

- Let's migrate the current --help option to a new -H|--full-help option.
- For the --help option, we should then remove all of the subcommands except for the most useful ones from a user's perspective from the output and then provide much better help text for each one of them.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
