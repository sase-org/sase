---
create_time: 2026-06-29 10:02:52
status: done
prompt: sdd/prompts/202606/pyvision_stale_github_alias_pragmas_1.md
---
# Plan: Fix cross-repo CI failures from the project display-name migration

## Problem

Two GitHub Actions pipelines are red, and they share a single root cause.

### Failure A — `sase` repo (the reported error)

`just lint` (the `_lint-pyvision` recipe) fails:

```
Error: pyvision pragma in src/sase/project_aliases.py:243: external repository 'https://github.com/sase-org/sase-github.git' does not reference symbol 'allocate_project_alias'
Error: pyvision pragma in src/sase/project_aliases.py:479: external repository 'https://github.com/sase-org/sase-github.git' does not reference symbol 'ensure_project_alias_locked'
```

### Failure B — `sase-github` repo (the "related" failure)

`sase-github`'s `lint` job (`mypy`) and `test` job fail because `src/sase_github/workspace_plugin.py` now imports

```python
from sase.project_aliases import allocate_project_name, ensure_project_name_locked
```

but its CI pins the `sase` dependency to an old tag that does not contain those functions (details below).

## Root Cause

A **"project display names" feature was split across the two repos but never sequenced or released atomically.** The
work introduced a new `_name` (display-name) family of functions intended to supersede the older auto-allocation
`_alias` family for repo-ref naming:

| Old (`_alias`) — auto-allocation pair | New (`_name`) — display-name pair |
| ------------------------------------- | --------------------------------- |
| `allocate_project_alias`              | `allocate_project_name`           |
| `ensure_project_alias_locked`         | `ensure_project_name_locked`      |

What landed where:

- **`sase` master**, commit `1cbe79f91 feat: support project display names`: _added_ the `_name` functions
  (`allocate_project_name`, `ensure_project_name_locked`, `set_project_name_locked`) but **left the now-superseded
  `_alias` pair in place**, including their `# pyvision: https://github.com/sase-org/sase-github.git` pragmas. This
  commit is the current `HEAD` and is **unreleased** — `git tag --contains 1cbe79f91` is empty; it is not in any tag,
  not even the latest (`v0.5.0`).
- **`sase-github` master**, commit `65ddc1d feat: write project display names for repo refs`: _migrated_
  `workspace_plugin.py` from the `_alias` pair to the `_name` pair (diff shows
  `allocate_project_alias → allocate_project_name` and `ensure_project_alias_locked → ensure_project_name_locked`).

Each side's CI validates against the _other_ side, so the migration broke both:

- **Failure A mechanism.** A URI pragma asserts that the named external repo really consumes the symbol, and pyvision
  verifies the claim against `sase-github`'s **live `master`** (it prefers a local sibling checkout matching the origin,
  else falls back to a shallow `git clone` of the remote). Once `sase-github` migrated away (`65ddc1d`), its `master` no
  longer references `allocate_project_alias`/`ensure_project_alias_locked`, so the two pragmas in `project_aliases.py`
  became stale. The `sase` repo's CI started failing **even though no `sase` code changed in the failing run** — the
  trigger was the other repo's merge. The two symbols now have **no non-test consumer anywhere** (verified: in `sase`
  they are referenced only by `tests/test_project_alias_services.py`, `__all__`, and their own defs; in `sase-github`,
  `git grep` finds zero references).
- **Failure B mechanism.** `sase-github`'s `ci.yml` checks out `sase-org/sase` at `SASE_CORE_REF: v0.1.3` into
  `.ci/sase` and installs it editable (`SASE_CORE_PATH=.ci/sase`). Its `Justfile` `lint` runs `mypy`, and `test` runs
  `pytest`. But `v0.1.3` (and every existing tag through `v0.5.0`) contains only the `_alias` pair, **not** the `_name`
  pair — the `_name` functions exist only on unreleased `sase` master. So `mypy` reports the imports as missing
  attributes and the tests fail at import time. The pin to `v0.1.3` is badly stale: `sase` is already at `v0.5.0`.

In short: the display-name migration completed on `sase-github` but the `sase` side was left half-finished (dead
`_alias` code with stale pragmas) **and** the new functions `sase-github` now depends on were never shipped in a release
that `sase-github`'s CI consumes.

## Fix Approach

Complete the migration cleanly on both sides. This is one logical change with an ordering dependency.

### Part 1 — `sase` repo: delete the orphaned `_alias` pair (fixes Failure A)

The two symbols are dead code, so the correct fix is deletion, not pragma editing. Removing only the pragmas would leave
pyvision flagging both as unused public symbols (their only references are tests). Re-pointing the pragmas at a doc/tale
file would be whitelisting genuinely dead code, contradicting the linter's purpose and `tools/AGENTS.md` ("delete the
symbol, make it private and call it from a non-test path, or use a non-test pragma target").

Changes:

1. **`src/sase/project_aliases.py`**
   - Delete the `allocate_project_alias` definition and its `# pyvision: …sase-github.git` pragma comment.
   - Delete the `ensure_project_alias_locked` definition and its `# pyvision: …sase-github.git` pragma comment.
   - Remove `"allocate_project_alias"` and `"ensure_project_alias_locked"` from `__all__`.
2. **`tests/test_project_alias_services.py`**
   - Remove both names from the `from sase.project_aliases import (...)` block.
   - Delete the eight `test_allocate_project_alias_*` tests and the three `test_ensure_project_alias_locked_*` tests.

Safety checks (verified; restate during implementation):

- The alias _mutation_ helpers (`add/remove/clear/set_project_aliases_locked`) stay — they are in active CLI/TUI use
  (`src/sase/main/project_handler.py`, `src/sase/ace/tui/modals/...`). Only the auto-allocation pair and the idempotent
  ensure helper were orphaned by the migration.
- Private helpers remain used after deletion, so pyvision's "private symbol must be used in its file" guard still
  passes: `_occupied_project_refs` is still used by `allocate_project_name`; `_mutate_project_aliases_locked` is still
  used by the kept `set/add/remove_project_alias_locked` helpers.
- The kept `_name` pair already has a valid non-test consumer (`sase-github`) and its existing
  `sdd/tales/202606/project_name_field.md` doc pragma is unaffected — out of scope here.

### Part 2 — Ship a `sase` release containing the `_name` functions (prerequisite for Part 3)

The functions `sase-github` depends on are unreleased. They must be cut into a tag that `sase-github`'s CI can consume.
Recommended ordering so the release is green and complete:

1. Land Part 1 on `sase` master → `sase` CI (pyvision) is green again.
2. Cut a new `sase` release from that green master (next minor, e.g. `v0.6.0`, via the repo's normal release flow). The
   tag then contains both the new `_name` functions and the Part 1 cleanup.

This is a release-coordination step that the user/maintainer drives (the repos use a release-please-style flow); it is
called out here as an explicit dependency for Part 3, not something to force out-of-band.

### Part 3 — `sase-github` repo: bump the pinned `sase` ref (fixes Failure B)

In `sase-github`'s `.github/workflows/ci.yml`, change `env.SASE_CORE_REF` from `v0.1.3` to the new release tag from Part
2 (e.g. `v0.6.0`) — a tag that contains commit `1cbe79f91`. After this, `mypy` and the test suite resolve the `_name`
imports and `sase-github` CI goes green. No `sase-github` source changes are needed; its display-name migration is the
intended behavior.

> Interim fallback (only if a release cannot be cut promptly): set `SASE_CORE_REF: master`. This unblocks immediately
> but sacrifices reproducibility and couples `sase-github` CI to `sase` HEAD; the versioned-tag pin is preferred and the
> repo clearly intends pinned tags.

## Validation

- **`sase`:** `just install` (ephemeral workspace may have stale deps) then `just check`; confirm `_lint-pyvision`
  passes and `git grep allocate_project_alias\|ensure_project_alias_locked` returns only this plan / SDD docs.
- **`sase-github`** (after Parts 2–3, via `sase workspace open -p sase-github`): `just check` against the bumped
  `.ci/sase` checkout; confirm `mypy` and tests resolve `allocate_project_name`/`ensure_project_name_locked`.

## Risks & Decision Points

- **Deletion vs. preservation of the `_alias` pair.** A scope note in
  `sdd/tales/202606/project_alias_stray_dir_conflict.md` once described `allocate_project_alias` as "intentionally left
  as-is," but that was a non-goal of a _different_ change, not a directive to keep it past its last consumer. With
  `sase-github` migrated and no other consumer, deletion is the conventional fix. If the maintainer wants to retain
  alias auto-allocation as forward-looking public API, the alternative is to add a real non-test consumer; there is none
  today.
- **Release timing.** Failure A is fixed by Part 1 alone and needs no release. Failure B _requires_ a `sase` release (or
  the `master` fallback) — it cannot be fixed by editing `sase-github` source. Bumping `SASE_CORE_REF` to an existing
  tag like `v0.5.0` will **not** work, because no released tag yet contains the `_name` functions.

## Non-Goals

- No changes to `sase-github` _source_; only its CI `SASE_CORE_REF` pin.
- No changes to the alias _mutation_ CLI/TUI helpers or to the `_name` helpers' existing pragmas.
- No pyvision tool changes — the linter is behaving correctly and is vendored (must not be edited here regardless).
