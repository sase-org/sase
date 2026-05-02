---
create_time: 2026-04-10 19:53:02
status: done
prompt: sdd/prompts/202604/nonblocking_agent_launch.md
---

# Plan: Non-blocking TUI Agent Launching

## Problem

When a user hits `<enter>` in the TUI prompt input, the event handler `_finish_agent_launch()` runs synchronously on
Textual's event loop. This blocks the entire TUI until all work completes:

- **Multi-model (`%model`)**: `_launch_multi_model_agents()` calls `time.sleep(1)` between each model launch, blocking
  for (N-1) seconds total. With 3 models, the TUI freezes for ~2 seconds.
- **Bulk launches**: `_launch_bulk_agents()` has the same `time.sleep(1)` loop, blocking for (N-1) seconds.
- **Single agent**: The synchronous pre-launch work (VCS resolution, xprompt processing, subprocess spawning, workspace
  claiming) adds noticeable latency before the event handler returns.

## Existing Pattern

`_launch_multi_prompt_agents()` (line 347 of `_agent_launch.py`) already solves this correctly:

```python
thread = threading.Thread(target=_run, daemon=True)
thread.start()
# Immediate feedback while agents launch in background.
self.notify(f"Launching {n} agent(s)...")
```

It spawns a daemon thread for the blocking work, returns immediately, and uses `self.call_later()` to safely update
Textual state from the background thread.

## Approach

Apply the same threading pattern to all three blocking code paths: multi-model, bulk, and single-agent launches.

### Phase 1: Thread-ify `_launch_multi_model_agents`

**File**: `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`

Wrap the body of `_launch_multi_model_agents()` in a `threading.Thread`, matching the pattern from
`_launch_multi_prompt_agents()`:

- Move the for-loop (workspace allocation, `time.sleep(1)`, `_launch_background_agent` calls) into a thread target
  function.
- Keep immediate notification (`self.notify(f"Launching {n} agent(s)...")`) outside the thread.
- Use `self.call_later()` for the final `_load_agents` refresh and completion notification from inside the thread.
- Add exception handling with `log.exception()` + error notification via `call_later`, matching the multi-prompt
  pattern.

### Phase 2: Thread-ify `_launch_bulk_agents`

**File**: `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`

Same transformation for `_launch_bulk_agents()`:

- Move the for-loop over `changespecs` (with its `time.sleep(1)`, workspace allocation, and `_launch_background_agent`
  calls) into a thread target function.
- Clear `_bulk_changespecs` and `_prompt_context` before starting the thread (already done).
- Perform `marked_indices` clearing and `_refresh_display()` immediately (before thread start) since they're UI state.
- Move the final notification and `_load_agents` refresh into the thread via `call_later`.

### Phase 3: Thread-ify single-agent post-unmount work in `_finish_agent_launch`

**File**: `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`

The single-agent path at the end of `_finish_agent_launch` (lines 260-280) calls `_launch_background_agent` +
`_load_agents` + `notify` synchronously. Move just the `_launch_background_agent` call into a short-lived thread:

- Keep all the pre-launch resolution work (VCS, xprompts, history save) synchronous since it's needed to determine
  launch parameters and is relatively fast.
- Spawn a daemon thread for `_launch_background_agent()` + the follow-up `call_later(self._load_agents)` and `notify()`.
- Show an immediate "Launching agent..." notification before the thread starts.

This also covers the multi-model and multi-prompt dispatch points earlier in `_finish_agent_launch`, since those methods
will now be non-blocking after Phases 1-2.

## Out of Scope

- Making `_finish_agent_launch`'s pre-launch resolution work (VCS resolution, xprompt expansion) async. This work is
  relatively fast and the prompt bar is already unmounted before it runs, so the user gets visual feedback. Threading
  the actual launch calls is the high-impact fix.
- Eliminating `time.sleep(1)` between launches. The sleep ensures unique timestamps. Could be replaced with a monotonic
  counter approach, but that's a separate concern and the sleep is fine in a background thread.
