---
create_time: 2026-05-28 14:30:51
status: done
prompt: sdd/prompts/202605/selective_artifact_dirty_routing.md
---
# Selective Artifact Dirty Routing Plan

## Goal

Reduce unnecessary ACE TUI Agents reloads by changing artifact watcher dirty routing so ordinary artifact content writes
do not mark the Agents surface dirty or schedule `load_agents_from_disk_with_state`.

The prior profiling run showed that `j`/`k` mutation is cheap, while repeated `agents.load_from_disk` calls dominate
perceived latency. The highest-leverage single change is to make `_dirty_surfaces_for_paths()` distinguish
loader-visible marker changes from unrelated files under `artifacts/`.

## Current Behavior

`EventRefreshMixin._dirty_surfaces_for_paths()` treats any path containing an `artifacts` component as an Agents change.
That is safe but too broad: live agent runs write files such as `live_reply.md`, timestamps, logs, stdout, generated
artifacts, and output directories. Those writes do not change the Agents list/status projection, yet they repeatedly set
`_dirty_agents` and call `_schedule_agents_async_refresh()`.

The TUI already has follow-on safeguards: navigation gating, off-tab gating, a 5-second debounce floor, and a 60-second
sanity refresh. The remaining problem is the event classification itself.

## Loader-Visible Marker Set

Keep Agents reloads for artifact paths that can affect rows, status, grouping, identity, tags, workflow structure,
pending-question state, or index/query visibility:

- `agent_meta.json`
- `done.json`
- `running.json`
- `waiting.json`
- `pending_question.json`
- `workflow_state.json`
- `plan_path.json`
- `prompt_step_*.json`
- `retry_state.json`

Also keep reloads for artifact directory creation/deletion at likely agent-root depth, because a watcher can observe a
newly materialized directory before it observes the marker files inside it.

Do not reload Agents for artifact-content files such as `live_reply.md`, `live_reply_timestamps.jsonl`,
`codex_thinking.jsonl`, `usage.json`, `sase.md`, `response.md`, stdout/log files, or nested generated artifact files.
Detail panels and artifact views can continue to rely on their own caches, direct reads, user action, or the safety
refresh.

## Implementation Approach

1. Add small helper functions/constants near `_dirty_surfaces_for_paths()` in
   `src/sase/ace/tui/actions/_event_refresh.py`.
   - One helper decides whether a path under an `artifacts` tree affects the Agents surface.
   - Use `Path.parts` to locate the `artifacts` component, not string contains beyond the existing path classification.
   - Treat known marker filenames and `prompt_step_*.json` as Agents-relevant.
   - Treat likely agent-root directories as Agents-relevant by structure:
     `.../artifacts/<workflow>/<timestamp-or-run-dir>` and possibly direct `.../artifacts/<agent-dir>` for legacy/test
     layouts.
   - Treat deeper directories/files as not Agents-relevant unless their basename is a marker.

2. Update `_dirty_surfaces_for_paths()`.
   - For artifact paths, add `"agents"` only when the helper returns true.
   - If a changed artifact path is non-loader-visible, add no target for that path.
   - Preserve conservative fallback behavior for non-artifact unknown paths, project files, beads, notifications, and
     no-path calls.
   - Preserve the final fallback for cases where all provided paths are unclassifiable, but avoid letting ignored
     artifact-content paths fall through into that fallback.

3. Update tests in `tests/ace/tui/test_event_handlers_dirty_flags.py`.
   - Keep the existing `done.json` test as the positive marker case.
   - Add negative cases proving `live_reply.md` and nested generated artifact files do not set `_dirty_agents` or
     schedule an Agents refresh.
   - Add positive cases for `workflow_state.json`, `prompt_step_*.json`, and likely new artifact-root directory
     creation.
   - Add a mixed burst test proving one marker path plus unrelated artifact content still schedules exactly one Agents
     refresh.
   - Keep notification/project/bead behavior unchanged.

4. Validate locally.
   - Run the focused dirty-flag tests first.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.
   - If full `just check` fails for unrelated environmental reasons, capture the failing command and focused test
     result.

## Risk Management

The main risk is missing a file that affects the Agents list. The marker set comes from the agent scan wire contract and
the TUI loader helpers. The 60-second sanity refresh remains as a backstop, and the STARTING-agent transition poll still
nudges refreshes when `agent_meta.json` or `waiting.json` appears after a missed watcher event.

The implementation should stay entirely in Python TUI event routing. It does not change core backend scan semantics,
artifact index writes, file watcher mechanics, or loader behavior.
