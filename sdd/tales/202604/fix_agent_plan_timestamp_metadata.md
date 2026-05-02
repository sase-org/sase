---
create_time: 2026-04-29 11:35:47
status: done
prompt: sdd/prompts/202604/fix_agent_plan_timestamp_metadata.md
---
# Plan: Preserve PLAN timestamps in Agents metadata

## Context

The `sase ace` Agents tab metadata panel renders timestamps from `Agent.timestamps_display`. That renderer already
supports `PLAN` entries through `agent.plan_times`, and the filesystem artifact loader already accepts both a scalar
string and a list for `plan_submitted_at`.

The observed panel shows `BEGIN` and `CODE`, but no `PLAN`, for a plan-approved agent. That means the display layer is
not the root problem; the plan submission timestamp is being lost before it reaches `agent.plan_times`.

## Root Cause

`handle_plan_marker()` records a plan submission with:

```python
update_meta_field(..., "plan_submitted_at", datetime.now(UTC).isoformat())
```

That writes `plan_submitted_at` as a scalar string in `agent_meta.json`.

The direct loader path in `src/sase/ace/tui/models/_loaders/_artifact_loaders.py` is tolerant and converts either a
string or a list into `agent.plan_times`. The newer snapshot/wire path goes through
`src/sase/core/agent_scan_facade.py`, whose `_coerce_str_list()` currently returns an empty list for scalar strings. The
Agents tab uses the snapshot path, so scalar `plan_submitted_at` values are dropped before
`enrich_agent_from_meta_wire()` can populate `agent.plan_times`.

This same mismatch can affect `feedback_submitted_at`, `questions_submitted_at`, and other metadata fields that have
migrated toward list semantics while retaining scalar compatibility in the direct loader.

## Implementation

1. Update the core snapshot facade's string-list coercion to preserve scalar strings as single-item lists, matching the
   direct artifact loader's compatibility behavior.
2. Add focused coverage proving `scan_agent_artifacts()` preserves scalar `plan_submitted_at` values in `AgentMetaWire`.
3. Add or update loader-level coverage proving an agent built from the snapshot receives a `PLAN` timestamp in
   `timestamps_display`.
4. Keep the change narrow: do not change timestamp rendering, status override behavior, or the existing metadata file
   shape in this fix.

## Verification

1. Run the focused tests covering core scan metadata coercion and agent timestamp loading.
2. Run `just install` if needed for the workspace.
3. Run `just check` before reporting back, per repository memory.
