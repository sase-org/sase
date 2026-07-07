---
create_time: 2026-07-07 11:55:08
status: done
prompt: sdd/prompts/202607/pr_terminology_rename.md
---
# Replace CL Terminology With PR

## Goal

Replace SASE's Google-specific "CL" terminology with "PR" across the primary `sase` repo and the linked `sase-core`,
`sase-github`, and `sase-telegram` repos.

The end state should be:

- User-facing UI, CLI text, docs, generated prompts, comments, and tests say `PR`, not `CL`.
- New and modified ChangeSpec files write the review URL field as `PR:`.
- Existing project files that still contain `CL:` remain readable during a compatibility window.
- Internal names become accurate: use `pr` / `pr_url` for the stored review URL, `pr_number` for a GitHub PR number, and
  `changespec_name` or `branch_name` for ChangeSpec/branch names that are not actually PR identifiers.

## Current Findings

The rename is cross-cutting. It is not safe to do as a blind text replacement.

- The Python ChangeSpec parser already accepts both `CL:` and `PR:` but stores the value in `ChangeSpec.cl`.
- The Rust core parser also accepts both labels and emits the wire field `cl_or_pr`.
- Writers and update helpers still preserve or emit `CL:` in several paths:
  - ChangeSpec creation accepts `cl_url` and `cl_label`, defaulting to `CL`.
  - status-state field updates preserve the existing `CL:` label instead of normalizing to `PR:`.
  - deltas and commit utilities look for `CL:` while deciding insertion order.
- The GitHub plugin already treats the review object as a PR, but still has `cl_url` parameters and messages such as
  `ChangeSpec CL field`.
- The Telegram repo appears to have only one visible docstring occurrence.
- The primary repo has a large historical `sdd/` footprint plus protected memory files. Root agent instruction files
  mirror memory content. Memory edits need explicit user approval.

## Scope Policy

Update these categories by default:

- Active code, tests, fixtures, schemas, xprompts, and product docs in all four repos.
- Root agent instruction files generated from current repo memory, if the matching source memory is also approved for
  update.
- `sdd/` markdown where the wording is product terminology rather than an immutable quoted artifact.

Handle these categories deliberately:

- `memory/*.md`: do not edit until Bryan explicitly approves memory edits.
- `sdd/beads/issues.jsonl`: treat as historical issue-log data. Leave unchanged unless Bryan confirms he wants the
  historical issue log rewritten too.
- Legacy compatibility code/tests may retain tiny, explicitly named references to the old `CL:` label so older project
  files still parse. If the requirement becomes literal zero `CL` bytes in source, that would require dropping legacy
  `CL:` support and is not recommended.

## Implementation Plan

### 1. Establish terminology and compatibility constants

Add a small central compatibility layer for ChangeSpec review field labels:

- Primary label: `PR`.
- Legacy accepted label: `CL`.
- Parser behavior: accept both `PR:` and legacy `CL:`.
- Writer behavior: always write `PR:` for new or updated review URL fields.
- Update behavior: when an existing `CL:` line is touched, rewrite it as `PR:`.

Use this central helper everywhere instead of scattering `("CL:", "PR:")` checks.

### 2. Rename core data model and wire shape

In `sase-core`:

- Rename `ChangeSpecWire.cl_or_pr` to a PR-oriented field, preferably `pr_url`.
- Bump the ChangeSpec wire schema version.
- Add serde/PyO3 compatibility for the previous `cl_or_pr` key during deserialization or dict conversion.
- Update Rust parser internals from `cl` to `pr_url` where they represent the review URL.
- Update Rust tests, golden corpus expectations, README wording, and Python binding parity tests.

In the primary `sase` repo:

- Rename `ChangeSpec.cl` to `ChangeSpec.pr_url` or `ChangeSpec.pr`.
- Update wire conversion in both directions.
- Keep a short-lived compatibility alias only if needed for linked plugins during the same rollout; remove it once all
  four repos are updated in the same change set.

### 3. Rename Python APIs and active code

Update active Python modules in the primary repo:

- `cl_url` -> `pr_url`.
- `cl_number` -> `pr_number`.
- `cl_label` / `get_change_label` -> PR-oriented naming, or remove the label abstraction if every provider now writes
  `PR`.
- `cl_name` only when it truly means a PR name. Otherwise rename it to `changespec_name`, `branch_name`, or `change_ref`
  based on local semantics.
- File/module names such as `cl_handler.py`, `cl_status.py`, `rename_cl_modal.py`, and
  `sase_chop_cl_submitted_checks.py` should be renamed if they are part of active code, with imports and tests updated.

Avoid turning every `cl_name` into `pr_name`: much of that variable family actually names a ChangeSpec/branch, not the
GitHub PR object.

### 4. Normalize ChangeSpec writing and migration behavior

Update all ChangeSpec writers and mutators so they produce `PR:`:

- ChangeSpec creation.
- status-state review URL updates/resets.
- commit/rewind/accept helpers that insert fields near the review URL field.
- archive/revert/mail/sync flows that mention removing or requiring the old field.

Add or update tests for:

- Reading legacy `CL:` still works.
- Reading current `PR:` works.
- Updating a legacy `CL:` line rewrites it as `PR:`.
- New ChangeSpecs use `PR:`.
- Missing PR URL handling still works when the field is absent.

### 5. Update linked plugin repos

In `sase-github`:

- Rename hook parameters and helpers from `cl_url` / `changespec.cl` to the new PR URL API.
- Update messages, comments, xprompts, and tests to say `PR`.
- Keep GitHub-specific `pr_number` terminology where appropriate.

In `sase-telegram`:

- Update the visible formatter docstring and any tests if present.

Coordinate these changes with the primary repo's plugin hook signatures so all linked repos remain import-compatible.

### 6. Update user-facing text, docs, tests, and snapshots

Update active documentation and tests in the primary repo:

- `docs/change_spec.md`, `docs/workspace.md`, `docs/vcs.md`, `docs/ace.md`, `docs/xprompt.md`, `docs/cli.md`,
  `docs/configuration.md`, blog docs, README, schemas, xprompt skills, and onboarding/quickstart text.
- TUI labels and help text: `CL list`, `CL row`, `project or CL`, `CL grouping`, `CL Number`, `CL Name`, etc.
- Test fixtures and assertions containing `CL:` or visible `CL` text.
- Visual snapshot assertions and PNG goldens if rendered onboarding/help text changes.

Use `PR` for the review object and `ChangeSpec` for the SASE record. Prefer `PR branch` or `ChangeSpec branch` only when
the text is specifically about a branch/ref rather than the review object.

### 7. Historical and protected-file pass

After active code and docs are green:

- Run a final repo-wide scan in all four repos for `CL`, `CL/PR`, `cl_url`, `cl_or_pr`, and misleading lowercase
  identifier names.
- Update `sdd/` markdown occurrences that describe current SASE behavior.
- Ask Bryan before editing `memory/glossary.md` or any other memory file. If approved, update memory and then update the
  root agent instruction files that mirror it.
- Leave `sdd/beads/issues.jsonl` unchanged unless Bryan explicitly wants historical bead issue text rewritten.

### 8. Verification

Run checks in dependency order:

1. `sase-core`: `cargo fmt --all --check`, `cargo test --workspace`, and any binding/parity tests affected by the wire
   schema change.
2. Primary `sase`: `just install` first, then `just check`. If visual text changed, run or update the dedicated visual
   snapshot suite as needed.
3. `sase-github`: `just install`, then `just check`.
4. `sase-telegram`: `just install`, then `just check`.

Finish with repo-wide scans in all four repos. Expected remaining matches should be limited to explicitly named legacy
compatibility tests/constants and any protected historical files Bryan chose not to rewrite.

## Risks

- Renaming the Rust/Python wire field is a schema/API change. Mitigate with a schema bump and dual-read compatibility.
- Renaming `ChangeSpec.cl` touches many modules and plugins. Keep the compatibility window short and update linked repos
  in the same rollout.
- A blind `cl_name` rename would create wrong terminology. Many `cl_name` values are actually ChangeSpec names or branch
  names.
- Editing memory files without approval would violate repo instructions. Treat them as a separate approval point.
- Updating visual TUI text may require snapshot refreshes.
