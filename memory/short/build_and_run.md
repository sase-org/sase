# Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just test          # Fast parallel pytest run (no coverage)
just test-cov      # pytest with coverage + 50% gate (used by just check / CI)
```

IMPORTANT: If you made file changes in this repo (the sase repo), make sure to run the `just check` command before
terminating / replying to the user.
