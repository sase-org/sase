---
type: reference
parent: AGENTS.md
description: |-
  If you changed any file tracked by git in the sase repo (excluding file changes in the separate repos contained in the
  sase/repos/ directory), you MUST read this note before you finish your turn.
---

# Linting And Testing

```bash
just install       # Install in editable mode with dev deps
just fmt           # Auto-format Python + Markdown
just lint          # Every whole-repo lint gate (ruff, mypy, symvision, toobig, ...)
just check         # Agent default: whole-repo lint gates + a diff-scoped
                   # test lane that never queues behind another agent's run
just check-full    # Exhaustive verification: every lint gate + the full
                   # test suite + local TUI screenshot update; run before
                   # landing. CI does not run this recipe.
just test          # Fast parallel pytest run (excludes PNG visual snapshots)
just test-cov      # pytest with coverage + 50% gate (used by CI); also
                   # excludes the visual snapshot suite
just fix-tui-screenshots  # Capture, compare, and apply ACE/pager PNG goldens
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

Run `just check-full` instead — every lint gate plus the full test suite, then a local
TUI screenshot update that can modify goldens — before landing an epic's combined tree,
when the change touches the broadening set, or any time `just check`'s scoped run
escalated or reported an unusual selection.

`just check-full` routinely outruns a single agent turn, so run it **only** through your
`/sase_monitor` skill, never inline, using the `TESTING` / `TESTED` status pair.
`just check` may be run inline, but hand it to a monitor the same way whenever it is
taking a long time. [[decisions/two-speed-verification]] has the host capacity
measurements that make this rule non-negotiable.

Before handing `just check` or `just check-full` to a verify monitor, run `just fix`
inline first (or at minimum `just fmt`); it takes seconds and prevents common avoidable
formatting and keep-sorted monitor failures.

**IMPORTANT**: SASE agents run from ephemeral `sase_<N>` workspace clones that each own
an isolated virtualenv, so you MAY need to run `just install` before `just check` — this
workspace may have sat unused while pinned dependencies changed.

## Gate-Specific Help

[[symvision.md]] covers the `symvision` unused/misused-symbol gate, whose failures are
the ones least often fixed correctly by deleting the reported symbol.

## PNG Snapshot Tests

`just check` does not run TUI PNG snapshots. When your work changes rendered TUI output
or snapshot coverage, run `just fix-tui-screenshots` explicitly. Use selectors after
`--` for a targeted capture; a full run is required before stale goldens can be removed.
`just test-visual` is the check-only alias (`--check`); `just update-visual-snapshots`
is the update alias. `--sase-update-visual-snapshots` is retired.

Local `just check-full` runs the update form after the other exhaustive gates and can
modify goldens. SASE agent shells export `CI=true`; that flag alone does not block the
update. Detached `sase monitor` commands drop `SASE_AGENT*` identity but set
`SASE_MONITOR_ID`, which is treated the same way so a monitored local update still
writes. CI's dedicated `visual-test` job runs `just fix-tui-screenshots --check` and
never writes goldens. Comparison is exact pixel equality locally and in CI; do not treat
CI as a tolerance lane. The fixtures pin color and the bundled Fira Code / DejaVu / Noto
Emoji renderer stack.

Goldens live under `tests/ace/tui/visual/snapshots/png/` and
`tests/pager/visual/snapshots/png/`. Reports land in unique run directories under
`.pytest_cache/sase-visual/`; `latest-report.json` points at the current run. Inspect
every creation and removal, then each update group (representative plus members), and
expand groups with unexpected differences. Generation is not approval. For a mutating
verification run, the monitor follow-up must inspect that report and the golden diff
before finalization; do not attach a prepared host-completion intent that skips the
inspection.

Full and targeted visual commands may require `/sase_monitor` with `TESTING` / `TESTED`.
Increase the timeout for a full run (the update form also does a bounded verification
pass). Do not run the contention harness or repeat full visual suites routinely.

For live TUI screenshots outside the visual snapshot harness, read
[[tui_screenshot.md]].
