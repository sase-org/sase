---
create_time: 2026-05-14 11:20:00
status: done
bead_id: sase-3e.7.5
---
# Phase 7E Handoff: Durable Workflow Transition Scheduler

Bead: `sase-3e.7.5`. Epic: `sdd/epics/202605/epic7_daemon_scheduler_phases.md`.

## Changed Files

- `../sase-core/crates/sase_core/src/projections/workflows.rs`
  - Added workflow scheduler causes, durable workflow task rows, stable step ids, task ids on workflow events, and replay
    support.
- `../sase-core/crates/sase_core/src/projections/migrations.rs`
  - Added projection schema version 10 with `workflow_tasks`, step ids, scheduler task/cause JSON columns, and workflow
    event task ids.
- `../sase-core/crates/sase_gateway/src/local_transport.rs`
  - Added daemon write surfaces for `workflow.step_transition` and `workflow.hitl_request`.
  - Existing `workflow.state` and `workflow.action_response` writes now attach scheduler cause/task metadata.
- `src/sase/xprompt/workflow_daemon_writes.py`
  - Added Python helpers for HITL request materialization and step transition writes, with direct-mode fallback.
- `src/sase/xprompt/workflow_executor.py`
  - Emits durable step-transition writes when prompt step markers are written.
- `src/sase/xprompt/workflow_hitl.py`
  - Writes TUI HITL request files through daemon workflow writes before falling back to direct file writes.
- `src/sase/daemon/write_facade.py`
  - Advertises the new workflow write surfaces under `workflows.write`.

## Flags And Fallbacks

- No default routing flag changed.
- Workflow execution remains Python-owned.
- If daemon workflow writes are disabled or unavailable, `workflow_state.json`, prompt step markers, and HITL request /
  response files still use the direct source-file paths.

## Verification

- `just install`
- `just check`
- `cargo test --manifest-path ../sase-core/Cargo.toml -p sase_core workflow_live_projection_matches_replay_and_preserves_step_order`
- `cargo test --manifest-path ../sase-core/Cargo.toml -p sase_gateway workflow`
- `LD_LIBRARY_PATH=/home/bryan/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib PYO3_PYTHON=/home/bryan/projects/github/sase-org/sase_102/.venv/bin/python PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 cargo test --manifest-path ../sase-core/Cargo.toml -p sase_gateway indexer::tests::reconciliation_requeues_sources_missed_by_watcher`

Full `cargo test --manifest-path ../sase-core/Cargo.toml --all` reaches the gateway suite but the existing
`indexer::tests::reconciliation_requeues_sources_missed_by_watcher` test fails in the full parallel run and passes when
rerun directly with the same environment.

## Remaining Risks

- Workflow retry/resume is now represented as task/event shape in the projection model, but routing user-facing retry and
  resume controls through graph operations remains a follow-up for the later scheduler-authoritative rollout.
- Shell/Python output summaries are bounded for workflow step transition events; full log storage/indexing remains
  host-side.
