---
create_time: 2026-06-15 17:01:38
status: wip
prompt: sdd/prompts/202606/rename_skill_command.md
---
# Plan: Rename `sase skills` to `sase skill`

## Goal

Make `sase skill` the canonical command group for generated skill inspection, initialization, audit logging, and audit
recording. Update active code, tests, docs, CI, generated skill content, and the chezmoi-generated provider skill files
so current command examples and generated instructions use `sase skill ...`.

## Constraints and Scope

- Do not modify protected `memory/*` files without explicit user approval.
- Do not rewrite historical SDD notes, bead event logs, or archived planning records just to change past command text.
- Do not rename the provider skill directories such as `~/.codex/skills/`, the source directory
  `src/sase/xprompts/skills/`, or the internal `sase.skills` package; those are domain names and filesystem contracts,
  not the CLI command spelling.
- Treat active command references in source, tests, docs, CI, and generated chezmoi `SKILL.md` files as in scope.

## Implementation Strategy

1. Update CLI registration and dispatch.
   - Change the top-level command parser from `skills` to `skill`.
   - Update the entry dispatch branch so `args.command == "skill"` invokes the existing skill command handler.
   - Rename parser/handler docstrings, help text, examples, usage errors, and subcommand dests where they describe the
     command spelling.
   - Keep subcommands `init`, `list`, `log`, and `use`, with bare `sase skill` still defaulting to `sase skill list`.

2. Update init-namespace wiring.
   - Change the init compatibility path from `sase init skills` to `sase init skill`.
   - Update bare `sase init` planning prompts/spec names so generated prompts say `sase init skill --force`.
   - Keep labels like `Skills` and filesystem paths with `skills` where they are describing the artifact class rather
     than the CLI spelling.

3. Update generated skill audit directives and command output.
   - Change the generated first-step audit directive from `sase skills use ...` to `sase skill use ...`.
   - Update `sase skill use` and `sase skill log` error prefixes and list dashboard refresh notes.
   - Preserve audit event storage schema unless tests show it encodes the old command spelling; this is a command
     rename, not a data-model migration.

4. Update active references.
   - Replace command examples in `.github/workflows/ci.yml`, `docs/*.md`, active source help text, and active tests.
   - Update command references in generated skill source tests and expected rendered `SKILL.md` snippets.
   - Use exact searches for old command forms such as `sase skills`, `sase init skills`, `skills init`, `skills list`,
     `skills log`, and `skills use` across active repo paths and the chezmoi source tree.

5. Regenerate chezmoi skill files.
   - After the code and docs update, run `just install` if the editable CLI is stale.
   - Run `.venv/bin/sase skill init --force` so generated provider `SKILL.md` files in the chezmoi repo pick up
     `sase skill use ...`.
   - If the automatic chezmoi apply path reports unrelated drift, inspect the output and use the narrowest safe
     follow-up that updates the generated skill targets without overwriting unrelated user changes.

6. Verification.
   - Run focused parser/handler/generated-skill tests, including: `tests/main/test_skills_handler.py`,
     `tests/main/test_skills_log.py`, `tests/main/test_parser_help.py`, `tests/main/test_init_skills_plan.py`,
     `tests/main/test_init_skills_handler.py`, `tests/main/test_init_skills_deploy.py`,
     `tests/main/test_init_onboarding_flow.py`, `tests/main/test_init_onboarding_parser.py`, and
     `tests/test_github_actions_ci.py`.
   - Run CLI smoke checks for `sase skill --help`, `sase skill list`, `sase skill init --dry-run --force`,
     `sase skill log --help`, and `sase skill use --help`.
   - Run final reference audits over active repo paths and `/home/bryan/.local/share/chezmoi/home` to confirm no active
     generated or documented command reference still says `sase skills ...`.
   - Run `just check` if focused verification passes and time permits.

## Expected Result

Users and generated agents use `sase skill ...` everywhere in current command surfaces. The chezmoi-generated skill
files are regenerated from source, not hand-edited. Any remaining `skills` text should be limited to legitimate nouns,
filesystem directories, Python package names, protected memory, or historical records rather than the old CLI command.
