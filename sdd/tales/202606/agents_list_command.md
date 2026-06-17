---
create_time: 2026-06-17 07:11:06
status: done
prompt: sdd/prompts/202606/agents_list_command.md
---
# Plan: Rename `sase agents status` to `sase agents list`

## Goal

Rename the public running-agent listing command from `sase agents status` to `sase agents list`, and make bare
`sase agents` invoke that list command by default.

## Context

- `src/sase/main/parser_agents.py` currently registers the `status` subcommand with `-a/--all`, `-j/--json`, and
  `-p/--project`.
- `src/sase/main/agents_handler.py` currently defaults a missing `agents_subcommand` to `status`.
- The root parser already has `_default_list_subcommands()`, which defaults any command group with an exact `list` child
  to that child and copies parser defaults. Adding `agents list` should therefore follow the existing CLI convention
  used by `memory`, `skill`, `notify`, `workspace`, and similar command groups.
- The generated `/sase_agents_status` skill source is `src/sase/xprompts/skills/sase_agents_status.md`; generated
  runtime `SKILL.md` files should not be edited by hand.
- Current, user-facing references include CLI help examples, README/docs/blog pages, the PyPI smoke docs/workflow,
  shipped skill tests, and the Phase 7 perf benchmark command invocation. Historical SDD/research records may retain old
  wording when they describe past artifacts rather than current executable behavior.

## Proposed Changes

1. Update the agents CLI parser:
   - Register `list` instead of `status` for the running-agent listing view.
   - Keep the existing options and output behavior unchanged: `-a/--all`, `-j/--json`, `-p/--project`.
   - Update help text/descriptions so `sase agents --help` advertises `list`, and bare `sase agents` defaults through
     the existing list-default parser convention.

2. Update dispatch and internal naming:
   - Default `handle_agents_command()` to `list`.
   - Route `agents_subcommand == "list"` to the existing listing implementation.
   - Rename internal comments/docstrings and, if low-risk, module/function names from status-oriented names to
     list-oriented names so the code matches the public command.
   - Update the direct unknown-subcommand usage string to list the new command set.

3. Update tests:
   - Change bare-agent dispatch tests to expect the list command path.
   - Add or adjust parser coverage for `sase agents`, `sase agents list`, and list flags.
   - Update help/smoke tests that assert `sase agents status` appears in examples.
   - Update shipped skill-source tests to assert `sase agents list -j`.

4. Update generated skill source and related xprompt docs:
   - Change `src/sase/xprompts/skills/sase_agents_status.md` command examples from `status` to `list`.
   - Update `src/sase/xprompts/skills/sase_chats.md` fallback references that call the agents listing command.
   - Keep the skill name `/sase_agents_status`; this task renames the CLI command, not the installed skill identity.
   - Regenerate provider skill files through the supported `sase skill init` flow after editing the source, without
     hand-editing generated `SKILL.md` files.

5. Update current documentation and executable references:
   - README quickstart/common commands.
   - `docs/cli.md`, current blog examples, and current generated-skill documentation entries.
   - PyPI smoke README and publish workflow grep.
   - Perf benchmark command invocation from `agents status -j` to `agents list -j`, while preserving historical surface
     IDs where they are artifact names rather than commands.

6. Verification:
   - Run focused tests for parser/dispatch/help and shipped skill sources.
   - Run or dry-run skill generation as appropriate for the repo configuration.
   - Run `just install` followed by `just check`, per project instructions for file changes.
   - Finish with a final `rg` over current code/docs/test surfaces for `sase agents status` and classify any remaining
     hits as historical-only before reporting them.
