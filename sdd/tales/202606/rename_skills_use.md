---
create_time: 2026-06-15 16:21:06
status: done
prompt: sdd/prompts/202606/rename_skills_use.md
---
# Plan: Rename Skill-Use Audit Command

## Goal

Free `sase skills log` for a future memory-log-like inspection command by moving the existing write-only skill-use audit
command to a clearer subcommand name.

Use `sase skills use <name> --reason <reason>` as the replacement. The current command records that the current agent is
using a generated xprompt skill; `use` names that auditable action directly, while `log` should be reserved for reading
or inspecting the audit log later.

## Non-Goals

- Do not implement the future `sase skills log` query/summary command.
- Do not keep `sase skills log` as a compatibility alias; leaving the alias would keep the name occupied and undermine
  the migration.
- Do not change the skill-use JSONL schema, storage path, or TUI loaders. The persisted domain is still a skill-use log;
  only the public command that appends events changes.

## Implementation

1. Update the `sase skills` parser.
   - Replace the `log` subparser in `src/sase/main/parser_skills.py` with a `use` subparser.
   - Keep arguments the same: positional `skill-name` and required `-r, --reason`.
   - Update help text and examples to describe recording skill use through `sase skills use`.
   - Keep subcommands alphabetized as required by the CLI rules: `init`, `list`, `use`.

2. Update command dispatch.
   - Rename handler-facing functions in `src/sase/main/skills_handler.py` from log-oriented names to use-oriented names.
   - Dispatch `skills_subcommand == "use"` to the existing append-event behavior.
   - Update fallback usage text to `sase skills {init,list,use}`.

3. Rename the CLI handler module for clarity.
   - Move `src/sase/skills/cli_log.py` to `src/sase/skills/cli_use.py`.
   - Rename `handle_skills_log_command()` to `handle_skills_use_command()`.
   - Update docstrings and user-facing error prefix from `sase skills log:` to `sase skills use:`.
   - Leave `src/sase/skills/use_log.py` and exported log helper names intact because they describe the stored audit log,
     not the append command.

4. Update generated skill directives.
   - Change `src/sase/main/init_skills_handler.py` so generated `SKILL.md` files instruct agents to run
     `sase skills use <name> --reason ...`.
   - Keep `log_skill_use` field semantics unchanged: `true` injects the directive, `false` omits it.

5. Update docs and examples.
   - Replace references to the append command in `docs/init.md`, `docs/cli.md`, `docs/configuration.md`, and
     `docs/xprompt.md`.
   - Describe generated skills as using `sase skills use`, and avoid documenting `sase skills log` until the future
     read/query command exists.

6. Update tests.
   - Update parser and handler tests in `tests/main/test_skills_handler.py` from `log` to `use`.
   - Update generated directive tests in `tests/main/test_init_skills_plan.py`.
   - Add or update coverage that `sase skills use` requires `--reason`, writes an attributed event, reports missing
     agent identity with the new command prefix, and that the bare `sase skills` default remains `list`.

## Verification

After file changes:

1. Run `just install` first, because this workspace may be stale.
2. Run focused tests:
   - `.venv/bin/pytest tests/main/test_skills_handler.py tests/main/test_init_skills_plan.py tests/test_skill_use_log.py`
3. Run `just check`, as required for source/docs changes in this repo.

## Rollout Notes

Existing generated skill files outside the repo may still contain `sase skills log` until regenerated. This change
should make newly generated files use `sase skills use`; users can refresh deployed skills with the existing
`sase skills init --force` flow.
