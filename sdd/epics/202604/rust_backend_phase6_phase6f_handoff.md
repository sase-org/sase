---
create_time: 2026-04-29 17:13:32
status: done
bead_id: sase-1b.6
---
# Rust Backend Phase 6F Handoff — Flip Default Backend To Rust

## Scope landed in this phase

Phase 6F flips `DEFAULT_BACKEND` from `Backend.PYTHON` to `Backend.RUST` in
`src/sase/core/backend.py`. With `SASE_CORE_BACKEND` unset, every shipped
operation now dispatches through Rust; explicit `SASE_CORE_BACKEND=python`
continues to select the pure-Python implementations as the documented
Phase 6/7 escape hatch.

The flip is a single-line change to the constant. All other behavior is
inherited from the Phase 6A–6E prerequisites that this phase exists to
bless:

- Phase 6A shipped `sase-core-rs` as a wheel-distributed PyPI package.
- Phase 6B made `sase` declare it as a runtime dependency, so a normal
  `pip install sase` now resolves the Rust extension automatically.
- Phase 6C audited every `dispatch(...)` call site under `src/sase/core/`
  and pinned the shipped/unported classification with
  `tests/test_core_facade/test_backend_contract.py`.
- Phase 6D added `sase core health` as the scriptable contract for "is
  the active backend loadable and working?".
- Phase 6E removed the only known hot-path regression
  (`is_workflow_complete`) by pinning that predicate to a targeted Python
  traversal regardless of backend.

The default flip is therefore neutral on every previously identified
risk: shipped operations have parity-tested Rust impls, missing bindings
fail loudly, dual-run logging is still available, and the one regression
that motivated Phase 6E is no longer routed through the snapshot facade.

## What changed

### `src/sase/core/backend.py`

- `DEFAULT_BACKEND` is now `Backend.RUST`.
- Module docstring rewritten: the env var description now lists `rust`
  as the default and `python` as the documented escape hatch through
  Phase 7.
- `get_active_backend` docstring updated to "default rust".
- `dispatch` docstring rewritten to reflect the new default-on-Rust
  ordering (raise / call rust_impl by default; explicit Python is the
  alternate path).

The dispatcher logic itself is unchanged — every code path the previous
default ran is still reachable, just selected by setting
`SASE_CORE_BACKEND=python` instead of being implicit.

### `src/sase/core/__init__.py`

- "The backend boundary" paragraph now describes Rust as the default and
  Python as the temporary opt-out.
- "Why Rust is optional" was retitled "Why a Python escape hatch still
  exists" so the package docstring matches actual runtime behavior. The
  rollback rationale (Python implementations stay through Phase 7 so a
  patch release can revert the default) is called out explicitly.

### Tests

The handful of tests that asserted "default Python" semantics or relied
on the implicit default were updated:

- `tests/test_core_backend.py`
  - `test_default_backend_is_python` → `test_default_backend_is_rust`
  - `test_backend_display_default_python` → `test_backend_display_default_rust`
  - `test_backend_display_explicit_rust` → `test_backend_display_explicit_python`
    (mirror so the indicator's Python rendering is still pinned)
  - `test_dispatch_python_default` → renamed to `test_dispatch_python_explicit`
    (sets `SASE_CORE_BACKEND=python`) and a new `test_dispatch_rust_default`
    asserts the unset path now selects the Rust impl.
- `tests/test_core_facade/test_backend_contract.py`
  - `test_default_backend_is_still_python` → `test_default_backend_is_rust`.
    The doc comment block explaining "this audit exists so 6F's flip
    cannot discover a silent fallback" was updated to past-tense now
    that the flip has landed.
- `tests/test_backend_indicator.py`
  - `test_backend_indicator_renders_python` →
    `test_backend_indicator_renders_rust_by_default`
  - `test_backend_indicator_renders_rust` →
    `test_backend_indicator_renders_python_when_explicit`
- `tests/test_core_dual_run.py::test_dual_run_dispatch_no_op_without_rust_impl`
  now sets `SASE_CORE_BACKEND=python` explicitly. The test's intent is
  to pin the dual-run no-op behavior when no `rust_impl` is registered;
  under the new default that path would raise
  `RustBackendUnavailableError` before reaching the dual-run branch, so
  explicit Python preserves the test's purpose without changing the
  behavior under audit.
- `tests/test_core_agent_scan.py::_clean_backend_env`
  (autouse fixture) now pins the suite to `SASE_CORE_BACKEND=python`.
  The Phase 3 facade tests cover the Python snapshot scanner end-to-end
  (fixture parity, soft-error counting, etc.) and tests that need Rust
  dispatch set the env var themselves; pinning Python keeps the tests
  predictable when the suite runs without `sase_core_rs` installed.
- `tests/test_core_git_query.py`
  - `test_dispatch_default_backend_uses_python_for_all_helpers` →
    `test_dispatch_python_backend_uses_python_for_all_helpers`
  - `test_dispatch_default_backend_ignores_fake_rust_module` →
    `test_dispatch_python_backend_ignores_fake_rust_module`

  Both tests now set `SASE_CORE_BACKEND=python` explicitly. The previous
  "default = Python" assumption is what these tests were pinning; under
  the new default they would either raise (no rust_impl available) or
  call the fake Rust module (which is what the rename-target test
  exists to verify).

The Phase 4F circular-import workaround in
`sase/status_state_machine/transitions.py` is unaffected — Phase 6F does
not touch that module.

### Docs

`docs/rust_backend.md` was updated to reflect the new default:

- The header paragraph now says "Starting in Phase 6F, Rust is the
  default backend".
- The architecture ASCII diagram labels Rust as `(default)` and the
  Python column as `(escape hatch)`.
- The runtime selection table reorders the values column to lead with
  `rust (default)` and notes that `python` is temporary through Phase 7.
- The `sase core health` exit-code table collapses the duplicated
  "unset / `rust` (Phase 6F+)" rows into a single set of cases for the
  unset / `rust` selection.
- A new Phase 6F roadmap entry documents the flip, the rollback path
  (revert the constant + ship a patch release), and the unchanged
  Phase 6E `is_workflow_complete` pin.

## Behavior contract preserved

- Unset `SASE_CORE_BACKEND` selects Rust for shipped operations
  (`get_active_backend()` returns `Backend.RUST`,
  `DEFAULT_BACKEND is Backend.RUST`).
- `SASE_CORE_BACKEND=python` continues to select the pure-Python
  implementations and does **not** require `sase_core_rs` to be
  importable — covered by the existing Phase 6D health check tests
  (`test_python_mode_ok_without_extension`,
  `test_cli_python_mode_does_not_require_extension`).
- `SASE_CORE_BACKEND=rust` continues to select Rust strictly — missing
  shipped bindings still raise `RustBackendUnavailableError` and the
  error text still names the operation, the extension module, and the
  `SASE_CORE_BACKEND=python` escape hatch.
- Invalid values still fail clearly via `get_active_backend()`'s
  `ValueError` (covered by `test_unknown_backend_raises`).
- Dual-run still returns the Python result whenever `rust_impl` is
  registered, regardless of which backend is selected — the existing
  `test_dual_run_dispatch_returns_python_result` test does not need to
  change because it provides a `rust_impl` and enables dual-run, so the
  dispatcher reaches the comparison branch before any backend-specific
  routing.
- The TUI backend indicator now defaults to "backend: Rust" (green
  pill) when both env vars are unset; the explicit-Python rendering
  ("backend: Python", blue pill) and dual-run rendering
  ("backend: Python+Rust dual", purple pill) are unchanged and still
  pinned by their respective tests.
- `is_workflow_complete` continues to use the Phase 6E targeted Python
  traversal regardless of backend.
- The unported facade operations
  (`build_query_context`, `evaluate_query`, `evaluate_query_with_context`,
  `build_changespec_graph_index`, `transition_changespec_status`)
  continue to route to Python under Rust mode via
  `rust_unavailable="python"`.

## Verification

```
just install
just check
.venv/bin/pytest tests/test_core_backend.py \
  tests/test_core_facade/test_backend_contract.py \
  tests/test_backend_indicator.py \
  tests/test_core_dual_run.py \
  tests/test_core_agent_scan.py \
  tests/test_core_git_query.py \
  tests/test_core_health.py
SASE_CORE_BACKEND=python .venv/bin/pytest tests/test_core_backend.py \
  tests/test_core_facade/test_backend_contract.py \
  tests/test_backend_indicator.py
```

Both backend modes pass the focused subset; `just check` is green
locally. CI will exercise the matrix in Phase 6G.

## Out of scope (handed to later subphases)

- **Phase 6G** — CI matrix, parity gate, and release smoke. Phase 6F
  flipped the default in code; Phase 6G is responsible for adding the
  CI jobs that exercise both default-Rust and explicit-Python suites,
  the dual-run parity gate over the golden corpus and a sanitized
  home-tree fixture, and the publish-side install smoke.
- **Phase 6H** — Documentation close-out and rollback playbook. The
  Phase 6F doc edits cover the immediate "Rust is default" pivot; the
  broader rewrite of `docs/rust_backend.md` from "optional Rust
  backend" framing to "Rust is the production default" framing, plus
  the formal rollback procedure and `sdd/research/202604/rust_backend_migration.md`
  status update, is Phase 6H's job.
- **Phase 7** — Backend matrix narrowing, Python-implementation removal
  preparation, and the eventual default removal of
  `SASE_CORE_BACKEND=python`.

## Exit criteria

- [x] With `SASE_CORE_BACKEND` unset and `sase_core_rs` installed,
      shipped operations run through Rust by default
      (`test_default_backend_is_rust` plus the existing Rust-routing
      facade tests).
- [x] With `SASE_CORE_BACKEND=python`, the same focused tests pass
      without requiring `sase_core_rs`
      (covered by the Phase 6D health-check tests and the renamed
      git-query / agent-scan suites that pin themselves to explicit
      Python).
- [x] Default Rust fails clearly when `sase_core_rs` is missing and a
      shipped operation is invoked (existing
      `test_shipped_dispatch_raises_when_rust_binding_missing` parametrized
      across all 12 shipped operations).
- [x] Explicit `SASE_CORE_BACKEND=python` works without `sase_core_rs`
      (`test_python_mode_ok_without_extension`,
      `test_cli_python_mode_does_not_require_extension`).
- [x] Backend display and TUI indicator reflect Rust by default
      (`test_backend_indicator_renders_rust_by_default`,
      `test_backend_display_default_rust`).
- [x] Dual-run, Python implementations, and the unported fallback policy
      are unchanged (no edits to `dual_run.py`, the facade modules, or
      `rust_unavailable="python"` call sites).
