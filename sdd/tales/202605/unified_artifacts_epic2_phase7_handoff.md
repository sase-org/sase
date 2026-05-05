---
create_time: 2026-05-05 14:20:00
bead_id: sase-23.2.7
tier: plan
status: completed
---
# Unified Artifacts Epic 2 Phase 7 Handoff

## Implemented Source Kinds

Epic 2 rebuilds now derive graph data from these source kinds:

- `directory`
- `project_file`
- `changespec`
- `commit`
- `bead_store`
- `agent_artifact`
- `agent_created_file`
- `agent_thought`

Phase 7 added a final reconciliation pass after source ingestion. It materializes cross-source links only when both
endpoints are visible in the index:

- bead `worker` links from pending worker metadata to agent artifacts
- bead `related` links to ChangeSpecs
- agent `related` links to ChangeSpecs
- agent retry, follow-up, and parent timestamp `related` links when the timestamp resolves to exactly one agent

Unresolved worker and related targets remain in derived payload diagnostics so `artifact_doctor` can report them.
Resolved diagnostics are cleared by reconciliation.

## Metadata Gaps

Phase automation currently relies on bead `assignee` as the intended worker agent ID. This works for distinct agent
names, but an explicit launch metadata field such as `worker_for_bead_id` would avoid ambiguity when an agent display
name and bead ID collide.

Retry and follow-up links still depend on timestamp references. Ambiguous timestamp matches are not linked; they remain
as unresolved diagnostics.

## Performance Characteristics

The reconciliation pass scans derived bead and agent payload rows already present in the SQLite index. It does not
rescan project files, bead stores, or artifact directories. Fixture rebuild tests cover full rebuilds, targeted
out-of-order rebuilds, doctor checks, detail queries, and deterministic full-graph JSON export.

## Deferred Work

Epic 3 owns the `sase artifact` CLI and user-facing commands.

Epic 4 owns artifact TUI presentation and replacing the old `A` keybinding path.

Epic 5 owns migration cleanup for the legacy agent artifact index and any broader identity migration.
