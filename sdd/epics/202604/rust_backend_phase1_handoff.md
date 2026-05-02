---
create_time: 2026-04-29 06:30:00
status: done
bead_id: sase-16.6
---

# Rust Backend Phase 1F — Cross-Repo Parity Gate and Handoff

This doc closes Phase 1 of `plans/202604/rust_backend_phase1.md`. It records
what landed where, the parity contract between repos, the Phase 1E benchmark
posture, and a go/no-go on flipping `SASE_CORE_BACKEND=rust` to the default.

## Phase status

| Phase | Scope                                                          | Status                                                                                |
| ----- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 1A    | `../sase-core` workspace + wire types                          | landed in sase-core (`3b63869`); closed by `ebacae96` here                            |
| 1B    | `../sase-core` scalar parser                                   | landed in sase-core (`a04b697`)                                                       |
| 1C    | `../sase-core` section parser parity                           | landed in sase-core (`6e02ada`)                                                       |
| 1D    | `../sase-core` PyO3 binding + `sase_100` facade adapter        | binding in sase-core (`33e3278`); adapter wiring here in `43ffcff9`                   |
| 1E    | `sase_100` Justfile + end-to-end benchmark + packaging posture | benchmark example in sase-core (`8518b47`); `Justfile` and `bench_core_parse` in `8880108b`; lint cleanup in `2a68e676` and `f34f521b` |
| 1F    | this handoff + Python-side parity smoke test                   | this commit                                                                           |

The Rust-side parity gate
(`../sase-core/crates/sase_core/tests/golden_corpus_parity.rs`) is the
authoritative Rust check and runs under `cargo test --workspace`. The
Python-side smoke test added in this phase
(`tests/test_core_parity_smoke.py`) is the cross-repo gate: when
`sase_core_rs` is importable, both backends parse the in-tree golden corpus
and the JSON shapes are compared byte-for-byte after the documented
`source_span.end_line` normalization. The smoke test exercises both the
direct binding (`sase_core_rs.parse_project_bytes`) and the
`parser_facade.parse_project_bytes` route under `SASE_CORE_BACKEND=rust`,
so the Phase 1D adapter wiring (dict → `ChangeSpecWire` rehydration) is
also verified.

## Parity contract

The Rust parser produces the same `ChangeSpecWire` JSON shape as the Python
parser, with one intentional, documented deviation:

- `source_span.end_line` — Python's `changespec_to_wire` defaults
  `end_line == start_line` because the Python parser doesn't track end
  positions. Rust's parser tracks real end lines.

**Decision (Phase 1F): normalize at the parity boundary; do not backfill
Python end-line tracking.** Rationale:

1. The Python placeholder is internal to the wire-conversion shim, not the
   parser itself; replacing it would require either (a) a new pass over the
   parser's intermediate state, or (b) a post-parse line walk. Both are
   wasted work the moment the Rust backend becomes the default.
2. Real end-line behavior is exercised by Rust unit tests, by the
   Rust-side `golden_corpus_parity` test, and by the Python-side
   `test_rust_reports_real_end_line_beyond_python_placeholder` check in
   `tests/test_core_parity_smoke.py`.
3. Keeping the normalization at the boundary lets the
   `SASE_CORE_DUAL_RUN=1` match metric stay green without papering over a
   real divergence — the Rust direct/facade output is compared against the
   Python golden after normalization, and the Rust direct output is
   compared against itself before normalization to catch a
   silent-Python-style regression in Rust.

If a future caller ever depends on `end_line` being correct under the
Python backend, the recorded follow-up is "make `parse_project_file_python`
emit real end lines" — track it as a separate phase under whatever epic
flips the default.

## Dual-run logging

`SASE_CORE_DUAL_RUN=1` is the production canary. With the Phase 1D adapter
wired up, every `parser_facade.parse_project_bytes` call now compares
Python and Rust output and writes one record to
`~/.sase/perf/core_dual_run.jsonl`. Phase 1F does not flip the default
because dual-run has not yet been exercised over a release cycle on real
project files (only the in-tree golden corpus); a quiet stretch in the
canary log is the gate that should drive the eventual flip.

## Verification run (Phase 1F exit)

| Check                | Command                                                 | Result                          |
| -------------------- | ------------------------------------------------------- | ------------------------------- |
| Rust workspace tests | `cargo test --workspace` (in `../sase-core`)            | pass — 52 + 3 + 2 tests         |
| Python core tests    | `pytest tests/test_core_*.py tests/test_changespec*.py` | pass                            |
| Repo-wide gate       | `just check`                                            | pass on the changes in this CL  |

The Rust-side parity test
(`golden_corpus_parity::project_corpus_matches_python_golden_after_end_line_normalization`
and the archive variant) runs as part of `cargo test --workspace` above.
The Python-side parity smoke test added in this CL
(`tests/test_core_parity_smoke.py`) is skipped when `sase_core_rs` is not
installed, so a Python-only contributor's `just check` keeps passing.

## Benchmarks

Phase 1E shipped two benchmark harnesses:

- **Rust direct** — `cargo run --release --example bench_parse` from
  `../sase-core` (or `just rust-bench` from this repo). Times the pure
  Rust parser over the golden corpus and a synthetic multi-spec file.
  No Python in the loop.
- **End-to-end Python** — `tests/perf/bench_core_parse.py` (or
  `just bench-core`). Times Python direct, Python facade,
  `sase_core_rs.parse_project_bytes` direct, the facade through PyO3 +
  dict→`ChangeSpecWire` rehydration, and the `SASE_CORE_DUAL_RUN=1`
  overhead.

The end-to-end harness is the number that drives the default-flip
decision. Phase 1F does not record a single benchmark snapshot in this
doc on purpose: the numbers depend on the host's Rust toolchain and the
synthetic-corpus size, and a snapshot in markdown rots fast.
Contributors with the extension installed should run
`just bench-core --runs 5` and `just rust-bench` locally before any
default-flip CL.

## Go / no-go: default backend

**No-go for Phase 1.** The default remains `SASE_CORE_BACKEND=python`.

The parity story is in place — the Rust parser matches the Python golden
corpus byte-for-byte under the documented `end_line` normalization, both
in the `cargo test` gate and (when the extension is installed) in the
`sase_100` Python-side smoke test added by this commit. The Phase 1D
adapter is wired and Phase 1E's benchmark harness is on disk.

The default does not flip yet because:

1. **`SASE_CORE_DUAL_RUN=1` has not been exercised in CI for a release
   cycle.** Latent divergence in suffix types, drawer ordering, or exotic
   mentor entries needs a sustained quiet stretch on real project files
   before users see Rust output as the default.
2. **No CI job builds the wheel.** Phase 1E deliberately kept Rust out of
   the gate so Python-only contributors are unblocked. A default flip
   needs CI evidence that the extension builds reproducibly across the
   target platforms and that `bench-core` numbers do not regress on the
   Python side.
3. **The Rust extension is opt-in, not packaged.** A default flip without
   a packaged wheel would silently fall through to the Python backend
   for every user who hasn't run `just rust-install`, which is worse
   than the current explicit opt-in story.

The Python fallback remains tested. Pure-Python `pip install -e ".[dev]"`
and `just install` are unaffected — `sase_core_rs` is opt-in.

## Phase 2 handoff

Phase 2 is "query evaluation and graph index" per
`sdd/research/202604/rust_backend_migration.md`. Recommendation:

- **Phase 2 may proceed without paying parser-span debt first.** The
  `end_line` normalization at the parity boundary is the agreed steady
  state, not a debt to clear. Phase 2 inherits it for free because Phase
  2's wire types do not touch `source_span`.
- Once `SASE_CORE_DUAL_RUN=1` has been quiet on real project files for at
  least one release cycle, Phase 2 can model `Query` and
  `QueryEvalResult` in the Rust wire crate. Graph index follows as
  Phase 2B and is independent of query evaluation parser debt.
- **Do not start porting status transitions in Phase 2.** That phase needs
  its own design pass because file-rewrite semantics interact with
  filesystem locking that the wire contract doesn't currently express.
- Before Phase 2 starts, decide whether to add a CI job that builds the
  `sase_core_py` wheel and runs `pytest tests/test_core_parity_smoke.py`
  with `sase_core_rs` installed. That job is the prerequisite for any
  Phase 3 default flip; getting it stood up alongside Phase 2 keeps the
  feedback loop tight.

## File map

- `plans/202604/rust_backend_phase1_handoff.md` — this doc.
- `tests/test_core_parity_smoke.py` — Python-side parity gate, skipped
  when `sase_core_rs` is not installed.
- `../sase-core/crates/sase_core/tests/golden_corpus_parity.rs` — Rust
  side of the gate (already present from Phase 1C).
- `../sase-core/README.md` — cross-repo workflow docs (already present
  from Phase 1E).
- `tests/perf/bench_core_parse.py` — end-to-end Python benchmark harness
  (Phase 1E).
- `Justfile` — `rust-install`, `rust-test`, `rust-fmt-check`,
  `rust-clippy`, `rust-bench`, `rust-check`, `bench-core` targets
  (Phase 1E).
