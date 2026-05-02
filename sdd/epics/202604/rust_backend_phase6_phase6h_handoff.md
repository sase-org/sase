---
create_time: 2026-04-29 22:00:00
status: done
bead_id: sase-1b.8
---
# Rust Backend Phase 6H Handoff — Documentation, Rollback Plan, And Close-Out

## Scope landed in this phase

Phase 6H closes Phase 6 with the documentation and rollback artifacts that
the Phase 6A–6G code/CI work produced but did not yet narrate from the
production-default voice:

1. **`docs/rust_backend.md` rewritten in production-default voice.** The
   page already said "Rust is the default" after Phase 6F, but it still
   read like a roadmap in places. Phase 6H adds two new top-level
   sections (`Verifying The Backend`, `Rollback`) and two new roadmap
   entries (Phase 6G, Phase 6H, Phase 7) so the document is self-contained
   for users who land on it without prior context. The
   `SASE_CORE_DUAL_RUN` row in the env-var table is reframed as a
   parity/safety rail (CI gate + ad-hoc verification) rather than a
   normal production mode.
2. **`sdd/research/202604/rust_backend_migration.md` updated to Phase 6
   complete.** The "2026-04-29 update" header is rewritten to reflect that
   Phases 0–6 have shipped, with explicit subsections for the default
   flip, packaging decision, `is_workflow_complete` resolution, CI matrix
   and parity gate, backend health/contract, and the documentation /
   rollback artifacts. The Phase 6 section in Part 4 is marked complete
   with an outcome paragraph; the "Recommended next concrete actions" list
   is rewritten to point at Phase 7 (measurement + benchmark gate) and
   Phase 8 (Python implementation removal) instead of the now-stale
   pre-Phase 6 punch list.
3. **Rollback playbook.** `docs/rust_backend.md` now records the formal
   rollback procedure for both windows of the release cycle:
   - **During Phase 6/7** (Python implementations still ship): per-user
     mitigation is `SASE_CORE_BACKEND=python`; project-wide rollback is a
     patch release that reverts `DEFAULT_BACKEND` in
     `src/sase/core/backend.py` and the matching tests called out in
     Phase 6F's handoff. The `sase-core-rs` runtime dependency stays in
     place so explicit `SASE_CORE_BACKEND=rust` continues to work for
     anyone who opts back in.
   - **After Phase 8** (Python implementations removed): rollback is a
     wheel/package fix because the Python halves are gone; the
     `SASE_CORE_BACKEND` env var is removed alongside the implementations
     and is no longer a user mitigation.

No production code under `src/sase/` changed in this phase — Phase 6H is a
narrative close-out, not a behavior change. The default flip from Phase 6F
and the CI guarantees from Phase 6G are unchanged.

## What changed

### `docs/rust_backend.md`

- **`SASE_CORE_DUAL_RUN` description (Selecting the Backend at Runtime
  table).** Reframed as "parity/safety rail" — it now explicitly names the
  CI parity gate (`tests/parity/dual_run_parity.py`) as the production
  use of dual-run and notes that the env var is for ad-hoc verification,
  not normal sessions.
- **New `Verifying The Backend` section** added after `Benchmarking`. It
  catalogues the four commands users and CI rely on (`sase core health`,
  `just check`, `just parity-check`, `just rust-check`), restates the
  documented `parse_project_bytes` divergence and where it is pinned, and
  describes the CI matrix shape and `install-smoke` failure-mode
  diagnostics so a reader can verify their install end-to-end without
  cross-referencing the workflow YAML.
- **New `Rollback` section** added after `Verifying The Backend`. Covers
  both Phase 6/7 reversible rollback (per-user `SASE_CORE_BACKEND=python`,
  plus the five-step project-wide patch-release path that mirrors the
  Phase 6F flip) and the post-Phase 8 wheel-fix path. Cross-links to
  `plans/202604/rust_backend_phase6_phase6f_handoff.md` for the exact
  test list to flip during the project-wide rollback.
- **Roadmap entries.** New entries for Phase 6G and Phase 6H summarize
  what landed in those phases. A new Phase 7 entry restates the
  measurement / benchmark-gate work as the open next track. The "Future
  phases" entry that previously trailed Phase 6F is preserved verbatim
  beneath the new entries.

### `sdd/research/202604/rust_backend_migration.md`

- **Header status update** ("2026-04-29 update") rewritten from "Phases
  0–5 of this plan have shipped" to "Phases 0–6 of this plan have
  shipped". Replaces the single "Default backend remains `python`"
  bullet with structured subsections for the default flip, packaging
  decision (sase-core-rs separate PyPI distribution, `sase` declares it
  as a runtime dependency, supported wheel matrix, free-threaded
  CPython out of scope), `is_workflow_complete` Phase 6E pin and
  benchmark numbers, CI matrix / parity gate / install-smoke shape,
  shipped vs. unported contract counts (12 / 5), and the documentation
  + rollback artifacts. Each subsection links back to its Phase 6
  handoff for the full record. The closing paragraph is updated so the
  forward agenda is Phase 7 → Phase 8 → deferred ports rather than the
  Phase 6 consolidation track.
- **Phase 6 section in Part 4** ("Migration order") marked
  `✅ complete` with a new outcome paragraph that summarizes the realized
  state and points back to the per-subphase handoffs.
- **"Recommended next concrete actions" rewritten.** The previous list
  began "Phases 0–4 are done" and walked through wheel-build, regression
  fix, and Phase 6 epic open. Phase 6H replaces it with three forward
  items: Phase 7 measurement + benchmark gate, Phase 8 Python
  implementation removal, and "re-profile after Phase 7 numbers land"
  so future ports are re-justified against measured baselines rather
  than Phase 0 research.

### `plans/202604/rust_backend_phase6_phase6h_handoff.md` (this file)

- New file. Phase 6 close-out record + rollback summary anchor.

### Optional release-notes file

- **Skipped.** The repo does not currently maintain a `CHANGELOG.md` /
  `RELEASE_NOTES.md` file (verified by `ls docs/` + a top-level scan).
  The plan called this file optional; Phase 6H does not add one. If one
  is introduced later, the Phase 6 entry can be assembled from
  `plans/202604/rust_backend_phase6_*_handoff.md` and the migration
  research update.

## Rollback summary (anchor for future agents)

The two rollback paths are documented in full in
`docs/rust_backend.md` under `## Rollback`. This handoff records the
short version so a future agent who lands here without reading the docs
has the punch list in one place.

### Phase 6/7 (Python implementations still ship)

Per-user mitigation, no release required:

```bash
export SASE_CORE_BACKEND=python
sase core health   # confirms python mode + status="ok" without sase_core_rs
```

Project-wide rollback (single patch release):

1. `src/sase/core/backend.py` — set `DEFAULT_BACKEND = Backend.PYTHON`.
2. Update the tests Phase 6F renamed to assert "default Rust" so they
   re-assert "default Python":
   - `tests/test_core_backend.py::test_default_backend_is_rust` →
     `test_default_backend_is_python` (and the matching display /
     dispatch tests; the Phase 6F handoff lists every rename).
   - `tests/test_core_facade/test_backend_contract.py::test_default_backend_is_rust`
     → `test_default_backend_is_still_python`.
   - `tests/test_backend_indicator.py::test_backend_indicator_renders_rust_by_default`
     → `test_backend_indicator_renders_python_by_default` (and the
     mirror test under `test_backend_indicator_renders_python_when_explicit`).
3. `docs/rust_backend.md` — flip the `## Selecting the Backend at
   Runtime` table back to `python (default)` and update the header
   paragraph that currently says "Starting in Phase 6F, Rust is the
   default backend".
4. Cut a patch release. The `sase-core-rs` runtime dependency stays
   declared so `SASE_CORE_BACKEND=rust` still works for opt-in users;
   no wheel republish is required.
5. Keep `SASE_CORE_DUAL_RUN=1` running in CI so the parity record
   stays current. Re-attempt the flip after the triggering regression
   is fixed.

### After Phase 8 (Python implementations removed)

Rollback is a `sase-core-rs` patch wheel + `pyproject.toml` pin update,
not a constant flip — there is no Python implementation to fall back to
once Phase 8 lands. If parity drifted before Phase 8 closed, the only
safe path is to revert the Phase 8 PR(s) before the patch release and
redo Phase 7 verification before re-attempting Phase 8. The
`SASE_CORE_BACKEND=python` env var is removed alongside the Python
implementations and is no longer a user mitigation post-Phase 8.

## Verification

```
just install
just check
.venv/bin/pytest tests/test_core_backend.py \
  tests/test_core_facade/test_backend_contract.py \
  tests/test_backend_indicator.py \
  tests/test_core_health.py
SASE_CORE_BACKEND=python .venv/bin/pytest tests/test_core_backend.py \
  tests/test_core_facade/test_backend_contract.py \
  tests/test_backend_indicator.py
just parity-check
```

Phase 6H makes no behavior changes, so the focused tests should pass
unchanged from Phase 6G. `just check` is the local gate for the lint /
type / test bundle on the active backend; `just parity-check` is the
local mirror of the CI `parity-gate` job (zero mismatches expected for
non-divergent shipped operations, documented divergence allow-listed for
`parse_project_bytes`).

## Behavior contract preserved

- `DEFAULT_BACKEND` is still `Backend.RUST` (Phase 6F).
- Shipped vs. unported classification, `RustBackendUnavailableError`
  messaging, and the dual-run no-op semantics for operations without a
  registered `rust_impl` are unchanged.
- `is_workflow_complete` continues to use the Phase 6E targeted Python
  traversal regardless of backend selection.
- The CI `test` / `test-python-backend` / `parity-gate` /
  `install-smoke` shape from Phase 6G is unchanged. No workflow YAML
  was edited in this phase.
- No production code under `src/sase/` changed.

## Out of scope (handed to Phase 7)

- **Performance section in `docs/rust_backend.md`.** Phase 7 is the
  measurement pass: it runs the bench suite + TUI cold-open + cold
  agent listing under default-Rust vs. explicit-Python and records the
  realized speedups in a new `Performance` section here. The Phase 6H
  doc rewrite intentionally leaves that section absent and points
  Phase 7 at it via the new roadmap entry.
- **Benchmark regression floor in CI.** Phase 7 codifies the measured
  numbers as a `bench` CI job (or scheduled run) that fails on
  >X% regression vs. the recorded medians. Phase 6G's `parity-gate`
  protects correctness; the regression floor is what protects the
  *speedup* from silently eroding once the Python escape hatch is
  removed in Phase 8.
- **Python implementation removal.** Phase 8 removes the Python halves
  of the ported operations, the dual-run plumbing for those operations,
  and the `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` env vars. Per the
  Phase 6/7 contract the rollback path stays open until that phase
  ships.

## Exit criteria

- [x] `sdd/research/202604/rust_backend_migration.md` says Phase 6 is
      complete and Phase 7 can begin (header status block + Phase 6
      "Migration order" entry + rewritten "Recommended next concrete
      actions" section).
- [x] `docs/rust_backend.md` matches actual runtime behavior (Rust is
      default; Python escape hatch is documented; dual-run is described
      as a parity/safety rail; health-check command and failure modes
      are documented; source-development workflows are documented;
      verification and rollback have dedicated sections; Phase 6G,
      Phase 6H, and Phase 7 entries are in the roadmap).
- [x] The handoff tells a future agent exactly how to roll back during
      the Phase 6/7 release cycle (the "Rollback" section in
      `docs/rust_backend.md` plus the rollback summary in this file
      list the exact files / tests / docs to flip and the patch-release
      shape).
