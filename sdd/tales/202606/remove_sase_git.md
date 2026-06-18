---
create_time: 2026-06-18 14:30:30
status: done
prompt: sdd/prompts/202606/remove_sase_git.md
---
# Remove the `sase git` CLI Command

## Context

`sase git` currently exists only as a top-level command group for `sase git init`. That command initializes
bare-repo-backed git projects and exposes custom `--bare-dir`, `--clone-dir`, and `--existing` flags.

The product direction is now that users should not run `sase git init` directly: `#git:<project>` initializes a missing
bare-git project on first use, and `#git:<bare-repo-path>` can register an existing bare repository by path. The
implementation should therefore remove the obsolete public CLI command while keeping the bare-git project initializer
available for the workspace provider.

## Goals

- Remove `sase git` from the public argparse command surface, root full help, and command dispatch.
- Preserve `#git:<project>` auto-initialization and `#git:<path>` registration.
- Keep `init_bare_git_project()` as an internal/shared implementation used by bare-git reference resolution and tests.
- Update docs so users learn the current `#git` workflow and no longer see `sase git init` as a supported command.
- Add/adjust tests so this command cannot silently reappear.

## Non-Goals

- Do not remove the built-in bare-git workspace provider or `#git` workflow.
- Do not remove `init_bare_git_project()` unless a deeper API migration is separately requested.
- Do not add a replacement CLI command under `sase init`; the request is to remove the manual command because first-use
  `#git` is the supported path.

## Implementation Plan

1. Remove CLI registration.
   - Delete `register_git_parser()` from `src/sase/main/parser_init.py`, or leave no public callable if keeping nearby
     initialization parser helpers is clearer.
   - Remove the `register_git_parser` import and call from `src/sase/main/parser.py`.
   - Keep top-level subcommand ordering tests passing after `git` disappears.

2. Remove command dispatch.
   - Delete the `if args.command == "git":` branch from `src/sase/main/entry.py`.
   - Keep `init_bare_git_project()` imports localized to the bare-git provider and tests.

3. Update parser and CLI tests.
   - Change `tests/main/test_parser_help.py` so the init namespace test covers only `sase init ...` migrated commands.
   - Add an explicit rejection assertion for `parser.parse_args(["git", ...])` and/or assert the root subparser choices
     do not include `git`.
   - Remove the mocked CLI handler test for `sase git init`.
   - Retain direct initializer coverage by renaming or rewriting `tests/test_cli_init_git.py` as bare-git initializer
     tests, or by moving those cases into `tests/test_bare_git_workspace.py`.

4. Update documentation.
   - Remove the `sase git init` row from `docs/cli.md` and delete its dedicated flag section.
   - Rewrite bare-git setup docs in `docs/workspace.md` and `docs/xprompt.md` to describe `#git:<project>` first-use
     initialization and `#git:<bare-repo-path>` existing-repo registration.
   - Replace remaining `sase git init` references in `docs/configuration.md`, `docs/init.md`, `docs/sdd.md`, and
     `docs/project_spec.md` with current `#git`/workspace materialization language.
   - Run `rg "sase git init|sase git"` and address any remaining live-doc references, excluding historical SDD
     prompt/tale artifacts unless they are actively presented as current documentation.

5. Verify behavior.
   - Run targeted parser tests: `uv run pytest tests/main/test_parser_help.py`.
   - Run targeted bare-git initialization/workspace tests:
     `uv run pytest tests/test_bare_git_workspace.py tests/test_cd_spawn_env.py` plus the renamed/updated bare-git
     initializer test file.
   - Run `just install` before repository-wide validation if needed for this ephemeral workspace.
   - Run `just check` after file changes, per repo instructions.

## Risks and Mitigations

- Risk: removing `sase git init --existing` removes the only documented way to choose both an existing bare repo and a
  custom clone directory. Mitigation: document the supported `#git:<bare-repo-path>` registration path and leave custom
  ProjectSpec editing as the advanced escape hatch only if docs already tolerate manual ProjectSpec edits.

- Risk: dead tests continue to assert the removed command. Mitigation: make rejection explicit in parser tests and move
  initializer tests away from CLI naming.

- Risk: docs drift between generated/reference pages. Mitigation: finish with a repository search for `sase git init`
  and `sase git` in source docs/tests.
