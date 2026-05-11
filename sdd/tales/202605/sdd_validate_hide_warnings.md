---
create_time: 2026-05-11 18:36:13
status: done
prompt: sdd/prompts/202605/sdd_validate_hide_warnings.md
---
# Plan: Hide `sase sdd validate` warning lines by default

## Problem

`sase sdd validate` currently prints every issue regardless of severity. Warnings (unpaired historical files, downgraded
legacy errors, etc.) clutter the output even on the happy path where validation succeeds —
`validation passed: N files, M warnings` is followed by a wall of `warning: ...` lines. Users have to scroll past noise
to confirm there are no actionable errors.

We want the default text output to surface **only errors**, with warnings hidden behind an opt-in flag. JSON output
(`-j`) should continue to emit the full set — it's the machine-readable contract.

## Goals

1. Default text output for `sase sdd validate` shows the summary line + error lines only. No `warning:` lines.
2. A new flag (`--show-warnings`, short `-W`) reveals the warning lines.
3. The summary line still includes the warning count, so a user noticing `N warnings` knows to re-run with
   `--show-warnings`.
4. When warnings exist but are hidden, the summary line nudges the user (e.g. appends
   `(use --show-warnings to display)`).
5. JSON mode (`-j`) is unchanged — `warnings` array always populated.
6. `--strict` mode is unaffected (it converts warnings → errors _before_ filtering, so they will print as errors).

## Non-goals

- Re-classifying any existing issue. The error/warning split in `src/sase/sdd/links.py` stays as-is.
- Touching `sase sdd repair-links` output, which always emits JSON.
- Changing exit codes.

## Design

### Flag

Add to the `validate` subparser in `src/sase/main/parser_sdd.py:22-37`:

```python
validate_parser.add_argument(
    "-W", "--show-warnings", action="store_true",
    help="Show warning-severity issues (hidden by default)",
)
```

Short flag `-W` chosen because `-w` is taken by `repair-links --write` (not the same subcommand, but consistent
capital-W = "warnings" reads well and avoids operator confusion).

### Handler & print function

In `src/sase/main/sdd_handler.py`:

- `_handle_validate` passes `args.show_warnings` into `_print_validation`.
- `_print_validation(validation, *, show_warnings: bool)` iterates issues and skips `severity == "warning"` unless
  `show_warnings` is true.
- The summary line gains a single trailing hint segment when warnings exist and `show_warnings` is false:
  - `SDD validation passed: 42 files, 3 warnings (use --show-warnings to display)`
  - When `show_warnings=True` or `warnings == 0`, no hint.
  - On failure, same treatment: `... 2 errors, 3 warnings (use --show-warnings ...)`.

### Interaction with `--quiet`

`--quiet` currently suppresses the success summary entirely; warnings are already implicitly hidden in that path because
nothing prints when `validation.ok`. On failure, `--quiet` still prints the summary + issues — under the new behavior it
will print the summary + errors only (no warnings), which matches user intent. `--quiet --show-warnings` together =
print warnings on failure.

### JSON mode

No change. `--json` ignores `--show-warnings` (still always emits the full payload). Document this in the
`--show-warnings` help text only if it adds clarity; otherwise leave unstated since `-j` is the obvious "I want
everything" channel.

## Files touched

- `src/sase/main/parser_sdd.py` — add the flag.
- `src/sase/main/sdd_handler.py` — filter warnings in `_print_validation`, thread `show_warnings` through
  `_handle_validate`, append hint.
- `tests/main/test_sdd_handler.py` —
  - Update `_args(...)` default to include `show_warnings=False`.
  - Update the `parser.parse_args([...])` assertion in `test_parser_registers_sdd_subcommands` to cover `-W`.
  - Update `test_validate_allows_default_unpaired_warnings` — it currently asserts `"unpaired-file" in out`; flip it to
    assert the warning line is **absent** and the `(use --show-warnings ...)` hint **is** present.
  - Add a new test `test_validate_show_warnings_flag_displays_warning_lines` asserting that with `show_warnings=True`
    the warning line returns and the hint disappears.
  - Audit other validate tests — most pass via JSON or assert error codes, so they should be unaffected, but verify by
    running the suite.

## Risks / open questions

- **CI or scripts that grep `warning:` from stdout** — none expected in this repo (warnings live in `tests/` and `sdd/`
  markdown only), but worth a quick `grep -r "warning:" --include="*.py"` before merging.
- **Hint phrasing** — `(use --show-warnings to display)` is the current proposal; happy to drop it entirely if it feels
  noisy. Leaning toward keeping because the warning _count_ on the summary line is otherwise a dead-end signal.

## Verification

1. `just check` (lint + mypy + tests).
2. Manual smoke: run `sase sdd validate` against this repo's own `sdd/` tree, confirm default output shows the summary
   only, then re-run with `-W` to confirm warning lines reappear.
