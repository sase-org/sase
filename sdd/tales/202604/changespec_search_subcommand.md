---
create_time: 2026-04-29 16:05:21
status: done
prompt: sdd/prompts/202604/changespec_search_subcommand.md
---
# Plan: Move `sase search` under `sase changespec search`

## Goal

Move the existing ChangeSpec query command from the top-level CLI form:

```bash
sase search '<query>' -f markdown
```

to the ChangeSpec namespace:

```bash
sase changespec search '<query>' -f markdown
```

The new subcommand should preserve the existing query language, output formats, result ordering, exit behavior, and
markdown/plain/rich rendering. The old top-level `sase search` parser and dispatch path should be removed unless a
compatibility requirement appears during implementation.

## Current Shape

- CLI parser:
  - `src/sase/main/parser.py` registers top-level `register_search_parser(...)`.
  - `src/sase/main/parser_commands.py` defines `register_search_parser(...)`.
  - `register_changespec_parser(...)` currently owns `current` and `sync-deltas`.
- Dispatch:
  - `src/sase/main/entry.py` routes top-level `args.command == "search"` to `handle_search_command(args)`.
  - `src/sase/main/changespec_handler.py` dispatches `current` and `sync-deltas`.
- Search implementation:
  - `src/sase/main/search_handler.py` contains the actual query validation, ChangeSpec lookup, and display helpers.
  - `tests/test_search_markdown.py` validates markdown rendering helpers directly.
- Documentation and callers:
  - `src/sase/xprompts/skills/sase_changespecs.md` documents many `sase search ...` examples.
  - `docs/xprompt.md`, `docs/configuration.md`, and `README.md` mention the top-level command.
  - `src/sase/scripts/sase_bug` shells out to `sase search`.

## Implementation Steps

1. Move parser registration into the `changespec` parser.
   - Add a `search` subparser inside `register_changespec_parser(...)`.
   - Reuse the existing positional `query` and `-f/--format` choices/default/help.
   - Remove the top-level `register_search_parser(...)` function and stop importing/calling it from `parser.py`.
   - Keep short options intact per repo convention.

2. Move command dispatch into the `changespec` handler.
   - Route `changespec_subcommand == "search"` to the existing search handler.
   - Remove the top-level `args.command == "search"` dispatch from `entry.py`.
   - Update usage text for `sase changespec` to include `search`.
   - Update docstrings/error prefixes in the search handler if needed so they name `sase changespec search`.

3. Update in-repo callers and documentation.
   - Change `src/sase/scripts/sase_bug` to call `sase changespec search`.
   - Update `README.md` command table from `sase search` to `sase changespec search`.
   - Update `docs/configuration.md` CLI reference heading/examples.
   - Update `docs/xprompt.md` skill summary.
   - Leave historical plans/sdd/research/specs alone unless they are user-facing current docs; they document past work.

4. Update xprompt skill sources and generated skills.
   - Replace all `sase search ...` examples in `src/sase/xprompts/skills/sase_changespecs.md` with
     `sase changespec search ...`.
   - Update prose that refers to the primary command.
   - Run the skill generation/deploy workflow required by repo memory:
     - `sase init-skills --force`
     - `chezmoi apply`
   - Do not hand-edit generated live `SKILL.md` files.

5. Add parser/dispatch coverage.
   - Add tests that `create_parser().parse_args(["changespec", "search", "<query>", "-f", "markdown"])` produces:
     - `command == "changespec"`
     - `changespec_subcommand == "search"`
     - `query` and `format` populated as before.
   - Add/update tests ensuring top-level `sase search` is no longer accepted, if existing test structure makes that
     clean and non-brittle.
   - Keep existing markdown rendering tests focused on output helpers unless behavior changes.

6. Verify.
   - Per workspace memory, run `just install` before repo checks if needed.
   - Run focused tests first:
     - parser/current/search tests
     - markdown search tests
   - Run `sase init-skills --force` after the skill source change.
   - Run `chezmoi apply` to deploy generated skill files.
   - Run `just check` before finishing, as required for changes in this repo.

## Risks and Decisions

- Compatibility: removing top-level `sase search` may break external callers. The user explicitly asked to move the
  command, so the plan removes the old top-level command and updates in-repo callers. If preserving an alias becomes
  important, it should be an explicit compatibility decision.
- Search implementation location: keeping `src/sase/main/search_handler.py` is acceptable because the behavior remains
  shared and self-contained. Renaming the file would add churn without improving the CLI contract.
- Generated skills: source templates in `src/sase/xprompts/skills/` are the authoritative files. Generated live skill
  files should be refreshed through `sase init-skills --force` and deployment, not edited directly.
