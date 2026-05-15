---
create_time: 2026-05-14 22:08:23
status: done
prompt: sdd/prompts/202605/async_artifact_discovery.md
---
# Plan: Move agent-detail artifact discovery off the UI thread

## Problem statement

Section #3 of `sdd/research/202605/tui_blocking_audit.md` calls out that every debounced agent-detail refresh
(`_apply_agent_detail_update()` in `src/sase/ace/tui/actions/agents/_display_detail.py:128-147`) ends up calling
`_list_selected_agent_artifacts(current_agent)` synchronously, purely to derive a single `has_agent_artifacts: bool` for
the footer's `update_agent_bindings(...)` call.

On a cache miss, that synchronous call walks through:

- `_list_selected_agent_artifacts` (`_panel_artifacts.py:190-235`)
- `read_agent_artifacts_for_tui` (`_artifact_provider.py:26-37`)
- `list_agent_artifacts` (`sase.core.agent_artifact_facade`)
- `synthesize_default_agent_artifacts` (`sase/core/agent_artifact_defaults.py:37-134`): reads `done.json`,
  `agent_meta.json`, `plan_path.json`, the markdown-PDF index, and for legacy agents globs `raw_xprompt.md` +
  `*_prompt.md` and reads each prompt file to discover image paths.
- `list_indexed_agent_artifacts` (the explicit artifact JSONL index).

That whole pipeline runs on the Textual event loop on every cold selection, which is what the audit blames for
"selected-agent detail can stutter even after the j/k debounce."

The audit's prescribed fix: **compute artifact availability off the UI thread and patch the footer once the worker
result arrives.** The footer should render immediately (with no artifact binding) and update later when the discovery
completes.

## Goals

1. Cache-miss artifact discovery for the agent-detail footer never runs on the Textual event loop.
2. The footer paints immediately on cold selection without waiting for any filesystem I/O. The "open artifacts" /
   artifact-viewer keybinding is then patched in once the worker finishes, if the selection is still the same.
3. The cache-hit path (warm selection) stays synchronous and on the UI thread — `os.stat` of four marker files is cheap
   and not worth moving.
4. User-initiated paths that _consume_ the artifact list (`action_open_agent_artifacts`,
   `_collect_marked_agent_artifacts`) still work. They may keep their current behavior, since they are user-driven and
   not part of the j/k hot path.
5. No regressions in the existing selection-generation / stale-result guard that `_panel_artifacts.py:222-230` already
   implements for the daemon-backed provider.

## Non-goals

- Moving the workflow JSON loads, ChangeSpec RUNNING field, or any other audit-section beyond #3.
- Reworking the `_artifact_provider` daemon plumbing; we keep the `_ArtifactReadResult` / `_AgentArtifactPage` shapes
  and only change _where_ `read_agent_artifacts_for_tui` is invoked from the detail path.
- Changing the `update_agent_bindings()` footer API.
- Pre-warming the artifact cache during the agent-loader worker. (The audit mentions this as an alternative; the loader
  is already the hottest part of the refresh path, and pushing per-agent JSON reads into it is broader scope than this
  fix needs.)

## Design

### Shape of the new flow

`_apply_agent_detail_update()` currently does:

```python
list_artifacts = getattr(self, "_list_selected_agent_artifacts", None)
has_agent_artifacts = (
    bool(list_artifacts(current_agent))
    if current_agent and callable(list_artifacts)
    else False
)
```

We replace that with a _fast-path_ helper that:

1. Reads from `_agent_artifact_page_cache` only — no disk I/O beyond the marker stats already done by
   `_agent_artifact_cache_key`. (The cache key already calls `os.stat` on four small marker files; that is cheap and we
   leave it on the UI thread.)
2. If the cache has an entry for the current key, returns its truthiness directly.
3. If not, returns `False` and _schedules_ a background discovery via `asyncio.to_thread`. The footer paints "no
   artifacts" for now.

When the worker resolves, on the UI thread, we:

- Populate `_agent_artifact_page_cache[row_key]` with the discovered list.
- Check that the currently-selected agent's cache key still matches the worker's key. If not (user navigated away, or
  marker files changed), drop the result silently — the new selection will re-trigger if needed.
- If it still matches, re-invoke the existing `_fire_debounced_detail_update()` so the footer re-renders. Because the
  cache is now populated, the fast path will return the cached value synchronously and the second call is cheap.

### Dedupe / coalescing

Rapid j/k can re-enter the cold-selection branch many times for the same agent. To avoid spawning N parallel
`asyncio.to_thread` tasks:

- Add a new attribute `_agent_artifact_discovery_inflight: dict[tuple, asyncio.Task]` keyed by the same `row_key` the
  cache uses.
- Before scheduling, look up the row_key in the in-flight dict; if a task is already running, do nothing — the running
  task will trigger the re-render when it completes.
- On task completion (success, error, or cancelled), remove the entry from the in-flight dict.

The selection-generation token already in place (`_agent_artifact_selection_generation`) is a separate concern (it
guards _daemon_ responses by request); we leave it intact and add the row_key in-flight dedupe alongside it.

### Stale-selection guard

When the worker resolves, the user may have already navigated to a different agent. The check is straightforward:
recompute the _current_ selected agent's row_key on the UI thread; only re-render if it equals the row_key the worker
was launched for. If not, still populate the cache (free win for if the user navigates back) but skip the footer patch.

### Error handling

`read_agent_artifacts_for_tui` already raises bare `Exception` paths today that are caught at the call site
(`_panel_artifacts.py:218-221`). The worker wrapper catches the same, logs at debug level, and treats the result as an
empty artifact list. We do _not_ surface a toast — this is a footer state update that the user did not explicitly
request.

### Module / call-site changes

**`src/sase/ace/tui/actions/agents/_panel_artifacts.py`**

- New helper `_cached_agent_artifacts(agent) -> list[Any] | None`: read-only cache probe; returns `None` on miss, the
  cached list on hit (no disk reads beyond the marker stat used by `_agent_artifact_cache_key`).
- New helper `_schedule_agent_artifacts_discovery(agent) -> None`: dedupe on row_key, spawn an `asyncio.to_thread` task
  that runs `read_agent_artifacts_for_tui(agent)`. The continuation, on the UI thread, populates the cache and (if the
  selection still matches) calls back into the detail-refresh path.
- Initialize `_agent_artifact_discovery_inflight: dict[tuple, asyncio.Task]` in the existing state-init mixin alongside
  `_agent_artifact_page_cache`.
- Keep `_list_selected_agent_artifacts(agent)` as-is. It is used by:
  - `action_open_agent_artifacts` (user pressed the open-artifact binding)
  - `_collect_marked_agent_artifacts` (gathering across marked agents for the picker modal) Both are user-initiated and
    can keep their synchronous-with-cache-fallback behavior. (We can revisit those in a follow-up — they are user-driven
    and not part of the j/k hot path the audit ranks.)

**`src/sase/ace/tui/actions/agents/_display_detail.py`**

- Inside `_apply_agent_detail_update`, replace the `list_artifacts(...)` block with the new
  `_cached_agent_artifacts(...)` probe.
- If the probe returns `None`, set `has_agent_artifacts=False` for this paint and call
  `_schedule_agent_artifacts_discovery(current_agent)`.
- The worker's completion callback re-invokes `_fire_debounced_detail_update()` (idempotent and cheap on a warm cache).

**`src/sase/ace/tui/actions/_state_init.py`** (or wherever the artifact-page cache is currently initialized — verify
during implementation)

- Initialize `_agent_artifact_discovery_inflight` to an empty dict.

### Cancellation on app shutdown

If the app shuts down while a discovery task is in flight, we want to cancel the task rather than leak it. Pattern: on
shutdown, iterate the in-flight dict and call `task.cancel()`. Hook into whatever shutdown path the existing TUI uses —
most workers are tied to Textual's `run_worker` lifecycle, but because we are using bare `asyncio.to_thread` we need an
explicit cleanup step. Verify during implementation whether there is an existing `on_unmount` / shutdown hook in the
agents action mixin tree we should extend.

Alternative considered: use `self.run_worker(thread=True)` (matching the file-panel pattern at
`widgets/file_panel/__init__.py:383`). Textual's worker lifecycle would then handle cancellation automatically. The
trade-off: `run_worker` results are typically consumed via `on_worker_state_changed`, which is widget-scoped and doesn't
fit cleanly in an action mixin. `asyncio.to_thread` is more natural here because we can attach the continuation inline.
The implementation should pick whichever integrates more cleanly with the rest of the actions module; this plan treats
them as interchangeable.

## Step-by-step implementation

1. **Add the cache-probe helper** (`_cached_agent_artifacts`) in `_panel_artifacts.py`. Extract the cache-lookup half of
   the current `_list_selected_agent_artifacts` body — everything up to and including the
   `if cached is not None: return list(cached)` branch — into a shared helper that returns `None` on miss. Have the
   existing `_list_selected_agent_artifacts` call the new helper, then fall through to the same blocking provider call
   it does today.

2. **Add the worker-scheduling helper** (`_schedule_agent_artifacts_discovery`). Compute the row_key, bail if it's
   already in the in-flight dict, then schedule `asyncio.to_thread(read_agent_artifacts_for_tui, agent)` and attach a
   completion callback that:
   - Populates `_agent_artifact_page_cache[row_key]`.
   - Removes the in-flight entry.
   - If the currently-selected agent's row_key equals the worker's row_key, calls `self._fire_debounced_detail_update()`
     (or the immediate equivalent) so the footer re-renders.
   - Catches and logs any exception so a bad worker run does not bubble up to the event loop.

3. **Wire the in-flight dict into state init**. Find where `_agent_artifact_page_cache` is initialized; initialize
   `_agent_artifact_discovery_inflight = {}` alongside it.

4. **Switch the call site** in `_apply_agent_detail_update` (`_display_detail.py:128-147`) from
   `list_artifacts(current_agent)` to `_cached_agent_artifacts(current_agent)`, with the cache-miss branch calling
   `_schedule_agent_artifacts_discovery(current_agent)` and treating `has_agent_artifacts` as `False` for the initial
   paint.

5. **Cancellation hook**. Add a small `_cancel_pending_artifact_discovery()` cleanup helper and call it from the
   existing shutdown / `on_unmount` path. If no such hook exists in the agents mixin, fall back to having tasks check a
   shutdown flag before running their UI continuation.

6. **Tests**:
   - Unit test: cold selection of an agent with artifacts now does _not_ call `list_agent_artifacts` on the UI thread;
     instead a task is scheduled. After the task completes (await it in the test), the cache is populated and the
     footer's `has_agent_artifacts` reflects the real value on the next refresh.
   - Unit test: rapid j/k over the same agent only schedules one discovery task (verify via the in-flight dict).
   - Unit test: if the selection changes before the worker completes, the footer for the _new_ selection is not stomped
     on by the stale worker's continuation.
   - Regression check: `action_open_agent_artifacts` still works on a cold selection (it can still take the synchronous
     path; verify `AgentArtifactSelectionModal` mounts as expected).

7. **Manual verification**:
   - Start the TUI on a project with several artifact-bearing agents and cold caches.
   - Hold j to scan rapidly across them; the footer should paint without stalls.
   - For the settled selection, the artifact key should appear in the footer after a brief delay (one event-loop tick
     after the worker resolves).
   - Press the open-artifact binding on the settled selection and confirm the artifact picker still opens.

8. **Run `just check`** before reporting the task done (per project conventions in `memory/short/build_and_run.md`).

## Risks and mitigations

- **Footer flicker**: cold selections will show "no artifacts" for a brief window before the worker resolves.
  Mitigation: the discovery is typically sub-100ms; if needed, we can render a neutral "..." or simply leave the binding
  absent (preferred). Users won't see a "false negative" then a "true positive" jump because the binding either is there
  or isn't — no flashing label.

- **Stale cache after artifact creation**: artifacts created by a running agent invalidate the cache via
  `_agent_artifact_cache_key`'s marker stats; the next cold selection picks up the new key and re-runs discovery. This
  is unchanged behavior.

- **Worker leak on shutdown**: addressed by the explicit cancellation hook in step 5.

- **Selection-generation drift**: the existing daemon-token check at `_panel_artifacts.py:222-230` lives inside
  `_list_selected_agent_artifacts`. Because we keep that synchronous helper for user-initiated open-artifact paths, the
  daemon-token check is preserved there. The worker path uses the row_key-based stale check instead, which is sufficient
  for the in-process provider.

- **Increased complexity in `_panel_artifacts.py`**: roughly two short helpers plus a small dict on state init. Net code
  change is modest and localized.

## Out of scope (follow-up)

- Moving `action_open_agent_artifacts` to a worker so the very first artifact-open on a cold cache doesn't briefly
  block. Lower priority — it is user-initiated and one-shot, not part of the j/k hot path.
- Pre-warming the cache in `_load_agents_async`. Would eliminate the cold miss entirely but is out of proportion with
  the actual cost; revisit if the per-selection latency proves visible to users after this fix lands.
