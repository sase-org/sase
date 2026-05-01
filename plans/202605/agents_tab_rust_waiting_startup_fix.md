---
create_time: 2026-05-01 02:41:41
status: done
---
# Agents Tab Rust WAITING and Startup Regression Plan

## Problem Statement

The `sase ace` Agents tab recently regressed in two ways:

- Agents in dependency wait state display as `RUNNING` instead of `WAITING`.
- TUI startup increased from roughly 3s to roughly 5s.

The recent change that lines up with both symptoms is the switch of Agents-tab composition to the Rust
`sase_core_rs.compose_agent_list` path by default, while leaving substantial Python composition code in the hot path as
a reference/fallback.

The user requirement for this fix is strict: if this behavior has a Rust implementation, the product route should use
Rust, and the old Python implementation should not be kept around as an alternate version.

## Current Findings

### WAITING status root cause

The Python RUNNING-field loader used to build a RUNNING agent, call
`enrich_agent_from_meta(agent, agent.get_artifacts_dir())`, and let that enrichment read `waiting.json`. When
`waiting.json` existed and the row status was `RUNNING`, the Python path changed the row to `WAITING` and populated
`waiting_for`, `wait_duration`, and `wait_until`.

The Rust composer builds RUNNING-field rows from `RunningClaimWire` in
`../sase-core/crates/sase_core/src/agent_compose/mod.rs::build_running_claim_agents()`. That function does not join the
claim to the matching `AgentArtifactRecordWire`, so it does not see the artifact record's `agent_meta`, `waiting`, or
prompt-step metadata. Other Rust-built rows, such as home running agents and workflow agents, already call
`enrich_from_meta(&mut agent, &record.agent_meta, &record.waiting)`.

This explains the visible `RUNNING` instead of `WAITING`: the Rust route has the marker data in the same compose input
but never applies it to RUNNING-field claims.

### Startup regression root cause

`src/sase/ace/tui/models/agent_loader.py::load_all_agents_with_dismissed()` currently does this even when the selected
backend is Rust:

1. Collects Rust compose inputs.
2. Builds the full Python candidate list via `_load_agents_from_collected_sources(inputs)`.
3. Uses that Python list only to collect PID liveness.
4. Throws the Python list away and calls `compose_rust_agent_list_with_dismissed(compose_input)`.

That means the Rust product path still pays for the old Python artifact-to-Agent construction, ChangeSpec agent
construction, Python enrichment, and Python workflow-step construction before invoking Rust. The extra work is a direct
startup cost, and it is also why deleting the Python composition path matters for performance rather than only code
hygiene.

## Goals

1. Restore correct `WAITING` status for RUNNING-field agents on the Rust product path.
2. Remove Python composition from the default hot path so startup no longer constructs a full Python agent list before
   Rust composition.
3. Delete the old Python composition fallback/reference modules for behavior that is now implemented in Rust.
4. Keep Python only for host-owned responsibilities: collecting project files, parsing ChangeSpecs into wire records,
   scanning artifacts through the Rust facade, checking process liveness, rehydrating Rust wire rows into TUI `Agent`
   objects, and TUI/UI side effects.
5. Add regression coverage in Rust and Python so this does not silently regress again.

## Non-Goals

- Do not reintroduce `SASE_AGENT_COMPOSE_BACKEND=python` as a product escape hatch.
- Do not rewrite the PyO3 dict/JSON boundary in this change unless measurements after removing the double Python
  composition still miss the startup target.
- Do not change unrelated Agents-tab rendering, grouping, or keybindings.

## Implementation Plan

1. Fix Rust enrichment for RUNNING-field claims.
   - In `../sase-core/crates/sase_core/src/agent_compose/mod.rs`, build an index from artifact-scan records keyed by
     project plus normalized timestamp, with workflow-name matching where useful (`ace(run)` / `run` to `ace-run` /
     `run`, `workflow(name)` to `workflow-name`).
   - Pass that index into `build_running_claim_agents()`.
   - When a RUNNING claim matches an artifact record, set `artifacts_dir` and call the existing Rust
     `enrich_from_meta()` and `enrich_from_prompt_markers()` helpers on the claim-built row.
   - Update `enrich_from_meta()` so it mirrors Python semantics: a present `waiting` marker changes only `RUNNING` rows
     to `WAITING`, wait fields from `waiting.json` override `agent_meta.json`, and `%plan` status transitions happen
     only if the row is still `RUNNING`.

2. Remove the Python composition backend from the TUI loader.
   - Delete backend selection and shadow-compare logic from `agent_loader_backend.py`.
   - Make `load_all_agents_with_dismissed()` always call the Rust composer.
   - Remove `_compose_python_agent_list()`, `_filter_dead_pids()`, `_load_agents_from_collected_sources()` and the
     imports that exist only to build Python candidate rows for composition.
   - Delete Python modules whose behavior is now owned by Rust composition (`agent_loader_status.py`,
     `agent_loader_ordering.py`, and composition-only dedup helpers) once no supported Python callers remain.

3. Replace Python-list PID collection with direct wire-input PID collection.
   - Add a small Python host helper that collects PIDs directly from `RunningClaimWire`, `AgentArtifactScanWire`
     `running` markers, active workflow-state markers, and ChangeSpec running-agent suffixes.
   - Use the existing `is_process_running()` check once per PID to populate `alive_pids` and `dead_pids` on
     `AgentComposeInputWire`.
   - Keep this as host logic because process liveness is explicitly outside the Rust deterministic composer boundary.

4. Update docs and tests to the new contract.
   - Remove tests that assert the Python backend exists.
   - Convert existing Python composer tests to assert Rust facade invocation and rehydration.
   - Add/adjust Python tests proving `load_all_agents()` does not call old Python source loaders when Rust can compose
     from collected wire inputs.
   - Add Rust unit tests in `sase-core` for a RUNNING-field claim with matching `agent_meta.json` / `waiting.json`
     snapshot data, asserting `WAITING` and wait field precedence.
   - Update `docs/rust_backend.md` and any handoff docs that still describe the Python compose backend as available.

5. Verify behavior and performance.
   - Run focused Rust tests for `agent_compose`.
   - Run `just rust-install` in `sase_101` so the local venv imports the edited Rust extension.
   - Run focused Python tests around `test_agent_loader.py`, `test_core_agent_compose.py`, and any affected loader
     integration tests.
   - Run a small startup/compose timing check before and after the loader change to confirm the full Python candidate
     build is gone from the Rust path.
   - Run `just check` in `sase_101` before reporting back.
   - If Rust source changed in `../sase-core`, run the relevant Rust check target there or `just rust-test` from
     `sase_101`.

## Risks and Mitigations

- Matching artifact records to RUNNING claims by timestamp alone could collide across projects or workflow dirs.
  Mitigation: key by project and timestamp, then prefer workflow-compatible records.

- Deleting Python composition helpers can break tests that were intentionally testing the old reference route.
  Mitigation: move behavioral coverage to Rust unit tests and Python facade tests; keep Python tests only at the
  wire/rehydration boundary.

- A stale installed `sase_core_rs` could make Python tests validate old Rust behavior. Mitigation: rebuild with
  `just rust-install` after Rust edits and confirm `.venv` imports the local extension.

- Removing the double Python composition may expose missing PID sources. Mitigation: add direct PID-source tests
  covering RUNNING claims, home `running.json`, workflow-state PID, and ChangeSpec running-agent suffixes.
