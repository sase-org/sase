---
create_time: 2026-04-15 16:42:30
status: done
prompt: sdd/prompts/202604/profile_output_path.md
---

# Plan: Accept optional file path for `sase ace --profile`

## Context

Currently `sase ace --profile` is a `store_true` boolean flag. When set, it profiles the TUI session and writes the
results to `ace_profile_<timestamp>.txt` in the current working directory. The user wants to:

1. Accept an **optional file path** so `--profile` can be used as `--profile`, `--profile /tmp/out.txt`, or
   `-p /tmp/out.txt`.
2. When no path is given, default to writing the file in `$SASE_TMPDIR` (via the existing `get_sase_tmpdir()` helper in
   `src/sase/core/paths.py`). If `$SASE_TMPDIR` is not set, fall back to the current directory (preserving today's
   behavior).

## Changes

### 1. Change `--profile` from `store_true` to `nargs="?"` with a `const` sentinel

**File**: `src/sase/main/parser_ace.py`

Replace the current `action="store_true"` definition with:

```python
ace_parser.add_argument(
    "-p",
    "--profile",
    nargs="?",
    const="",
    default=None,
    help="Profile the TUI session with pyinstrument. Optionally provide a file path "
    "for the output (default: $SASE_TMPDIR/ace_profile_<timestamp>.txt)",
)
```

- `default=None` — flag not supplied at all.
- `const=""` — flag supplied without an argument (`sase ace --profile`). The empty string signals "use the default
  path".
- Any other value — flag supplied with an explicit path (`sase ace --profile /tmp/out.txt`).

### 2. Update the handler to resolve the output path

**File**: `src/sase/main/ace_handler.py`

Replace the `if getattr(args, "profile", False):` block:

1. Check `args.profile is not None` (flag was supplied).
2. If `args.profile` is the empty string (no explicit path), build the default path:
   - Use `get_sase_tmpdir()` from `sase.core.paths`. If it returns a directory, write there.
   - Otherwise fall back to the current working directory.
   - Filename: `ace_profile_<timestamp>.txt` (same as today).
3. If `args.profile` is a non-empty string, use it as the literal output path. Ensure parent directories exist.
4. Write the profile output and print the path to stderr (unchanged).
