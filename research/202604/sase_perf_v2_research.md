I couldn’t clone the repo locally because this container could not resolve `github.com`, but I was able to inspect `sase-org/sase` through the GitHub app on `master`.

## Executive read

A lot of the intended responsiveness work is already implemented. Single-agent dismiss and single-agent launch are mostly off the UI thread now. The biggest remaining blockers I found are:

1. **Kill still does notification disk I/O synchronously on the UI thread.**
2. **Kill-all loops through single kills, causing repeated immediate refresh/count work.**
3. **The “immediate” detail update after navigation is not truly lightweight; it still renders prompt content and can read artifacts synchronously.**
4. **Dismiss/kill optimistic removal still tends to do a full list rebuild, so large agent lists can still hitch.**
5. **Launch fan-out paths are nonblocking, but refresh scheduling is still noisy and thread ownership is a bit ad hoc.**

## What is already in good shape

### Single dismiss is now mostly nonblocking

`_dismiss_done_agent()` updates the in-memory state first, notifies, removes the agent from the visible list, then schedules `_run_dismiss_persistence_async()` with `call_later`. The persistence path uses `asyncio.to_thread(...)` for bundle saves, artifact deletion, workspace release, notification dismissal, and dismissed-set persistence. On successful completion it only refreshes notification counts asynchronously; it does not schedule a redundant full agent reload. That matches the “done” plan for async single-agent dismissals.  

The remaining dismiss cost is the optimistic UI prologue: `_apply_dismissal_in_memory()` still refilters and ultimately refreshes the full agents display. That is much better than blocking on disk, but for large lists it can still block briefly on widget rebuild work. 

### Single launch is mostly off-thread

`_finish_agent_launch()` unmounts the prompt bar immediately, shows a launch toast, and schedules `_run_agent_launch_body_async()`. That async method runs `_run_agent_launch_body()` inside `asyncio.to_thread(...)`, which keeps VCS resolution, history writes, xprompt expansion, workflow dispatch, and subprocess spawn off the Textual event loop. 

The actual subprocess spawn path writes the prompt temp file, opens output files, calls `subprocess.Popen`, claims/transfers workspace, and records chop-agent launch metadata. Those can all block, but in the TUI single-launch path they are already invoked from the worker thread. 

### Agent reloads are now gated and mostly worker-prepped

`_load_agents_async()` offloads changespec cache lookup, disk loading, loader cleanup, and the main apply-prep filtering to `asyncio.to_thread(...)`. `_run_agents_async_refresh()` now checks `NavigationGate` and defers if the user is currently navigating, which addresses the earlier post-launch `j/k` lag diagnosis.  

## Highest-impact remaining fix: kill notification I/O

The single kill path still does this on the main thread:

```python
dismiss_notifications_for_agent(agent)
self._refresh_notification_count()
self._apply_killed_agents_in_memory(...)
```

That is a problem because `dismiss_notifications_for_agent()` loads notifications from disk and marks individual rows dismissed, and `_refresh_notification_count()` also loads/parses notifications from disk before updating the indicator.   

The persistence code already has the right place for this. `_kill_persistence.py` contains worker-side kill persistence, and the bulk path already has `dismiss_notifications_for_agents(...)`, which loads/re-writes notifications at most once.  

### Proposed change

For `_do_kill_agent()`:

```python
# Remove these from the immediate stage:
dismiss_notifications_for_agent(agent)
self._refresh_notification_count()

# Keep this immediate:
self._apply_killed_agents_in_memory(...)
```

Capture a dismissed snapshot at schedule time:

```python
dismissed_snapshot = set(self._dismissed_agents)
self.call_later(
    self._run_kill_persistence_async,
    agent,
    kind,
    agents_with_children_snapshot,
    dismissed_snapshot,
)
```

Then in `_run_kill_persistence_async()`:

```python
await asyncio.to_thread(
    persist_kill_side_effects,
    agent,
    kind,
    agents_with_children_snapshot,
)

await asyncio.to_thread(save_dismissed_agents, dismissed_snapshot)

await asyncio.to_thread(
    dismiss_notifications_for_agents,
    _agents_related_to_kill(agent, agents_with_children_snapshot),
)

await self._refresh_notification_count_async()
```

This makes the kill immediate stage essentially: classify, signal process group, remove from in-memory list, refresh visible rows, schedule persistence. The notification file read/write and count refresh no longer block the next keystroke.

For bulk kill, remove the synchronous `_refresh_notification_count()` in `_do_bulk_kill_agents()`. `persist_bulk_kill_side_effects()` already dismisses notifications in the worker, so the completion path should refresh the count asynchronously after the worker finishes.  

## Fix kill-all burst behavior

`_kill_and_dismiss_all_agents()` currently loops through `killable` and calls `_do_kill_agent(agent)` for each one, then dismisses completed agents. That means N immediate-stage operations, N display refreshes, and N persistence tasks for live agents. 

You already have `_do_bulk_kill_agents(killable, dismissable)`, and marked/group kill already routes through that bulk path. 

Change the confirm callback in `_kill_and_dismiss_all_agents()` to:

```python
if confirmed:
    self._do_bulk_kill_agents(killable, dismissable)
```

That should make “kill all” behave like one optimistic UI transaction with one persistence worker, instead of a cascade of single-kill refreshes.

## Make the “immediate” detail path actually immediate

The display code correctly defers full detail rendering when `defer_detail=True`, and `j/k` uses `_refresh_agents_display_debounced()`. 

But `_apply_agent_detail_immediate()` calls `agent_detail.update_display_immediate(...)`, and `AgentDetail.update_display_immediate()` calls `prompt_panel.update_display(agent)`. That prompt panel path can build full Rich renderables and read prompt/reply artifacts through the global artifact cache. The cache helps, but first misses still do `os.listdir`, `os.stat`, and file reads on the UI thread.     

This undercuts the “header-only” goal.

### Proposed change

Add a truly cheap prompt-panel method, something like:

```python
def update_header_only(self, agent: Agent) -> None:
    header_text, error_tb_syntax = build_header_text(agent)
    self.update(Group(header_text, error_tb_syntax) if error_tb_syntax else header_text)
```

Then make `AgentDetail.update_display_immediate()` call that instead of `prompt_panel.update_display(agent)`.

The full prompt, reply, thinking, and file panels should remain in the debounced `_fire_debounced_detail_update()` path. The debouncer is already in place and defaults to 150 ms. 

A stricter version would avoid even `build_header_text()` if you find it expensive, because it can inspect embedded workflows and metadata. But the main win is to stop reading prompt/reply artifacts during the immediate navigation frame.

## Reduce full list rebuilds on optimistic removal

The current optimistic dismiss/kill path still tends to rebuild the list. `_refresh_panel_widgets()` updates every panel by calling `AgentList.update_list(...)`, while `_try_patch_agent_row()` only handles in-place single-row mutations, not removals. 

For large agent lists, a single removed agent should not require `clear_options()` + re-add every visible row.

### Proposed incremental path

Add a conservative removal fast path:

```python
_try_remove_agent_rows(removed_identities: set[AgentIdentity]) -> bool
```

Use it only when all of these are true:

* current tab is `agents`;
* no active agent search query;
* grouping mode is not a mode where banner counts/order would be risky;
* removed agents are in one panel and not changing panel structure;
* not removing a workflow parent with folded/child complexity, at least for the first pass.

Otherwise fall back to `_refresh_agents_display(list_changed=True, defer_detail=True)`.

Even a limited version helps the common case: dismissing one completed leaf agent or killing one running top-level agent from a large flat list.

## Launch fan-out: nonblocking, but worth cleaning up

Bulk, multi-model, multi-prompt, and repeat launch helpers all run fan-out work in raw `threading.Thread(...)`, so they do not directly block the UI thread.    

The two things I would improve:

1. **Unify launch fan-out on `asyncio.to_thread` or Textual workers.** The single-launch path is structured around `asyncio.to_thread`; the fan-out helpers use raw threads. They all call back into UI with `call_later`, which is good, but a single worker model will be easier to reason about and test.

2. **Use source-aware refresh coalescing.** Multi-prompt currently schedules a refresh on each spawned agent plus a final refresh. Coalescing prevents a full stampede, but you still risk “one in flight + one follow-up.” A source-aware debounce like `request_agents_refresh(source="launch", debounce_ms=150, latest_only=True)` would let launch bursts collapse into one refresh after the spawn burst settles.  

One subtle thread-safety note: `_run_agent_launch_body()` runs in a worker thread but reads/mutates `self._prompt_context` and its `ctx`. It mostly marshals UI actions back through `call_later`, but the cleaner design is: snapshot immutable launch context on the UI thread, pass that snapshot to the worker, and have the worker return launch actions/results for UI-thread commit. 

## Smaller cleanup: quarantine legacy sync kill handlers

`_kill_type_handlers.py` still contains synchronous per-type kill methods that parse/update project files, release workspaces, save bundles, delete artifacts, and persist dismissed agents inline. Search only found them defined there, so the current action path appears to use `_do_kill_agent()` plus `_kill_persistence.py` instead.  

I would either remove those legacy methods or turn them into wrappers that call the modern optimistic async path. Otherwise they are a future regression trap.

## Suggested implementation order

1. **Move kill notification dismissal/count refresh off the immediate path.** This is the most obvious remaining main-thread disk I/O.
2. **Route kill-all through `_do_bulk_kill_agents()` once.**
3. **Make `update_display_immediate()` header-only.**
4. **Add an incremental row-removal fast path for single dismiss/kill.**
5. **Normalize launch fan-out on one worker model and add source-aware refresh debounce.**

## Tests I’d add

* Single kill immediate stage does **not** call `load_notifications`, `mark_dismissed`, `save_dismissed_agents`, `parse_project_file`, or `delete_agent_artifacts`.
* Single kill schedules exactly one persistence task and removes the agent from in-memory lists before persistence runs.
* Single kill persistence refreshes notification count via `_refresh_notification_count_async()` after worker completion.
* Bulk kill does not synchronously refresh notification count before worker persistence.
* Kill-all calls `_do_bulk_kill_agents(killable, dismissable)` once rather than looping `_do_kill_agent()`.
* `AgentDetail.update_display_immediate()` does not call the full prompt-panel `update_display()` and does not read artifact files.
* Launch refreshes remain gated by `NavigationGate`; no apply/finalize/display refresh overlaps a synthetic `j/k` burst.

The repo already has the right architecture for this. The main next win is to make the kill path match the dismiss path: optimistic UI now, all disk and notification side effects later.
