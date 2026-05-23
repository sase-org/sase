---
create_time: 2026-05-23 13:16:26
status: done
prompt: sdd/prompts/202605/skills_command.md
---
# Add `sase skills`

## Goal

Add a top-level `sase skills` command group that mirrors the `sase memory` interface:

- `sase skills` defaults to `sase skills list`.
- `sase skills list` prints a useful, concise Rich dashboard for generated SASE skills.
- `sase skills init` delegates to the existing `sase init skills` implementation and keeps the same flags.
- Existing `sase init skills` behavior remains compatible.

## Current Shape

`sase memory` is implemented as a dedicated parser module plus a small handler:

- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- `src/sase/memory/cli_list.py`
- `src/sase/memory/inventory.py`

`sase init skills` already exists in `src/sase/main/init_skills_handler.py` and contains the important skill
source/render/deploy logic:

- discover xprompt entries with `skill: true` or `skill: [provider, ...]`
- resolve target providers through the LLM provider plugin registry
- render provider-specific `SKILL.md` contents
- compute generated target paths, including provider-specific extra deploy paths
- support chezmoi deployment controls

The new command should reuse that behavior instead of introducing a second skill generation path.

## Design

### Parser and Dispatch

Add `src/sase/main/parser_skills.py` with a `skills` command group.

Subcommands:

- `list`
  - no flags initially; keep the surface intentionally small.
- `init`
  - same flags as `sase init skills`: `--no-apply`, `--no-commit`, `--force`, `--dry-run`, `--no-push`, and
    `--provider`.

Register it from `src/sase/main/parser.py` in sorted top-level order, and add an `args.command == "skills"` branch in
`src/sase/main/entry.py`.

Add `src/sase/main/skills_handler.py`:

- default missing subcommand to `list`
- dispatch `init` to the existing skills initializer
- dispatch `list` to the new skills list renderer

For `skills init`, avoid duplicating generation logic. Reuse `run_init_skills()` or a small wrapper in
`init_skills_handler.py`.

### Inventory Model

Add a small read-only inventory module under `src/sase/skills/`.

The inventory should summarize the skill source catalog and generated target state without writing files:

- source skill name
- description
- source location
- target provider list after provider filtering rules are applied
- generated target paths for each provider
- per-target status:
  - `current`: target exists and matches rendered output
  - `stale`: target exists but differs
  - `missing`: target does not exist
- aggregate counts for sources, providers, targets, current, stale, and missing
- whether output paths are normal home paths or chezmoi source paths

To avoid drift, reuse helpers from `init_skills_handler.py` where practical:

- `_load_skill_xprompts`
- `_get_target_providers`
- `_render_skill_targets`
- `_planned_skill_operation`
- `_all_providers`

If tests make private helper coupling too awkward, extract narrow public helpers inside `init_skills_handler.py`; keep
the behavior byte-identical with the init path.

### Rich List Output

Add `src/sase/skills/cli_list.py`.

The output should be compact and visually polished:

- A summary panel titled `SASE Skills`
  - source count
  - provider count
  - generated target count
  - current/stale/missing counts
  - deploy mode: home or chezmoi
- A table titled `Skill Sources`
  - skill name, styled as a slash command-like token
  - providers as small colored labels
  - status summary such as `5 current`, `2 missing`, `1 stale`
  - source path
  - one-line description
- A small focused panel for drift when there are stale or missing targets
  - target status
  - provider/skill
  - path
  - keep it capped or naturally concise so common output stays scannable
- A notes panel with only actionable hints:
  - `sase skills init --force` refreshes generated skill files
  - `sase init skills` remains an alias-compatible initializer

Use Rich styling and syntax-aware rendering where it helps:

- `rich.syntax.Syntax` with lexer `markdown` for the description/source preview when showing skill descriptions in table
  cells would otherwise flatten Markdown too much.
- Rich `Text` spans for provider chips and statuses.
- Avoid a noisy wall of generated target paths in the common healthy case.

### Tests

Add tests modeled after `tests/main/test_memory_handler.py` and the existing init-skills tests:

- parser registers `sase skills`, `sase skills list`, and `sase skills init`
- bare `sase skills` defaults to list
- `sase skills init` dispatches through the existing initializer and preserves flags
- `sase init skills` remains accepted
- skills inventory classifies missing/current/stale generated targets
- list rendering includes summary counts, provider names, source path, description, and concise drift hints

Use monkeypatching like the existing init-skills tests to keep filesystem and provider behavior deterministic.

## Verification

After implementation:

1. Run targeted tests for the new command and touched init-skills behavior.
2. Run `just install` because this is an ephemeral SASE workspace.
3. Run `just check` before finishing, per repository instructions.

## Non-Goals

- Do not modify generated skill source files in `src/sase/xprompts/skills/`.
- Do not edit deployed `SKILL.md` files under home or chezmoi.
- Do not change the existing `sase init` onboarding order.
- Do not add provider-specific branches; use provider plugin hooks uniformly.
