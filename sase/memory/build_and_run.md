---
type: short
parent: AGENTS.md
---

# Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just check         # Agent default: whole-repo lint gates + a diff-scoped
                   # test lane that never queues behind another agent's run
just check-full    # Exhaustive verification: every lint gate + the full
                   # test suite; run before landing and in CI
just test          # Fast parallel pytest run (excludes PNG visual snapshots)
just test-cov      # pytest with coverage + 50% gate (used by CI); also
                   # excludes the visual snapshot suite
```

## IMPORTANT: Two-Speed Verification — Run `just check` if you Made File Changes

If you made file changes in this repo (the sase repo), make sure to run the `just check`
command before terminating / replying to the user. See the below subsection for
exceptions to this rule.

`just check` runs every whole-repo lint gate plus a diff-scoped test lane
(`just test-scoped`) that selects tests via a static import-graph closure. The scoped
run is serial unless a middle gear wins it a small, bounded suite-gate lease, and it
never queues behind other agents' runs either way. Selection is a heuristic backstopped
by CI: `tools/select_tests --explain` shows why a test was or was not chosen, and
`just selection-health` shows whether the heuristic has ever been wrong.

Run `just check-full` instead — every lint gate plus the full test suite — before
landing an epic's combined tree, when the change touches the broadening set, or any time
`just check`'s scoped run escalated or reported an unusual selection.

**IMPORTANT**: One consequence of sase's ephemeral workspace directories (see the
sase.md file in this directory) is that you need to run `just install` before running
other commands like `just check` (since it is possible we haven't used this workspace
directory in a long time and package dependencies may have changed).

## PNG Snapshot Tests

Run `just test-visual` for the dedicated ACE PNG snapshot suite; goldens live in
`tests/ace/tui/visual/snapshots/png/`. On failures, inspect `.pytest_cache/sase-visual/`
for actual/expected/diff/source artifacts, and use `--sase-update-visual-snapshots`
to accept intentional visual changes. Local runs use exact pixel equality by default,
while CI allows a small ratio-only renderer drift tolerance; the visual fixtures pin
color and fontconfig/Fira Code to keep rendering deterministic.
