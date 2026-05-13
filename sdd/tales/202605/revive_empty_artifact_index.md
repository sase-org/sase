---
create_time: 2026-05-12 21:11:46
status: done
prompt: sdd/prompts/202605/revive_empty_artifact_index.md
---
# Plan: Fix Revive Visibility When the Artifact Index Is Empty/Stale

## Problem

Reviving a dismissed agent reports success, the audit log writes `agent_revived` with `outcome: "success"`, the
dismissed set is updated, and the artifact files (`done.json`, `workflow_state.json`, `agent_meta.json`) are recreated
on disk — but the agent never appears as a new row on the Agents tab.

Concrete evidence from the user's machine:

- Most recent revive: workflow `sase` / `raw_suffix=20260512172355`, logged as `outcome: success` in
  `~/.sase/logs/events.jsonl`.
- All restored artifact files are present at `~/.sase/projects/sase/artifacts/ace-run/20260512172355/`.
- `~/.sase/agent_artifact_index.sqlite` exists but its `agent_artifacts` table is empty (confirmed via direct SQLite
  query).

## Root Cause

After artifact restoration, `_do_revive_agent` and `_do_revive_agents` (in `src/sase/ace/tui/actions/agents/_revive.py`)
call `self._load_agents()` synchronously. That path is Tier 1 only:

1. `_load_agents` (`src/sase/ace/tui/actions/agents/_loading.py:163`) calls
   `load_agents_from_disk_with_state(..., full_history=bool(_agent_search_query))`, which for an empty search defaults
   to `full_history=False`.
2. The Tier 1 snapshot comes from `_query_artifact_index_for_loader` (`src/sase/ace/tui/models/agent_loader.py:121`).
   When the index file exists, it queries the index. **An empty-but-valid index returns zero records cleanly with no
   exception**, so the bounded source-scan fallback (only triggered in an `except` clause) is never taken.
3. The revived completed workflow is therefore absent from the new snapshot.
4. `_preserve_revived_agents_for_incomplete_load` (`_loading.py:333`) cannot rescue it: it walks
   `self._agents_with_children`, which never contained the long-dismissed agent (it was filtered out as dismissed before
   revive).
5. The pending Tier 2 flag (`_agents_refresh_pending_full_history = True`) is set, but no code in the sync revive path
   schedules an async refresh. Tier 2 only fires once another trigger (auto-refresh timer, inotify, tab switch) calls
   `_schedule_agents_async_refresh`. In practice the user sees nothing after revive.

## Fix

Two changes, layered so the user-visible behavior is correct even when one layer underperforms:

### 1. Force a Tier 2 (full-history) load from the revive path

- Add a `full_history: bool = False` kwarg to `_load_agents()` in `src/sase/ace/tui/actions/agents/_loading.py:163` and
  pipe it through to
  `load_agents_from_disk_with_state(..., full_history=full_history or bool(getattr(self, "_agent_search_query", "")))`.
- Update both `_do_revive_agent` (`_revive.py:478`) and `_do_revive_agents` (`_revive.py:624`) to call
  `self._load_agents(full_history=True)`.

This guarantees a source-scan-backed snapshot immediately after revive, which finds the restored artifact files
regardless of artifact-index freshness. Revive is a deliberate user action, so the added scan latency is acceptable.

### 2. Belt-and-suspenders preserve fallback

Update `_preserve_revived_agents_for_incomplete_load` (`_loading.py:333`) so that for any revived `raw_suffix` still
missing from `prep.filtered_agents`, it first looks in `self._agents_with_children` (existing behavior) and then falls
back to the matching object in `self._dismissed_agent_objects`. The revive flow has already hydrated those bundle agents
into memory, so this fallback always has the data on hand and guarantees first-paint visibility even if step 1 returns
an incomplete history.

The existing clear-on-complete-history logic still applies: once a Tier 2 load includes the revived suffix, it is
removed from `_revived_agent_raw_suffixes` and the fallback stops kicking in.

### 3. Regression coverage

- Add a focused test (extend `tests/test_agent_revive.py` or add `tests/test_agent_revive_load_tier.py`) that:
  - Builds a dismissed completed workflow agent with restored artifacts on disk.
  - Stubs `_query_artifact_index_for_loader` to return an empty snapshot with `complete_history=False` (simulating an
    empty index).
  - Revives the agent.
  - Asserts the post-revive `self._agents` contains the revived agent without requiring any extra async refresh.
- Add a separate test for the preserve fallback that:
  - Seeds `_dismissed_agent_objects` with a revived bundle agent.
  - Drives `_preserve_revived_agents_for_incomplete_load` with an incomplete `prep` and an empty
    `_agents_with_children`.
  - Asserts the revived agent is preserved into the final list.

### 4. Verify

- `just install` (fresh workspace).
- Run the new targeted tests plus the existing revive/loader suites.
- `just check` per the repo's mandatory pre-reply gate.

## Out of Scope

- Repairing or rebuilding the empty `agent_artifact_index.sqlite`. That is a background maintenance concern
  (`sase agents index rebuild`) and is not what blocks revive correctness — even with a healthy index, a future bundle
  revived from outside the index's recent-completed window would hit the same Tier 1 miss. The fix above is the right
  structural answer.
- Broadening `_query_artifact_index_for_loader` to treat an empty-but-valid index as a fallback trigger. That would
  change normal Tier 1 paths and is not necessary to fix revive.
