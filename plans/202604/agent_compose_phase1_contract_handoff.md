# Agent Compose Phase 1 Contract Handoff

Bead: `sase-1p.1`

## Summary

Phase 1 adds the Python-side contract for a future Rust `compose_agent_list` operation without routing product code
through a new path.

Changed files:

- `src/sase/core/agent_compose_wire.py`
- `src/sase/core/agent_compose_facade.py`
- `tests/agent_compose_golden/`
- `tests/test_core_agent_compose.py`
- `tests/perf/bench_agent_compose.py`
- `plans/202604/perf_artifacts/agent_compose_phase1_baseline.json`

## Contract

The new wire module pins:

- `RunningClaimWire`
- `AgentComposeOptionsWire`
- `AgentComposeInputWire`
- `AgentWire`
- `ComposedAgentListWire`
- `DropReasonWire`
- `MergeReasonWire`

`AgentWire` intentionally carries raw row fields needed for identity, sorting, dismissal, kill/revive, retry lineage,
follow-up grouping, workflow-step rendering, file-panel routing, and status override parity. Display-only properties stay
out of the wire.

The reference facade currently delegates to `load_all_agents()` and projects the Python `Agent` result into
`ComposedAgentListWire`. `dropped` and `merge_log` are empty in Phase 1 because the current Python pipeline does not
emit structured diagnostics; Phase 2 should populate those while preserving the result shape.

## Golden Coverage

`tests/agent_compose_golden/fixture_builder.py` covers:

- plan workflow row with `PLAN APPROVED` status and follow-up linkage;
- workflow child/prompt-step row;
- running follow-up/code row;
- unanswered-question row with `QUESTION`;
- retry parent/child lineage;
- status ordering and JSON-safe round-trip through the wire dict shape.

This is a focused contract corpus rather than a full filesystem corpus. The later shadow-integration phase should add
artifact-tree fixtures once composition inputs are collected in one stage.

## Baseline Measurements

Command run:

```bash
.venv/bin/python tests/perf/bench_agent_compose.py --agents 100 1000 6000 --runs 3 --output plans/202604/perf_artifacts/agent_compose_phase1_baseline.json
```

Median timings from this workspace:

- 100 agents: `dead_pid_filter` 2.30 ms, `dedup_status_sort` 2.56 ms, `wire_projection` 3.26 ms, `full_reference` 5.51 ms
- 1,000 agents: `dead_pid_filter` 25.96 ms, `dedup_status_sort` 27.26 ms, `wire_projection` 36.18 ms, `full_reference` 32.98 ms
- 6,000 agents: `dead_pid_filter` 179.50 ms, `dedup_status_sort` 198.16 ms, `wire_projection` 248.17 ms, `full_reference` 187.71 ms

Raw output is in `plans/202604/perf_artifacts/agent_compose_phase1_baseline.json`.

## Verification

- `just test tests/test_core_agent_compose.py`
- `just check`

## Open Risks

- `AgentWire` is intentionally broad. Phase 2 should preserve every pinned field first, then identify safe reductions
  only after parity is green.
- Structured `DropReasonWire` / `MergeReasonWire` values are not emitted by Python yet. Phase 2 should make diagnostics
  deterministic and update goldens with non-empty examples.
- The reference facade accepts `AgentComposeInputWire` for signature parity but does not consume those inputs yet.
  Phase 4 is responsible for splitting input collection from composition in the product loader.
