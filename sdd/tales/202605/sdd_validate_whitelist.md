---
create_time: 2026-05-02 13:10:09
status: done
prompt: sdd/prompts/202605/sdd_validate_whitelist.md
---
# Plan: SDD Validate Legacy Error Whitelist

## Goal

Make `sase sdd validate` usable in CI while preserving strict validation for all new SDD files. The command should
support a deliberately tiny, source-controlled whitelist of known legacy files whose validation errors are allowed. This
whitelist is a quarantine for historical invalid artifacts only. It must be clearly documented that no new file should
ever be added.

## Current Findings

- `sase sdd validate` is implemented in `src/sase/sdd/links.py` and invoked by `src/sase/main/sdd_handler.py`.
- The CLI exits nonzero when `_SddValidation.ok` sees any error issue.
- Current SDD validation failures are missing or reverse-missing frontmatter links between `sdd/specs/202605/*` and
  `sdd/plans`, `sdd/epics`, or `sdd/tales` counterparts.
- `sase sdd repair-links -p sdd` can infer and backfill most of the reported errors mechanically.
- `specs/` is treated as prompt-like and legacy `plans/` is treated as tale-like, so any whitelist should key by the
  validator's normalized relative paths, not by absolute paths or raw frontmatter link text.

## Design

1. Add an explicit validation allowlist constant in `src/sase/sdd/links.py`.
   - Store exact validator-relative paths such as `specs/YYYYMM/name.md`.
   - Name it as an error allowlist or legacy invalid file allowlist.
   - Put a direct comment above it: this is closed, historical-only, and new files must not be added.

2. Apply the allowlist inside `validate_sdd_tree` after issue collection.
   - Only downgrade or suppress `severity == "error"` issues whose `issue.path` is in the allowlist.
   - Do not suppress warnings; warnings already do not fail non-strict validation.
   - Preserve JSON and text output consistency by returning a validation object whose `errors` no longer include allowed
     legacy errors.
   - Prefer converting allowed errors into warnings with a distinct code suffix/message rather than hiding them
     completely, so users can still see historical debt without breaking CI.

3. Repair all mechanically inferable current files before using the allowlist.
   - Use `sase sdd repair-links -p sdd -w` or equivalent frontmatter updates for files with unambiguous counterparts.
   - Re-run validation and add only remaining error-producing file paths to the allowlist.
   - If repair removes all current errors, leave the allowlist empty but present and documented so CI has the feature
     without normalizing an exception.

4. Add tests in `tests/main/test_sdd_handler.py` or a focused SDD links test.
   - Parser behavior should remain unchanged unless a new CLI flag is introduced. Prefer no flag: the repo-level
     allowlist is part of the command's default policy.
   - Cover that a broken non-allowlisted file still fails.
   - Cover that an allowlisted file's error does not make validation fail and is reported as a warning.
   - Cover JSON output reflects the downgraded issue as a warning, not an error.

5. Verify.
   - Run the focused SDD tests.
   - Run `.venv/bin/sase sdd validate` to confirm CI would pass.
   - Run `just install` if needed, then `just check` as required by repo memory.

## Risks

- A broad allowlist could hide real regressions. The implementation must use exact relative file paths only.
- Suppressing errors completely would make legacy debt invisible. Downgrading to warning keeps it visible while
  unblocking CI.
- Mechanical repair rewrites frontmatter and may normalize YAML values. Keep edits limited to the affected SDD files.
