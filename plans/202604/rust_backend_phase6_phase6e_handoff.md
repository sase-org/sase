---
create_time: 2026-04-29 16:57:00
status: done
bead_id: sase-1b.5
---
# Rust Backend Phase 6E Handoff — Resolve `is_workflow_complete` Regression

## Scope landed in this phase

Phase 6E pins `sase.agent.names._lookup.is_workflow_complete` to a
targeted Python traversal so the predicate no longer pays for a full
artifact-tree snapshot. The targeted path walks
`~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` directly and
only opens marker files whose `workflow_name` matches the queried name,
preserving every existing return-value semantic (missing root, root
dead-without-done, child liveness, dismissed-prefix, exact / workflow
match preference, parent-timestamp filtering). The path runs regardless
of `SASE_CORE_BACKEND`. `find_named_agent` is untouched and continues
to consume the snapshot facade — its access pattern reads multiple
record fields per match and benefits from the shared backend-dispatched
walk.

The default backend is **unchanged** — Python is still the default
through Phase 6E; the flip is Phase 6F.

## Why pin to Python instead of adding a Rust early-exit binding

The Phase 6E plan permitted either approach. The targeted Python
traversal won on three counts:

1. **It already eliminates the regression.** The micro-benchmark below
   shows the targeted path is ~3× faster than the snapshot-backed
   Python shape and ~2.6× faster than the snapshot-backed Rust shape
   on the synthetic workload. Adding a Rust early-exit predicate would
   trade one regression for a new PyO3 surface and another opportunity
   for parity drift.
2. **The predicate API is narrow.** A Rust binding would have to take
   a workflow name and reproduce the same liveness / done-marker
   logic; `is_process_alive` is currently Python-only because it pokes
   `/proc` and the project's process table. Pulling that into Rust
   crosses a plugin/process boundary the Phase 6 plan explicitly
   avoids.
3. **The Phase 6F flip is safer.** Defaulting to Rust while one shipped
   operation regresses on a real workload is exactly the situation
   Phase 6E exists to prevent. The pinned Python path makes the flip
   neutral for this predicate.

The handoff to a future phase: if profiling on a much larger artifact
tree (≫ 1200 records / 10 workflows) shows the targeted Python walk
becoming a bottleneck, a Rust early-exit predicate is still the
follow-up. The predicate API should stay scoped to "is workflow X
complete?" rather than the broader streaming primitive Phase 3G ruled
out.

## Behavior contract preserved

Every existing assertion in `tests/test_agent_names_workflow.py` still
holds:

- no workflow with the queried name → `None`
- running root, no done → `False`
- done root with all children done/dead → `True`
- live child without done → `False`
- root without `done.json`, no children → `False`
- root dead without `done.json`, all children done → `True`
- single root with done, no children → `True`
- children exist but no root found → `None`
- absent `~/.sase/projects` → `None`

A new parametrized test
(`test_backend_does_not_route_through_snapshot`) asserts the targeted
path is in effect under `SASE_CORE_BACKEND` ∈ {`python`, `rust`,
unset} by patching `sase.core.agent_scan_facade.scan_agent_artifacts`
to raise. Any future regression that re-routes the predicate through
the snapshot facade will fail this test loudly.

## Bench evidence

Workload: 6 projects × 200 artifacts = 1200 records, 10 workflows
(`wf_0`..`wf_9`), target = `wf_0`. Each agent gets a `workflow_name`
in `agent_meta.json`, a dead PID, a `stopped_at` timestamp, and a
`done.json` marker so liveness checks resolve as "dead, marked done".

Source: `tests/perf/bench_workflow_complete.py`
(JSON: `plans/202604/perf_artifacts/bench_workflow_complete_phase6e.json`).

| Backend mode | `is_workflow_complete` (Phase 6E) | snapshot-then-filter (pre-6E shape) |
| -------- | --------: | --------: |
| python   | 34 ms     | 102 ms |
| rust     | 34 ms     |  88 ms |
| dual_run | 33 ms     | 188 ms |

Reading the table:

- **Targeted Python path** is invariant across backends — it does not
  call `dispatch(...)` so backend selection has no effect.
- **Snapshot-then-filter** reproduces what the previous
  implementation paid: one full `scan_agent_artifacts` plus the same
  `workflow_name == name` filter.
- **Dual-run** doubles the snapshot cost because the dispatcher runs
  both implementations and records a comparison row. The targeted
  path is unaffected because it never enters the dispatcher.

The previous Phase 3H bench (`bench_agent_scan` on a 4×40 synthetic
workload) reported `is_workflow_complete` at 0.20 ms (Python) vs
0.61 ms (Rust). Those numbers measured the short-circuit path —
`Path.home()` was patched to a directory without a `.sase/projects`
subtree, so the predicate returned `None` before walking anything. The
new bench fixes the home patch by building under `<tmp>/.sase/projects`
and tagging every artifact with a workflow name, exposing the actual
regression Phase 6E was scoped to fix.

## Changes in this repo

- `src/sase/agent/names/_lookup.py`: `is_workflow_complete` rewritten
  to walk `Path.home() / ".sase" / "projects" / */artifacts/ace-run/*`
  directly. Module docstring updated to call out the asymmetry —
  `find_named_agent` keeps the snapshot path; `is_workflow_complete`
  pins to the targeted Python walk.
- `tests/test_agent_names_workflow.py`: new
  `test_backend_does_not_route_through_snapshot` parametrized over
  `python` / `rust` / unset backends. Patches
  `sase.core.agent_scan_facade.scan_agent_artifacts` to raise so the
  test fails loudly if a future change re-routes the predicate.
- `tests/perf/bench_workflow_complete.py` (new): one-shot Phase 6E
  micro-benchmark. Builds a workflow-tagged synthetic tree and times
  the targeted path against `snapshot_then_filter` under the three
  backend modes. Short option per repo convention for every flag.
- `plans/202604/perf_artifacts/bench_workflow_complete_phase6e.json`
  (new): JSON output of the run reported above.
- `docs/rust_backend.md`: Phase 6E roadmap entry added with the
  benchmark table, the pinned-Python rationale, and a note that the
  Rust early-exit binding is a future-phase option, not needed now.

## Tests run in this workspace

```
.venv/bin/pytest tests/test_agent_names_workflow.py
.venv/bin/pytest -k "agent_names or agent_ref_resolution \
  or agent_names_workflow or agents_handler or list_all_agents \
  or running_agents or agent_loader or workflow_states \
  or workflow_loaders or done_agent_loader \
  or core_facade or core_backend or dual_run or agent_scan"
.venv/bin/python tests/perf/bench_workflow_complete.py \
    -p 6 -n 200 -w 10 -r 5 -W 2 \
    -o plans/202604/perf_artifacts/bench_workflow_complete_phase6e.json
just check
```

The 14 focused workflow tests pass (11 existing + 3 new from the
parametrized backend test). The broader 356-test bucket the Phase 3H
handoff used as the regression net also passes. `just check` is green.

## Out of scope (handed to later subphases)

- `Phase 6F` — flipping `DEFAULT_BACKEND` to `Backend.RUST`. Phase 6E
  is the prerequisite "no known hot-path regressions" gate; the flip
  itself is Phase 6F's job.
- `Phase 6G` — full CI matrix and dual-run parity gate. The Phase 6E
  bench numbers are local; CI parity coverage is Phase 6G.
- `Phase 6H` — documentation close-out and rollback plan. The Phase 6E
  doc entry is a single roadmap item; the broader rewrite from
  "optional Rust backend" to "Rust is the default" is Phase 6H's job
  after the 6F flip.

## Exit criteria

- [x] `is_workflow_complete` is no slower under default Rust than the
      documented Python path. Both backends now share the same targeted
      Python walk, so the Phase 3H structural regression is removed
      rather than pinned-with-evidence.
- [x] Regression tests prove every documented return value
      (no-workflow → `None`, running root → `False`, done root + done
      children → `True`, live child without done → `False`, root
      without `done.json` and no children → `False`, root dead without
      `done.json` but all children complete → `True`, no root /
      children-only → `None`).
- [x] Backend selection does not route this operation through the
      snapshot path (new `test_backend_does_not_route_through_snapshot`).
- [x] Benchmark numbers recorded after the fix
      (`plans/202604/perf_artifacts/bench_workflow_complete_phase6e.json`,
      summarized in `docs/rust_backend.md`).
- [x] Handoff records whether a Rust early-exit API is still worth
      considering (answer: no for current workloads; revisit only if a
      future profile shows the targeted Python walk becoming a
      bottleneck on a much larger tree).
