---
create_time: 2026-04-10 22:40:15
status: done
---

# Plan: Make revived Agents entries round-trip exactly to pre-dismiss state

## Goal

Reviving an agent from the Agents tab (`R`) should reconstruct the entry exactly as it appeared immediately before
dismissal, including status, metadata panel fields, and hierarchy behavior.

## Problem framing

Current revive writes synthetic artifacts from bundled `Agent` objects, but the serialization is not fully compatible
with loader expectations. Two likely classes of drift are present:

1. Status canonicalization drift:

- Revive persists display statuses directly into `workflow_state.json`.
- Loader only understands canonical workflow statuses (`completed`, `failed`, etc.).
- Synthetic statuses such as `PLAN DONE` can be interpreted as active/running and then converted to `FAILED` when PID is
  dead.

2. Metadata fidelity drift:

- Revive currently restores only a minimal subset of `agent_meta.json` fields.
- Loader derives timeline/status context (WAIT/BEGIN/END, PLAN/FBACK/CODE/QUEST/RETRY, role suffix behavior,
  hidden/workspace linkage) from additional meta fields.
- Missing fields causes revived entries to differ from original display.

## Design approach

Use a lossless “write canonical + write complete metadata” restoration strategy:

1. Canonicalize persisted marker statuses:

- In revive marker builders, map all dismissable completion-like display statuses to canonical completed marker states.
- Ensure `PLAN DONE`, `PLAN COMMITTED`, and other terminal success-like display statuses are written as completed in
  workflow markers.
- Preserve explicit failure statuses as failed.

2. Restore full agent metadata footprint:

- Expand `_restore_agent_meta()` to write the full set of loader-consumed fields available on bundled `Agent` objects.
- Include timeline fields (`run_started_at`, `stopped_at`, plan/feedback/question/retry timestamps), display control
  fields (`hidden`, `role_suffix`, `workspace_num`, `parent_timestamp`), and existing identity/provider fields.
- Keep write behavior stable and idempotent.

3. Preserve revive semantics for parent/child artifacts:

- Keep existing child/parent restoration flow and alias cleanup behavior.
- Avoid changes to dismissal semantics unless required by evidence from failing tests.

## Validation plan

1. Add/extend unit tests in revive-focused tests to cover:

- Workflow status canonicalization when restoring agents with synthetic terminal statuses.
- `agent_meta.json` restoration includes the loader-relevant fields needed for exact display round-trip.

2. Run targeted tests first:

- `tests/test_agent_revive.py`
- Any adjacent loader tests if impacted.

3. Run repo checks per project instructions:

- `just install` (workspace freshness guarantee)
- `just check`

## Risks and mitigations

- Risk: Overwriting existing meta could clobber newer runtime updates. Mitigation: keep current “write if missing”
  behavior unless tests show stale-file overwrite is required for correctness.

- Risk: Mapping too many statuses to completed could hide true failures. Mitigation: preserve explicit failed statuses;
  only canonicalize known terminal-success display statuses.

## Expected outcome

Revived entries on the Agents tab retain original status and metadata-driven presentation (timestamps, role-dependent
states, and hierarchy cues), eliminating false `FAILED` states and visual drift after revive.
