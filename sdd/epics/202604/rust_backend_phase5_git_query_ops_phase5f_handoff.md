---
create_time: 2026-04-29 19:20:13
bead_id: sase-1a.6
status: complete
---
# Rust Backend Phase 5F Handoff: Close-Out, Documentation, and Rollout Decision

## Scope

Phase 5F closes Phase 5 (Git query ops) with the documentation and
research updates the original plan deferred to this subphase, a full
verification pass on the Phase 5E provider integration, and the rollout
decision for the five Git query parsers. No production code is
restructured here — Phase 5C/5D/5E left the dispatch wiring, the Rust
parsers, and the `GitQueryOpsMixin` provider integration in their final
shape; this phase only ratifies what landed and writes it down.

## Decision: keep `SASE_CORE_BACKEND` default `python`. Phase 5 ships as opt-in Rust.

The Rust Git query parsers are shipped, parity-tested under the dual-run
facade, and opt-in via `SASE_CORE_BACKEND=rust`. Default-flipping the
backend to `rust` for Git query operations is not justified by Phase 5
evidence:

- Phase 5A and the Phase 5E re-bench both show that subprocess fork+exec
  dominates end-to-end Git query cost. The Rust parser is neutral
  (within noise) on every measured workload — `parse_git_name_status_z`
  on synthetic_large is ~9 ms in either backend; the `end_to_end_500`
  parse-only path is ~722 µs Python vs ~705 µs Rust against ~10.5 ms of
  subprocess time; the four small normalizers are sub-microsecond on
  both backends.
- The shared-core hygiene goal (Phase 5A motivation) is met regardless
  of which backend is the default — the Rust crate now owns the same
  parsers and exposes them through PyO3 plus the standalone
  `tests/git_query_parity.rs` parity suite for any future Rust caller
  (server, mobile, web).
- The Phase 6 default-flip prerequisites (wheel build, packaging story,
  full release cycle with `SASE_CORE_DUAL_RUN=1` in CI on the golden
  corpus and a sanitized home-tree fixture) still need to land first.
  Phase 5 does not change those prerequisites.

No per-operation default-Rust override is recommended for any of the
Phase 5 operations.

`gix` remains out of scope. Phase 5A's recommendation A (parse `git`
output in Rust, do not replace the subprocess) was correct: there is no
hot caller invoking these helpers in a tight loop, and the gap between
parse cost and subprocess cost is small enough that ripping out `git`
would only matter on workloads that do not exist on the Git query
surface today. If a future profile flags one, open a separate epic
against the concrete workload — do not reopen Phase 5.

## What landed in Phase 5F

### Verification

All steps from the plan's Phase 5F verification list pass on this
workspace:

```bash
just install
just rust-install
just rust-check                                                          # cargo fmt + clippy + test
.venv/bin/pytest tests/ace/deltas/test_diff_name_status_git.py \
  tests/test_vcs_provider_git_query.py \
  tests/test_vcs_provider_git_sync.py \
  tests/test_core_git_query.py                                           # 75 passed
SASE_CORE_BACKEND=rust .venv/bin/pytest \
  tests/ace/deltas/test_diff_name_status_git.py \
  tests/test_vcs_provider_git_query.py \
  tests/test_vcs_provider_git_sync.py \
  tests/test_core_git_query.py                                           # 75 passed
SASE_CORE_DUAL_RUN=1 .venv/bin/pytest \
  tests/ace/deltas/test_diff_name_status_git.py \
  tests/test_vcs_provider_git_query.py \
  tests/test_vcs_provider_git_sync.py \
  tests/test_core_git_query.py                                           # 75 passed
just check                                                               # fmt + lint + test all green
```

`cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets --
-D warnings`, and `cargo test --workspace` in `../sase-core` all pass
through `just rust-check`.

### Dual-run parity (`~/.sase/perf/core_dual_run.jsonl`)

Counted across the active dual-run log on this workstation, restricted
to records produced on or after the Phase 5E session start
(`2026-04-29T19:00:00Z`):

```
parse_git_name_status_z:    820 records, 0 mismatches
parse_git_branch_name:      880 records, 0 mismatches
derive_git_workspace_name: 1100 records, 0 mismatches
parse_git_conflicted_files: 220 records, 0 mismatches
parse_git_local_changes:    440 records, 0 mismatches
                          ----- 
                            3460 records, 0 mismatches total
```

Combined with the prior parity logs for parser, query, agent scan, and
status planner, the parity gate is satisfied for the Phase 5 rollout
decision. Dual-run sample records start at timestamp
`2026-04-29T19:10:59Z` and span the Phase 5E `pytest` runs of
`tests/ace/deltas/test_diff_name_status_git.py`,
`tests/test_vcs_provider_git_query.py`,
`tests/test_vcs_provider_git_sync.py`, and `tests/test_core_git_query.py`
under `SASE_CORE_DUAL_RUN=1`.

(The same log file shows pre-existing mismatches for `parse_project_bytes`
and `scan_agent_artifacts` from earlier sessions on this workstation;
those are unrelated to Phase 5 — the Phase 5 helpers contribute zero
mismatches across all 3460 records produced after Phase 5E started — and
Phase 5F follows the cross-phase guardrail to leave unrelated parity
state alone.)

### Bench evidence

The Phase 5F decision uses the Phase 5E bench artifact
(`plans/202604/perf_artifacts/bench_git_query_ops_phase5e.json`)
unchanged. Phase 5F did not re-bench because Phase 5E already recorded
the three runs the plan asks for (Python facade, Rust facade, dual-run)
on the production code path, and there is no source change in Phase 5F
that would invalidate those measurements. Median values restated for
the rollout decision:

#### `parse_git_name_status_z` (synthetic streams)

| workload          | size      | Python facade | Rust facade |
| ----------------- | --------- | ------------- | ----------- |
| synthetic_small   |  1.3 KB   |  ~41 µs       |  ~9 µs      |
| synthetic_medium  | ~12 KB    | ~120 µs       | ~93 µs      |
| synthetic_large   | ~605 KB   | ~9.0 ms       | ~9.0 ms     |

#### Other normalizers (sub-microsecond on both backends)

| helper                       | Python facade | Rust facade |
| ---------------------------- | ------------- | ----------- |
| `parse_git_branch_name`      |  ~0.4 µs      |  ~0.5 µs    |
| `derive_git_workspace_name`  |  ~0.7 µs      |  ~0.8 µs    |
| `parse_git_conflicted_files` |  ~0.5 µs      |  ~0.7 µs    |
| `parse_git_local_changes`    |  ~0.4 µs      |  ~0.5 µs    |

The Rust binding overhead (Python↔Rust dict round-trip + GIL hop) is
larger than the parser cost itself on the four small normalizers.
This is the same pattern as the Phase 4 line helpers — the shared-core
gain is correctness and schema reuse, not microseconds.

#### End-to-end (`vcs_diff_name_status` against a temporary git repo)

| workload          | parse-only median | subprocess time |
| ----------------- | ----------------- | --------------- |
| end_to_end_50     | ~37–73 µs         | ~2.7 ms         |
| end_to_end_500    | ~705–722 µs       | ~10.5 ms        |

The Rust parser shaves a few percent off `end_to_end_50` parse cost but
is dwarfed by the subprocess. `end_to_end_500` is parser-tied because
both backends sit on the same `git diff --name-status -z` invocation.

#### Dual-run overhead

Dual-run roughly doubles parse cost as expected (both implementations
run plus the comparison and JSONL append). The 3460 records logged
across this session reflect the Phase 5E pytest runs; mismatch count is
zero.

### Documentation updates

- `docs/rust_backend.md` — added Phase 5E and Phase 5F roadmap entries.
  Phase 5E entry captures the `GitQueryOpsMixin` provider integration,
  the public hookimpl shape preservation, and the Phase 5E bench
  artifact location. Phase 5F entry captures the verification pass,
  the dual-run parity counts, the rollout decision, and the rollback
  path. The operations preamble already listed the five Git query
  parsers from earlier subphases — no change needed there.
- `sdd/research/202604/rust_backend_migration.md` — updated the
  "2026-04-29 update" header from "Phases 0–4 of this plan have shipped"
  to "Phases 0–5 of this plan have shipped", expanded the operations
  list to include the five Git query parsers, added a bullet covering
  the `GitQueryOpsMixin` provider rewire, rewrote the
  "Phase 5 — Git query ops" section from the recommendation A/B/C
  decision sketch to *(complete; opt-in, default `python`)* with the
  shipped helper table, what stayed Python and why, the bench summary,
  the rollout decision, and an explicit "`gix`?" note. Updated the
  Phase 8 "anything Phase 4+" reference to "anything Phase 6+" so the
  cleanup ordering reflects Phase 5 closure.

### CI and Justfile

No durable CI or Justfile additions are required by Phase 5F. The
existing `just bench-core`, `just bench-agent-scan`,
`just bench-status-state-machine`, `just rust-check`, and `just check`
targets cover the Phase 5 verification matrix; the Phase 5A-era
`tests/perf/bench_git_query_ops.py` is run on demand against the
production facade (no Justfile alias is necessary because Phase 5
benches are not on the rollout regression floor). If Phase 7 codifies
a per-op regression floor, the Git query parsers can be added to that
suite at the same time as the parser/query/agent-scan helpers.

## Files changed in `sase_100`

- `docs/rust_backend.md` — Phase 5E and Phase 5F roadmap entries.
- `sdd/research/202604/rust_backend_migration.md` — Phase 0–5 update
  header, expanded operations list, `GitQueryOpsMixin` rewire bullet,
  Phase 5 section rewrite, Phase 8 cleanup-ordering update.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5f_handoff.md`
  (this file).

## Commands run

```bash
just install
just rust-install
just rust-check
.venv/bin/pytest tests/ace/deltas/test_diff_name_status_git.py \
  tests/test_vcs_provider_git_query.py \
  tests/test_vcs_provider_git_sync.py \
  tests/test_core_git_query.py
SASE_CORE_BACKEND=rust .venv/bin/pytest \
  tests/ace/deltas/test_diff_name_status_git.py \
  tests/test_vcs_provider_git_query.py \
  tests/test_vcs_provider_git_sync.py \
  tests/test_core_git_query.py
SASE_CORE_DUAL_RUN=1 .venv/bin/pytest \
  tests/ace/deltas/test_diff_name_status_git.py \
  tests/test_vcs_provider_git_query.py \
  tests/test_vcs_provider_git_sync.py \
  tests/test_core_git_query.py
just check
```

## Phase 5 completion check

- ✅ Git query wire contract documented and parity-tested (Phase 5B,
  reaffirmed in Phase 5F dual-run sweep).
- ✅ Rust implements the five pure parsers (Phase 5C) with byte-for-byte
  parity against the Python golden corpus
  (`tests/git_query_parity.rs`).
- ✅ Python routes the five helpers through Rust under
  `SASE_CORE_BACKEND=rust` (Phase 5D); missing bindings raise
  `RustBackendUnavailableError`.
- ✅ `GitQueryOpsMixin` consumes the facade for every parsing/
  normalization step (Phase 5E); subprocess invocation, timeouts, and
  mutating sync paths stay on Python by design.
- ✅ Dual-run works without duplicating side effects: the parsers are
  pure, so `SASE_CORE_DUAL_RUN=1` runs both implementations on every
  dispatched call and logs comparison records to
  `~/.sase/perf/core_dual_run.jsonl`.
- ✅ Benchmark and parity evidence recorded
  (`bench_git_query_ops_phase5e.json` for the three-backend bench;
  3460 dual-run records, zero mismatches in
  `~/.sase/perf/core_dual_run.jsonl`).
- ✅ Docs/research state the rollout decision: default backend stays
  `python`; Phase 5 ships opt-in. Rollback is `SASE_CORE_BACKEND=python`
  (the default) with no provider-side change.

## Rollback plan

Python implementations remain available as
`git_query_facade.parse_git_name_status_z_python`,
`parse_git_branch_name_python`, `derive_git_workspace_name_python`,
`parse_git_conflicted_files_python`, and `parse_git_local_changes_python`.
If a binding bug surfaces in production, set `SASE_CORE_BACKEND=python`
(this is already the default) to restore pure-Python behavior with no
provider-side change. A more aggressive rollback — temporarily marking
specific helpers as `rust_unavailable="python"` so even Rust mode falls
back per-op — is supported by the dispatcher contract and only needs a
one-line registration change in `git_query_facade.py`.

## Known limits and follow-up recommendations

- **Per-call wire round-trip cost on small inputs.** The four
  normalizers (`parse_git_branch_name`, `derive_git_workspace_name`,
  `parse_git_conflicted_files`, `parse_git_local_changes`) all pay a
  Python↔Rust round-trip that is larger than their actual work. They
  remain valuable for shared-core hygiene (one canonical
  implementation across Python/Rust/uniffi/wasm) but should not be
  cited as performance wins.
- **Default-flip blockers (Phase 6) inherited from Phases 3H and 4F.**
  Wheel build, packaging story, the `is_workflow_complete` regression,
  and the dual-run-in-CI gate all still need to be solved before any
  default-flip discussion. Phase 5 does not change those prerequisites.
- **Mutating Git ops are intentionally not in scope.** Anyone tempted
  to extend Phase 5 into checkout/sync/rebase/branch-rename/commit
  should open a separate epic; the cross-phase guardrails for Phase 5
  exclude that work because the gain is dominated by `git`'s own work
  and the surface is large.
- **Bench regression floor not yet wired.** Phase 7's "regression
  floor in CI" work could pick up the Phase 5E bench artifact as a
  reference point. Until then, the Phase 5 bench is a one-shot
  measurement, not a CI gate.

## Phase 6+ pointers

- The next likely Rust port is the graph-index / agent-status state
  machine, both of which surface in Phase 4 and Phase 6 follow-ups.
  Re-profile the TUI cold-open + `sase ace` refresh on the user's home
  tree under `SASE_CORE_BACKEND=rust` before committing to either, so
  the choice is grounded in evidence rather than the next-most-obvious
  candidate.
- The Phase 5 wire-contract pattern (small dataclass for the only
  structured shape, primitives elsewhere; pure parsers with no host
  services; serde-compatible Rust mirror; golden parity tests; dual-
  run logging on the public tuple shape) generalizes to any future
  pure-parser port. Reuse it when porting additional Git output or
  wire-format parsers.
- Phase 6 (default-backend rollout) inherits the Phase 5 evidence
  unchanged. Phase 5 produces a *neutral* signal: the parser is shared
  across implementations and parity-tested, but the user-visible win
  is dominated by subprocess cost. Phase 6 should weigh this alongside
  the Phase 3 (1.55× home-tree win) and Phase 4 (~5–7 % overhead)
  signals when deciding whether to ship `rust` as the default.
