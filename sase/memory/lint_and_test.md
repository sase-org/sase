---
type: reference
parent: AGENTS.md
description: |-
  IMPORTANT: if you changed ANY file in the sase repo, you MUST read this note before
  you finish your turn. Verification is not optional here and the lanes are not
  interchangeable: this note covers the `just` command surface, the two-speed rule that
  makes `just check` the agent default and `just check-full` a monitor-only landing
  gate, the `just install` prerequisite for ephemeral workspace clones, and the PNG
  snapshot suite.
---

# Linting And Testing

```bash
just install       # Install in editable mode with dev deps
just fmt           # Auto-format Python + Markdown
just lint          # Every whole-repo lint gate (ruff, mypy, symvision, toobig, ...)
just check         # Agent default: whole-repo lint gates + a diff-scoped
                   # test lane that never queues behind another agent's run
just check-full    # Exhaustive verification: every lint gate + the full
                   # test suite; run before landing and in CI
just test          # Fast parallel pytest run (excludes PNG visual snapshots)
just test-cov      # pytest with coverage + 50% gate (used by CI); also
                   # excludes the visual snapshot suite
```

## Two-Speed Verification: Run `just check` If You Changed Files

If you made file changes in this repo (the sase repo), make sure to run the `just check`
command before terminating / replying to the user.

`just check` runs every whole-repo lint gate plus a diff-scoped test lane
(`just test-scoped`) that selects tests via a static import-graph closure. The scoped
run is serial unless a middle gear wins it a small, bounded suite-gate lease, and it
never queues behind other agents' runs either way. Selection is a heuristic backstopped
by CI: `tools/select_tests --explain` shows why a test was or was not chosen, and
`just selection-health` shows whether the heuristic has ever been wrong.

Run `just check-full` instead — every lint gate plus the full test suite — before
landing an epic's combined tree, when the change touches the broadening set, or any time
`just check`'s scoped run escalated or reported an unusual selection.

`just check-full` routinely outruns a single agent turn, so run it **only** through your
`/sase_monitor` skill, never inline, using the `TESTING` / `TESTED` status pair.
`just check` may be run inline, but hand it to a monitor the same way whenever it is
taking a long time. `sase memory read decisions:two-speed-verification` has the host
capacity measurements that make this rule non-negotiable.

**IMPORTANT**: SASE agents run from ephemeral `sase_<N>` workspace clones that each own
an isolated virtualenv, so you MAY need to run `just install` before `just check` — this
workspace may have sat unused while pinned dependencies changed.

## Gate-Specific Help

`sase memory read symvision.md` covers the `symvision` unused/misused-symbol gate, whose
failures are the ones least often fixed correctly by deleting the reported symbol.

## PNG Snapshot Tests

Run `just test-visual` for the dedicated ACE PNG snapshot suite; goldens live in
`tests/ace/tui/visual/snapshots/png/`. On failures, inspect `.pytest_cache/sase-visual/`
for actual/expected/diff/source artifacts, and use `--sase-update-visual-snapshots` to
accept intentional visual changes. Local runs use exact pixel equality by default, while
CI allows a small ratio-only renderer drift tolerance; the visual fixtures pin color and
fontconfig/Fira Code to keep rendering deterministic.
