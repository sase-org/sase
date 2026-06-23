# TUI startup agents-tab freeze research - 2026-06-23

## Summary

The agents tab was not slow because j/k navigation itself takes a minute. It was slow because the Textual event loop was
blocked during an agents refresh apply step. While that synchronous work was running, keypresses could not be processed,
so moving between agent rows appeared frozen.

The direct stack in the latest startup-related stall is:

```text
_event_refresh.py:_on_auto_refresh
  -> agents/_loading_disk.py:_load_agents_async
  -> agents/_loading_apply.py:_apply_loaded_agents_prepared_inner
  -> sync_dismissed_agent_artifact_index(...)
  -> _run_active_tier_maintenance(...)
  -> terminalize_stale_active_agent_artifact_index_rows(...)
  -> Rust artifact-index terminalizer
```

This path violates the TUI performance rule from `memory/tui_perf.md`: no synchronous disk/JSON/subprocess/Rust-index
work on the Textual event loop.

## Evidence

### Relevant runtime

The running TUI in the logs and this workspace are on the same code:

```text
commit d6b9ebe1bf1e3f7bdc742783a8eb281feb7136bd
branch master
```

The stack paths point at `/home/bryan/projects/github/sase-org/sase`, and the relevant files are identical to this
workspace.

### Watchdog stalls

`~/.sase/logs/tui_stalls.jsonl` currently contains 32 stall records. Classified by top cause:

| Cause | Count |
| --- | ---: |
| Blocking external editor/subprocess/viewer | 20 |
| Dismissed/artifact-index maintenance | 7 |
| Artifact viewer key-read loop | 4 |
| Artifact-index row upsert during revive | 1 |

The external editor/viewer stalls are user-initiated modal/external-tool waits. They are noisy in the stall log, but
they do not explain "I just started the TUI and could not navigate rows."

The index-maintenance stalls are the important ones. On 2026-06-23:

| Time | Duration | Stack class | Notes |
| --- | ---: | --- | --- |
| 11:50:22 | recovered after 15.006s | `replace_agent_artifact_index_dismissed_agents` | Projection rewrite on UI thread |
| 11:51:31 | recovered after 65.053s | `terminalize_stale_active_agent_artifact_index_rows` | Almost exactly the reported "almost a minute" symptom |
| 14:07:01 | no recovery line; pid later gone | `terminalize_stale_active_agent_artifact_index_rows` | Latest startup-adjacent stall; current tab `agents`, `current_idx=0` |

The latest 14:07 watchdog JSON has:

```text
current_tab=agents
current_idx=0
_event_refresh.py:535:_on_auto_refresh
_loading_disk.py:403:_load_agents_async
_loading_apply.py:256:_apply_loaded_agents_prepared
_loading_apply.py:320:_apply_loaded_agents_prepared_inner
agent_artifact_index_lifecycle.py:190:sync_dismissed_agent_artifact_index_report
agent_artifact_index_lifecycle.py:351:_run_active_tier_maintenance
agent_scan_facade.py:176:terminalize_stale_active_agent_artifact_index_rows
```

The 14:07 stalled pid is no longer running, so there is no complete recovery duration for that exact process. The same
stack recovered after 65.053s earlier today, which matches the user-visible delay.

### Artifact-index state

The current artifact index is large:

| Source | Current size/count |
| --- | ---: |
| `~/.sase/agent_artifact_index.sqlite` | 136 MB |
| `agent_artifacts` rows | 18,694 |
| projected `dismissed_agents` rows | 43,313 |
| `~/.sase/dismissed_agents.json` | 2.5 MB |
| `~/.sase/dismissed_bundles` files | 38,059 |
| `~/.sase/projects` files | 187,448 |

`sase agent index status` now reports the index is healthy:

```text
Agent artifact index ready for normal refresh: 546 visible rows, 43313 dismissed
identities (/home/bryan/.sase/agent_artifact_index.sqlite)
```

That health check is after the problematic maintenance ran. The database mtime moved around 14:10, consistent with the
14:07 terminalization pass doing work before the later healthy state.

Current row-state query:

| State | Count |
| --- | ---: |
| `done` | 15,530 |
| `completed` | 2,631 |
| `running` | 350 |
| `waiting` | 122 |
| `failed` | 60 |
| `starting` | 1 |

There are still 350 `running` rows with no marker files; 217 are older than one day. A no-op call to the terminalizer
after cleanup still reports `rows_skipped=255`, so the maintenance path continues to inspect stale active-tier
candidates even when no rows are actually changed.

### Direct timing

After the cleanup had already happened, I timed the sync and terminalization paths from this workspace using the same
home index:

```text
sync_dismissed_agent_artifact_index_report(load_dismissed_agents()):
  660.9 ms
  552.7 ms
  671.3 ms

terminalize_stale_active_agent_artifact_index_rows(...):
  787.0 ms, rows_indexed=0, rows_skipped=255
  616.2 ms, rows_indexed=0, rows_skipped=255
  219.9 ms, rows_indexed=0, rows_skipped=255
```

So even when it does no useful cleanup, this path is already hundreds of milliseconds. When it has real stale rows to
terminalize, the same event-loop call crosses the 5s watchdog threshold and has reached about a minute in today's logs.

## Code path

### Startup fix exists, but only for one call site

`src/sase/ace/tui/actions/_state_init.py` deliberately avoids doing dismissed-index sync in `AceApp.__init__`:

```text
_init_app_state:
  load_dismissed_agents()
  dismissed_agents_file_signature()
  # sync is deliberately not run here
```

`src/sase/ace/tui/actions/startup.py` schedules startup dismissed-index sync after first paint, using
`asyncio.to_thread(...)` inside `_run_dismissed_index_startup_sync`. That was the right shape for startup.

The problem is that normal agents refresh/apply still calls the same lifecycle function synchronously on the UI thread.

### The blocking call site

In `src/sase/ace/tui/actions/agents/_loading_disk.py`, agent loading and prep are mostly off-thread:

```text
_load_agents_async:
  await asyncio.to_thread(load_agents_from_disk...)
  await asyncio.to_thread(prepare_loaded_agents_worker_boundary...)
  await asyncio.to_thread(attach_finalize_plan_to_boundary...)
  self._apply_loaded_agents_prepared(...)
```

The final apply step is a UI-thread continuation, as expected. But inside
`src/sase/ace/tui/actions/agents/_loading_apply.py`, it persists dismissed changes and immediately calls:

```python
sync_dismissed_agent_artifact_index(
    self._dismissed_agents,
    added=added_identities or None,
)
```

That function is not UI-safe. It enters `src/sase/core/agent_artifact_index_lifecycle.py`:

```python
with agent_artifact_index_operation_lock():
    report = _sync_projection(...)
    return _run_active_tier_maintenance(index, report)
```

The key issue is that `_run_active_tier_maintenance(...)` is unconditional. It runs even when:

- the caller used the "authoritative added set" fast path;
- projection metadata already matches;
- the TUI is just applying a refresh result;
- the current user action is row navigation, or startup just reached the agents tab.

`_run_active_tier_maintenance(...)` then calls the Rust terminalizer through
`terminalize_stale_active_agent_artifact_index_rows(...)`, still under the index operation lock. This is exactly the
stack captured in the 14:07 watchdog event.

## What triggered it at startup

The startup sequence currently does this:

1. First paint happens.
2. `_start_post_mount_background_loads()` starts `_run_agent_index_startup_prepare_and_refresh()`.
3. `_run_agent_index_startup_prepare()` checks schema staleness off-thread.
4. `_run_agents_async_refresh()` loads agents.
5. During the UI-thread apply step, if the loader found recovered bundle identities or auto-dismissed identities, it
   persists dismissed changes.
6. Persisting dismissed changes calls `sync_dismissed_agent_artifact_index(...)` directly on the UI thread.
7. That call always runs active-tier maintenance, which can spend seconds in Rust scanning/terminalizing stale active
   rows.

So the startup first paint can succeed, but the first agents refresh can immediately freeze the app before row
navigation is usable.

## Ruled out

### Import-time startup cost

There is a prior plan about heavy `import sase.ace.tui` cost. That can delay first paint, but it does not match the
watchdog stack or the "agents tab is visible but row navigation is unavailable" symptom. The 14:07 stall happens inside
Textual's running event loop, after mount.

### j/k model update cost

The existing j/k perf data shows agents-tab paint is over the 16 ms target, but the model movement itself is sub-ms to
low-ms in normal operation. That is a separate responsiveness problem. It cannot explain a 60s inability to navigate.

### External editor/viewer stalls

Most stall records are external editor/viewer waits. They should probably be classified differently by the watchdog, but
they are not the startup agents-tab freeze. The startup-relevant stalls are the dismissed/artifact-index stacks.

## Recommended solution

Move artifact-index dismissed projection sync and active-tier terminalization out of the UI-thread agents apply path,
and split "projection update" from "maintenance."

Concretely:

1. Replace the direct `sync_dismissed_agent_artifact_index(...)` call in
   `agents/_loading_apply.py` with a queued background maintenance request. The UI-thread apply should only update
   in-memory state, persist `dismissed_agents.json` if needed, and schedule the index work.
2. Add a small coalescing maintenance queue for artifact-index lifecycle work:
   - one in-flight task at a time;
   - last-request-wins dismissed snapshot;
   - run blocking work via `asyncio.to_thread()` or a tracked background task;
   - on completion, schedule a normal agents refresh only if projection/terminalization changed visibility.
3. Change `sync_dismissed_agent_artifact_index_report()` so active-tier maintenance is not unconditional:
   - projection sync should do only projection sync;
   - terminalization should be an explicit maintenance operation;
   - startup/session maintenance can be throttled by mtime/monotonic interval and skipped while the user is navigating.
4. Add a cheap "is maintenance worth running?" gate before Rust terminalization. The database can answer candidate
   counts/signatures quickly enough to avoid the repeated 500-800 ms no-op path. At minimum, do not run terminalization
   more than once per session/startup interval unless the artifact index version or active-tier candidate signature
   changed.
5. Add tests that guard this exact regression:
   - `_apply_loaded_agents_prepared_inner(...)` must not call `sync_dismissed_agent_artifact_index(...)` synchronously.
   - a slow fake terminalizer must not block j/k navigation or the agents apply continuation.
   - startup sync may schedule a follow-up refresh, but it must complete on a worker thread.

This is the highest-value fix because it removes the hard freeze mechanism. Optimizing normal j/k paint and detail-panel
rendering is still worthwhile, but it should come after the event-loop blocking index maintenance is gone.
