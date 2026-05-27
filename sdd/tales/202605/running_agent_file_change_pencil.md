---
create_time: 2026-05-27 13:00:25
status: done
prompt: sdd/prompts/202605/running_agent_file_change_pencil.md
---
# Running Agent File-Change Pencil Plan

## Context

The Agents tab row renderer already shows the pencil glyph when an `Agent` has `diff_path` populated, and renderer/cache
tests already cover this for running rows. Completed agents get `diff_path` from `done.json`, so the pencil appears
after completion. Running agents that have already committed or proposed changes write `commit_result.json` with
`diff_path`, but that value is not currently available to the running-agent row model.

## Performance Constraint

Do not add git status/diff calls, workspace scans, tool-call JSONL reads, or per-render filesystem checks to the TUI.
The Agents tab must continue to render from the in-memory `Agent` model and the existing row-render cache key. The
running-agent refresh path already reads or receives the `agent_meta.json` projection, including through the Rust-backed
artifact scan/index path, so the new signal should ride on that existing marker.

## Proposed Design

1. When the commit/proposal workflow writes `commit_result.json`, also persist only the produced `diff_path` into
   `agent_meta.json` as `commit_diff_path` when a non-empty diff path exists.
   - Do not copy graph relationship fields such as `commit_entry_id`, `commit_result`, or `commit_changespec_name` into
     `agent_meta.json`.
   - Refresh the artifact index after mutating `agent_meta.json` so indexed snapshot consumers see the same marker
     state.

2. Teach both metadata enrichment paths to map `commit_diff_path` onto `Agent.diff_path` when `Agent.diff_path` is not
   already set.
   - Filesystem path: `enrich_agent_from_meta`.
   - Snapshot/wire path: `enrich_agent_from_meta_wire`.
   - Completed-agent `done.json` remains authoritative because it already sets `diff_path` before metadata enrichment.

3. Leave row rendering unchanged except for any cache-key adjustment required by the model field. Since this design
   populates the existing `diff_path` field, the current renderer and `bool(agent.diff_path)` cache key should remain
   sufficient.

4. Add focused regression tests.
   - Commit result writing persists `commit_diff_path` into `agent_meta.json` without persisting graph relationship
     fields.
   - Filesystem metadata enrichment sets `Agent.diff_path` from `commit_diff_path`.
   - Wire metadata enrichment sets `Agent.diff_path` from `AgentMetaWire.commit_diff_path`, covering Rust/index-backed
     snapshots.
   - Existing renderer tests continue to prove the pencil appears for running rows once `diff_path` is populated.

## Validation

Run the narrow test set covering commit marker persistence, metadata enrichment, and agent-list rendering first. Because
this repo requires it after code edits, run `just install` if needed and then `just check` before finishing.
