---
create_time: 2026-06-06 08:56:33
status: done
prompt: sdd/prompts/202606/recent_agent_restore.md
---
# Plan: Recent Agent Dismissals in Agent Restore

## Goal

Add a fast restore path for the last ten user-initiated agent or agent-group dismissals. Recent dismissals should appear
in the Agents-tab restore panel and behave like saved dismissed-agent groups: selecting a row revives the referenced
dismissed bundles without opening the slow custom archive search that loads all dismissed agents from disk.

## Current Architecture

- Dismissed agents are tracked in `dismissed_agents.json` and serialized into per-agent dismissed bundles before
  artifacts are deleted.
- Same-session revive uses `_dismissed_agent_objects`, but cross-session revive currently requires the custom archive
  search path, which calls `load_dismissed_bundles()` with no suffix filter and can be slow.
- Saved agent groups already use `SavedAgentGroupWire` / `SavedAgentGroupSummaryWire`, are listed in
  `SavedAgentGroupRevivalModal`, and revive by loading only the suffixes referenced by the selected group.
- The saved-group archive is canonical backend behavior in `sase-core`; Python exposes it through
  `src/sase/ace/dismissed_agent_groups.py` and `src/sase/ace/dismissed_agents.py`.
- Plain dismiss paths are optimistic in the TUI and persist asynchronously in `_dismissing.py` /
  `_dismiss_persistence.py`; marked save-and-dismiss already builds a `SavedAgentGroupWire` in `_marking.py`.

## Proposed Design

Use the existing saved-group wire format for recent dismissals, but store them in a separate capped "recent dismissals"
archive rather than mixing them into the durable user-saved group directory.

This keeps the restore panel fast and bounded:

- Opening the panel reads at most ten recent group metadata records.
- Selecting one recent row loads only the referenced dismissed bundles by suffix.
- The existing full archive search remains available as the explicit "Custom revival search..." fallback.

### Recent Dismissal Store

Add backend support for a capped recent-dismissal store:

- Store records as `SavedAgentGroupWire` with `source="recent_dismissal"` for automatic plain/bulk dismissals.
- Keep explicit saved-and-dismissed marked groups as normal saved groups, and also mirror their group record into the
  recent store so they appear in the recent section without duplicating revive logic.
- Maintain newest-first order and cap to ten dismissal actions, not ten agents.
- Dedupe by `group_id`; optionally replace older records with the same identity/suffix set if the same operation is
  retried.
- Store in a small dedicated JSON file or directory under `~/.sase`, separate from `dismissed_agent_groups`, with atomic
  write semantics and corrupt-file tolerance.

Because this is cross-frontend domain behavior, implement the canonical capped-store operations in `sase-core`, then
expose them through the PyO3 binding and Python facade with a pure-Python fallback:

- `record_recent_dismissed_agent_group(root, group, limit=10) -> SavedAgentGroupWire`
- `list_recent_dismissed_agent_groups(root, limit=10) -> SavedAgentGroupPageWire`
- `load_recent_dismissed_agent_group(root, group_id) -> SavedAgentGroupWire | None`
- `mark_recent_dismissed_agent_group_revived(root, group_id, revived_at) -> SavedAgentGroupWire | None`

### Shared Group Builder

Refactor saved-group construction out of `_marking.py` into a reusable helper module, for example
`src/sase/ace/tui/actions/agents/_saved_group_records.py`.

The helper should build `SavedAgentGroupWire` from concrete `Agent` objects and support:

- `source="marked_agents"` for explicitly saved groups.
- `source="recent_dismissal"` for automatic recent restore records.
- Stable ASCII-safe group ids such as `recent-<utc timestamp>-<short identity hash>`.
- Existing summary fields: title, counts, project names, CL names, statuses, model/provider/tag refs, workflow-child
  metadata, and bundle paths when available.

For workflow parents and grouped dismissals, include every agent row hidden by the dismissal plan, including workflow
children. The restore execution should still revive top-level rows first, as the saved-group path already does.

### Dismiss Integration Points

Record recent dismissals from the same user-facing operations that currently hide agents and persist dismissed state:

- `_dismiss_planned_agent`: one recent group for the single dismiss action, including workflow children from the cleanup
  plan.
- `_do_dismiss_all`: one recent group for the batch dismiss action.
- `_save_marked_agent_group`: mirror the saved group into the recent store after building it, so the restore panel's
  recent section reflects the action.
- `_do_bulk_kill_agents`: record the dismiss portion of mixed kill/dismiss operations, and include killed rows only if
  the existing cleanup path saves dismissed bundles for them and revive is expected to work.

Keep disk writes off the UI thread:

- Build and cache the recent group optimistically in memory at dismiss time so the restore panel can show it
  immediately.
- Pass the group into the existing async persistence transaction.
- Persist the recent record after dismissed bundles have been saved and before or alongside `save_dismissed_agents`.
- If persistence fails, keep current failure behavior: notify and schedule refresh. A stale optimistic recent row may
  later warn that bundles are missing, which matches existing partial saved-group handling.

Do not record automatic loader cleanup or archive self-heal events as recent user dismissals.

### Restore Panel UI

Evolve `SavedAgentGroupRevivalModal` into an Agent Restore panel while preserving existing behavior:

- Title: `Agent Restore`.
- First section: `Recent dismissals`, showing up to ten recent records.
- Second section: `Saved groups`, showing saved group pages from `list_dismissed_agent_groups`.
- Final row remains `Custom revival search...`.
- `Load more saved groups...` still pages only saved groups, not recent dismissals.
- Recent rows use the same preview and selection behavior as saved groups, with a small source label such as `recent`.
- Revived recent rows can use the existing `revived` dim/italic treatment.

Result routing should know whether the selected group came from the recent store or saved-group archive. Use namespaced
option ids or include a source/location field in `SavedAgentGroupRevivalResult`.

On selection:

- Recent group: load from the in-memory recent cache first, then the recent store.
- Saved group: load from the saved-group archive.
- Resolve refs with the existing `resolve_saved_group_agents()` helper so only the selected suffixes are loaded.
- Reuse `_do_revive_agents()` so alias removal, artifact restoration, full-history refresh, and logging stay consistent.
- Mark the recent record revived after successful revive; if the same group also exists as a saved group, mark both
  records revived.

### State Initialization

Initialize a small `_recent_dismissed_agent_groups` cache during TUI state setup by reading only the capped recent
store. This does not load dismissed bundles.

Add helper methods on the relevant mixin to:

- Merge optimistic recent groups with disk-loaded recent groups.
- Cap and dedupe the in-memory cache.
- Build the restore modal's initial recent + saved-group view.
- Load a recent group by id for previews and revive routing.

## Edge Cases

- If a recent group references bundles that no longer exist, show the same missing-ref warning used by saved groups and
  do not mark the group revived unless at least one agent was restored.
- If an agent is revived and later dismissed again, create a new recent record; the old one can remain until pushed out
  by the cap.
- If a bulk dismissal includes many agents, keep the record as one dismissal action even if it has many refs.
- If saved-group listing fails, still show recent dismissals and the custom search row.
- If recent-store loading fails or the file is corrupt, treat it as empty and notify at warning/debug level rather than
  blocking restore.

## Test Plan

Core / binding:

- Rust unit tests for recent-store save/list/load/mark-revived, ten-record cap, newest-first order, dedupe, and
  corrupt-file tolerance.
- PyO3 binding coverage for the new functions.
- Python facade tests for normal binding use and pure-Python fallback.

TUI behavior:

- Single dismiss records one recent group including the dismissed agent and does not synchronously touch disk.
- Workflow parent dismiss records parent plus child refs.
- Batch/group dismiss records one group for the action, not one row per agent.
- Marked save-and-dismiss mirrors the saved group into recent without duplicate rows in the panel.
- Opening Agent Restore lists recent dismissals before saved groups and does not call `load_dismissed_bundles()`.
- Selecting a recent row loads only its suffixes and dispatches through the saved-group revive path.
- Missing recent refs warn and do not mark the group revived.
- Revive marks the recent record revived and preserves the existing saved-group mark behavior.
- Visual snapshot coverage for the Agent Restore panel with recent rows, saved rows, empty state, and load-more row.

Implementation verification:

- Run `just install` first if dependencies are stale.
- Run targeted tests while developing:
  - `pytest tests/test_dismissed_agent_groups.py tests/test_agent_group_revival_routing.py tests/test_agent_group_revival_execution.py tests/test_agent_dismiss_in_memory.py tests/test_agent_dismiss_persistence.py tests/ace/tui/modals/test_saved_agent_group_revival_modal.py`
  - relevant `sase-core` Rust/PyO3 tests after adding backend functions.
- Run `just check` in this repo after code changes.

## Rollout Notes

This plan intentionally keeps the full dismissed archive search as a fallback and adds only a bounded fast path for the
most recent user dismissals. It avoids a startup or panel-open scan of all dismissed bundles, and it keeps restore
execution on the already-tested saved-group revive path.
