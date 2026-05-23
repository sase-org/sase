---
plan: sdd/epics/202605/memory_command_1.md
---
#gh:sase Can you help me add a new `sase memory` command with two subcommands, `list` and `init`?

- The `init` command should be the new main implementation of the `sase init memory` command's behavior and that command
  should be considered an alias (like the `sase init sdd` command).
- The `list` command should output a rich list / dashboard of all of the memory files that would be loaded into and/or
  referenced in a sase agent's context if one were launched from the current directory. Make sure to display how many
  tokens and lines would be loaded into (e.g. `@` references are loaded into context whereas normal file references are
  not--except for the references themselves of course) context. #bea
- If the `sase memory` command is run without arguments, it should default to the behavior of the `sase memory list`
  command.

%(#plan,#epic)
