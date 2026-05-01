---
create_time: 2026-05-01 00:00:00
status: complete
bead_id: sase-1p.4
---

# Agent Compose Phase 4 Shadow Handoff

## Summary

Phase 4 wires the TUI agent loader into explicit input collection and Python composition stages while keeping the Python
result as the product path. Rust composition is available as an opt-in shadow path via `SASE_AGENT_COMPOSE_SHADOW=1` or
`SASE_AGENT_COMPOSE_BENCH=1`.

Changed files:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/models/_loaders/_running_loaders.py`
- `src/sase/ace/tui/models/_loaders/__init__.py`
- `src/sase/ace/tui/actions/agents/_loading_helpers.py`
- `src/sase/core/agent_compose_facade.py`
- `src/sase/core/agent_compose_wire.py`
- `tests/test_agent_loader.py`
- `tests/test_core_agent_compose.py`
- `plans/202604/agent_compose_phase4_shadow_handoff.md`

## Loader Wiring

`load_all_agents()` now separates:

- ChangeSpec/project/RUNNING/artifact/dismissal input collection;
- Python candidate construction from those collected inputs;
- one PID liveness map reused by Python filtering and Rust shadow input;
- existing Python dedup/status/sort composition;
- optional Rust shadow composition and trace comparison.

The Agents tab passes dismissed identities into `load_all_agents()` so the compose input contains dismissed identities
and raw suffixes when the loader is called from the real refresh path. `AgentSnapshotCache` supplements still run after
composition in `_loading_helpers.py`.

RUNNING-field parsing is collected once into `RunningClaimWire` records, then converted back into the current Python
`Agent` rows for the product path.

## Shadow Behavior

Shadow mode calls `sase_core_rs.compose_agent_list(input: dict) -> dict` through
`compose_agent_list_rust()`. It compares the Python and Rust wire payloads for agents, workflow steps, and
`dismissed_from_loader`, then emits an `agent_compose.shadow` trace event when `SASE_TUI_TRACE=1`.

Shadow failures or mismatches are logged/traced but do not change the returned product result.

## Shadow Performance Sample

Command run from this workspace:

```bash
SASE_AGENT_COMPOSE_SHADOW=1 SASE_TUI_TRACE=1 \
  SASE_TUI_TRACE_PATH=/tmp/sase_agent_compose_shadow_trace.jsonl \
  .venv/bin/python - <<'PY'
import json, time
from sase.ace.tui.models.agent_loader import load_all_agents
start = time.perf_counter()
agents = load_all_agents()
print(json.dumps({"agents": len(agents), "load_all_agents_shadow_ms": (time.perf_counter() - start) * 1000.0}))
PY
```

Result from this live artifact tree:

- 1,814 returned agents
- 3,786 ms end-to-end `load_all_agents()` with Rust shadow enabled
- shadow trace: Python and Rust both returned 1,814 agents; Rust emitted 928 drops and 872 merge diagnostics; field-level
  parity was not clean

A follow-up diagnostic run on a later refresh returned equal counts again:

- Python agents: 1,756
- Rust agents: 1,756
- Python workflow steps: 5,869
- Rust workflow steps: 5,869
- first sampled field mismatch: `stop_time` on the first workflow row

## Verification

- `just install`
- `just test tests/test_core_agent_compose.py tests/test_agent_loader.py tests/test_agent_loader_status_overrides.py tests/test_agent_loader_dedup_pid.py tests/ace/tui/actions/test_agent_loader_phase5_wiring.py`

## Open Risks

- Rust shadow parity is count-clean on the sampled live refresh but not field-clean. The first sampled mismatch is
  `stop_time`; Phase 5 should route focused tests through Rust only after reviewing these wire-field differences.
- Shadow mode intentionally swallows Rust failures after tracing/logging them because Phase 4 is measurement-only.
