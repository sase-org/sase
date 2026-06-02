---
create_time: 2026-06-02 07:23:30
status: wip
prompt: sdd/prompts/202606/zorg_live_artifact_cleanup.md
---
# Plan: clean stale live artifact markers blocking `zorg` deletion

## Context

Deleting the SASE project `zorg` is currently blocked because `delete_project_locked()` refuses to remove a project
directory while it can find live artifact marker files under:

`/home/bryan/.sase/projects/zorg/artifacts`

The blocker is not the `zorg` working tree. The working tree shown by the project record is:

`/home/bryan/projects/github/zettel-org/zorg/`

That workspace must not be deleted by this cleanup.

## Evidence gathered

The project record is otherwise deletable:

- `sase project show zorg --json` reports `active_claim_count: 0`.
- The project is not system-managed.
- `sase agents status -p zorg -j` returns `[]`.
- The deletion blocker count matches the ACE snapshot: exactly 5 marker files.

The five marker files are all `waiting.json` files:

- `/home/bryan/.sase/projects/zorg/artifacts/ace-run/20260221161953/waiting.json`
  - `waiting_for: ["260221.beads"]`
  - no PID in `agent_meta.json`
  - `ready.json` is also present
- `/home/bryan/.sase/projects/zorg/artifacts/ace-run/20260221172603/waiting.json`
  - `waiting_for: ["260221.beads"]`
  - no PID in `agent_meta.json`
  - `ready.json` is also present
- `/home/bryan/.sase/projects/zorg/artifacts/ace-run/20260503002635/waiting.json`
  - agent name `zorg-4.4.0`
  - PID `1429679`
  - `waiting_for: ["zorg-4.3"]`
- `/home/bryan/.sase/projects/zorg/artifacts/ace-run/20260503002656/waiting.json`
  - agent name `zorg-4.5.0`
  - PID `1430511`
  - `waiting_for: ["zorg-4.4"]`
- `/home/bryan/.sase/projects/zorg/artifacts/ace-run/20260503002711/waiting.json`
  - agent name `zorg-4.6.0`
  - PID `1434347`
  - `waiting_for: ["zorg-4.5"]`

`ps -p 1429679,1430511,1434347` returned no rows, so the PIDs recorded by the May 3 markers are no longer live.

## Cleanup plan

1. Re-run a preflight check immediately before mutation:
   - enumerate live marker files under `/home/bryan/.sase/projects/zorg/artifacts`;
   - confirm the set is still exactly the five paths above;
   - confirm `sase project show zorg --json` still reports zero active claims;
   - re-check the recorded PIDs if the same May 3 markers are present.

2. If the live marker set changed, or if any recorded PID is live, stop and report the new evidence instead of deleting
   anything.

3. Remove only the five stale `waiting.json` marker files. Do not remove:
   - memory files;
   - the `zorg` working tree;
   - unrelated project directories;
   - unrelated artifact directories.

4. Refresh/reconcile the agent artifact index after the marker mutation so ACE does not keep a stale indexed view:
   - use the supported `sase agents index gc -j` path;
   - if index reconciliation fails for an unrelated index issue, report that separately after the filesystem blocker has
     been removed.

5. Verify the blocker is gone:
   - re-run the live-marker `find` command and confirm zero files;
   - re-run `sase agents status -p zorg -j` and confirm no active `zorg` agents;
   - re-check `sase project show zorg --json` while the project state still exists.

6. Complete project deletion only through the locked lifecycle helper used by the Project Management TUI, not by
   `rm -rf`:
   - call `delete_project_locked("zorg")` from this checkout with `PYTHONPATH=src`;
   - rely on its built-in re-check of RUNNING claims and live marker files;
   - confirm it removes `/home/bryan/.sase/projects/zorg`;
   - confirm it does not remove `/home/bryan/projects/github/zettel-org/zorg/`.

7. Reconcile the artifact index once more after project-state deletion, because deleting the project state directory
   removes all `zorg` artifact directories and may leave stale index rows otherwise.

8. Final verification:
   - `test -d /home/bryan/.sase/projects/zorg` should fail;
   - `test -d /home/bryan/projects/github/zettel-org/zorg` should succeed;
   - `sase project show zorg --json` should report the project is not found;
   - `sase agents status -p zorg -j` should remain empty.

## Safety boundary

The only direct manual deletions should be the five stale `waiting.json` files. Project state deletion should happen
through `delete_project_locked()` so the same safety checks that blocked ACE deletion are enforced immediately before
the destructive project-state removal.
