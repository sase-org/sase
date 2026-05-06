# Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just test          # Fast parallel pytest run (no coverage)
just test-cov      # pytest with coverage + 50% gate (used by CI)
```

IMPORTANT: If you made file changes in this repo (the sase repo), make sure to run the `just check` command before
terminating / replying to the user. EXCEPTION: If the only file changes you've made are bead changes (i.e. changes to
files in the sdd/beads/ directory), then there is no point in running the `just check` command.

## Editor-integration completion commands

Thin JSON helpers used by sase-nvim (and other editor plugins) to drive `<ctrl+t>` completion without reimplementing TUI
logic:

- `sase file-history list` — JSON array of recently-referenced paths (most recent first).
- `sase file-history delete -p <path>` — remove one entry from `~/.sase/file_reference_history.json`.
- `sase file list [-p PATH] [-t TOKEN]` — JSON array of `{display, insertion, is_dir, name}` candidates rooted at
  `--path` (default CWD), filtered by partial `--token`.
