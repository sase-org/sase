---
create_time: 2026-05-14 15:10:24
status: done
prompt: sdd/prompts/202605/config_xprompt_skills_1.md
---
# Plan: Generate Config-Defined XPrompt Skills

## Context

`sase xprompt list` recognizes `sase_gmail` from `config_overlay:sase_athena.yml` with `is_skill: true`, but
`sase init-skills` does not generate a `SKILL.md` for it. The reason is that `handle_init_skills_command` only scans
`src/sase/xprompts/skills/*.md`, parses markdown front matter directly, and never asks the xprompt loader for
config-defined xprompts.

This creates a split-brain behavior:

- XPrompt runtime/catalog paths load built-ins, default config, plugin config, user config, overlays such as
  `sase_athena.yml`, memory, project, and file xprompts.
- `init-skills` only loads packaged markdown files under `xprompts/skills/`.

## Goal

Make `sase init-skills` generate provider `SKILL.md` files for every loaded xprompt whose `skill` field targets the
selected provider(s), including config-defined xprompt skills like `sase_gmail`.

## Non-Goals

- Do not edit generated chezmoi `SKILL.md` files directly.
- Do not change the xprompt runtime/catalog semantics.
- Do not change provider deploy paths or the existing chezmoi deploy flow.
- Do not require `#sase_gmail` to be moved from `sase_athena.yml` into package markdown.

## Proposed Design

1. Refactor `init_skills_handler` around loaded `XPrompt` objects instead of raw package markdown files.
   - Use `load_xprompts_from_internal()` for packaged markdown skills.
   - Use `get_all_xprompts(project=None)` for the full global xprompt set so config overlays participate.
   - Filter to entries with a truthy `skill` field and with providers resolved by `_get_target_providers`.

2. Preserve precedence and avoid duplicates.
   - `get_all_xprompts(project=None)` already applies the runtime xprompt priority rules.
   - Iterate its final values sorted by skill name for deterministic output.
   - This means if a higher-priority config/file xprompt overrides a built-in skill name, `init-skills` follows the same
     winning definition the runtime sees.

3. Render from the `XPrompt` fields.
   - `name` comes from `xp.name`.
   - `description` comes from `xp.description` or an empty string.
   - body comes from `xp.content`.
   - provider-specific Jinja2 context and final frontmatter generation remain unchanged.

4. Improve dry-run accounting.
   - The current dry-run reports only the number of package source files scanned.
   - Change that to report the number of skill source entries considered after filtering to `skill` xprompts, so
     config-defined skills are visible in the count.

5. Add regression tests.
   - A focused `init-skills` test should patch the full xprompt set to include a config-overlay
     `XPrompt(name="sase_gmail", skill=True, ...)` and assert dry-run/writes include the provider target path.
   - A provider-list test should assert `skill: [codex]` only generates for the listed provider and respects
     `--provider`.
   - Existing shipped skill discovery tests should still pass.

6. Verify with targeted tests first, then the broader relevant test files.
   - Run the `tests/main/test_init_skills_*.py` suite.
   - Run xprompt loader/catalog tests touched by the import/precedence path if needed.
   - Optionally run `sase init-skills --dry-run --provider codex` locally to confirm `sase_gmail` appears when the user
     config is present.

## Risks and Mitigations

- `get_all_xprompts()` may include project-local or home file xprompts. Passing `project=None` still auto-detects a
  project today. To keep `init-skills` global and avoid project namespacing, call loader functions in a way that
  disables project detection for this command, or introduce a small helper that merges only global sources needed by
  installable skills.
- Memory-derived xprompts may accidentally declare `skill`. If that is not desired, keep generation to built-ins plus
  config/plugin/file-backed global xprompts and document the source set in code.
- Config-defined skill descriptions can be absent. Existing `_build_output` supports an empty description, so this is
  acceptable unless tests reveal provider tooling rejects it.

## Acceptance Criteria

- `sase init-skills --dry-run --provider codex` includes a path for `sase_gmail/SKILL.md` when `sase_athena.yml` defines
  `sase_gmail` with `skill: true` or `skill: [codex]`.
- Packaged skills continue to render exactly as before.
- Existing provider filters and provider-specific Jinja2 template context still work.
- Targeted tests pass.
