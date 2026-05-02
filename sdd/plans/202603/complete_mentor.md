---
create_time: 2026-03-30 17:26:23
status: done
prompt: sdd/prompts/202603/complete_mentor.md
---

# Plan: Replace 'testing' mentor profile with 'complete' mentor profile

## Context

The repo's `sase.yml` currently has two mentor profiles: `gotchas` and `testing`. The `testing` profile focuses on test
quality (coverage, isolation, substance, edge cases). The user wants to replace it with a `complete` profile that shifts
focus from test quality to **functional completeness** and **bug detection** in source code.

## What changes

**File: `sase.yml`** (only file modified)

Remove the entire `testing` profile block (lines 70-99) and replace it with a new `complete` profile containing:

- **profile_name**: `complete`
- **mentor**: single mentor named `complete` with a role describing a completeness and correctness reviewer
- **Focus area 1 — `functional_completeness`**: Checks that the code change fully implements the intended behavior — no
  partial implementations, missing branches, TODO stubs, or incomplete handling of stated requirements.
- **Focus area 2 — `bugs`**: Checks for logic errors, off-by-one mistakes, incorrect assumptions, race conditions,
  null/None handling issues, and other bugs that would cause incorrect behavior at runtime.
- **file_globs**: `src/**/*.py` (same trigger scope as the old `testing` profile)

## Why this design

- Two focus areas (not four) keeps the profile lightweight — completeness and bugs are the two highest-signal categories
  for catching real issues in source code.
- Keeping the same `file_globs` (`src/**/*.py`) means the profile triggers on the same commits as before — no change to
  when mentors run.
- The `gotchas` profile is untouched.

## Verification

- Run `just check` after the edit to confirm YAML validity and that nothing breaks.
