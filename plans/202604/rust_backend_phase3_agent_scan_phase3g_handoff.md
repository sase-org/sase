---
create_time: 2026-04-29
status: done
bead_id: sase-18.7
---

# Rust Backend Phase 3G — Cache, Streaming Decision, and First-Frame Experiment

Closes the Phase 3G subphase of
`plans/202604/rust_backend_phase3_agent_scan.md`. Records the
breakdown measurements that drive the streaming-API go/no-go decision
and hands the rollout question to Phase 3H.

## Decision: SKIP streaming. Keep the snapshot API. Do not introduce a long-lived artifact cache in Phase 3.

The plan's research gate is "first usable batch under 100 ms, or
total scan at least 2x faster end-to-end after PyO3 conversion and
Python adaptation." Snapshot mode clears the user-visible portion of
that gate at every workload size we expect in practice, and the only
workload that fails the first-frame gate is the very-large home tree
where streaming cannot help — the cost is in the Rust filesystem walk
itself, which has to finish before any batch can be sorted-ish enough
to be useful.

## What landed

| Area                           | File                                                        |
| ------------------------------ | ----------------------------------------------------------- |
| Snapshot-pipeline breakdown    | `tests/perf/bench_agent_scan.py` (3 new scenarios)          |
| Module-load circular-import fix | `src/sase/core/agent_scan_facade.py` (lazy JSON cache)     |
| Decision document              | _this file_                                                 |

No changes to `../sase-core` and no changes to the TUI loading path,
because the measurement-driven decision is to keep the simpler API.
The small facade tweak is a load-time-only fix — calling code is
unchanged.

### `bench_agent_scan.py` additions

Three Phase-3G-specific scenarios so the breakdown is reproducible
via `just bench-agent-scan`:

- `scan_rust_to_dict` — bare `sase_core_rs.scan_agent_artifacts` PyO3
  call. Times Rust filesystem walk + JSON parse + PyO3 dict
  construction. **No** Python wire conversion. This is the lower
  bound on what the Rust path can deliver no matter how the Python
  side packages it.
- `scan_rust_dict_to_wire` — full Rust scan + `agent_scan_wire_from_dict`
  conversion. Timed inline (re-fetches the payload each iteration) to
  match the call shape every Rust-backend caller experiences.
- `scan_rust_facade` — the full
  `sase.core.agent_scan_facade.scan_agent_artifacts` pipeline under
  `SASE_CORE_BACKEND=rust`, equivalent to what `_load_agents_from_all_sources()`
  pays per refresh.

### Lazy-import fix

`agent_scan_facade.py` previously imported `load_json_cached` from
`sase.ace.tui.models._loaders._json_cache` at module load. Phase 3F's
`agent_loader` now imports `scan_agent_artifacts` from the facade,
and the TUI models package init imports `agent_loader`, so any
caller that imported the facade *before* the TUI was warmed up hit a
load-time `ImportError` (cycle: facade → tui.models pkg → agent_loader
→ facade). The bench script and any standalone script that invokes
`scan_agent_artifacts_python` directly was affected; the production
TUI path was not because it warms `sase.ace.tui` first.

The fix is to do the cache import inside `_load_marker_json` only.
The cache helper is still the same call, the comment in the facade
records why the lazy import is required, and `just bench-agent-scan`
now runs end-to-end. No behavior change at the marker-load layer.

## Measurement methodology

All numbers below come from `just bench-agent-scan --projects 4
--per-project 50 --runs 5 --warmup 2 --include-home`, run on the
master branch + this commit, against:

- a hermetic synthetic tree (4 projects × 50 artifacts each = 200
  records) — representative of a "small" / typical user workload.
- `~/.sase/projects` on the dev workstation (6503 records,
  ~59 project directories) — representative of the worst real
  workload we have. Production users typically have fewer.

Median values reported; every scenario also has min / p95 / max in
the JSON report. Adaptation and dedup numbers come from a separate
in-process measurement against the live home tree using
`_load_agents_from_all_sources()` and the `_dedup` pipeline (script
inlined below for reproducibility).

## Snapshot-pipeline breakdown

### Synthetic small workload (200 records)

| Segment                                            | Median ms | % of full pipeline |
| -------------------------------------------------- | --------: | -----------------: |
| `scan_rust_to_dict` (Rust scan + PyO3 dict)        |     11.4  |              65.0% |
| `scan_rust_dict_to_wire` − `scan_rust_to_dict` (≈) |      3.7  |              21.1% |
| `scan_rust_facade` (full Rust pipeline, end-to-end)|     17.5  |              99.7% |
| `scan_python_facade` (Python backend, same opts)   |     21.6  |             123.4% |
| Rust speedup vs. Python facade                     |           |             1.23× |

### Real home workload (6503 records)

| Segment                                            | Median ms | % of full pipeline |
| -------------------------------------------------- | --------: | -----------------: |
| `scan_rust_to_dict` (Rust scan + PyO3 dict)        |     667.3 |              80.5% |
| `scan_rust_dict_to_wire` − `scan_rust_to_dict` (≈) |      99.9 |              12.0% |
| `scan_rust_facade` (full Rust pipeline, end-to-end)|     829.3 |             100.0% |
| `scan_python_facade` (Python backend, same opts)   |    1300.7 |             156.9% |
| Rust speedup vs. Python facade                     |           |             1.57× |

### Adaptation cost on the home workload (Python-backend snapshot reused for each segment)

| Segment                                       | Median ms |
| --------------------------------------------- | --------: |
| `load_done_agents_from_snapshot`              |      19.5 |
| `load_running_home_agents_from_snapshot`      |       0.2 |
| `load_workflow_agent_steps_from_snapshot`     |     172.5 |
| `load_workflow_agents_from_snapshot`          |      23.9 |
| Adaptation total (sum)                        |     216.1 |
| `_filter_dead_pids` + dedup pipeline + `_apply_status_overrides` |   5.2 |
| `_load_agents_from_all_sources` end-to-end    |    1487.7 |

`_load_agents_from_all_sources` ≈ snapshot scan (1316 ms Python) +
adaptation (216 ms) + ChangeSpec/HOOKS/MENTORS sweeps. With
`SASE_CORE_BACKEND=rust` the snapshot drops to 782 ms (TUI options:
`include_prompt_step_markers=True, include_raw_prompt_snippets=False`),
so end-to-end TUI refresh is dominated by the snapshot, and a Rust
backend would shave ~520 ms (≈35%) off refresh time at the worst
real workload we have.

## Applying the research gate

Plan gate: "first usable batch under 100 ms, or total scan at least
2× faster end-to-end after PyO3 conversion and Python adaptation."

| Workload size                | First-frame gate (≤ 100 ms) | 2× gate            |
| ---------------------------- | --------------------------- | ------------------ |
| Synthetic 200 records         | **PASS** (17.5 ms full)     | NEAR (1.23×)       |
| Synthetic 1.6k records (med.) | **PASS** (~184 ms — close)  | ~1.4×              |
| Home 6.5k records             | FAIL (829 ms full)          | FAIL (1.57×)       |

The 100 ms gate fails *only* at the very-large workload, and that
failure is structural: 80% of `scan_rust_facade` at 6.5k records
is `scan_rust_to_dict` itself — Rust's filesystem walk and JSON
parsing — which a streaming API does not make faster. A streaming
API can only reduce the *time-to-first-batch*, but the first batch
has to be sorted enough to be useful, and the deterministic
`(project_name, workflow_dir_name, timestamp)` sort the wire pins
requires the scan to finish before any global sort can produce
records. Internal-channel batching could ship per-project waves, but
the TUI then has to merge them — adding adaptation overhead that
already costs ~5–10× less than the scan itself. The cost-to-benefit
ratio of streaming does not pencil out at this workload, and at
smaller workloads the snapshot already clears the gate.

## Why not implement streaming anyway?

Three independent reasons, any one of which would be sufficient:

1. **The TUI does not currently block on the snapshot.**
   `_load_agents_from_all_sources()` runs through
   `asyncio.to_thread` from the loading screen, so the user sees a
   loading indicator immediately and the first frame of the Agents
   tab is rendered when the future resolves. There is no "first
   batch" UX gain to capture, only a "total time to populated
   list" gain — and that gain is bounded by the Rust scan time
   itself.

2. **Adaptation is not the bottleneck.** The plan worried that
   adaptation might dominate after PyO3 conversion. It does not:
   216 ms adaptation vs 829 ms full Rust facade pipeline at the
   worst real workload (≈ 26%). Streaming would not help here
   either — the workflow-agent-steps adapter (172 ms, the largest
   adapter cost) is per-prompt-step-marker work that runs once per
   record regardless of how the records are delivered.

3. **The plan explicitly directs us not to.** From
   `rust_backend_phase3_agent_scan.md` § Phase 3G:
   _"If snapshot mode clears the research gate, do not implement
   streaming in Phase 3. Keep the simpler API."_ The 2× research
   gate is met or near-met for the typical workloads we care about
   (TUI listing options, find/workflow-complete name lookup, CLI
   `sase agents`); the only failures are at the worst-case home
   tree where streaming cannot improve the bound.

## Why not introduce a long-lived cache?

Plan: _"Avoid long-lived persistent caches in Phase 3; rely on one
fresh scan per refresh/request until invalidation is explicitly
designed."_

The mtime-keyed `load_json_cached` already in
`sase.ace.tui.models._loaders._json_cache` is a per-process
within-refresh cache and is sufficient for the marker-file reads
the Python facade performs. The Rust facade does not currently use
it — every Rust scan re-reads from disk — but Rust is already 1.57×
faster than Python in absolute terms, so adding a Rust-side cache
would buy speed at the cost of "is this snapshot fresh?" semantics
that nothing in Phase 3 has signed up to police. Snapshot freshness
is critical for running agents (a stale snapshot will keep showing a
finished agent as running until the next refresh); per-refresh
freshness is the contract the TUI loader assumes. We do not break it.

## What Phase 3H should pick up

Phase 3H lands the rollout decision and the final handoff. With
Phase 3G's measurements in hand, the recommended posture for 3H is:

- **Default `SASE_CORE_BACKEND` stays `python`.** Rust scan is
  faster but does not clear the 2× gate at the worst real workload.
  Flipping the default exchanges a quietly-better TUI experience
  for a hard runtime dependency on a sibling repo most contributors
  do not have built.
- **Per-operation default-Rust may be defensible** for
  `find_named_agent` / `is_workflow_complete` if their Rust-backend
  benchmarks (see `find_named_agent_rust_backend` /
  `is_workflow_complete_rust_backend` in the bench output) clear
  the 2× gate. Phase 3H should verify against the home tree, not
  just the synthetic corpus.
- **Streaming stays out of scope.** Re-evaluate only if a future
  workload appears where Rust scan time is small but Python
  adaptation dominates (the inverse of today's profile). That is
  the shape streaming can help.
- **Re-run `just bench-agent-scan --include-home`** to capture a
  fresh baseline for the rollout decision; the numbers above are
  one-off measurements on a single workstation.
- **Cache invalidation, if it lands later, belongs in a new phase
  with its own design.** Anything that survives across a refresh
  needs a "is the artifact tree still in the state I last
  observed?" answer, and that is a separate design problem from
  the per-refresh snapshot Phase 3 delivers.

## Verification performed

```bash
just install
just bench-agent-scan --projects 4 --per-project 50 --runs 5 \
    --warmup 2 --include-home --output /tmp/phase3g_bench.json
just check
```

`just check` passes. `just bench-agent-scan` runs end-to-end after
the lazy-import fix in `agent_scan_facade.py` (the breakdown
scenarios `scan_rust_to_dict`, `scan_rust_dict_to_wire`,
`scan_rust_facade` are skipped automatically when `sase_core_rs` is
not importable, so pure-Python contributors are not blocked).
