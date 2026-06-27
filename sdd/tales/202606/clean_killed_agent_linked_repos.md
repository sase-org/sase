---
create_time: 2026-06-27 09:53:20
status: wip
prompt: sdd/prompts/202606/clean_killed_agent_linked_repos.md
---
# Clean Linked Repo Workspaces After Agent Kill

## Root Cause

SASE already records linked repositories opened by an agent run in `opened_linked_workspaces.json` and uses that marker
in the commit finalizer. For suffix-strategy linked repos, the finalizer treats dirty opened linked workspaces as
enforced work that must be committed.

The kill path does not currently mirror that ownership boundary. The TUI kill flow signals the agent, hides it
optimistically, then persists kill side effects inside a tracked cleanup task. That persistence releases the primary
workspace claim and updates dismissed/notification/artifact state, but it does not clean the linked workspaces opened by
the killed run. As a result, dirty files can remain in a numbered linked checkout after the owning agent is gone. Later
runs that receive or open the same numbered linked checkout can inherit stale dirty state, and the finalizer can ask the
wrong agent to commit it.

## Proposed Fix

Add linked-workspace cleanup to the durable kill cleanup path, not to the UI event handler.

1. Add a small helper for killed-agent linked workspace cleanup.
   - Read opened linked-repo records from the killed agent's artifact directory.
   - Cross-check against the agent's resolved linked-repo metadata when available, so `workspace.strategy: none` static
     linked repos stay advisory and are not automatically cleaned.
   - Use the recorded workspace path when present, falling back to launch metadata only when needed.
   - Normalize and dedupe paths so bulk/workflow cleanup does not clean the same checkout more than once.
   - Skip missing paths and non-suffix/static repos; attempt cleanup only for concrete suffix-strategy linked workspace
     paths.

2. Clean selected linked workspaces with the existing VCS provider primitive.
   - Use provider `stash_and_clean(...)` rather than deleting changes directly, matching `workspace open` / workspace
     preparation behavior and preserving a recoverable backup for accidental cleanup.
   - Use a kill-specific backup label that includes stable context such as the linked repo name and agent or ChangeSpec
     label.
   - Return a structured outcome with cleaned, skipped, and failed repos so the tracked task can surface failures
     without blocking the UI.

3. Wire the helper into the kill persistence transaction.
   - Call it from the shared durable kill path used by TUI kill persistence and plan-rejection cleanup.
   - For bulk kill, run it for killed agents only, not for agents that are merely dismissed, and dedupe across killed
     agents.
   - Keep it inside the existing tracked cleanup task submitted by `_submit_kill_persistence_task` /
     `_submit_bulk_kill_persistence_task`, so all disk and subprocess work stays off the Textual event loop.
   - Do not run linked cleanup from dismiss-only flows; a completed agent's dirty work should remain visible to the
     normal finalizer/review paths.

4. Preserve existing kill semantics.
   - The optimistic UI removal and process signal request remain fast.
   - Primary workspace claim release, dismissed-agent persistence, notification dismissal, artifact deletion, and
     cleanup-plan intent execution continue to happen through the existing transaction.
   - Cleanup failures should be visible in the task result and logs, but should not reintroduce synchronous TUI work.

## Tests

Add targeted coverage at three levels:

1. Linked-workspace cleanup helper tests.
   - Dirty suffix linked repo recorded in opened markers is stashed/cleaned.
   - Static `workspace.strategy: none` linked repo is skipped.
   - Canonical and legacy opened markers are both honored.
   - Duplicate records/metadata clean a path once.
   - Missing or malformed marker data is a no-op.

2. Kill transaction/task tests.
   - Single-agent TUI kill submits the existing tracked task, and the worker runs linked cleanup inside that task.
   - Bulk kill cleans linked repos for killed agents and not dismiss-only agents.
   - A cleanup failure is reported through the cleanup task outcome without blocking the event loop.

3. Regression/finalizer behavior.
   - After the kill cleanup helper runs on a dirty opened suffix linked repo, the commit finalizer dirty-state
     collection no longer sees that linked repo as needing a commit.

## Validation

Run focused tests first:

```bash
pytest tests/test_linked_repos.py
pytest tests/ace/tui/test_agent_cleanup_tasks.py
pytest tests/llm_provider/test_commit_finalizer_linked_repos_compat.py
```

Then run the repository-required validation:

```bash
just install
just check
```
