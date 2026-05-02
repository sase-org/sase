---
create_time: 2026-05-02 13:14:39
status: wip
prompt: sdd/prompts/202605/migrate_sdd_specs_plans.md
---
# Plan: Migrate Remaining SDD Specs And Plans

## Goal

Move the remaining version-controlled files from legacy SDD directories to the canonical SDD directories:

- `sdd/specs/` -> `sdd/prompts/`
- `sdd/plans/` -> `sdd/tales/`

Then update repository references so canonical docs, frontmatter, tests, and validation flows point at `sdd/prompts/`
and `sdd/tales/`. Compatibility aliases for old `specs` and `plans` names should stay in place where they are
intentionally supporting historical data.

## Current State

- Canonical destination directories already exist:
  - `sdd/prompts/{YYYYMM}/`
  - `sdd/tales/{YYYYMM}/`
- Legacy source directories still contain May 2026 artifacts:
  - `sdd/specs/202605/`: ten prompt snapshots.
  - `sdd/plans/202605/`: six ordinary plans.
- No same-relative-path collisions were found between:
  - `sdd/specs/**` and `sdd/prompts/**`
  - `sdd/plans/**` and `sdd/tales/**`
- `src/sase/sdd/files.py` already writes new artifacts to `prompts` and `tales`, while retaining lookup aliases for
  `specs` and `plans`.
- `src/sase/sdd/links.py` already lists canonical kinds but still resolves legacy `sdd/plans` links to canonical
  `sdd/tales`; this compatibility should remain.
- Exact legacy path references remain in repository artifacts, notably:
  - `.prettierignore`
  - `sdd/plans/202605/*` frontmatter back-links to `sdd/specs`
  - some existing `sdd/tales/202605/*` frontmatter back-links to `sdd/specs`
  - `tests/main/test_sdd_handler.py` compatibility coverage for `sdd/plans`
  - historical planning/research docs and bead notes that mention older migration steps.

## Migration Policy

1. Use `git mv` for source files so Git tracks the renames.
2. Preserve existing destination files; the read-only collision check found no direct destination conflicts.
3. Update frontmatter links in moved files and existing counterparts:
   - Prompt snapshots should use `plan: sdd/tales/...`, `sdd/epics/...`, or `sdd/legends/...` as appropriate.
   - Plan-like files should use `prompt: sdd/prompts/...`.
4. Update canonical references to `sdd/specs/` and `sdd/plans/` when they describe current SDD locations.
5. Keep compatibility references where they are deliberately testing or documenting legacy resolution behavior:
   - legacy alias constants and tests in SDD lookup/validation code
   - prose that explicitly says old trees may contain `specs` or `plans`
   - historical migration artifacts where changing the text would distort the record
6. Remove empty legacy directories after the moves.

## Implementation Steps

1. Reconfirm the working tree and collision state immediately before editing.
2. Move `sdd/specs/202605/*.md` into `sdd/prompts/202605/`.
3. Move `sdd/plans/202605/*.md` into `sdd/tales/202605/`.
4. Remove empty `sdd/specs/` and `sdd/plans/` directories if Git leaves them behind.
5. Run a targeted reference update:
   - update moved plan frontmatter from `prompt: sdd/specs/...` to `prompt: sdd/prompts/...`
   - update existing canonical SDD plan files that still link back to `sdd/specs/...`
   - update moved prompt frontmatter or prose that points at `sdd/plans/...` to `sdd/tales/...`
   - update `.prettierignore` so it ignores canonical SDD prompt/tale directories and no longer names removed
     `sdd/specs/`
6. Review exact remaining matches for `sdd/specs` and `sdd/plans`:
   - keep intentional compatibility/historical mentions
   - update any remaining live canonical references
7. Run SDD validation/repair checks:
   - run `sase sdd validate` or the equivalent focused tests
   - use `sase sdd repair-links --write` only if unambiguous link repair is needed after review
8. Run focused tests covering SDD paths and validation:
   - `pytest tests/test_sdd.py tests/test_sdd_paths.py tests/main/test_sdd_handler.py`
9. Run `just install` if this workspace needs dependency refresh, then run `just check` before finishing, per repo
   instructions.

## Non-Goals

- Do not remove legacy alias support from SDD code; old references should still resolve.
- Do not rewrite unrelated root `plans/` or `specs/` history unless a reference is clearly a live canonical SDD path.
- Do not alter `~/.sase/plans`, `SASE_PLAN`, ChangeSpec terminology, or generic prose that uses "plan" or "specs" in
  another domain.
