---
create_time: 2026-05-13 19:44:49
status: done
prompt: sdd/prompts/202605/wait_timestamp_display.md
---
# WAIT Timestamp Display Plan

## Problem

The Agents tab metadata panel currently renders `Agent.timestamps_display` with `START` as the first timestamp for every
agent. While an agent is blocked by a `%wait` directive, the display appends a second `WAIT` row using the same launch
timestamp, so users see both:

```text
START | ...
WAIT  | ...
```

After the wait barrier clears, `waiting.json` is removed and metadata enrichment promotes the row from `STARTING` to
`RUNNING` via `wait_completed_at` or `run_started_at`. At that point the special WAITING-only branch no longer runs, so
the metadata panel goes back to showing `START` and stops showing `WAIT`, even though this agent did wait before it ran.

Desired behavior:

- Before a wait marker exists, a newly launched agent can still show `START`.
- Once the agent enters `%wait`, replace `START` with `WAIT`; do not show both.
- After the wait clears, keep using `WAIT` as that agent's launch/pre-run timestamp label for the rest of its lifecycle.
- Continue showing later lifecycle timestamps such as `RUN`, `PLAN`, `CODE`, and `DONE` when available.

## Current Code Path

- `src/sase/ace/tui/models/agent.py`
  - `Agent.timestamps_display` is the metadata-panel source.
  - It always appends `START` from `start_time`.
  - It appends `WAIT` only when `status == "WAITING"` and `run_start_time is None`.
- `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`
  - Reads `agent_meta.json` and optional `waiting.json`.
  - `waiting.json` flips active rows to `WAITING` and populates wait details.
  - `wait_completed_at` promotes post-wait/pre-run-start rows to `RUNNING`.
- `src/sase/axe/run_agent_wait.py`
  - Writes `waiting.json` while the agent is blocked.
  - Records durable `wait_completed_at` in `agent_meta.json` before removing `waiting.json`.
- `src/sase/core/agent_scan_wire_markers.py`
  - Snapshot wire already carries `wait_for`, `wait_duration`, `wait_until`, and `wait_completed_at`.

This is TUI presentation/state-enrichment behavior. No Rust-core change is needed if we continue using the existing
artifact/launch timestamp as the WAIT timestamp, which matches the WAIT row currently shown while blocked.

## Implementation Plan

1. Add a display-state field to `Agent`.

   Add `wait_start_time: datetime | None = None` to `src/sase/ace/tui/models/agent.py`. This field means: "this agent
   has entered the pre-run wait phase, so the first timestamp row should be labeled WAIT instead of START." Initially it
   can reuse `start_time`, because the current WAIT row already uses `start_time` and the wait marker does not persist a
   separate wait-created timestamp.

2. Populate `wait_start_time` during metadata enrichment.

   In both `enrich_agent_from_meta` and `enrich_agent_from_meta_wire`:
   - When a live `waiting.json` / `WaitingMarkerWire` is present, set `agent.wait_start_time = agent.start_time`.
   - When durable metadata shows that the agent crossed a wait barrier (`wait_completed_at`), set
     `agent.wait_start_time = agent.start_time`.
   - Consider also setting it when persisted wait directive fields exist (`wait_for`, `wait_duration`, `wait_until`) so
     completed historical agents with wait metadata but no `wait_completed_at` still display as waited agents.

   Keep filesystem and wire enrichment in lockstep.

3. Change `Agent.timestamps_display` first-row logic.

   Replace the current "always START, sometimes append WAIT" logic with:
   - Use `WAIT` as the first tag when `wait_start_time` is set, or when the row is currently `WAITING`.
   - Otherwise use `START`.
   - Append `RUN` when `run_start_time` exists.
   - Do not append a separate `WAIT` row.

   This yields:
   - Newly launched, not yet waiting: `START`
   - Currently waiting: `WAIT`
   - Wait completed, pre-run-start: `WAIT`
   - Wait completed and running: `WAIT`, `RUN`
   - Waited and completed: `WAIT`, `RUN` if known, `DONE`

4. Update tests.

   Focused unit tests should cover the behavior without requiring a visual snapshot update:
   - Update `tests/test_agent_model_timestamps.py::test_timestamps_display_wait_tag_for_waiting_status` to expect only
     `WAIT`.
   - Add tests for:
     - a post-wait `RUNNING` agent with `wait_start_time` and no `run_start_time` showing only `WAIT`;
     - a post-wait running agent with `run_start_time` showing `WAIT`, `RUN`;
     - a terminal waited agent preserving `WAIT` through `DONE`.
   - Update/add `tests/test_enrich_agent_waiting.py` assertions that:
     - live `waiting.json` sets `wait_start_time`;
     - `wait_completed_at` sets `wait_start_time`;
     - wire enrichment mirrors both cases.

5. Verification.

   Run targeted tests first:

   ```bash
   just install
   uv run pytest tests/test_agent_model_timestamps.py tests/test_enrich_agent_waiting.py
   ```

   Because this changes repo files, finish with:

   ```bash
   just check
   ```

## Risks and Notes

- The plan intentionally does not introduce a new persisted `wait_started_at` field. If exact wait-entry time becomes
  important later, that should be a separate marker-schema change touching `waiting.json`, scan wire projection, and
  compatibility tests.
- The TUI list runtime behavior already treats waiting time separately via `run_start_time`; this plan only changes the
  metadata-panel timestamp labels.
- The existing `wait_completed_at` promotion behavior remains intact so rows still transition from `WAITING` to
  `RUNNING` when the wait barrier clears.
