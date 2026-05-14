---
bead_id: sase-3e.4
created_at: 2026-05-14
create_time: 2026-05-13 22:34:20
status: wip
prompt: sdd/prompts/202605/sase_3e_4_remaining_shadow_indexing.md
---

# Remaining Work Plan: sase-3e.4 Shadow Indexers

## Findings

The epic bead and all child beads are marked closed, but verification found that the implementation is not complete:

- Only the Phase 4A implementation commit is present in `../sase-core`; later child bead note SHAs are not reachable in
  the sibling repo history, while a large set of related source changes remains uncommitted.
- Notification and pending-action indexing is not implemented in the daemon rebuild, verify, diff, watcher, or
  reconciliation paths; the daemon currently reports notifications as an empty OK summary.
- Catalog indexing only covers xprompt catalog rows. Workflow catalog, config catalog, memory catalog, artifact-index,
  and file-history backfill/diff/watch behavior from Phase 4F is incomplete.
- Incremental watcher output only constructs projected events for ChangeSpecs, agents, and beads. Catalog and
  notification source changes are only reported as indexing counters, not applied to projections.
- The plan file still advertises `status: wip`.

## Plan

1. Reopen/mark `sase-3e.4` as in progress while completing the missing work.
2. Finish notification and pending-action shadow indexing in `../sase-core`:
   - discover notification JSONL and pending-action store files;
   - backfill projections through existing notification store loaders;
   - handle append, rewrite, state-update-equivalent, pending-action rewrite/update/cleanup cases;
   - add shadow diff records for missing, stale, extra, and corrupt notification/pending-action rows.
3. Wire notifications into `../sase-core/crates/sase_gateway/src/indexer.rs`:
   - classify notification and pending-action source paths;
   - generate projection events for rebuild and incremental watcher batches;
   - include notifications in reconciliation source discovery and bounded diagnostics;
   - make verify/diff use real notification source comparisons.
4. Complete Phase 4F catalog coverage:
   - add backfill/diff support for config, memory, file-history, workflow catalog, and artifact-index sources where
     existing loaders define stable current behavior;
   - keep plugin/generated inputs as explicit resync-required diagnostics when they cannot be passively watched;
   - generate projection events for catalog watcher changes instead of reporting counters only.
5. Add focused Rust tests for the missing surfaces:
   - notification append/rewrite/invalid-line/pending-action diff behavior;
   - daemon rebuild/verify/diff summaries for notifications;
   - catalog config/memory/file-history/workflow watcher and diff behavior;
   - reconciliation including notification/catalog sources.
6. Re-run verification:
   - `cargo test -p sase_core projections`;
   - `cargo test -p sase_gateway indexer`;
   - after `just install` in this repo, `pytest -q tests/test_daemon_client.py tests/test_daemon_lifecycle.py`;
   - broader `just check` in any repo with source changes.
7. Commit or otherwise land the completed implementation with commit messages containing the relevant child bead IDs.
8. Update `sdd/epics/202605/rust_daemon_epic4_shadow_indexers.md` frontmatter to `status: done`.
9. Close the epic bead with `sase bead close sase-3e.4`, then run `just pyvision` after the epic is closed.
