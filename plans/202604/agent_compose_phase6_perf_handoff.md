# Agent Compose Phase 6 Performance Handoff

Bead: `sase-1p.6`

## Scope

Phase 6 measured the opt-in Phase 5 agent-compose route before default routing.
The product switch is `SASE_AGENT_COMPOSE_BACKEND=rust` for
`load_all_agents()`. The gate measures both that opt-in loader route and the
narrower composer boundary: pre-collected `RunningClaimWire` inputs composed by
Rust, with a second row that hydrates Rust `AgentWire` records back to Python
`Agent` objects.

## Files changed

- `tests/perf/bench_agent_compose.py`
  - Adds Phase 6 Python-vs-Rust compose scenarios on identical synthetic
    running-claim inputs.
  - Adds `load_all_agents()` Python-vs-Rust backend scenarios for the Phase 5
    opt-in route.
  - Keeps the original Python-only pipeline timings as optional diagnostics.
  - Emits a Phase 7-style artifact with parity and gate comparison rows.
- `tests/perf/phase7_check_regression.py`
  - Teaches the floor checker how to run a future `compose_agent_list` anchor.
  - Maps Rust compose scenarios to the matching Python baseline row.
- `plans/202604/perf_artifacts/agent_compose_phase6_product_perf.json`
  - Captured compose benchmark artifact.
- `plans/202604/perf_artifacts/agent_compose_phase6_sase_agents_status_listing.json`
  - Diagnostic CLI listing artifact. This surface is not currently routed
    through agent-compose.

## Measurements

Captured with Python 3.14.3 and the local editable `sase_core_rs` build. All
compose rows had clean visible parity: `agents_match=true`, equal agent counts,
and no Rust drops or merge diagnostics.

| Workload | `load_all_agents()` Python | `load_all_agents()` Rust | Gate result |
| --- | ---: | ---: | --- |
| `synthetic_25_running_claims` | 1.481 ms | 2.925 ms | Rust is 1.97x slower |
| `synthetic_1000_running_claims` | 41.184 ms | 118.845 ms | Rust is 2.89x slower |
| `synthetic_6000_running_claims` | 277.764 ms | 855.460 ms | Rust is 3.08x slower |

| Workload | Python candidate compose | Rust compose wire | Rust wire -> Python Agent | Gate result |
| --- | ---: | ---: | ---: | --- |
| `synthetic_25_running_claims` | 0.614 ms | 1.242 ms | 1.633 ms | Rust is 2.02x / 2.66x slower |
| `synthetic_1000_running_claims` | 26.177 ms | 67.697 ms | 75.571 ms | Rust is 2.59x / 2.89x slower |
| `synthetic_6000_running_claims` | 198.356 ms | 459.355 ms | 545.710 ms | Rust is 2.32x / 2.75x slower |

Diagnostic `sase agents status -j` synthetic 8-project/25-agent listing:
308.10 ms median over 3 runs. `cli_status` still does not consume the TUI
`compose_agent_list` route, so this is a user-visible diagnostic rather than
the default-routing gate.

## Regression floor

No `compose_agent_list` row was added to
`tests/perf/baselines/phase7_regression_floor.json`. The design explicitly says
to add a floor row only after the routed surface clears the gate; this capture
does not clear the gate.

The checker is ready for a future row once Rust composition beats the Python
candidate compose baseline on the routed surface.

## Default routing decision

Do not default-route agent composition to Rust yet.

Phase 7 is not authorized by this handoff. The next implementation pass should
first reduce the Rust boundary cost, likely by avoiding expensive Python dict
projection / hydration on the hot path or by widening the Rust-owned work enough
that the FFI and conversion costs are amortized.

## Verification

- `just install`
- `.venv/bin/python tests/perf/bench_agent_compose.py --agents 25 1000 6000 --runs 5 --warmup 1 --no-legacy --output plans/202604/perf_artifacts/agent_compose_phase6_product_perf.json`
- `PYTHONPATH=. .venv/bin/python tests/perf/bench_phase7_e2e.py --surface sase_agents_status_listing --backend default_rust --runs 3 --warmup 1 --projects 8 --per-project 25 --output plans/202604/perf_artifacts/agent_compose_phase6_sase_agents_status_listing.json`
- `.venv/bin/pytest -q tests/perf/phase7/test_phase7_check_regression.py tests/perf/bench_agent_compose.py tests/test_core_agent_compose.py tests/test_agent_loader.py`
