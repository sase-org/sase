---
create_time: 2026-05-02 13:25:00
---

# Plan: Migrate Remaining SDD Artifacts

## Goal

Move the remaining legacy SDD artifacts into the canonical directories:

- `sdd/specs/` -> `sdd/prompts/`
- `sdd/plans/` -> `sdd/tales/`
- root `plans/` -> `sdd/tales/`

Then update live references so current code, validation, frontmatter, and repository docs point at `sdd/prompts/` and
`sdd/tales/`. Existing compatibility support for historical `specs` and `plans` references should remain.

## Current State

- Canonical directories already exist and contain many files: `sdd/prompts/` and `sdd/tales/`.
- Legacy `sdd/specs/202605/` still has ten prompt snapshots.
- Legacy `sdd/plans/202605/` still has six ordinary plan files.
- Root `plans/202605/` still has one plan file.
- No same-relative-path collisions exist for `sdd/specs/** -> sdd/prompts/**`.
- No same-relative-path collisions exist for `sdd/plans/** -> sdd/tales/**`.
- One collision exists for root `plans/** -> sdd/tales/**`: `plans/202605/migrate_sdd_tales.md` maps to an existing
  `sdd/tales/202605/migrate_sdd_tales.md`.
- SDD path helpers already treat `prompts` and `tales` as canonical while retaining `specs` and `plans` lookup aliases.

## Migration Policy

1. Use `git mv` for moved artifacts when possible.
2. Do not overwrite an existing destination file. For the root `plans/202605/migrate_sdd_tales.md` collision, preserve
   both artifacts by moving the root file to a distinct tale filename, then update references to that moved root file.
3. Update generated frontmatter links:
   - prompt snapshots use `plan: sdd/tales/...`, `sdd/epics/...`, or `sdd/legends/...`;
   - plan-like artifacts use `prompt: sdd/prompts/...`.
4. Update references only when they describe current canonical SDD locations or the specific files being moved.
5. Keep intentional legacy references in alias code, compatibility tests, and historical prose that explicitly discusses
   old layouts.

## Implementation Steps

1. Reconfirm `git status` and collision checks before editing.
2. Move all files from `sdd/specs/202605/` into `sdd/prompts/202605/`.
3. Move all files from `sdd/plans/202605/` into `sdd/tales/202605/`.
4. Move root `plans/202605/migrate_sdd_tales.md` into `sdd/tales/202605/` under a non-conflicting name.
5. Remove empty legacy directories if they remain.
6. Update exact live references:
   - moved plan frontmatter from `prompt: sdd/specs/...` to `prompt: sdd/prompts/...`;
   - moved prompt frontmatter from `plan: sdd/plans/...` to `plan: sdd/tales/...`;
   - existing canonical `sdd/tales` and `sdd/epics` frontmatter that still links to `sdd/specs/...`;
   - `.prettierignore` entries for removed legacy SDD dirs;
   - references to the root `plans/202605/migrate_sdd_tales.md` file, if any.
7. Review remaining `sdd/specs` and `sdd/plans` matches. Update live canonical references, but leave deliberate
   compatibility and historical migration notes intact.
8. Run focused SDD validation/tests:
   - `sase sdd validate`
   - `pytest tests/test_sdd.py tests/test_sdd_paths.py tests/main/test_sdd_handler.py`
9. Run `just install`, then `just check`, per workspace instructions.

## Non-Goals

- Remove legacy alias support from SDD code.
- Rename `~/.sase/plans`, `SASE_PLAN`, plan approval terminology, bead `plan` tiers, or generic conceptual uses of
  "plans".
- Rewrite old sdd/research/history prose unless it is a live path reference that would mislead current users or tooling.
