---
create_time: 2026-04-29
status: handoff
bead_id: sase-1f.7
---
# Rust Backend Migration Phase 8G Handoff: Golden Contract, Documentation, And Close-Out

## Scope

Phase 8G is the documentation pass that closes out Phase 8. After Phase
8F deleted the dispatcher, dual-run plumbing, and CI parity matrix, the
``docs/rust_backend.md`` user-facing page and the
``sdd/research/202604/rust_backend_migration.md`` plan document still
described the Phase 6/7 dual-backend architecture (env-var selection,
dual-run JSONL, ``parity-gate`` job, post-Phase-8 path framed as a
future). Several facade and module docstrings carried per-subphase
narrative ("Phase 8D rewired…", "After Phase 8E…") that belonged in
handoffs, not in source.

This subphase rewrites ``docs/rust_backend.md`` to the steady-state
voice, flips ``sdd/research/202604/rust_backend_migration.md`` to mark
Phase 8 complete, collapses the Phase 8X language inside facade
docstrings into single-paragraph descriptions of current behavior, and
records the final verification.

## Documentation Changes

### `docs/rust_backend.md`

Full rewrite to the post-Phase-8 steady state:

- Opening paragraph states Rust is hard-required, no env vars, no
  Python fallback for ported operations. The shipped operation list
  now lists 11 surfaces (``parse_query`` is shipped; ``evaluate_query_many``
  is documented as Python-owned host logic alongside the other deferred
  query helpers).
- Architecture diagram replaces the "SASE_CORE_BACKEND=python|rust"
  branches with "ported facades / unported facades" and labels the Rust
  side as "required extension".
- Module table updated: ``rust.py`` and ``health.py`` are listed
  explicitly; ``backend.py`` and ``dual_run.py`` are no longer mentioned
  (they don't exist).
- ``Selecting the Backend at Runtime`` section deleted entirely (no env
  vars to select).
- ``Backend Health Check`` section trimmed to the post-Phase-8 contract
  (no Python-mode escape hatch, three exit-code rows instead of four).
- ``Performance`` section keeps the Phase 7B/7C numbers as historical
  baseline, calls them out as "frozen evidence rather than live
  measurements" since the Python halves are gone, and drops the
  ``evaluate_query_many`` row (deferred). Adds an explicit
  "regression floor" subsection naming the
  ``phase7-perf-floor`` GitHub Actions job.
- ``Verifying The Backend`` section drops the dual-run / parity-check
  references and ``SASE_CORE_BACKEND=python`` smoke; matches the actual
  remaining Justfile targets.
- New ``Golden Contract`` section names every test surface that pins the
  Rust output byte-for-byte and points at the cross-language parity
  tests in ``../sase-core``. Replaces the live Python/Rust parity
  language with golden-corpus-as-contract language per the Phase 8 plan
  exit criteria.
- ``Rollback`` section rewritten as wheel/package-fix-only (no env-var
  workaround, no Python fallback). The Phase 6/7 reversible path is
  removed; the post-Phase-8 support workflow is the only path
  documented.
- ``Roadmap`` section deleted; replaced with a one-paragraph
  ``Migration History`` pointer to ``sdd/research/202604/rust_backend_migration.md``
  and the per-phase plans/handoffs.

### `sdd/research/202604/rust_backend_migration.md`

- ``2026-04-29 update`` block flipped to Phases 0–8 complete. Body
  bullets updated:
  - "Default backend is now `rust`" → "Rust is the only backend" with a
    pointer to the Phase 8A–8G handoffs.
  - CI bullet rewritten: ``test-python-backend`` and ``parity-gate`` are
    deleted; ``phase7-perf-floor`` is the active perf gate.
  - Backend health/contract bullet now describes the post-Phase-8
    operation disposition (11 ported surfaces, 6 Python-owned host
    surfaces) and points at the Phase 8A inventory + Phase 8B deferral.
  - Documentation/rollback bullet flipped to wheel/package-fix only.
- ``Phase 8`` section retitled "✅ complete" with a per-subphase summary
  (8A–8G) at the top. The original prose plan stays below as the
  historical narrative.
- ``Recommended next concrete actions`` retitled "What's left" and
  rewritten to enumerate post-Phase-8 forward work (Phase 9 server
  surface, ``evaluate_query_many`` re-port if amortisation shows up,
  graph index / status transition future ports).

### Facade and module docstrings

Single-paragraph descriptions of current behavior, with the Phase 8X
narrative collapsed into the handoffs:

- ``src/sase/core/parser_facade.py`` — module + ``parse_project_bytes``
  docstrings.
- ``src/sase/core/agent_scan_facade.py`` — module +
  ``scan_agent_artifacts`` docstrings.
- ``src/sase/core/query_facade.py`` — module + every entry-point
  docstring (the ``evaluate_query_many`` deferral rationale is moved
  into the module docstring once, not duplicated per function).
- ``src/sase/core/status_facade.py`` — module + ``plan_status_transition``
  docstrings.
- ``src/sase/core/git_query_facade.py`` — module +
  ``parse_git_name_status_z`` docstrings.
- ``src/sase/core/health.py`` — module docstring.
- ``src/sase/agent/names/_lookup.py`` — module + ``is_workflow_complete``
  docstrings (drop "Phase 3H/6E" callouts; keep the structural reason).
- ``src/sase/status_state_machine/transitions.py`` — module +
  ``transition_changespec_status`` public-entry docstring.
- ``tests/test_core_agent_scan.py``, ``tests/test_core_git_query.py``,
  ``tests/test_core_facade/test_query.py`` — module docstrings reframed
  to the steady-state contract (the dispatch / dual-run language is
  removed; the Python ``*_python`` helpers are described as
  golden-contract references rather than fallbacks).

The facade ``*_python`` helpers themselves (``parse_git_name_status_z_python``,
``plan_status_transition_python`` in ``status_wire_conversion``,
``read_status_from_lines_python`` / ``apply_status_update_python`` in
``status_state_machine.field_updates``, ``parse_query_python`` in
``ace.query.parser``, etc.) keep their existing per-function docstrings
since those describe the byte-for-byte golden contract still pinned by
``test_core_*`` tests.

### Plan / spec / xprompt files

No changes. The plan files under ``plans/202604/`` and the bundled
xprompts under ``src/sase/xprompts/`` are historical and deliberately
preserve the Phase 6/7 narrative. Searching ``rg "SASE_CORE_BACKEND"
plans/`` continues to surface the per-subphase handoffs as the
authoritative record of what shipped when.

## Final Phase 8 Completion Checklist (close-out)

- [x] No production code reads ``SASE_CORE_BACKEND``
      (``rg "SASE_CORE_BACKEND" src/`` returns nothing).
- [x] No production code reads ``SASE_CORE_DUAL_RUN``
      (``rg "SASE_CORE_DUAL_RUN" src/`` returns nothing).
- [x] No facade imports ``sase.core.backend``
      (``rg "sase\.core\.backend" src/`` returns nothing).
- [x] ``src/sase/core/dual_run.py`` is deleted.
- [x] ``tests/parity/dual_run_parity.py`` and ``just parity-check`` are
      deleted.
- [x] CI has no explicit Python-backend test job and no dual-run
      parity job.
- [x] ``sase core health --json`` fails if ``sase_core_rs`` is missing
      or stale (verified: ``status="ok"`` on this workspace).
- [x] Golden-contract tests cover parser, query, agent scan, status,
      and Git helper output without live Python/Rust parity. The
      ``Golden Contract`` section in ``docs/rust_backend.md`` enumerates
      the test files; the Python ``*_python`` helpers remain as
      byte-for-byte references and the cross-language pairing is
      ``tests/test_core_*`` plus ``../sase-core/.../tests/``.
- [x] ``evaluate_query_many`` has either an accepted Rust path or an
      explicit documented deferral. (Documented deferral: Phase 8B handoff
      + ``query_facade.py`` module docstring + ``docs/rust_backend.md``
      operation-disposition list.)
- [x] ``docs/rust_backend.md`` documents post-Phase 8 rollback as a
      wheel/package fix, not an env-var workaround.

## Verification

- ``just install`` — succeeds (workspace ephemeral install rebuilt the
  Rust core editable).
- ``just check`` — green (``fmt`` (python+markdown) → ``lint``
  (keep-sorted/ruff/mypy/pyscripts/pyvision) → ``test``).
- ``just rust-check`` — green (``cargo fmt --check`` + ``clippy`` +
  ``cargo test --workspace`` in ``../sase-core``).
- ``just phase7-perf-check`` — green; the four ``must_beat_python:
  false`` anchors record ``python=n/a`` with a "baseline missing" note,
  and the absolute Rust ceiling check passes for every anchor. Report
  written to ``plans/202604/perf_artifacts/rust_backend_phase7_floor_check.json``.
- ``sase core health --json`` — ``status="ok"``,
  ``rust_extension_loaded=true``, ``probe_ok=true``.
- Final close-out greps (post-Phase 8G):
  - ``rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|RustBackendUnavailableError|is_rust_available|sase\.core\.backend|sase\.core\.dual_run" src/``
    — empty.
  - ``rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\.core\.backend|sase\.core\.dual_run|python_core_backend" tests/``
    — only ``tests/perf/bench_phase7_e2e.py`` matches, and that hit is
    the post-Phase-8 docstring noting the env var is gone.
  - ``rg "from sase\.core\.backend|from sase\.core\.dual_run" src/ tests/``
    — empty.

## Operation Disposition (final state)

11 ported surfaces — call ``sase_core_rs`` directly via
:func:`sase.core.rust.require_rust_binding`:

| Surface                    | Facade                  |
| -------------------------- | ----------------------- |
| `parse_project_bytes`      | `parser_facade.py`      |
| `parse_query`              | `query_facade.py`       |
| `scan_agent_artifacts`     | `agent_scan_facade.py`  |
| `read_status_from_lines`   | `status_facade.py`      |
| `apply_status_update`      | `status_facade.py`      |
| `plan_status_transition`   | `status_facade.py`      |
| `parse_git_name_status_z`  | `git_query_facade.py`   |
| `parse_git_branch_name`    | `git_query_facade.py`   |
| `derive_git_workspace_name`| `git_query_facade.py`   |
| `parse_git_conflicted_files`| `git_query_facade.py`  |
| `parse_git_local_changes`  | `git_query_facade.py`   |

7 Python-owned host surfaces — call their Python implementations
directly as host logic, not backend fallbacks:

| Surface                       | Facade                  | Reason                                                         |
| ----------------------------- | ----------------------- | -------------------------------------------------------------- |
| `parse_project_file`          | `parser_facade.py`      | File-path API; Rust binding consumes bytes                     |
| `build_query_context`         | `query_facade.py`       | Per-row helpers; intentionally unported                        |
| `evaluate_query`              | `query_facade.py`       | Per-row helpers; intentionally unported                        |
| `evaluate_query_with_context` | `query_facade.py`       | Per-row helpers; intentionally unported                        |
| `evaluate_query_many`         | `query_facade.py`       | Phase 8B deferral — prototype Rust 6-9× slower than Python batch |
| `build_changespec_graph_index`| `graph_index_facade.py` | Intentionally unported                                          |
| `transition_changespec_status`| `status_facade.py`      | Side-effecting host logic; planner inside it routes through Rust |

Python ``*_python`` helpers retained as byte-for-byte
golden-contract references (not backend fallbacks):
``read_status_from_lines_python`` and ``apply_status_update_python`` in
``sase.status_state_machine.field_updates``,
``plan_status_transition_python`` in
``sase.core.status_wire_conversion``,
``parse_git_*_python`` in ``sase.core.git_query_facade``,
``parse_query_python`` in ``sase.ace.query.parser``,
``build_query_context_python`` / ``evaluate_query_python`` /
``evaluate_query_with_context_python`` in ``sase.ace.query.context``.

## Files Touched

```
docs/rust_backend.md
sdd/research/202604/rust_backend_migration.md
src/sase/agent/names/_lookup.py
src/sase/core/agent_scan_facade.py
src/sase/core/git_query_facade.py
src/sase/core/health.py
src/sase/core/parser_facade.py
src/sase/core/query_facade.py
src/sase/core/status_facade.py
src/sase/status_state_machine/transitions.py
tests/test_core_agent_scan.py
tests/test_core_facade/test_query.py
tests/test_core_git_query.py
plans/202604/rust_backend_phase8_phase8g_handoff.md   (this file)
```

## What's next

Phase 8 is closed. Forward work options (none of which are required by
Phase 8 itself):

1. **Phase 9 — server surface for web/mobile.** The Rust crate is now
   the only implementation of parsing, querying, and scanning, so a
   ``sase-server`` binary in ``../sase-core`` plus a uniffi-bound static
   lib for mobile is unblocked. Do not start without an explicit
   product requirement; the auth / data-residency questions reshape the
   design.
2. **``evaluate_query_many`` re-port.** Phase 8B's deferral stays in
   force until a Rust path either accepts a reusable corpus payload or
   a Python-side wire cache amortises the per-call ``ChangeSpecWire``
   reconstruction. Target: beat the existing optimised Python batch
   median on the Phase 7B synthetic workloads (1k / 10k specs).
3. **``BackendChoice`` enum cleanup.** ``tests/perf/phase7/metadata.py``
   still exposes ``DEFAULT_PYTHON`` / ``EXPLICIT_PYTHON`` / ``DEFAULT_RUST``
   / ``EXPLICIT_RUST`` because Phase 7C artifact filenames embed those
   tags. Once those historical artifacts are pruned (or an explicit
   decision to keep them is made), the Python-flavoured enum values can
   be deleted.
