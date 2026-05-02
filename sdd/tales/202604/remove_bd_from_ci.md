---
create_time: 2026-04-24 09:14:06
status: done
prompt: sdd/prompts/202604/remove_bd_from_ci.md
---
# Remove steveyegge/beads (`bd`) install from GitHub Actions CI

## Problem

The `lint` job in `.github/workflows/ci.yml` fails at the "Install Go tools (bd, keep-sorted)" step:

```
go: github.com/steveyegge/beads/cmd/bd@latest (in github.com/steveyegge/beads@v1.0.2):
    The go.mod file for the module providing named packages contains one or
    more replace directives. ...
Error: Process completed with exit code 1.
```

Upstream `steveyegge/beads v1.0.2` now ships a `go.mod` with `replace` directives, which `go install <pkg>@latest`
refuses to honor. That breaks CI.

We no longer depend on the external `bd` binary — this repo has its own `sase bead` / `BeadProject` implementation
(`src/sase/bead/`). The remaining references in source (e.g. `src/sase/sdd/beads.py:22`) are docstring comments that
don't shell out to `bd`. A ripgrep for actual invocations (`which bd`, `bd --`, `bd show`, `bd init`,
`subprocess(...bd...)`) hits only CI yaml lines and doc/plan prose — no runtime code paths.

## Scope

One file change: `.github/workflows/ci.yml`.

## Plan

### 1. Drop the `bd` install + verification from the `lint` job

In `.github/workflows/ci.yml`:

- Remove the `BD_NO_DB: "true"` env entry (job-level env used nowhere else).
- Rename the "Install Go tools (bd, keep-sorted)" step to just install `keep-sorted` (still needed by `just lint` →
  `lint-keep-sorted`, which shells out to the `keep-sorted` binary in `Justfile:78`).
- Delete the entire "Verify bd installation" step (the `which bd` / `bd --version` / `bd show sase-0xd` block).
- Bump the cache key (`go-bin-v3-...` → `go-bin-v4-...`) so the cached `~/go/bin` from prior runs (which contains a
  stale `bd` binary) is invalidated and future runs restore a clean cache containing only `keep-sorted`. Without the
  bump, cache-hit paths would still carry `bd` around, though that wouldn't cause failures.

### 2. Out of scope (deliberate non-changes)

- `src/sase/sdd/beads.py`: the docstring at line 22 ("Runs `bd init --skip-hooks`") is stale wording — the function
  actually calls `BeadProject.init(...)`. Leaving this for a separate docs pass; not part of fixing CI.
- `docs/sdd.md`, `docs/beads.md`, `sdd/research/*`, `plans/*`, `specs/*`: historical references to `bd`. Not touched — these
  documents record past state and aren't consulted at runtime.
- `publish.yml`: does not install `bd`, no change needed.

## Validation

- `just check` locally to confirm nothing regresses (lint still passes via `keep-sorted`).
- Push the branch and confirm the `lint` job reaches and passes `just lint` / `just pyvision` / `just pylimit` without
  the `bd` step.

## Risk

Very low. `bd` is never executed by application code or tests; the only caller was the removed CI verification step
itself.
