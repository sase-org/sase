---
create_time: 2026-04-29
status: handoff
bead_id: sase-1f.6
---
# Rust Backend Migration Phase 8F Handoff: Delete Dual-Run, Backend Dispatcher, CI Matrix, And Historical Tests

## Scope

Phase 8F removes the now-unused Phase 6/7 safety rails after every facade
was rewired to call ``sase_core_rs`` directly in Phases 8A–8E. The
``sase.core.backend`` and ``sase.core.dual_run`` modules are deleted,
the parity gate / parity test / ``just parity-check`` are gone, the
``test-python-backend`` and ``parity-gate`` jobs are dropped from CI
workflows, and the install-smoke / perf harnesses no longer toggle
``SASE_CORE_BACKEND``. The only supported Rust import path is the
strict loader from :mod:`sase.core.rust` (introduced in Phase 8A).

## Code Changes

### Deleted modules and test files

```
src/sase/core/backend.py             — dispatch, Backend, BACKEND_ENV_VAR,
                                       DUAL_RUN_ENV_VAR, get_active_backend,
                                       is_dual_run_enabled, is_rust_available,
                                       load_rust_extension, RustBackendUnavailableError
src/sase/core/dual_run.py            — DualRunRecord, run_with_comparison,
                                       append_dual_run_record, find_first_diff_path,
                                       compute_input_hash
tests/test_core_backend.py
tests/test_core_dual_run.py
tests/test_core_facade/test_backend_contract.py
tests/test_core_parity_smoke.py
tests/parity/dual_run_parity.py      — and its now-empty parent directory
```

### `Justfile`

- Dropped the ``parity-check`` recipe (the dual-run parity gate driver).
- Updated the ``rust-install-uv-tool`` recipe doc-comment so it no
  longer mentions ``SASE_CORE_BACKEND=rust``.
- Updated the ``bench-core`` and ``phase7-perf-check`` doc-comments to
  describe the post-Phase-8 single-backend reality.

### `.github/workflows/ci.yml` and `publish.yml`

- Removed the ``test-python-backend`` matrix job (covered the
  ``SASE_CORE_BACKEND=python`` escape hatch that no longer exists).
- Removed the ``parity-gate`` job (uploaded ``parity-artifacts/``).
- ``install-smoke`` keeps a single ``sase core health --json`` step;
  the ``SASE_CORE_BACKEND=python`` second invocation is gone.
- ``publish.yml`` install-smoke + diagnostics simplified the same way
  (one health probe, one diagnostics group instead of two).
- Doc-comments on the remaining jobs reworded so they no longer
  describe a "default-backend matrix" or "explicit Python escape hatch".

### `src/sase/core/`

- ``__init__.py`` rewritten so the module docstring describes the
  Phase 8 steady state (``sase.core.rust`` is the strict loader, no
  backend env vars, intentionally unported operations call their
  ``*_python`` helpers directly as host logic).
- ``parser_facade.py``, ``agent_scan_facade.py``, ``query_facade.py``,
  ``status_facade.py``, ``git_query_facade.py``, ``health.py``,
  ``rust.py`` — docstrings/comments scrubbed of "Phase 8X / dispatch /
  SASE_CORE_BACKEND" language that described the old layered routing
  rather than current behavior.

### `src/sase/status_state_machine/transitions.py` and `agent/names/_lookup.py`

- Reworded module/function docstrings so they describe the post-Phase-8
  call path (direct Rust planner, targeted Python walk for
  ``is_workflow_complete``) instead of "routes through Rust under
  ``SASE_CORE_BACKEND=rust``".

### Tests

- ``tests/conftest.py`` — dropped the ``BACKEND_ENV_VAR`` /
  ``DUAL_RUN_ENV_VAR`` / ``DUAL_RUN_LOG_OVERRIDE_ENV_VAR`` autouse
  cleanup fixture and the ``python_core_backend`` fixture itself. They
  guarded backend env-var leakage; with no such env vars to leak the
  fixtures are dead weight.
- Removed ``pytestmark = pytest.mark.usefixtures("python_core_backend")``
  from every consumer (``test_core_status_lines``,
  ``test_status_state_machine_field_updates``,
  ``test_status_state_machine_transitions``, ``test_vcs_provider_git_query``,
  ``test_vcs_provider_git_sync``, ``test_vcs_provider_git_integration``,
  ``test_core_golden``, ``tests/ace/deltas/test_diff_name_status_git``).
  These tests now exercise the direct-Rust facades under the real
  installed wheel.
- ``tests/test_core_facade/test_status.py`` and
  ``tests/test_core_git_query.py`` switched their
  ``RUST_EXTENSION_MODULE_NAME`` import from
  ``sase.core.backend`` (deleted) to ``sase.core.rust`` and dropped the
  "load_rust_extension" wording from helper docstrings.
- ``tests/test_core_facade/test_query.py`` — reframed the
  ``evaluate_query_many`` deferral test around a direct Python call
  (no env var) and removed the dual-run-noop subtest, which only made
  sense while ``dispatch`` existed.
- ``tests/test_core_facade/_helpers.py`` — pruned the
  ``SASE_CORE_BACKEND=rust`` callout from
  ``python_wire_records_as_dicts``'s docstring.
- ``tests/test_core_golden.py`` — removed the three tests that drove
  ``dispatch`` directly with fake-rust impls and dual-run logging; the
  remaining wire/JSON/canonical/query/status golden snapshots are
  untouched.
- ``tests/test_core_rust.py`` — docstring scrubbed of
  ``SASE_CORE_BACKEND`` references; the strict-loader contract tests
  are unchanged.
- ``tests/ace/changespec/test_snapshot_cache.py`` — removed the
  ``test_get_file_specs_parses_when_rust_backend_selected`` case (it
  asserted env-var routing, which is no longer a thing).
- ``tests/test_agent_names_workflow.py`` — collapsed the
  ``parametrize("backend", ["python", "rust", ""])`` case into a single
  test that proves the targeted Python walk does not materialise the
  scan-agent-artifacts snapshot.

### Performance harnesses

The Phase 8E handoff explicitly listed the env-var toggling in
``bench_status_state_machine`` as Phase 8F's job. After Phase 8F:

- ``tests/perf/bench_status_state_machine.py`` — removed
  ``_with_backend_env`` / the ``"python"`` vs ``"rust"`` split inside
  ``_measure_pure`` / ``_measure_transition`` / ``_print_human``. Each
  scenario is now timed once; the harness reports a single
  ``"scenarios"`` block per workload and omits the backend toggle from
  the human-readable output.
- ``tests/perf/bench_core_parse.py`` — dropped the ``python_facade``
  and ``dual_run`` rows. The harness still times ``python_direct``
  (Python file-path API), ``rust_direct``, and ``rust_facade`` (the
  only ported path).
- ``tests/perf/bench_core_query.py`` — dropped
  ``dual_run_evaluate_many`` and the env-var toggling around
  ``rust_facade_*`` rows; the remaining scenarios time direct Rust,
  the facade, and the Python golden references.
- ``tests/perf/bench_agent_scan.py`` — removed the
  ``find_named_agent_rust_backend`` /
  ``is_workflow_complete_rust_backend`` rows (they only existed to
  re-time the lookups under ``SASE_CORE_BACKEND=rust``) and reworded
  the docstring.
- ``tests/perf/bench_workflow_complete.py`` — removed the three-mode
  loop (``python`` / ``rust`` / ``dual_run``); the benchmark now times
  the targeted Python walk and the snapshot-backed comparator once,
  with no env-var manipulation.
- ``tests/perf/bench_phase7_e2e.py`` — ``_resolve_backend_env`` always
  returns ``{}``; ``_subprocess_env`` no longer pops
  ``SASE_CORE_BACKEND`` / ``SASE_CORE_DUAL_RUN`` (there is nothing
  inherited to strip). The ``--backend`` CLI flag is retained for
  filename compatibility against existing Phase 7C artifacts but no
  longer alters runtime behavior.
- ``tests/perf/phase7/run_phase7b.py`` — dropped the python/rust
  driver passes around ``bench_git_query_ops``; one direct-Rust pass
  feeds ``_merge_git_workloads`` instead.
- ``tests/perf/phase7/phase7b_summary.py`` — ``_merge_git_workloads``
  takes a single ``rust_run`` argument and emits ``candidate``-only
  workloads. ``_write_summary_artifact`` accepts the missing
  ``baseline`` and skips emitting it when no Python pass exists.
- ``tests/perf/phase7/phase7b_adaptors.py`` — bench-status adaptor
  consumes the new ``"scenarios"`` shape from
  ``bench_status_state_machine`` (no more
  ``scenarios_python_backend`` / ``scenarios_rust_backend`` fields).
- ``tests/perf/phase7/metadata.py`` — kept the ``BackendChoice`` enum
  (its values are still encoded into the historical Phase 7 artifact
  filenames under ``plans/202604/perf_artifacts/``) but reworded the
  class docstring so it no longer claims ``SASE_CORE_BACKEND``
  controls anything.

### Phase 7 regression-floor baseline

``tests/perf/baselines/phase7_regression_floor.json`` flips
``must_beat_python`` from ``true`` to ``false`` for the three anchors
whose Python halves were deleted in Phase 8D
(``parse_project_bytes.golden_myproj.facade``,
``parse_project_bytes.synthetic_200_specs.facade``,
``scan_agent_artifacts.synthetic_6p_200pp.scan_facade``). The
``phase7b_python_median_s`` field is preserved on each anchor so future
tooling can still read the historical value, but the relative check is
disabled — only the absolute Rust ceiling stays in force.
``parse_query.parse_only.direct`` keeps ``must_beat_python: true``: both
``parse_query_python`` and the Rust binding are still callable on the
same machine in the same process.

## Final Phase 8 Completion Checklist (close-out)

- [x] No production code reads ``SASE_CORE_BACKEND``
      (``rg "SASE_CORE_BACKEND" src/`` returns nothing).
- [x] No production code reads ``SASE_CORE_DUAL_RUN``
      (``rg "SASE_CORE_DUAL_RUN" src/`` returns nothing).
- [x] No facade imports ``sase.core.backend``
      (``rg "sase\.core\.backend" src/`` returns nothing).
- [x] ``src/sase/core/dual_run.py`` is deleted.
- [x] ``tests/parity/dual_run_parity.py`` and ``just parity-check`` are
      deleted (the ``tests/parity/`` directory itself is gone).
- [x] CI has no explicit Python-backend test job and no dual-run
      parity job (``.github/workflows/ci.yml`` no longer defines
      ``test-python-backend`` or ``parity-gate``).
- [x] ``sase core health --json`` fails if ``sase_core_rs`` is missing
      or stale (Phase 8C wired this and Phase 8F kept it untouched).

The remaining checklist items (golden-contract coverage,
``evaluate_query_many`` deferral language, post-Phase-8 rollback
documentation in ``docs/rust_backend.md``) are Phase 8G's
responsibility per the overall plan.

## Verification

- ``just install`` — succeeds (workspace ephemeral install rebuilt the
  Rust core editable).
- ``just check`` — green
  (``fmt`` → ``lint`` (ruff/mypy/pyscripts/pyvision) → ``test``).
- ``just rust-check`` — green (``cargo fmt --check`` + ``clippy`` +
  ``cargo test --workspace`` in ``../sase-core``).
- ``just phase7-perf-check`` — green; the four ``must_beat_python:
  false`` anchors now record ``python=n/a`` with a ``baseline missing``
  note, and the absolute ceiling check still passes for every anchor.
- Final close-out greps:
  - ``rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|RustBackendUnavailableError|is_rust_available|sase\.core\.backend|sase\.core\.dual_run" src/``
    — empty.
  - ``rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\.core\.backend|sase\.core\.dual_run|python_core_backend" tests/``
    — empty.

## Followups For Phase 8G

- ``docs/rust_backend.md`` still describes the Phase 6/7 architecture
  (Python escape hatch, ``SASE_CORE_BACKEND``, dual-run JSONL). Phase
  8G owns the rewrite to the post-Phase-8 steady state.
- ``sdd/research/202604/rust_backend_migration.md`` should be flipped to
  Phase 8 complete and record the operation-disposition table from
  Phase 8A as the final state.
- Phase 8G should also collapse the Phase 8 doc references inside the
  remaining facade docstrings (``parser_facade.py``,
  ``agent_scan_facade.py``, ``query_facade.py``, ``status_facade.py``,
  ``git_query_facade.py``) into single-paragraph descriptions of
  current behavior — the per-subphase narrative is preserved here in
  the handoff, not in the source.
- The historical ``BackendChoice`` enum in
  ``tests/perf/phase7/metadata.py`` retains
  ``DEFAULT_PYTHON`` / ``EXPLICIT_PYTHON`` / ``DEFAULT_RUST`` /
  ``EXPLICIT_RUST`` values because committed Phase 7 artifact
  filenames embed those tags. If Phase 8G deletes or relocates those
  artifacts, these enum values can be pruned.

## Files Touched

```
.github/workflows/ci.yml
.github/workflows/publish.yml
Justfile
src/sase/agent/names/_lookup.py
src/sase/core/__init__.py
src/sase/core/backend.py                                (deleted)
src/sase/core/dual_run.py                               (deleted)
src/sase/core/git_query_facade.py
src/sase/core/rust.py
src/sase/core/status_facade.py
src/sase/status_state_machine/transitions.py
tests/ace/changespec/test_snapshot_cache.py
tests/ace/deltas/test_diff_name_status_git.py
tests/conftest.py
tests/parity/                                           (directory deleted)
tests/perf/baselines/phase7_regression_floor.json
tests/perf/bench_agent_scan.py
tests/perf/bench_core_parse.py
tests/perf/bench_core_query.py
tests/perf/bench_git_query_ops.py
tests/perf/bench_phase7_e2e.py
tests/perf/bench_status_state_machine.py
tests/perf/bench_workflow_complete.py
tests/perf/phase7/metadata.py
tests/perf/phase7/phase7b_adaptors.py
tests/perf/phase7/phase7b_summary.py
tests/perf/phase7/run_phase7b.py
tests/test_agent_names_workflow.py
tests/test_core_backend.py                              (deleted)
tests/test_core_dual_run.py                             (deleted)
tests/test_core_facade/_helpers.py
tests/test_core_facade/conftest.py
tests/test_core_facade/test_backend_contract.py         (deleted)
tests/test_core_facade/test_query.py
tests/test_core_facade/test_status.py
tests/test_core_git_query.py
tests/test_core_golden.py
tests/test_core_parity_smoke.py                         (deleted)
tests/test_core_rust.py
tests/test_core_status_lines.py
tests/test_status_state_machine_field_updates.py
tests/test_status_state_machine_transitions.py
tests/test_vcs_provider_git_integration.py
tests/test_vcs_provider_git_query.py
tests/test_vcs_provider_git_sync.py
plans/202604/rust_backend_phase8_phase8f_handoff.md     (this file)
```
