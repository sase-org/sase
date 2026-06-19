---
plan: sdd/tales/202606/default_list_notice.md
---
 We already have an informal convention of using a list subcommand with sase subcommands that accept their own subcommands. When we do this the list subcommand is the default if that sase command is used without a subcommand. Can you help me do two things?
1. For each of the commands where we use the list subcommand as the default, start out by printing a message to the user letting them know that we are delegating to the list subcommand when that corresponding sase command is used with no subcommand.
2. Add all of these conventions that I just described to you to the cli_rules.md memory file to make these conventions a more formal rule.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
