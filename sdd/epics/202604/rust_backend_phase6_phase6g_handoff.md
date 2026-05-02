---
create_time: 2026-04-29 21:30:00
status: done
bead_id: sase-1b.7
---
# Rust Backend Phase 6G Handoff — CI Matrix, Parity Gate, And Release Smoke

## Scope landed in this phase

Phase 6G hardens the Phase 6F default flip with three CI guarantees:

1. **Two-backend test matrix.** A new `test-python-backend` job runs the
   pytest suite with `SASE_CORE_BACKEND=python` on the supported oldest
   and newest Pythons (3.12 and 3.14). The original `test` matrix keeps
   running the full 3.12/3.13/3.14 cross product on the default backend
   (Rust), so the explicit-Python path is exercised on the surface where
   it actually matters (Phase 7 escape hatch) without doubling the full
   matrix's wall-clock cost.
2. **Dual-run parity gate.** `tests/parity/dual_run_parity.py` exercises
   every shipped Rust binding under `SASE_CORE_DUAL_RUN=1`, reads the
   resulting `core_dual_run.jsonl`, and exits non-zero if any record
   reports `match: false` for an operation that should match exactly.
   The script drives the parser, query, agent-scan, status-planner, and
   git-query parser facades against the committed golden corpus
   (`tests/core_golden/myproj.gp`, `tests/_query_golden_corpus.py`) and
   the sanitized synthetic `~/.sase/projects` tree from
   `tests/agent_scan_golden/fixture_builder.build_fixture_tree`. CI
   uploads the JSONL log and per-operation summary as the
   `parity-artifacts` artifact so a regression can be inspected
   post-hoc.
3. **Release smoke diagnostics.** `publish.yml`'s `install-smoke` job
   already proved that a built `sase` wheel installs into a fresh venv
   and that both `sase core health --json` flavors (default-Rust /
   explicit-Python) succeed. Phase 6G adds a `if: failure()` step that
   re-runs the health checks, dumps `pip list`, prints
   Python/platform/architecture, and probes `sase_core_rs.__file__`
   plus `__version__` so the build log is sufficient to diagnose a
   missing-wheel or ABI-mismatch failure without a manual repro.

## Matrix shape decision

The plan permitted shrinking the full backend × Python cross product
when cost demanded it. Phase 6G keeps the full Python-version matrix
on the default-Rust job because:

- The Rust binding ships as wheels for every supported Python (Phase
  6A) and the dependency resolves on every leg, so the full matrix is
  the strongest signal on the path users actually take by default.
- The explicit-Python path's behavior is independent of which
  CPython interpreter version it runs under in the same way the
  default-Rust path is — a focused 3.12/3.14 leg keeps the regression
  surface covered while halving CI time relative to a full duplicate
  matrix. Coverage upload still runs from the 3.12 default-Rust leg.

## Documented parity gap (`parse_project_bytes`)

The dual-run record for `parse_project_bytes` will always report
`match: false` against the golden corpus because the Python parser does
not track `source_span.end_line` (Phase 1F decision —
`plans/202604/rust_backend_phase1_handoff.md`). The Rust parser fills
in real end positions; `tests/test_core_parity_smoke.py` is the
existing parity assertion and applies the documented end-line
normalization before comparing JSON shapes byte-for-byte.

The Phase 6G parity gate therefore treats `parse_project_bytes` as
**documented divergence**: the gate requires the operation to produce
at least one dual-run record (so a binding that crashes or fails to
register would still fail the gate) but does not require `match: true`
on those records. `DOCUMENTED_DIVERGENCE` in
`tests/parity/dual_run_parity.py` is the single source of truth for
this set; adding to it requires a code comment pointing to the parity
test that pins the alternative contract.

## What changed

### `.github/workflows/ci.yml`

- Renamed the existing `test` job's pytest step to "Run tests
  (default backend = Rust)" and added a comment block describing the
  Phase 6G matrix shape.
- Added `test-python-backend`: a 3.12/3.14 matrix with
  `SASE_CORE_BACKEND=python` set at the job level. Uses `just test`
  rather than `just test-cov` because coverage already comes from the
  default-Rust leg.
- Added `parity-gate`: installs the project, runs the new dual-run
  parity script, and uploads `parity-artifacts/` (the JSONL log and
  the JSON summary) using `actions/upload-artifact@v4`. The upload
  step is `if: always()` so a parity failure still archives the
  diagnostic record.

### `.github/workflows/publish.yml`

- Appended a `Report extension diagnostics on failure` step under
  `install-smoke`. It runs only when an earlier step in the job
  failed (`if: failure()`) and prints the two health-check JSONs,
  `pip list`, Python/platform info, and the
  `sase_core_rs.__file__` / `__version__` probe in collapsible
  GitHub log groups. Each command is `|| true` so the diagnostic
  step itself never masks the original failure.

### `Justfile`

- New `parity-check` target: `just parity-check [-- args]` invokes
  `tests/parity/dual_run_parity.py` with the project venv. Mirrors the
  existing `bench-*` targets so a contributor can reproduce CI's
  parity gate locally.

### `tests/parity/dual_run_parity.py` (new)

Standalone script (not a pytest test — placed under `tests/parity/`
to keep the home-tree fixture co-located with `tests/agent_scan_golden`,
and named without a `test_` prefix so pytest does not auto-collect
it). Behavior:

- Sets `SASE_CORE_DUAL_RUN=1` and `SASE_CORE_DUAL_RUN_LOG=<path>`,
  unsets `SASE_CORE_BACKEND` so the default-Rust dispatch path runs.
- Calls every shipped facade entry point on representative inputs:
  - `parser_facade.parse_project_bytes(myproj.gp)`
  - `query_facade.parse_query` and `evaluate_query_many` on each
    string in `tests._query_golden_corpus.GOLDEN_QUERIES`
  - `agent_scan_facade.scan_agent_artifacts` on the synthetic tree
    produced by `agent_scan_golden.fixture_builder.build_fixture_tree`
    (sanitized — no real `~/.sase/projects` data)
  - `status_facade.read_status_from_lines` /
    `apply_status_update` / `plan_status_transition` on lines from
    the golden project file plus a hand-built
    `StatusTransitionRequestWire`
  - `git_query_facade.parse_git_name_status_z`,
    `parse_git_branch_name`, `derive_git_workspace_name`,
    `parse_git_conflicted_files`, `parse_git_local_changes`
- Reads the JSONL log and prints a per-operation summary
  (`{ total, match, mismatch, errors }`).
- Exits non-zero with a punch-list of failures if any shipped
  operation produced zero records, any non-divergent operation has a
  mismatch, or any shipped operation logged a Rust-side exception.
- Optional `--summary-path` flag dumps the summary JSON for CI to
  archive.

## Verification

Locally (from `sase_100`):

```
just install
just parity-check
.venv/bin/pytest tests/test_core_parity_smoke.py
SASE_CORE_BACKEND=python .venv/bin/pytest tests/test_core_backend.py \
  tests/test_core_facade/test_backend_contract.py \
  tests/test_backend_indicator.py
just check
```

`just parity-check` reports `[parity] OK — 96 records, 12 shipped ops
all match`, with the documented `parse_project_bytes` divergence noted
inline. The summary JSON shows non-zero record counts for every
shipped operation:

```
parse_project_bytes:        1 record  (documented divergence)
parse_query:               38 records
evaluate_query_many:       38 records
scan_agent_artifacts:       1 record
read_status_from_lines:     4 records
apply_status_update:        2 records
plan_status_transition:     2 records
parse_git_name_status_z:    2 records
parse_git_branch_name:      2 records
derive_git_workspace_name:  2 records
parse_git_conflicted_files: 2 records
parse_git_local_changes:    2 records
```

CI itself is the source of truth for the full matrix on push.

## Behavior contract preserved

- No production code under `src/sase/` changed; the default-Rust flip
  from Phase 6F is unchanged.
- The dual-run policy is unchanged: both implementations run, the
  Python result is returned, and one record per call is appended to
  the JSONL log.
- The parity gate runs in its own CI job and never executes against a
  developer's `~/.sase/projects` tree (only the synthetic
  `tests/agent_scan_golden/fixture_builder` tree).

## Out of scope (handed to later subphases)

- **Phase 6H** — Documentation close-out and rollback playbook. The
  Phase 6G CI changes are referenced from the new
  `parity-gate` job and from `Justfile`; the wider rewrite of
  `docs/rust_backend.md` and `sdd/research/202604/rust_backend_migration.md`
  to reflect the production-default state, plus the formal rollback
  procedure, is Phase 6H's job.
- **Phase 7** — Backend matrix narrowing. Phase 6G keeps both backends
  exercised by CI through the Phase 6/7 escape-hatch window; Phase 7
  decides when the explicit-Python jobs and dual-run gate retire.

## Exit criteria

- [x] CI protects both default-Rust and explicit-Python modes (`test`
      job runs default-Rust on 3.12/3.13/3.14; new
      `test-python-backend` job runs `SASE_CORE_BACKEND=python` on
      3.12/3.14).
- [x] Dual-run parity has a zero-mismatch gate for the operations
      Phase 6 defaults to Rust (`parity-gate` job + the script's
      `SHIPPED_OPERATIONS` list); `parse_project_bytes` is gated on
      "produces records" only, with the documented Phase 1F gap and a
      pointer to `tests/test_core_parity_smoke.py`.
- [x] Publish workflow proves release artifacts install and start
      without a local Rust toolchain (existing default-Rust /
      explicit-Python health checks under `install-smoke`) and reports
      extension package / version / platform details on failure (new
      `if: failure()` diagnostic step).
- [x] CI does not rely on a developer's sibling `../sase-core`
      checkout — every job installs the project through `just install`
      which resolves `sase-core-rs` from the published wheel when no
      sibling repo is present.
