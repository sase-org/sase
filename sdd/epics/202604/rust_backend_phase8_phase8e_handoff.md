---
create_time: 2026-04-29
status: handoff
bead_id: sase-1f.5
---
# Rust Backend Migration Phase 8E Handoff: Direct-Rust Status And Git Helpers

## Scope

Phase 8E direct-wires the pure status and Git query facade entry points
to ``sase_core_rs`` without going through ``sase.core.backend.dispatch``,
re-runs the focused microbenchmarks against the direct-Rust path, and
documents the surviving Python ``*_python`` helpers as host-logic /
golden-contract references rather than backend fallbacks. The strict
loader is :func:`sase.core.rust.require_rust_binding` (introduced in
Phase 8A); facades that rewire to direct Rust call it once per entry
point and let its :class:`ImportError` (missing wheel) and
:class:`AttributeError` (stale wheel without the binding) propagate
verbatim.

The five direct-Rust ports completed in this subphase:

- ``read_status_from_lines``
- ``apply_status_update``
- ``plan_status_transition``
- ``parse_git_name_status_z``
- ``parse_git_branch_name``
- ``derive_git_workspace_name``
- ``parse_git_conflicted_files``
- ``parse_git_local_changes``

In addition, ``transition_changespec_status`` was moved off
``dispatch`` (it was already using ``rust_unavailable="python"``) and
becomes a direct call into ``transition_changespec_status_python``,
documented as host logic.

## Code Changes

- ``src/sase/core/status_facade.py`` — replaced every
  ``dispatch(operation=..., python_impl=..., rust_impl=...)`` call with
  one ``require_rust_binding(name)`` lookup against the Phase 8A strict
  loader at :mod:`sase.core.rust`. Each facade entry point now performs
  exactly one binding lookup and one Rust call.
  ``transition_changespec_status`` now calls
  ``transition_changespec_status_python`` directly with no dispatcher
  wrapper.
- ``src/sase/core/git_query_facade.py`` — same pattern for the five Git
  query helpers. The ``*_python`` golden-reference functions and the
  ``_parse_git_name_status_z_python`` / ``GitNameStatusEntryWire``
  helpers stay in place.
- ``src/sase/status_state_machine/field_updates.py`` — added ``# pyvision``
  pragmas pointing at the parity tests and rewrote the docstrings on the
  public entry points and the ``*_python`` helpers to describe them as
  host-logic golden references rather than backend fallbacks.
- ``src/sase/core/status_wire_conversion.py`` — added the matching
  pyvision pragma on ``plan_status_transition_python``.

## Decision: Keep ``*_python`` Helpers As Host-Logic Golden References

The Phase 8E plan permits removing the ``*_python`` helpers when no
non-test caller needs them. After direct-Rust wiring:

| Helper                              | Non-test callers | Disposition |
| ----------------------------------- | ---------------- | ----------- |
| ``read_status_from_lines_python``   | none (only parity tests) | retained as host-logic golden reference |
| ``apply_status_update_python``      | none (only parity tests) | retained as host-logic golden reference |
| ``plan_status_transition_python``   | none (only parity tests + ``test_core_status_wire``) | retained as host-logic golden reference |
| ``parse_git_name_status_z_python``  | none (only parity tests) | retained as host-logic golden reference |
| ``parse_git_branch_name_python``    | none (only parity tests) | retained as host-logic golden reference |
| ``derive_git_workspace_name_python``| none (only parity tests) | retained as host-logic golden reference |
| ``parse_git_conflicted_files_python``| none (only parity tests) | retained as host-logic golden reference |
| ``parse_git_local_changes_python``  | none (only parity tests) | retained as host-logic golden reference |

Strictly applying "remove if no non-test caller needs them" would delete
all eight functions. The preferred-fallback wording in Phase 8E (and the
plan's broader Phase 8G mandate to "replace live Python/Rust parity
language with golden-contract language") makes the practical retention
case stronger than the deletion case:

- ``tests/test_core_facade/test_status.py``,
  ``tests/test_core_status_wire.py``,
  ``tests/test_core_git_query.py``, and
  ``tests/test_status_state_machine_field_updates.py`` use these
  ``*_python`` functions as the byte-for-byte expectation for the Rust
  binding's output. Removing them would force every parity assertion to
  inline its expected value or duplicate the Rust-flat conversion logic;
  both are worse than keeping the host-logic implementation.
- The plan explicitly directs Phase 8 to reframe Python-vs-Rust
  comparisons as **golden-contract** comparisons. The retained ``_python``
  helpers *are* the golden contract: a small, hand-written reference the
  Rust port must match.
- The dispatcher-aware wrappers in ``field_updates.py`` are still the
  public ``apply_status_update`` / ``read_status_from_lines`` API used
  by ``transition_changespec_status_python``. Their docstrings now
  describe the call path as a direct facade call, not a dispatcher
  branch.

If a future phase decides the parity tests should compare against
committed JSON fixtures instead of live Python, the ``*_python`` helpers
become deletable without further facade work.

## Test Changes

- ``tests/test_core_facade/test_status.py`` — rewrote the dispatch-mode
  tests as direct-call tests:
  - removed every ``SASE_CORE_BACKEND``- or
    ``SASE_CORE_DUAL_RUN``-driven scenario;
  - added missing-extension cases that assert ``ImportError`` names the
    Rust extension, and missing-binding cases that assert
    ``AttributeError`` names the operation;
  - kept the registered-binding test, the rust-error-surfaces test, and
    the real-extension parity tests;
  - retained the two transition-side-effect tests that pin
    ``transition_changespec_status_python`` to the planner facade.
- ``tests/test_core_git_query.py`` — same shape: replaced the Phase 5D
  ``test_dispatch_*`` block with direct-call wiring tests, added a
  module-level skip when ``sase_core_rs`` is not importable, and kept
  every parser-content and real-extension parity test untouched.
- ``tests/test_core_facade/test_backend_contract.py`` — pruned the
  Phase 8E direct-wired operations from ``SHIPPED_OPERATIONS`` and
  removed ``transition_changespec_status`` from
  ``UNPORTED_OPERATIONS``. The remaining classifications cover the four
  operations still on the dispatcher (parser, query parse, batch
  evaluator, agent scan) plus the four Python-fallback unported
  operations (graph index, query context, per-row evaluators).
- The ``python_core_backend`` fixture is now a no-op for direct-wired
  operations; it is left in place where the file mixes direct-wired
  helpers with other dispatcher-routed assertions, but
  ``tests/test_core_facade/test_status.py`` and
  ``tests/test_core_git_query.py`` no longer use it.

## Re-Measurement

The plan asks that tiny normalizers be re-measured against the
direct-Rust wrappers and that any helper still materially worse under
direct Rust be reclassified as Python-owned host logic.

### Status helpers (``just bench-status-state-machine``)

After Phase 8E the env-var toggles inside ``bench_status_state_machine``
no longer change the line/plan helpers' execution path (both the
"python" and "rust" rows now hit the direct-Rust binding). The benchmark
output therefore measures direct-Rust performance under both labels —
they are within noise:

| Scenario                | Workload                  | Rust median (us) | Python-label median (us) |
| ----------------------- | ------------------------- | ---------------- | ------------------------- |
| ``read_status_from_lines`` | golden_myproj_pure (4 specs) | 3.28 | 3.18 |
| ``apply_status_update``    | golden_myproj_pure       | 3.68 | 3.61 |
| ``plan_status_transition`` | golden_myproj_pure       | 16.29 | 16.30 |
| ``read_status_from_lines`` | synthetic_100_specs_pure | 163.32 | 164.77 |
| ``apply_status_update``    | synthetic_100_specs_pure | 180.40 | 178.77 |
| ``plan_status_transition`` | synthetic_100_specs_pure | 16.05 | 16.07 |

(``transition_changespec_status_*`` is dominated by disk I/O — direct
Rust is within noise of the previous dispatcher-routed numbers.)

No helper regressed. No reclassification is required.

### Git helpers (``just bench-git-query-ops``)

| Scenario                          | Workload         | Rust median (us) |
| --------------------------------- | ---------------- | ---------------- |
| ``parse_git_name_status_z``       | synthetic_small  | 40.93 |
| ``parse_git_name_status_z``       | synthetic_medium | 840.09 |
| ``parse_git_name_status_z``       | synthetic_large  | 9205.01 |
| ``parse_git_branch_name`` x4      | normalizers      | 2.57 |
| ``derive_git_workspace_name`` x5  | normalizers      | 3.43 |
| ``parse_git_conflicted_files_50`` | normalizers      | 4.56 |
| ``parse_git_local_changes_150``   | normalizers      | 1.65 |

Every Git helper sits well below the Phase 7 noise floor. The
``end_to_end_*`` scenarios show ``parse_git_name_status_z`` continuing
to be a small fraction of the ``git diff`` subprocess cost (49.7us vs
2531.6us at 50 files, 369.5us vs 9747.5us at 500 files).

No helper regressed. No reclassification is required.

### Phase 7 floor check (``just phase7-perf-check``)

Passes:

```
[PASS] parse_project_bytes.golden_myproj.facade
[PASS] parse_project_bytes.synthetic_200_specs.facade
[PASS] parse_query.parse_only.direct
[PASS] scan_agent_artifacts.synthetic_6p_200pp.scan_facade
[PASS] apply_status_update.golden_myproj_pure.apply_status_update
```

The Phase 7E floor JSON anchors are unchanged. No baseline updates were
required — the helpers were already comfortably above the regression
floor and direct-Rust wiring did not materially change their numbers.

## Verification

- ``just install`` — succeeds (workspace ephemeral install).
- ``just lint`` — succeeds (ruff + mypy + pyvision + tools structure).
- ``just check`` — runs ``test`` then ``lint``; full pytest suite is
  6512 passed / 6 skipped / 1 deselected.
- ``just rust-check`` — succeeds (Rust unit/integration tests in
  ``../sase-core``).
- ``just phase7-perf-check`` — succeeds.
- ``just bench-status-state-machine`` — re-measured (numbers above).
- ``just bench-git-query-ops`` — re-measured (numbers above).

## What Does NOT Change In This Subphase

- ``src/sase/core/backend.py`` still owns ``dispatch``,
  ``Backend`` / ``DEFAULT_BACKEND`` / ``BACKEND_ENV_VAR`` /
  ``DUAL_RUN_ENV_VAR``, and ``RustBackendUnavailableError``. Phase 8F
  deletes them.
- ``src/sase/core/dual_run.py`` is untouched. Phase 8F deletes it. The
  status and Git facades simply no longer route through it.
- ``src/sase/core/health.py``, the TUI backend indicator, and
  ``sase core health`` still describe Python/Rust selection. Phase 8C is
  responsible for that surface.
- The query / parser / agent-scan facades still use ``dispatch``.
  Phase 8B (``evaluate_query_many`` regression) and Phase 8D (parser /
  agent-scan / query-parse direct wiring) cover those.
- ``docs/rust_backend.md`` still describes the Phase 6/7 architecture.
  Phase 8G is the documentation pass.

## Followups For Later Subphases

- **Phase 8F** should run the close-out grep
  (``rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|is_rust_available"``) and
  delete the env-var toggling in ``tests/perf/bench_status_state_machine.py``
  (the ``_with_backend_env`` helper and the python/rust-label split in
  ``_run_pair`` / ``_print_block``). With dispatch gone, the toggling is
  measurement noise.
- **Phase 8F** should also drop ``tests/parity/dual_run_parity.py``
  references to the eight Phase 8E direct-wired operations if any
  remain (none are required for these helpers any more).
- **Phase 8G** should rewrite ``docs/rust_backend.md::512`` so the
  ``plan_status_transition_python`` mention frames it as the
  golden-contract reference, not a backend fallback.

## Files Touched

```
src/sase/core/git_query_facade.py
src/sase/core/status_facade.py
src/sase/core/status_wire_conversion.py
src/sase/status_state_machine/field_updates.py
tests/test_core_facade/test_backend_contract.py
tests/test_core_facade/test_status.py
tests/test_core_git_query.py
plans/202604/rust_backend_phase8_phase8e_handoff.md  (this file)
```
