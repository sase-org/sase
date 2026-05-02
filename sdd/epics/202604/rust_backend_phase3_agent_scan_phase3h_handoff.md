---
create_time: 2026-04-29
status: done
bead_id: sase-18.8
---

# Rust Backend Phase 3H — Verification, Rollout Decision, and Handoff

Closes Phase 3 of `plans/202604/rust_backend_phase3_agent_scan.md`. Records
the verification run, applies the research go gate to the Phase 3G/3H
benchmark numbers, and pins the default-backend decision.

## Decision: keep `SASE_CORE_BACKEND=python` as the default. Do not flip any operation to Rust by default.

The plan's research gate is "first usable batch under 100 ms, or total
scan at least 2× faster end to end after PyO3 conversion and Python
adaptation." On the worst real workload we have (`~/.sase/projects`,
6503 artifact records on the dev workstation), the Rust facade is
**1.55× faster** end-to-end than the Python facade — a real win, but
short of the 2× gate. The 100 ms first-frame gate is also not met at
that workload (Rust facade ~817 ms median end-to-end). Streaming was
already ruled out in Phase 3G, and per-operation Rust defaults do not
clear the 2× gate either — see "Per-operation gate" below.

The Rust path is **opt-in and works**: contributors with the sibling
`sase-core` built and installed get a measurable speedup via
`SASE_CORE_BACKEND=rust`, and the dual-run channel still flags any
parity drift. We just do not flip the default for an extension that
most contributors do not have built.

## Verification performed

```bash
just install
just rust-install
just rust-check                  # cargo fmt --all -- --check, clippy -D warnings, cargo test --workspace
just bench-agent-scan --projects 4 --per-project 50 --runs 5 \
    --warmup 2 --include-home --output /tmp/phase3h_bench.json
just check
```

Focused test buckets from the plan's Verification Matrix were also
run under both backends:

```bash
.venv/bin/pytest -k "agent_names or agent_ref_resolution \
  or agent_names_workflow or agents_handler or list_all_agents \
  or running_agents or agent_loader or workflow_states \
  or workflow_loaders or done_agent_loader \
  or core_facade or core_backend or dual_run or agent_scan"
# 309 passed, 1 skipped (Python backend, default)

SASE_CORE_BACKEND=rust \
  .venv/bin/pytest -k "<same selector minus parse_project_file_matches>"
# 276 passed, 1 skipped — see "Test isolation note" below
```

`just check` passes. `cargo fmt --all -- --check`,
`cargo clippy --workspace --all-targets -- -D warnings`, and
`cargo test --workspace` all pass in `../sase-core`.

### Test isolation note

Two `tests/test_core_facade.py` cases (`test_parse_project_file_matches_python_impl`,
`test_evaluate_query_many_dual_run_logs_comparison`) raise
`RustBackendUnavailableError` when `SASE_CORE_BACKEND=rust` is set
*globally* in the environment. This is by design from Phase 0 / 1:
`parse_project_file()` is documented as Python-only because the Rust
binding consumes bytes, and these tests exercise the dispatcher's
"no Rust impl registered" path via that operation. They are not
regressions from Phase 3 and pass under their intended invocation
(default backend or with the test's own monkeypatched env). The phase
3D / 3E / 3F focused buckets all pass under both backends.

## Bench evidence

Single-workstation run, master + this commit. `tests/perf/bench_agent_scan.py`
report at `/tmp/phase3h_bench.json`. Median values reported here.

### Synthetic small workload (4 projects × 50 artifacts = 200 records)

| Scenario                                | Median ms |
| --------------------------------------- | --------: |
| `scan_python_facade`                    |     22.89 |
| `scan_python_facade_no_prompt_steps`    |     17.58 |
| `scan_rust_to_dict`                     |     11.66 |
| `scan_rust_dict_to_wire`                |     15.10 |
| `scan_rust_facade`                      |     18.31 |
| Rust speedup vs Python facade           |    1.25×  |
| `find_named_agent` (Python backend)     |    178.72 |
| `find_named_agent_rust_backend`         |    169.12 |
| Rust speedup, name lookup               |    1.06×  |
| `is_workflow_complete` (Python backend) |      0.20 |
| `is_workflow_complete_rust_backend`     |      0.61 |
| Rust speedup, workflow complete         |   **0.33×** (Rust slower) |
| `list_running_agents_shared_snapshot`   |     17.21 |
| `list_all_agents_shared_snapshot`       |     18.95 |
| `tui_artifact_load`                     |      0.20 |

### Real home workload (`~/.sase/projects`, 6503 records, 59 projects)

| Scenario                                | Median ms |
| --------------------------------------- | --------: |
| `scan_python_facade`                    |   1263.15 |
| `scan_python_facade_no_prompt_steps`    |    844.02 |
| `scan_rust_to_dict`                     |    685.11 |
| `scan_rust_dict_to_wire`                |    778.37 |
| `scan_rust_facade`                      |    816.77 |
| Rust speedup vs Python facade           |    1.55×  |
| `list_running_agents_shared_snapshot`   |    842.38 |
| `list_all_agents_shared_snapshot`       |    849.32 |

### Applying the research gate

| Workload          | First-frame (≤ 100 ms)  | 2× speedup   |
| ----------------- | ----------------------- | ------------ |
| Synthetic 200     | **PASS** (18 ms full)   | NEAR (1.25×) |
| Home 6.5k         | FAIL (817 ms full)      | FAIL (1.55×) |

### Per-operation gate

The plan permits a per-operation default-Rust switch when an
individual hot path clears the gate. Today's numbers do not justify
that for any of the routed operations:

- `find_named_agent`: 1.06× (synthetic). The synthetic gap is small
  enough that a home-tree measurement is unlikely to clear 2× either —
  most of the cost in the Rust path is the same filesystem walk that
  bottlenecks `scan_rust_facade`.
- `is_workflow_complete`: Rust is **3× slower** at the synthetic size.
  This is structural, not a bug: the Python implementation
  short-circuits at the first matching workflow timestamp dir, while
  the snapshot-backed Rust path has to walk the whole artifact tree
  before any predicate can run. Routing this operation through Rust by
  default would be a net regression.
- TUI listing (`list_*_shared_snapshot`): the shared-snapshot variants
  already pay one full scan per refresh — Rust improves the snapshot
  cost (845 ms → 817 ms at home; ~3% in shared mode because the scan
  is amortized across both list operations and other consumers). Not
  a 2× win and not a UX-visible win because refresh runs in a thread.

## Rollout decision

1. **Default `SASE_CORE_BACKEND` stays `python`.** Rust scan is faster
   but does not clear the 2× research gate at the worst real workload
   we have. Flipping the default would impose a hard runtime
   dependency on a built sibling repo for a quietly-better experience.
2. **Rust path remains explicitly opt-in.** Contributors who run
   `just rust-install` and set `SASE_CORE_BACKEND=rust` get the 1.25×
   – 1.55× scan speedup. `SASE_CORE_DUAL_RUN=1` continues to log
   parity records to `~/.sase/perf/core_dual_run.jsonl` so any drift
   surfaces during routine use.
3. **No per-operation default-Rust override.** None of the dispatched
   operations clear the 2× gate at the home workload, and at least one
   (`is_workflow_complete`) regresses on Rust because the snapshot
   model removes the short-circuit Python relies on.
4. **Streaming remains out of scope.** Phase 3G's analysis still
   applies: the bottleneck at the worst workload is the Rust
   filesystem walk itself, not adaptation, and streaming cannot
   improve that bound.
5. **Python loaders and direct Python scanner stay in place.** The
   plan's non-goal "Do not remove Python loaders or the Python
   backend" is preserved. The snapshot facade is the integration seam,
   not a replacement.

## What Phase 4 should pick up (or look at instead)

The original migration plan in `sdd/research/202604/rust_backend_migration.md`
identified Phase 4 as the agent status state machine. Whether to
proceed next depends on where the next user-visible cost lives:

- **Snapshot scan time still dominates a TUI refresh on the home
  tree.** At 1316 ms (Python) / 817 ms (Rust) for the snapshot itself
  vs. 216 ms for adaptation, the highest-leverage future work is
  shrinking the snapshot, not switching adapters. Candidates:
  - filtering marker types Rust deserializes when the caller only
    needs running agents (`include_prompt_step_markers=False` is
    already the cheap path: `scan_python_facade_no_prompt_steps` at
    home is 844 ms vs 1263 ms for the full-prompt-step variant);
  - bounding `list_all_agents` by per-project completed-agent caps
    *before* materializing wire records — today the cap is applied
    after adaptation;
  - a freshness signal cheaper than re-walking, paired with a real
    cache invalidation design (explicitly out of scope for Phase 3).
- **Phase 4 (status state machine) is still on the table** as the
  next migration target, but profiling on a realistic home workload
  after Phase 3 lands would settle whether the agent-status logic is
  actually a hot spot or whether scan/adaptation continues to
  dominate. Recommend re-profiling before committing to Phase 4
  as-spec'd.
- **Adaptation hotspots, if pursued, are workflow-agent-steps
  (~172 ms at home) and done-agent-loader (~20 ms at home).** Both
  are per-marker work that runs in Python today; they are candidates
  for a Rust-side adapter only if measurement shows they are blocking
  first-frame UI.

## Files in scope this subphase

| Area                  | File                                                                        |
| --------------------- | --------------------------------------------------------------------------- |
| Phase 3H handoff      | `plans/202604/rust_backend_phase3_agent_scan_phase3h_handoff.md` _(this)_   |
| Roadmap entry         | `docs/rust_backend.md` (Phase 3H entry)                                     |

No production code changes in this subphase: per the plan's cross-agent
dependency order, "Phase 3H lands last and should not be combined with
feature work." The `bench-agent-scan` script already covers the
verification scenarios (Phase 3G added the `scan_rust_*` breakdown
trio); no further bench changes were needed to apply the rollout gate.

## Phase 3 close-out

Phase 3 is complete when artifact scanning can run through Rust under
an explicit backend flag, selected Python call sites have parity-backed
integration, and benchmark evidence supports the rollout decision. All
three exit criteria are met:

- `sase_core_rs.scan_agent_artifacts` is reachable through
  `sase.core.agent_scan_facade.scan_agent_artifacts` whenever the
  extension is built, gated by `SASE_CORE_BACKEND=rust`.
- `find_named_agent`, `is_workflow_complete`, `list_running_agents`,
  `list_all_agents`, and `_load_agents_from_all_sources` consume the
  snapshot facade with the Python backend kept as the default and
  fallback (Phases 3D / 3E / 3F).
- The bench numbers above support keeping the default Python: the
  Rust path is real and shipped, but does not clear the 2× gate that
  would justify making it the implicit default.
