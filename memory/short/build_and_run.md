# Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just test          # Fast parallel pytest run, includes PNG visual snapshots
                   # (cairosvg/Pillow auto-installed via _setup-visual)
just test-cov      # pytest with coverage + 50% gate (used by CI); also runs
                   # the visual snapshot suite
```

IMPORTANT: If you made file changes in this repo (the sase repo), make sure to run the `just check` command before
terminating / replying to the user. EXCEPTION: If the only file changes you've made are bead changes (i.e. changes to
files in the sdd/beads/ directory), then there is no point in running the `just check` command.
