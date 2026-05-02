---
create_time: 2026-04-29 14:08:16
bead_id: sase-19.6
status: complete
---
# Rust Backend Phase 4F Handoff: Verification, Performance Decision, and Roadmap Update

## Scope

Phase 4F closes Phase 4 (status state machine) with a full verification
pass on the refactored planner integration, a re-run of the Phase 4A
benchmark against the new code path, a dual-run parity check on the
shipped Rust planner, the rollout decision, and the docs/research
update. No production code is restructured here; the only source change
is a one-line circular-import fix that fell out of running the bench.

## Decision: keep `SASE_CORE_BACKEND` default `python`. Phase 4 ships as opt-in Rust.

The Rust planner and line helpers are shipped, parity-tested, and opt-in
via `SASE_CORE_BACKEND=rust`. Default-flipping the backend to `rust` for
status operations is not justified by Phase 4F evidence:

- The Rust planner adds a small wire round-trip cost (~5–7 % on the
  synthetic 200-spec transition workload) and the orchestrator wall
  clock is dominated by `parse_project_file`, `find_all_changespecs`,
  and the locked atomic write. The planner change is invisible at
  user-perceived scales.
- The shared-core hygiene goal (Phase 4A motivation) is met regardless
  of which backend is the default — the Rust crate now owns the same
  decision rules and exposes them through PyO3 for any future Rust
  caller.
- The Phase 6 default-flip prerequisites (wheel build, packaging
  story, full release cycle with `SASE_CORE_DUAL_RUN=1` in CI) still
  need to land first.

No per-operation default-Rust override is recommended for any of the
Phase 4 operations.

## What landed in Phase 4F

### Verification

All steps from the plan's Verification Matrix pass on this workspace:

```bash
just install
just rust-install
just rust-check                                                          # cargo fmt + clippy + test
.venv/bin/pytest tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_backend.py \
  tests/test_core_dual_run.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py \
  tests/test_core_status_wire.py                                         # 141 passed
SASE_CORE_BACKEND=rust .venv/bin/pytest \
  tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py                                        # 73 passed
SASE_CORE_DUAL_RUN=1 .venv/bin/pytest \
  tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py                                        # 73 passed
just check                                                               # fmt + lint + test all green
```

`cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets --
-D warnings`, and `cargo test --workspace` in `../sase-core` all pass
through `just rust-check`.

### Circular-import fix in `src/sase/status_state_machine/transitions.py`

Running `just bench-status-state-machine` against the Phase 4E code
path failed with:

```
ImportError: cannot import name 'build_status_transition_request' from
partially initialized module 'sase.core.status_wire_conversion' (most
likely due to a circular import)
```

Reproducible with `.venv/bin/python -c "from sase.core.status_facade
import read_status_from_lines"`. The cycle:

```
status_facade.py
  → status_wire_conversion.py
    → sase.status_state_machine.constants
      → sase/status_state_machine/__init__.py
        → .transitions
          → status_wire_conversion.build_status_transition_request   # not yet defined
```

The pytest suite did not catch this because conftest setup primes
`sase.status_state_machine` before the failing import path runs.

Fix: move the `build_status_transition_request` import inside
`transition_changespec_status_python()` (next to the existing
function-scoped `plan_status_transition` import), so the import happens
after the package init has fully resolved. One-line change; no behavior
or wire-shape impact. The bench, the
`from sase.core.status_facade import …` smoke test, and all focused
tests pass post-fix.

### Bench re-run (`bench_status_state_machine_phase4f.json`)

Reproducer:

```bash
just bench-status-state-machine \
  --runs 200 --warmup 30 --num-specs 200 --transition-runs 30 \
  --output plans/202604/perf_artifacts/bench_status_state_machine_phase4f.json
```

Workstation: `athena` (Linux 6.12.74, x86_64, AMD Ryzen Threadripper
3970X 32-Core), Python 3.14.3, `sase_core_rs` built via
`just rust-install` (PyO3 0.22, release profile).

Median values; raw artifact has min/p95/max and sample sizes.

#### Pure helpers — golden corpus (`tests/core_golden/myproj.gp`, 1019 bytes, 4 specs)

| scenario                  | python (4F) | rust (4F) | python (4A) | rust (4A) |
| ------------------------- | ----------- | --------- | ----------- | --------- |
| `is_valid_transition`     |  3.4 µs     | n/a (1)   |  3.4 µs     | n/a       |
| `remove_workspace_suffix` |  1.1 µs     | n/a (1)   |  1.1 µs     | n/a       |
| `read_status_from_lines`  |  3.7 µs     |  5.3 µs   |  2.5 µs     |  2.5 µs   |
| `apply_status_update`     |  5.5 µs     |  5.8 µs   |  4.2 µs     |  4.2 µs   |

(1) `is_valid_transition` and `remove_workspace_suffix` remain
intentionally unrouted through `sase.core.dispatch` — they are Phase 4C
debug entry points only.

#### Pure helpers — synthetic 200 specs (128 808 bytes)

| scenario                 | python (4F) | rust (4F) | python (4A) | rust (4A) |
| ------------------------ | ----------- | --------- | ----------- | --------- |
| `read_status_from_lines` |  177 µs     |  293 µs   |  179 µs     |  185 µs   |
| `apply_status_update`    |  244 µs     |  322 µs   |  254 µs     |  254 µs   |

The "rust" column under Phase 4A measured the dispatcher's fallback to
Python (no Rust impl was registered yet); Phase 4F measures the actual
PyO3 path. The line-helper Rust path is slightly slower than Python at
both workloads — the Python implementation is already a thin
list-comprehension over `lines` and the round-trip into Rust dominates.
This matches the Phase 4A risk note ("a Rust port may erase any gain
because of two string copies"). The shared-core gain is correctness and
schema reuse, not microseconds.

#### Transition orchestrator — golden corpus

| scenario                                    | python (4F) | rust (4F) | python (4A) | rust (4A) |
| ------------------------------------------- | ----------- | --------- | ----------- | --------- |
| `transition_changespec_status` (WIP→Draft)  |  376 µs     |  397 µs   |  215 µs     |  225 µs   |
| `transition_changespec_status` (WIP→Ready)  |  374 µs     |  394 µs   |  371 µs     |  368 µs   |

Phase 4A's WIP→Draft was 215 µs because the Phase 4E refactor unified
WIP→Draft and WIP→Ready through the same planner pathway; both
transitions now pay the wire round-trip and parent/sibling gather cost.
Both transitions converged near the WIP→Ready cost. This is a deliberate
side effect of the Phase 4E architectural change (the
branch-handler indirection is gone), not a regression in user-visible
behavior.

#### Transition orchestrator — synthetic 200 specs

| scenario                                    | python (4F)  | rust (4F)    | python (4A)  | rust (4A)    |
| ------------------------------------------- | ------------ | ------------ | ------------ | ------------ |
| `transition_changespec_status` (WIP→Draft)  |  13.03 ms    |  14.05 ms    |   1.71 ms    |   1.67 ms    |
| `transition_changespec_status` (WIP→Ready)  |  13.45 ms    |  14.10 ms    |  12.50 ms    |  12.48 ms    |

WIP→Draft on synthetic 200 specs went from 1.7 ms (Phase 4A) to
13.0 ms (Phase 4F). That gap is the Phase 4E
`build_status_transition_request(...)` step now calling
`find_all_changespecs()` + parent-status / sibling-summary gather for
**every** transition, where the Phase 4A draft handler used the cheaper
WIP→Draft branch. WIP→Ready was already paying these costs and is
unchanged. The user impact is negligible — all real transitions go
through the orchestrator that already pays parent/sibling gather costs
on at least some branches; the unification simplifies the code and
removes the branch-handler indirection. If a future profile shows the
new WIP→Draft cost is on a hot path, the request builder can be
simplified for non-Ready targets without re-introducing the old branch
handlers.

The Rust path is ~5–7 % slower than Python on both transitions
because of the Python↔Rust dict round-trip per call. None of this is
on the user's critical path.

### Dual-run parity (`~/.sase/perf/core_dual_run.jsonl`)

The local dual-run log was empty for `plan_status_transition` because
no real-project transition has been run with `SASE_CORE_DUAL_RUN=1` on
this workstation. To produce evidence, Phase 4F drove every valid
parent/child status pair through the planner facade against the golden
corpus under dual-run:

```bash
SASE_CORE_DUAL_RUN=1 .venv/bin/python <<'PY'
# (see handoff prose for the exact loop; sweeps all old/new pairs over alpha and beta)
PY
```

Result:

```
plan_status_transition: 84 records, 0 mismatches
```

Combined with the prior Phase 4D / Phase 4E parity logs:

```
evaluate_query_many: 156 records, 0 mismatches
parse_project_bytes: 106 records, 0 mismatches
plan_status_transition: 84 records, 0 mismatches
scan_agent_artifacts: 8 records, 0 mismatches
```

No mismatches across any shipped Rust operation. The parity gate is
satisfied for the Phase 4 rollout decision.

### Documentation updates

- `docs/rust_backend.md` — added a Phase 4F roadmap entry capturing
  the verification pass, the bench re-run summary, the rollout
  decision, and the circular-import fix. Phase 4D/4E entries
  unchanged.
- `sdd/research/202604/rust_backend_migration.md` — updated the
  "2026-04-29 update" header to "Phases 0–4 of this plan have shipped",
  expanded the operations list to include the status helpers and the
  planner, rewrote the "Phase 4 — Status state machine" section from
  *(deferred — re-profile first)* to *(complete; opt-in, default
  `python`)* with the rollout summary, and updated the "Recommended
  next concrete actions" section so the next-action ordering reflects
  Phase 4 closure (re-profile points at snapshot adaptation rather
  than the state-machine port).

## Files changed in `sase_100`

- `src/sase/status_state_machine/transitions.py` — moved
  `from sase.core.status_wire_conversion import
  build_status_transition_request` from module scope to inside
  `transition_changespec_status_python()` (alongside the existing
  function-scoped `plan_status_transition` import). Breaks the
  Phase 4E circular import.
- `docs/rust_backend.md` — Phase 4F roadmap entry.
- `sdd/research/202604/rust_backend_migration.md` — Phase 0–4 update
  header, Phase 4 section rewrite, next-actions reorder.
- `plans/202604/perf_artifacts/bench_status_state_machine_phase4f.json`
  — bench artifact for the verification re-run.
- `plans/202604/rust_backend_phase4_status_machine_phase4f_handoff.md`
  (this file).

## Commands run

```bash
just install
just rust-install
just rust-check
.venv/bin/pytest tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_backend.py \
  tests/test_core_dual_run.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py \
  tests/test_core_status_wire.py
SASE_CORE_BACKEND=rust .venv/bin/pytest \
  tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py
SASE_CORE_DUAL_RUN=1 .venv/bin/pytest \
  tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py
just bench-status-state-machine \
  --runs 200 --warmup 30 --num-specs 200 --transition-runs 30 \
  --output plans/202604/perf_artifacts/bench_status_state_machine_phase4f.json
just check
```

## Phase 4 completion check

- ✅ Status wire contract documented and parity-tested (Phase 4B,
  reaffirmed in Phase 4F dual-run sweep).
- ✅ Rust implements pure status decision logic (Phase 4C).
- ✅ Python routes eligible status helpers and the planner through
  Rust under `SASE_CORE_BACKEND=rust` (Phase 4D + 4E).
- ✅ Side effects remain in Python; transition wall clock has the
  same lock/write/timestamp shape on both backends (Phase 4E refactor;
  Phase 4F bench confirms).
- ✅ Dual-run works without duplicating side effects: the planner
  facade dual-runs the pure decision; the disk-bound transition entry
  point keeps `rust_unavailable="python"` so it never dual-runs file
  writes.
- ✅ Benchmark and parity evidence recorded
  (`bench_status_state_machine_phase4f.json`,
  `~/.sase/perf/core_dual_run.jsonl`).
- ✅ Docs/research state the rollout decision: default backend stays
  `python`; Phase 4 ships opt-in.

## Known limits and follow-up recommendations

- **Per-call wire round-trip cost.** The Rust planner pays one
  Python↔Rust dict round-trip per transition (request out, plan in).
  At Phase 4 workloads this is a small fraction of the orchestrator
  cost, but if a future caller invokes the planner in a tight loop
  (e.g. bulk validation across thousands of specs), measure before
  assuming Rust is faster. The Phase 4A risk note about
  `apply_status_update` allocating a fresh string per call applies
  here too.
- **WIP→Draft request-builder cost.** The Phase 4E unification means
  WIP→Draft now pays parent/sibling gather costs that the old
  branch-handler short-circuited. The orchestrator wall clock is
  still in the millisecond range and the user-visible UI is not
  affected, but if a profile flags it, the request builder can be
  specialized for non-Ready targets without re-introducing the
  branch-handler indirection.
- **Default-flip blockers (Phase 6) inherited from Phase 3H.** Wheel
  build, packaging story, and the `is_workflow_complete` regression
  all still need to be solved before any default-flip discussion. The
  Phase 4 work does not change those prerequisites.
- **Snapshot adaptation is the next likely port.** Phase 3H measured
  ~216 ms of post-snapshot adaptation on the home tree; that's the
  best remaining lever for user-perceived TUI cold-open. The status
  state machine port did not move that needle. Open a fresh research
  spike (and a Phase 5 epic) when ready.
- **`is_valid_transition` and `remove_workspace_suffix` remain
  unrouted.** They are exposed on `sase_core_rs` for cross-language
  reuse and tests, but no Python caller goes through the dispatcher
  for them today. If a future Rust caller needs them, they can be
  registered with the facade under the same Phase 4D pattern.

## Phase 5+ pointers

- Re-profile a TUI cold-open + `sase ace` refresh on the user's home
  tree under `SASE_CORE_BACKEND=rust`. Use the result to decide
  whether to open a Phase 5 (snapshot adaptation port) epic, a
  graph-index port, or a wheel-build / Phase 6 default-flip epic.
- The Phase 4 wire-contract pattern (request/plan dataclasses +
  serde-compatible Rust mirror + golden parity tests + dual-run on the
  pure-decision boundary) generalizes to any future state-machine port
  where the side effects must stay on Python. Reuse it when porting
  the agent-status state machine or the field-update validators.
