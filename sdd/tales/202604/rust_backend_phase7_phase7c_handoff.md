# Phase 7C Handoff: End-To-End TUI And CLI Measurements

Bead: `sase-1e.3`. Plan: `plans/202604/rust_backend_phase7.md`. Phase 7C captures the user-facing TUI/CLI surfaces named
in the Phase 7 plan under both backends so Phase 7D has honest medians for "what users actually pay before any LLM
work" and Phase 7E knows which workloads are stable enough for a CI floor.

## What landed

- `tests/perf/bench_phase7_e2e.py` — single harness covering the three Phase 7C surfaces, one artifact per
  `(surface, backend)` invocation. Uses `tests.perf.phase7.build_metadata()` and `tests.perf.phase7.artifact_path()` so
  the JSON envelope and filename match the Phase 7A contract; recursive `_sanitize()` rewrites `$HOME` to `~` before
  writing.
- `plans/202604/perf_artifacts/rust_backend_phase7_sase_ace_cold_open_{default_rust,explicit_python}.json` — Pilot-based
  ace cold-open timings.
- `plans/202604/perf_artifacts/rust_backend_phase7_sase_agents_status_listing_{default_rust,explicit_python}.json` —
  cold subprocess `sase agents status -j` against a synthetic `~/.sase/projects` tree.
- `plans/202604/perf_artifacts/rust_backend_phase7_sase_run_startup_{default_rust,explicit_python}.json` — cold
  subprocess import of `sase.main.query_handler._query.run_query` (the `sase run` provider boundary; documented below).
- `.gitignore` — adds `plans/202604/perf_artifacts/local_only/` so private home-tree artifacts can sit next to the
  committed ones without leaking project paths. Used for the home-tree `sase agents status` workload below.

Out of scope for Phase 7C and explicitly not done:

- No documentation changes under `docs/rust_backend.md` or `sdd/research/202604/`. Phase 7D owns the user-facing narrative
  and tables.
- No CI integration. Phase 7E owns the regression floor.
- No live LLM provider invocation. The `sase run` measurement deliberately stops at the documented provider boundary
  (see "sase_run_startup boundary" below).
- No new `Justfile` targets. Phase 7E will add a `phase7-perf-check` body that drives the stable subset; right now the
  harness is invoked directly per surface.

## Headline medians (this workstation)

Captured 2026-04-29 on this workstation (Linux, x86_64, Python 3.14.3, `sase_core_rs` editable install with all 12
shipped bindings). Numbers are wall-time medians; see the per-artifact JSON for min/p95/max and run counts.

| Surface                        | Workload                       | runs | default_rust | explicit_python | speedup (Py/Rust) | % delta (Rust vs Py) |
| ------------------------------ | ------------------------------ | ---- | -----------: | --------------: | ----------------: | -------------------: |
| `sase_run_startup`             | `import_run_query_cold`        | 12   |    249.3 ms  |       252.6 ms  |             1.01× |                -1.3% |
| `sase_agents_status_listing`   | `synthetic_8_projects_25_agents` | 12 |    298.5 ms  |       774.5 ms  |             2.59× |               -61.5% |
| `sase_agents_status_listing`   | `home_tree` (local-only)       | 5    |    885.8 ms  |     1,799.7 ms  |             2.03× |               -50.8% |
| `sase_ace_cold_open`           | `synthetic_100_cs_50_agents`   | 10   |  1,472.5 ms  |     1,237.4 ms  |             0.84× |               +19.0% |

Read the table as: a `speedup` of `2.59×` means default Rust is 2.59× faster than explicit Python on that workload; a
`+19.0%` delta means default Rust is 19.0% slower than explicit Python.

### Surface-by-surface notes

- `sase_run_startup`: backend choice is invisible at the cold-import scope. The cost users pay before the dispatcher
  can call any LLM is dominated by Python interpreter startup + sase package import; routing through Rust vs Python
  inside `sase.core` does not show up because `run_query` is not exercised at import time. Phase 7D should report this
  honestly: the `sase run` provider boundary is **not** a Rust win/loss surface — it is an interpreter-startup surface.
- `sase_agents_status_listing`: the headline Rust win for end-to-end work. `sase agents status -j` invokes
  `scan_agent_artifacts`, which Phase 3 ported to Rust; on both the synthetic 8×25 tree and the real home tree, default
  Rust roughly halves the cold subprocess wall-time. This is the surface most worth gating in Phase 7E.
- `sase_ace_cold_open`: default Rust is **slower** than explicit Python here, by ~19% on this workstation. The Pilot
  harness mocks `find_all_changespecs`, so the Rust scan/parse hot paths are not exercised; what remains is AceApp /
  Pilot constructor cost plus per-call PyO3 dispatch overhead at small inputs (see Phase 4A/4F handoffs for the same
  pattern on the status state machine). Phase 7D should describe this as a known small-input dispatch tax, not a
  regression in the routed Rust operation; Phase 7E should keep ace cold-open out of the hard floor.

### Sample-size and stability caveats

- 10–12 runs on a developer workstation is enough to separate the agents_status 2× signal from noise (min/p95 stay
  within ~10% of the median in every committed artifact) but is not enough to reliably defend a tighter than ~25%
  ace_cold_open floor — see the Phase 7E section.
- `home_tree` measurements are workstation-specific by definition. They are committed to
  `plans/202604/perf_artifacts/local_only/` (gitignored per Phase 7A's sanitisation rule) and **not** suitable for CI;
  Phase 7E should keep them in the manual / `workflow_dispatch` path documented for slow workloads.
- `sase_run_startup` numbers will fluctuate with sase package import surface area (every new top-level import in the
  dispatcher import graph shows up here). Phase 7E can use this as a regression sentinel for accidental import bloat
  rather than as a backend gate.

## How to reproduce

The harness is one Python module, one artifact per invocation:

```bash
# default-Rust (no env override)
just install                         # rebuild sase_core_rs from ../sase-core if present
.venv/bin/python -m tests.perf.bench_phase7_e2e --surface sase_run_startup            --backend default_rust    --runs 12 --warmup 2
.venv/bin/python -m tests.perf.bench_phase7_e2e --surface sase_agents_status_listing  --backend default_rust    --workload synthetic --projects 8 --per-project 25 --runs 12 --warmup 2
.venv/bin/python -m tests.perf.bench_phase7_e2e --surface sase_ace_cold_open          --backend default_rust    --cs-count 100 --agent-count 50 --runs 10 --warmup 3

# explicit-Python (env-pinned; required at process launch so the in-process Pilot harness sees it)
SASE_CORE_BACKEND=python .venv/bin/python -m tests.perf.bench_phase7_e2e --surface sase_run_startup            --backend explicit_python --runs 12 --warmup 2
SASE_CORE_BACKEND=python .venv/bin/python -m tests.perf.bench_phase7_e2e --surface sase_agents_status_listing  --backend explicit_python --workload synthetic --projects 8 --per-project 25 --runs 12 --warmup 2
SASE_CORE_BACKEND=python .venv/bin/python -m tests.perf.bench_phase7_e2e --surface sase_ace_cold_open          --backend explicit_python --cs-count 100 --agent-count 50 --runs 10 --warmup 3
```

Optional home-tree (writes to gitignored `local_only/`):

```bash
.venv/bin/python -m tests.perf.bench_phase7_e2e \
  --surface sase_agents_status_listing --backend default_rust --workload home_tree \
  --runs 5 --warmup 2 \
  --output plans/202604/perf_artifacts/local_only/home_tree_default_rust.json
SASE_CORE_BACKEND=python .venv/bin/python -m tests.perf.bench_phase7_e2e \
  --surface sase_agents_status_listing --backend explicit_python --workload home_tree \
  --runs 5 --warmup 2 \
  --output plans/202604/perf_artifacts/local_only/home_tree_explicit_python.json
```

## sase_run_startup boundary

The Phase 7 plan asks for either a deterministic stub provider in a subprocess or an in-process `run_query()` call with
the provider invocation mocked. The harness picks a third documented option that satisfies the same constraint:
subprocess-cold `python -c "from sase.main.query_handler._query import run_query"`. Rationale:

- Captures every import the dispatcher pays before any LLM call (subprocess cold start, sase package, all transitive
  modules pulled in by the run-query module body).
- Stops strictly **before** any provider is resolved or invoked, so it never depends on the user's API keys, never
  touches the network, and never claims a workspace.
- Does not need a deterministic local provider plugin to ship in the repo. Phase 7E can replace this with a real
  registered stub provider if it wants to push the boundary further toward provider resolution; the artifact metadata's
  `extra.boundary` field documents the current scope so a future agent can compare apples to apples.

## Sanitisation

`bench_phase7_e2e._sanitize()` walks the artifact dict and rewrites any string starting with the current `$HOME` to
`~/<rest>`. This is sufficient for everything we capture: synthetic workloads use `tempfile.TemporaryDirectory()` paths
(noise but not private), `home_tree` runs are routed to `local_only/` (gitignored), and `metadata.rust_module_path` /
`extra.interpreter` are the only paths that intersect `$HOME` in a committed artifact. Greps for `/home/` and the
developer's username come up empty against every committed Phase 7C JSON.

If a future surface emits prompt text, project file names, or chat transcripts, route the artifact to `local_only/` and
add a workload-specific scrubber rather than expanding `_sanitize()` — the README sets that as the canonical escape
hatch.

## Verification commands run

- `just install`
- `.venv/bin/python -m tests.perf.bench_phase7_e2e --surface ... --backend ...` (six committed artifacts plus two
  `local_only/` home-tree artifacts; commands reproduced above).
- `just phase7-perf-check` — Phase 7A helper smoke (20 passed). The harness does not pull in any new test modules, so
  this stays green.
- `just check` — full repo check (fmt, lint, mypy, pyscripts, pyvision, fast tests).

## Open questions / nudges for later phases

- **Phase 7D**: pair the headline table above with the per-operation Phase 7B microbench numbers when those land — the
  agents_status 2× speedup is the clearest "users feel this" claim and should be linked to `scan_agent_artifacts`. The
  ace cold-open negative result deserves a one-paragraph "where Rust does not help yet" note explaining the dispatch
  tax at small inputs; reuse the framing from the Phase 4A handoff.
- **Phase 7E**: only `sase_agents_status_listing/synthetic_8_projects_25_agents` is stable enough for a hard PR floor.
  Recommended starting tolerance: candidate (default Rust) median ≤ 1.5× the recorded Phase 7C Rust median, with a
  hard floor that Rust must remain at least as fast as the Python baseline. Keep `sase_run_startup` as a soft import-
  bloat sentinel (allow ±15% of the Phase 7C Rust median); keep `sase_ace_cold_open` and `home_tree` in
  `workflow_dispatch` only.
- **Phase 7E (harness work)**: the harness already takes `--runs`, `--warmup`, and `--output`; Phase 7E only needs to
  add a Justfile recipe that loops the stable subset and feeds the artifacts through a regression checker. No changes
  to `bench_phase7_e2e.py` should be required.
- **Phase 7F**: the home-tree `local_only/` artifacts are reproducible from this workstation but not from a clean CI
  worker; verification should re-run them on the maintainer's box and compare against the medians above rather than
  re-recording into CI.
