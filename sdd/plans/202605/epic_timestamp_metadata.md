---
create_time: 2026-05-01 12:19:41
status: done
prompt: sdd/prompts/202605/epic_timestamp_metadata.md
---
# Epic timestamp metadata plan

## Goal

When a user approves a plan as an epic from the plan approval modal (`E`), the selected planner agent should show an
`EPIC` row in the Agents tab metadata panel's `Timestamps:` field, analogous to the existing `PLAN` row that appears
when the plan is submitted for approval.

## Current shape

- `PLAN` rows are driven by `agent_meta.json["plan_submitted_at"]`, written in `src/sase/axe/run_agent_exec_plan.py`
  when a `sase plan` marker is handled.
- The TUI loader parses `plan_submitted_at` into `Agent.plan_times` in
  `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`.
- `Agent.timestamps_display` renders timestamp lists in chronological order with short labels such as `PLAN`, `FBACK`,
  `QUEST`, `RETRY`, and `CODE`.
- The normal code approval path gets `CODE` by deriving it from the `.code` follow-up child start time in
  `src/sase/ace/tui/models/agent_loader.py`.
- The epic approval path creates a `.epic` follow-up and sets status to `EPIC APPROVED`, but there is no persisted
  timestamp field or `Agent` field for an `EPIC` row.
- Agent metadata is scanned through the required Rust extension (`../sase-core`), so new metadata fields must be added
  to both the Python wire dataclass and the Rust scanner projection.

## Design

Add a new metadata field named `epic_started_at`, parsed and rendered as `EPIC`.

The name is intentionally action-oriented rather than approval-modal oriented: it records when the epic creation
follow-up is launched, matching the user-visible event that the `EPIC APPROVED` status represents. It also mirrors the
`CODE` semantics, where the timestamp represents the follow-up work starting rather than the moment the modal button was
pressed.

## Implementation steps

1. Extend the Python `Agent` model with `epic_time: datetime | None`.
2. Update `Agent.timestamps_display` to include `(epic_time, "EPIC")` in the chronological middle section.
3. Update bundle serialization in `src/sase/ace/tui/models/agent_bundle.py` so dismissed/revived agents preserve
   `epic_time`.
4. Persist `epic_started_at` on the `.epic` follow-up artifacts when `handle_plan_marker()` creates the epic follow-up
   directory. Use the same UTC ISO format used by `plan_submitted_at`.
5. Parse `epic_started_at` in both filesystem and wire metadata enrichment paths in
   `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`.
6. Propagate `epic_time` from `.epic` follow-up children to their parent in `src/sase/ace/tui/models/agent_loader.py`,
   just as `.code` currently propagates `code_time`.
7. Include `epic_started_at` when reviving/dismissing plan-like agents in
   `src/sase/ace/tui/actions/agents/_revive_artifacts.py`.
8. Extend `AgentMetaWire` in `src/sase/core/agent_scan_wire.py`.
9. Extend the Rust scanner in `../sase-core`:
   - add `epic_started_at: Option<String>` to `AgentMetaWire`;
   - read it from `agent_meta.json` in `agent_meta_from_object()`;
   - add a scanner parity test covering the field.
10. Add focused tests:
    - `Agent.timestamps_display` includes `EPIC` in chronological order;
    - bundle round-trip preserves `epic_time`;
    - metadata enrichment parses `epic_started_at`;
    - loader status override propagation moves `.epic` child `run_start_time`/`epic_started_at` to the parent;
    - `handle_plan_marker()` writes `epic_started_at` on epic follow-up artifacts;
    - Python agent scan wire test sees `epic_started_at` from metadata.

## Validation

- Run the focused Python tests for agent timestamps, bundle serialization, metadata loading, loader overrides, and epic
  plan handling.
- Run `just rust-test` or the focused `cargo test -p sase_core agent_scan_parity` target after changing `../sase-core`.
- Because this repo changed, run `just install` if needed, then `just check` before reporting back.

## Risk and compatibility

- Existing metadata files without `epic_started_at` continue to render unchanged.
- The new field is optional in both Python and Rust wire models, so older artifacts and tests remain compatible.
- If the Rust extension installed in the local venv is stale, Python tests that call `scan_agent_artifacts()` may not
  see the new field until `just install` rebuilds `sase_core_rs` from `../sase-core`.
