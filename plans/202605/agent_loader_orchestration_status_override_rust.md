---
create_time: 2026-05-01 00:09:19
status: draft
bead_id: sase-1p
---

# Agent Loader Orchestration & Status Override Rust Migration Plan

## Context

`research/202604/rust_core_next_candidates.md` ranks "Agent loader orchestration & status override pipeline" as the next
high-value Rust migration after notification store and persistent query corpus work. The recommendation targets the
Agents refresh path after Phase 3's Rust artifact scan: `scan_agent_artifacts()` already walks and parses
`agent_meta.json`, `done.json`, `running.json`, `waiting.json`, `workflow_state.json`, `plan_path.json`, and
`prompt_step_*.json`, but Python still turns those records plus ChangeSpec data into `Agent` objects, filters dead PIDs,
runs several dedup passes, applies workflow-derived status overrides, attaches follow-up/retry relationships, and sorts
the display list.

Current Python hot path:

- `src/sase/ace/tui/models/agent_loader.py`
  - `_load_agents_from_all_sources()`
  - `_filter_dead_pids()`
  - `_apply_status_overrides()`
  - `_sort_and_reorder()`
  - `load_all_agents()`
- `src/sase/ace/tui/models/_dedup.py`
  - `dedup_axe_spawned_agents()`
  - `remove_vcs_workspace_claims()`
  - `dedup_workflow_entries()`
  - `dedup_running_vs_workflow()`
  - `dedup_by_pid()`
- `src/sase/ace/tui/actions/agents/_loading_helpers.py`
  - retry-state promotion to `RETRYING`
  - tags, attempt history, dismissed bundle supplement loading
  - dismissed-from-loader derivation
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
  - transient UI-only status overrides from notification actions

The current Rust boundary:

- `sase` Python repo has the facade pattern under `src/sase/core/`.
- `sase-core` sibling repo has `crates/sase_core/src/agent_scan/` and PyO3 bindings in `crates/sase_core_py/src/lib.rs`.
- `sase-core-rs` is a hard runtime dependency. There is no Python fallback for already-ported core operations.

The migration should keep the same discipline as the earlier Rust backend phases: define wire records first, land golden
parity tests, route the product path only after measurement clears the regression floor, and delete Python only after
the Rust route is the proven default.

## Design Target

Add an `agent_compose` operation family to `sase-core`:

```text
compose_agent_list(input: AgentComposeInputWire) -> ComposedAgentListWire
```

The operation should consume coarse-grained inputs in one FFI call:

- existing `AgentArtifactScanWire` from `scan_agent_artifacts()`;
- `ChangeSpecWire` records for the current ChangeSpec snapshot;
- `RunningClaimWire` records parsed from `.gp` `RUNNING:` fields;
- a pre-collected alive PID set or per-PID liveness result from Python;
- dismissed identities/suffixes needed to compute `dismissed_from_loader`;
- option flags for TUI vs CLI behavior.

It should produce:

- `AgentWire` records that are close to the current Python `Agent` model but remain a stable wire contract;
- `workflow_agent_steps` if the first integration phase still needs them separately;
- `dismissed_from_loader` or enough identity/drop metadata for Python to derive it without re-walking the full list;
- `dropped: Vec<DropReasonWire>` / `merge_log: Vec<MergeReasonWire>` diagnostics so parity failures explain which dedup
  or status rule diverged.

Rust should own deterministic list composition:

- artifact-snapshot to agent candidates;
- ChangeSpec HOOKS/MENTORS/COMMENTS agent candidates;
- RUNNING-field claim agent candidates from supplied `RunningClaimWire`;
- dead-PID filtering based on Python-supplied liveness;
- dedup and merge passes;
- deterministic workflow status overrides (`PLANNING`, `RUNNING`, `PLAN APPROVED`, `PLAN COMMITTED`, `EPIC APPROVED`,
  `PLAN DONE`, `EPIC CREATED`, `QUESTION`);
- follow-up agent attachment metadata;
- retry-chain sibling metadata;
- display ordering and workflow-step interleaving.

Rust should not own host/UI state in the first cut:

- process liveness remains Python and is passed in as data;
- filesystem mutation remains Python, including stale `running.json` cleanup;
- `AgentSnapshotCache` supplements (`attempts/`, `retry_state.json`, dismissed bundles, tags) stay Python until a later
  supplement-scan migration;
- `AgentLoadingMixin._agent_status_overrides` and `_agent_pre_question_status` remain Python app state. A later phase
  can move the pure "apply overrides to a visible list" operation to Rust, but the source of truth stays in the TUI.

## Phase Split for Distinct Agent Instances

Each phase below is intended for a separate `claude` / `gemini` / `codex` agent instance. Every phase should leave a
short handoff note under `plans/202604/` summarizing files changed, verification run, open risks, and whether the next
phase is unblocked.

### Phase 1: Contract, Corpus, and Baseline Measurements

Goal: make the migration measurable and pin the behavior before adding Rust composition.

Owner scope:

- `src/sase/core/agent_compose_wire.py`
- `src/sase/core/agent_compose_facade.py`
- focused adapters in `src/sase/ace/tui/models/agent_loader.py` only if needed to expose a Python reference function
- `tests/agent_compose_golden/`
- `tests/test_core_agent_compose.py`
- `tests/perf/bench_agent_compose.py`
- handoff: `plans/202604/agent_compose_phase1_contract_handoff.md`

Work:

1. Add wire dataclasses for `RunningClaimWire`, `AgentComposeOptionsWire`, `AgentComposeInputWire`, `AgentWire`,
   `ComposedAgentListWire`, `DropReasonWire`, and `MergeReasonWire`.
2. Add conversion helpers between Python `Agent` and `AgentWire`. Keep display-only computed properties out of the wire;
   keep raw fields needed for TUI rendering, identity, sorting, dismissal, kill, revive, and file-panel routing.
3. Add a pure-Python reference adapter behind `agent_compose_facade` that calls the current loader pipeline and converts
   the result to wire. This is a reference path, not a new product route.
4. Build golden fixture trees and ChangeSpec fixtures that cover:
   - RUNNING field agent and workflow claims;
   - home-mode `running.json` agents;
   - DONE/FAILED agents from `done.json`;
   - workflow roots and prompt step markers;
   - ChangeSpec-sourced hooks, mentors, and CRS agents;
   - duplicate axe-spawned agents across RUNNING and ChangeSpec fields;
   - VCS workspace-claim removal by shared PID;
   - workflow RUNNING vs workflow_state dedup;
   - PID recycling cases that must keep distinct suffixes;
   - plan workflow status overrides: `PLANNING`, `PLAN APPROVED`, `PLAN COMMITTED`, `EPIC APPROVED`, `PLAN DONE`,
     `EPIC CREATED`, `QUESTION`;
   - retry-chain linkage and retry-state `RETRYING` promotion as a documented Python-owned supplement.
5. Add a benchmark that separates current costs:
   - artifact scan;
   - Python candidate construction;
   - dead-PID filter;
   - each dedup/status/sort phase when practical;
   - full `load_all_agents()`;
   - `sase agents status -j` end to end on synthetic 8-project/25-agent and larger 6k-row fixture.

Exit criteria:

- Golden tests pin the reference output and diagnostic shape.
- Baseline benchmark output is recorded in the handoff.
- No product behavior changes.
- `just check` passes in `sase`.

### Phase 2: Pure Rust Compose Core

Goal: implement deterministic composition in the pure Rust crate without PyO3/product routing.

Owner scope:

- `../sase-core/crates/sase_core/src/agent_compose/`
- `../sase-core/crates/sase_core/src/lib.rs`
- Rust fixture tests under `../sase-core`
- handoff: `plans/202604/agent_compose_phase2_rust_core_handoff.md`

Work:

1. Mirror the Phase 1 wire contract in Rust with serde derives and deterministic serialization.
2. Implement candidate builders for:
   - RUNNING claims from `RunningClaimWire`;
   - done/running/workflow/prompt-step records from `AgentArtifactScanWire`;
   - ChangeSpec hooks, mentors, and comments from `ChangeSpecWire`.
3. Port deterministic timestamp parsing/normalization helpers used by agent loading.
4. Port dedup passes from `_dedup.py` with explicit `MergeReasonWire` / `DropReasonWire` output.
5. Port `_apply_status_overrides()` and `_sort_and_reorder()` exactly enough to satisfy Phase 1 goldens.
6. Keep liveness host-owned: accept `alive_pids` / `dead_pids` data and never inspect `/proc` or signal processes in
   Rust.

Exit criteria:

- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.
- Rust fixture output matches Phase 1 golden JSON, including merge/drop explanations.
- Handoff lists any behavior ambiguities found in the Python pipeline.

### Phase 3: PyO3 Binding and Python Facade Parity

Goal: expose the Rust composer to Python and run parity without routing the TUI to Rust yet.

Owner scope:

- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/agent_compose_facade.py`
- `src/sase/core/agent_compose_wire.py`
- `tests/test_core_agent_compose.py`
- `docs/rust_backend.md`
- handoff: `plans/202604/agent_compose_phase3_pyo3_facade_handoff.md`

Work:

1. Add `sase_core_rs.compose_agent_list(input: dict) -> dict`, releasing the GIL during Rust composition.
2. Add facade helpers that assemble `AgentComposeInputWire` from an already-collected artifact scan, ChangeSpec wire
   list, running claims, dismissed identities, and liveness results.
3. Add fake-binding tests and real-extension tests for dict shape, schema errors, and parity against the Python
   reference fixtures.
4. Add an opt-in dual-run/debug path that logs mismatches and includes `dropped` / `merge_log` details.
5. Update docs to describe the new operation as experimental/unrouted.

Exit criteria:

- Focused Python tests pass.
- Real Rust extension parity tests pass when `sase_core_rs` is installed from the sibling checkout.
- No TUI or CLI product path uses Rust composition by default.

### Phase 4: TUI Loader Shadow Integration

Goal: wire the current loader to collect composition inputs once and shadow-run Rust on realistic refreshes.

Owner scope:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/actions/agents/_loading_helpers.py`
- `tests/test_agent_loader*.py`
- `tests/perf/bench_agent_compose.py`
- handoff: `plans/202604/agent_compose_phase4_shadow_handoff.md`

Work:

1. Refactor `load_all_agents()` into explicit input collection and composition stages:
   - ChangeSpec snapshot to `ChangeSpecWire`;
   - project `.gp` files to `RunningClaimWire`;
   - artifact scan snapshot;
   - PID liveness map;
   - dismissed identity/suffix data when called from the Agents tab.
2. Keep Python composition as the returned product result, but shadow-call Rust in debug/benchmark mode and compare wire
   outputs.
3. Ensure stale `running.json` cleanup still happens in Python for dead home-mode markers.
4. Keep `AgentSnapshotCache` supplements after composition so retry promotion, tags, attempt history, and dismissed
   bundles remain behaviorally unchanged.
5. Expand tests around edge cases that historically drift:
   - plan feedback rounds (`.2`, `.3`);
   - `.epic` and `.commit` follow-ups;
   - active workflow children overriding `PLANNING` to `RUNNING`;
   - unanswered questions becoming `QUESTION`;
   - retry-chain siblings and `FAILED (RETRIED)` metadata.

Exit criteria:

- Existing agent loader tests pass.
- Shadow parity is clean on synthetic fixtures or documented with explicit follow-up issues.
- Handoff includes a first shadow performance report and whether Phase 5 may route tests through Rust.

### Phase 5: Product Routing Behind a Narrow Switch

Goal: make Rust composition the exercised route in focused tests and an opt-in route for local TUI/CLI verification.

Owner scope:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/agents/cli_status.py` only if it can reuse the same composed list without extra churn
- focused agent loader and CLI tests
- handoff: `plans/202604/agent_compose_phase5_optin_route_handoff.md`

Work:

1. Add an internal switch for the composition backend if the repo still uses switchable experimental routes; otherwise
   route only a focused helper used by tests.
2. Convert `AgentWire` back to Python `Agent` objects at the facade edge so downstream TUI rendering and kill/dismiss
   logic remain untouched.
3. Keep retry/tag/attempt/dismissed-bundle supplements in Python after Rust composition.
4. Run the existing loader suite against both Python reference and Rust composition where practical.
5. Validate `sase agents status -j --all` output parity on synthetic fixtures.

Exit criteria:

- Rust route produces the same visible ordering and statuses as Python in focused tests.
- `sase agents status -j` parity is pinned for synthetic fixtures.
- Handoff identifies remaining blockers before default routing.

### Phase 6: Performance Gate and Regression Floor

Goal: prove the routed Rust path wins on user-visible surfaces before defaulting it.

Owner scope:

- `tests/perf/bench_agent_compose.py`
- `tests/perf/bench_phase7_e2e.py` or a successor TUI trace harness
- `tests/perf/baselines/phase7_regression_floor.json`
- `plans/202604/perf_artifacts/`
- handoff: `plans/202604/agent_compose_phase6_perf_handoff.md`

Work:

1. Capture before/after timings for:
   - `compose_agent_list` microbench on synthetic small/medium/large lists;
   - full `load_all_agents()` with Python supplements included;
   - `sase agents status -j` synthetic 8-project/25-agent;
   - large synthetic 6k-row home-tree-like fixture;
   - TUI Agents-tab refresh trace if the harness exists.
2. Use Phase 7's rule: user-visible end-to-end wins matter more than microbench wins.
3. Gate default routing on:
   - no slower than Python on small fixtures;
   - at least 1.5x faster for full loader composition on medium/large fixtures, or a documented user-visible win on
     `sase agents status -j`;
   - no status/order parity drift on goldens.
4. Add a regression-floor row only after the routed surface clears the gate.

Exit criteria:

- `just phase7-perf-check --smoke` still works.
- Handoff contains measured medians, speedups, and the default-routing decision.

### Phase 7: Default Routing, Cleanup, and Documentation

Goal: make Rust composition the normal route and retire Python code only where Rust has replaced it.

Owner scope:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/models/_dedup.py`
- `src/sase/core/agent_compose_*`
- relevant tests and docs
- handoff: `plans/202604/agent_compose_phase7_default_handoff.md`

Prerequisite:

- Phase 6 handoff explicitly authorizes default routing.

Work:

1. Route `load_all_agents()` through Rust composition by default.
2. Delete or quarantine Python dedup/status/sort code only after tests no longer exercise it as a production fallback.
3. Keep Python-owned host supplements and transient TUI overrides intact.
4. Update `docs/rust_backend.md` shipped-operation list and intentionally Python-owned surface list.
5. Run focused tests, Rust checks, and full `just check`.

Exit criteria:

- Product path uses Rust composition with no silent fallback.
- Removed Python code has no live imports.
- Docs match the new boundary.

### Phase 8: Optional Transient Status Override Data Helper

Goal: decide whether the small UI-thread transient override pass is worth moving after the main route has landed.

Owner scope:

- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- optional `src/sase/core/agent_compose_facade.py` extension
- focused tests for plan approval/question notification flows
- handoff: `plans/202604/agent_compose_phase8_transient_overrides_handoff.md`

Work:

1. Measure `_loading_finalize.py`'s transient override cleanup/application cost after Phase 7.
2. If it is non-trivial, add a small pure-data Rust helper that takes visible `AgentWire` identities/statuses plus an
   override map and returns updated statuses plus override keys to clear.
3. If it is trivial, document that app-state override application remains Python-owned.

Exit criteria:

- Either a tiny helper lands with parity tests, or the handoff explicitly leaves this layer in Python as not worth a
  backend boundary.

## Risk Notes

- The `.gp` `RUNNING:` field is not currently part of `ChangeSpecWire`; the migration needs `RunningClaimWire` unless a
  separate parser extension is added.
- The research note's `compose_agent_list(scan, changespecs, dismissed_set, options)` shape is directionally right but
  underspecified for PID liveness, running claims, and dismissed bundle supplementation.
- `AgentSnapshotCache` is deliberately out of scope here. If composition wins are smaller than expected, candidate #4
  (supplement scan) should be planned separately rather than folded into this migration midstream.
- Transient notification-driven overrides are app state, not loader facts. Moving them too early would couple Rust to
  Textual UI lifecycle details.
- The implementation spans two repos (`sase` and sibling `../sase-core`). Agents must check both worktrees before
  editing and must not revert unrelated changes.

## Suggested Verification Commands

Use the narrowest command that proves the phase, then broaden before default routing:

```bash
just install
pytest tests/test_core_agent_compose.py
pytest tests/test_agent_loader.py tests/test_agent_loader_status_overrides.py tests/test_agent_loader_dedup_pid.py
just rust-check
just phase7-perf-check --smoke
just check
```

For phases that touch `../sase-core`, run Rust commands from the sibling repo or through the existing `just rust-*`
targets in `sase`.
