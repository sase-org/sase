---
create_time: 2026-04-10 22:53:49
status: done
---

# Plan: Prevent #pr sessions from downgrading to direct commits

## Goal

Ensure agents launched with embedded `#pr` workflow cannot accidentally commit directly (e.g., `--type commit`) when the
stop hook requests `create_pull_request`.

## Root Cause

In `#pr` runs, `SASE_COMMIT_METHOD=create_pull_request` is set in the environment and correctly observed by
`sase_commit_stop_hook`. However, `sase commit` currently resolves method as:

- CLI `--type` first
- then `$SASE_COMMIT_METHOD`
- then default `create_commit`

So an explicit `--type commit` overrides the `#pr` method and dispatches direct commits to the current branch.

## Design

1. Add commit-method guardrails in commit CLI handler:

- Canonicalize both CLI and env methods via aliases.
- If both are set and conflict, fail fast with a clear error.
- Allow explicit opt-out only via an escape hatch env var (for advanced/manual usage):
  `SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1`.

2. Preserve existing behavior in non-conflicting cases:

- No env method: CLI or default behavior unchanged.
- Env method only: env method used.
- CLI method only: CLI method used.

3. Strengthen stop-hook guidance text:

- When hook emits commit instructions, explicitly tell agent to follow the stated method and avoid conflicting `--type`
  values.

4. Add/adjust tests:

- `tests/test_commit_cli.py`
  - Conflicting CLI/env methods should exit with code 1 by default.
  - Conflicting methods should be allowed when `SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1`.
  - Existing method alias and default-path coverage should remain intact.
- `tests/test_commit_stop_hook.py`
  - Verify instruction text includes method-following/anti-override guidance.

## Validation

- Run `just install` (workspace freshness requirement).
- Run targeted tests for changed areas first.
- Run required full repo validation: `just check`.

## Expected Outcome

`#pr` sessions remain PR-safe even if an agent attempts `--type commit`; accidental direct commits to main/master are
blocked at command resolution time with an actionable error.
