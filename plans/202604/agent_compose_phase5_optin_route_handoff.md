---
create_time: 2026-05-01 00:00:00
status: complete
bead_id: sase-1p.5
---

# Agent Compose Phase 5 Opt-In Route Handoff

## Summary

Phase 5 adds a narrow product-route switch for the TUI agent loader while leaving
the default Python composition route unchanged.

Changed files:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/core/agent_compose_facade.py`
- `tests/test_agent_loader.py`
- `tests/test_core_agent_compose.py`
- `plans/202604/agent_compose_phase5_optin_route_handoff.md`

## Routing

Set `SASE_AGENT_COMPOSE_BACKEND=rust` to route `load_all_agents()` through
`sase_core_rs.compose_agent_list()` and rehydrate the returned `AgentWire` rows
back into normal TUI `Agent` objects. The default is still
`SASE_AGENT_COMPOSE_BACKEND=python`, which keeps the established Python
composition path and the Phase 4 shadow flags.

The opt-in Rust route does not silently fall back to Python. Missing or stale
Rust bindings raise through the existing facade so local verification catches
binding drift immediately.

## Python-Owned Surface

The loader still collects host-owned inputs in Python:

- ChangeSpec and project-file snapshots;
- RUNNING claim parsing;
- artifact scanning;
- process liveness checks;
- dismissed identity/suffix data.

Retry state, tags, attempt history, and dismissed-bundle supplementation remain
in `_loading_helpers.py` after `load_all_agents()` returns, so the Rust route
does not take ownership of those UI/runtime supplements.

## CLI Status

`sase agents status -j --all` remains on the existing snapshot listing path for
this phase. It uses `RunningAgentInfo`, prompt snippets, and per-project DONE
caps rather than the TUI visible-row model, so reusing the composed TUI list
would add behavioral churn outside this bead's narrow switch.

## Verification

Focused tests cover:

- opt-in Rust backend routing and `AgentWire` rehydration;
- follow-up and retry-chain relationship reconstruction;
- rejection of unknown backend values;
- existing Python route behavior.

Remaining blocker before default routing: Phase 4's live shadow run was
count-clean but not field-clean. Phase 6 should measure and compare the routed
Rust path on synthetic and user-visible fixtures before changing the default.
