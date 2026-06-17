---
type: long
parent: AGENTS.md
description: Read anytime new CLI subcommands or options are added.
---

# CLI Rules

When adding or changing CLI subcommands or options:

- Make `-h|--help` output excellent: clear, complete, consistent, and easy to scan.
- Keep listed subcommands and options sorted alphabetically.
- Give every public long option a short alias; this does not apply to internal subprocess arguments.
- Prefer beautiful, colored output over black-and-white output when color improves readability.
