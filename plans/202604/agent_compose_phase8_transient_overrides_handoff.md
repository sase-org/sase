---
create_time: 2026-05-01 00:00:00
status: complete
bead_id: sase-1p.8
---

# Agent Compose Phase 8 Transient Overrides Handoff

## Summary

Phase 8 keeps notification-driven status overrides Python-owned. I extracted
the existing `_loading_finalize.py` logic into a small data helper,
`apply_transient_status_overrides()`, so the policy is testable in isolation
without adding a Rust boundary for UI app state.

Changed files:

- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- `tests/test_agents_tab_query_integration.py`
- `plans/202604/perf_artifacts/agent_compose_phase8_transient_overrides.json`
- `plans/202604/agent_compose_phase8_transient_overrides_handoff.md`

## Decision

Do not add a Rust helper for this pass.

The helper is a single visible-list scan plus a small override-map cleanup. A
Rust route would need to marshal every visible identity/status and the override
maps across FFI, then apply the returned updates back to mutable Python `Agent`
objects. That conversion cost is not justified for transient TUI state, and it
would couple `sase_core_rs` to notification lifecycle details that are not
loader facts.

## Measurements

Measured with Python 3.14.3 after Phase 7 default routing, using a stable
visible list and fresh status/pre-question override maps per sample. The fixture
sets overrides for roughly 20% of rows plus one stale identity.

| Visible agents | Median | p95 | Max |
| ---: | ---: | ---: | ---: |
| 25 | 0.010 ms | 0.010 ms | 0.094 ms |
| 1,000 | 0.419 ms | 0.440 ms | 0.879 ms |
| 6,000 | 2.899 ms | 5.823 ms | 31.192 ms |

Raw artifact:
`plans/202604/perf_artifacts/agent_compose_phase8_transient_overrides.json`.

## Verification

```bash
just install
.venv/bin/pytest -q tests/test_agents_tab_query_integration.py
just check
```
