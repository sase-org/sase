---
plan: sdd/tales/202605/validate_command.md
---
  Can you help me add a new `sase validate` command that runs the `sase init --check` and
`sase sdd validate` commands and reports any errors with either of them?

- Make sure this command has good, concise user output.
- Replace the `sdd-validate` Justfile target with a new `validate` target that uses this command. This target should be
  run when `just lint` is run.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
