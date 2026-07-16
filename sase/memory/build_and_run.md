---
type: short
parent: AGENTS.md
---

# Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just test          # Fast parallel pytest run, includes PNG visual snapshots
                   # (resvg/Pillow auto-installed via _setup-visual)
just test-cov      # pytest with coverage + 50% gate (used by CI); also runs
                   # the visual snapshot suite
```

## IMPORTANT: You MUST Run `just check` if you Made File Changes

If you made file changes in this repo (the sase repo), make sure to run the `just check` command before terminating /
replying to the user. See the below subsection for exceptions to this rule.

**IMPORTANT**: One consequence of sase's ephemeral workspace directories (see the sase.md file in this directory) is
that you need to run `just install` before running other commands like `just check` (since it is possible we haven't
used this workspace directory in a long time and package dependencies may have changed).

### Exceptions

There is no point in running the `just check` command if the only file changes you made fall into one of the following
categories:

- Bead changes (i.e. changes to files in the sdd/beads/ directory).
- Changes to (or the creation of new) markdown files or images in the sdd/research/ directory.

## PNG Snapshot Tests

Run `just test-visual` for the dedicated ACE PNG snapshot suite; goldens live in `tests/ace/tui/visual/snapshots/png/`.
On failures, inspect `.pytest_cache/sase-visual/` for actual/expected/diff/source artifacts, and use
`--sase-update-visual-snapshots` only to accept intentional visual changes. Local runs use exact pixel equality by
default, while CI allows a small ratio-only renderer drift tolerance; the visual fixtures pin color and fontconfig/Fira
Code to keep rendering deterministic.
