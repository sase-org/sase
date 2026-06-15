---
create_time: 2026-06-15 17:39:41
status: done
---
# Plan: Rename `sase skills` to `sase skill`

## Goal

Make `sase skill` the canonical command group for generated SASE skill operations:

- `sase skill` and `sase skill list`
- `sase skill init`
- `sase skill log`
- `sase skill use`

All active source, tests, CI, help text, generated skill directives, and chezmoi-generated `SKILL.md` files should stop
referring to `sase skills ...`.

## Current Shape

- The CLI currently registers a top-level `skills` command in `src/sase/main/parser_skills.py` and dispatches it from
  `src/sase/main/entry.py` through `src/sase/main/skills_handler.py`.
- `sase skills init` is the newer canonical initializer, while `sase init skills` remains a compatibility alias.
- Generated skill files get their audit directive from `_skill_use_audit_directive()` in
  `src/sase/main/init_skills_handler.py`, which currently emits `sase skills use ...`.
- Active checks and docs reference the old spelling in parser tests, skills handler/log tests, init-skills generation
  tests, CI, and the GitHub Actions CI assertion.
- The chezmoi repo is clean and contains generated `SKILL.md` files with the old `sase skills use ...` directive. These
  should be regenerated, not hand-edited.

## Scope Decisions

- Treat this as a canonical rename, not just an added alias: active command examples and tests should use `sase skill`.
- Keep the resource noun "skills" where it describes files, directories, inventory rows, generated skill sets, or the
  existing `sase init skills` compatibility alias.
- Preserve `sase init skills` as a compatibility alias to `sase skill init`; update its help text to point at the new
  canonical command.
- Do not directly edit generated chezmoi `SKILL.md` files. Regenerate them via `.venv/bin/sase skill init --force` after
  the repo command is updated and installed.
- Do not directly edit canonical memory files unless separately approved. If stale command text remains only in memory
  or historical SDD/bead records, report that separately rather than rewriting audit/history artifacts.

## Implementation Steps

1. Rename the top-level parser surface from `skills` to `skill`.
   - Register `skill` in the root parser in the same sorted location.
   - Update command-group help, examples, subparser destination naming, and dispatch to use `skill`.
   - Update error prefixes from `sase skills ...` to `sase skill ...`.
   - Add or update a regression that the old top-level `sase skills` form is rejected unless implementation discovers an
     established alias policy that requires a hidden alias.

2. Update initialization wording and generated audit directives.
   - Change the generated skill audit directive to `sase skill use <name> --reason ...`.
   - Update `sase skill init` help text, list-view notes, warning labels, and chezmoi commit messages.
   - Keep internal function/module names such as `init_skills_handler` where they refer to generated skill files rather
     than the command spelling.

3. Update active references.
   - Update `.github/workflows/ci.yml` and `tests/test_github_actions_ci.py`.
   - Update parser/help tests, skills handler tests, skills log tests, and generated-skill tests that assert command
     text.
   - Update active docs or top-level provider instructions if they contain `sase skills ...`.
   - Run targeted `rg` sweeps for `sase skills`, `skills use`, `skills init`, `skills log`, and `skills list` across
     active source/test/doc paths.

4. Regenerate and deploy chezmoi skills.
   - Run `just install` first so `.venv/bin/sase` reflects the renamed command.
   - Run `.venv/bin/sase skill init --force` as requested. This is the full deploy path: regenerate, commit in chezmoi,
     push to `github.com:bbugyi200/dotfiles.git`, and apply.
   - Verify the chezmoi repo no longer contains `sase skills use` in generated `SKILL.md` files.

5. Verify behavior.
   - Run focused tests for CLI parsing/help, skill command handlers/logging, init-skills generation, and CI command
     assertions.
   - Run CLI smokes for `sase skill --help`, `sase skill init --dry-run`, and the `sase init skills` compatibility
     alias.
   - Because repo files will change, run `just check` before finishing.
   - Finish with `rg` sweeps showing no stale active references to the old command spelling, plus a note about any
     intentionally untouched historical or memory-only occurrences.

## Risks

- A hard removal of `sase skills` may break callers not covered by this repo. The user's request favors a true rename,
  so tests should make that behavior explicit.
- The chezmoi deploy step can fail due to network, push, or apply issues. If that happens, leave repo changes intact,
  report the failing command, and show the chezmoi status.
- Historical SDD/bead records may contain old command strings. Rewriting those would mutate history/audit material, so
  they should be handled only with explicit approval.
