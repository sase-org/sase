---
create_time: 2026-04-24 10:10:26
status: done
---
# Fix: `j`/`k` Navigation Unresponsive On Agents Tab After Agent Launch

## Problem

After the user submits a prompt in the `sase ace` TUI (Agents tab) to launch one or more agents, `j`/`k` navigation on
the Agents tab feels unresponsive — keys are dropped, delayed, or don't advance selection the expected number of
positions. Once the launch fully settles (a second or two later), navigation returns to normal.

The user reports "j/k don't work well right after launching one or more agents."

## Diagnosis

The launch entry point is `_finish_agent_launch` in `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:56`. It
does the minimum up-front work (`_unmount_prompt_bar`, which transfers focus back to the agent list) and then defers the
rest via `call_after_refresh(self._run_agent_launch_body, prompt)`. A comment on that call explicitly claims the purpose
is to let queued `j`/`k` keys drain "to their rightful target before any blocking I/O runs on the event loop."

That claim is only half true. The deferred body `_run_agent_launch_body` (lines 87–345) does _substantial_ synchronous
work directly on the Textual event-loop thread **before** spawning the daemon thread that actually runs the agent:

1. `resolve_agent_refs_in_prompt(prompt)` — disk I/O expanding `@name` → agent references.
2. `extract_vcs_workflow_tag` + `record_vcs_xprompt_usage` — disk I/O writing MRU state.
3. `get_ref_patterns` / `get_workflow_names` — workspace-provider lookups.
4. `_resolve_vcs_from_prompt` — potentially allocates a workspace (filesystem + VCS calls).
5. `add_or_update_prompt`, `_record_prompt_file_references` — history file writes.
6. `_try_execute_workflow` — may synchronously run a full workflow expansion (xprompt processor).
7. `process_xprompt_references` — xprompt expansion, which itself reads files.
8. Finally, `threading.Thread(...).start()` launches the actual agent subprocess in the background.

During steps 1–8, the event loop is blocked. Every `j`/`k` keystroke the user types in that window queues up. When the
body finally returns, the queued events fire in a burst (some may be coalesced/dropped by the terminal), which is what
the user perceives as "not working well."

There is a secondary contributor once the daemon thread finishes spawning: the background thread calls
`self.call_later(self._schedule_agents_async_refresh)`, which eventually reaches `_apply_loaded_agents` in
`src/sase/ace/tui/actions/agents/_loading.py:135`. `_apply_loaded_agents` runs synchronously on the event loop and does
non-trivial per-agent filtering / dedup work before finally calling `_refresh_agents_display(list_changed=True)` (which
rebuilds both OptionLists via `update_list`). If the list is large this can also perceptibly block the event loop for
tens of milliseconds, again swallowing rapid `j`/`k`.

**Why "after launching _one or more_ agents" specifically:**

1. Before the first launch the user hasn't blocked on a launch yet, so the window doesn't exist.
2. Each additional agent increases artifact/disk load time for subsequent refreshes and extends both blocking windows.
3. Repeat/bulk/multi-model launches call the launch body for each agent (see `_launch_repeat_agents`,
   `_launch_multi_model_agents`, `_launch_bulk_agents`), serializing the sync work on the UI thread.

**Why the existing mitigations don't fully solve it:**

- `call_after_refresh` only yields the loop _once_. The deferred body then re-acquires the loop for the full duration of
  its synchronous work.
- `_transfer_focus_off_prompt_bar` ensures the focus target is `#agent-list-panel`, so focus is not the root cause.
- `_programmatic_update` on `AgentList` only gates re-posting `SelectionChanged` messages during `update_list` /
  `update_highlight`; the app-level `j`/`k` bindings (`action_next_changespec` → `_navigate_agents_panel`) are _not_
  gated by that flag. So the flag isn't dropping keypresses — blocked event loop is.

## Root Cause Summary

`_run_agent_launch_body` performs blocking I/O (VCS resolution, history writes, xprompt expansion, workflow execution)
directly on the Textual event loop after `call_after_refresh`. The follow-up async refresh also runs a non-trivial
synchronous `_apply_loaded_agents` pass on the event loop. Together these produce a window of hundreds of milliseconds
during which `j`/`k` keystrokes are queued rather than processed, producing the observed "doesn't work well" feel
immediately after launch.

## Goals

1. Keep the event loop responsive during and immediately after agent launch so `j`/`k` is processed promptly.
2. Preserve current launch semantics: history is written, xprompt expansion happens, agent subprocess is spawned, the
   list refreshes, the correct agent ends up highlighted.
3. Apply the fix uniformly across single, repeat, multi-model, multi-prompt, and bulk launches.
4. Add regression coverage that asserts the launch body does not block for longer than a small budget.

## Non-Goals

1. Re-architecting the agent loader or disk scan pipeline (already tracked in `sase_plan_tui_refresh_nonblocking.md` and
   `sase_plan_tui_blazing_agents_navigation.md`).
2. Changing user-visible launch behavior (no new toast copy, no new keybindings).
3. Fixing any unrelated agent-list redraw issues.

## Design

Move the blocking portions of `_run_agent_launch_body` off the event-loop thread, so the loop stays live and `j`/`k`
keystrokes are processed during and after launch. Two complementary changes:

### 1. Off-load launch body to a worker thread

Wrap the body of `_run_agent_launch_body` (everything between the `_prompt_context` guard and the existing
`threading.Thread(target=_run, daemon=True).start()` call) in `asyncio.to_thread` (or `run_worker` /
`asyncio.get_event_loop().run_in_executor`, whichever fits the Textual idiom already used elsewhere — see
`_load_agents_async` in `actions/agents/_loading.py:107`).

Key design points:

- The call sites that need main-thread access (UI widget mutations, `self.notify`, `self.call_later`,
  `self._launch_multi_prompt_agents`, etc.) must continue to run on the main thread. Identify each such call and either:
  - keep it on the main thread by scheduling via `self.call_later(...)` from the worker, or
  - hoist it out of the worker (run it synchronously before the worker for fast, non-blocking ops like setting
    `ctx.timestamp`).
- Workflow dispatch (`_try_execute_workflow`) constructs workflow agents and writes artifacts. Decide whether it runs
  fully in the worker (preferred — it's all I/O) or is marshalled back to the main thread to preserve single-threaded UI
  invariants. Inspect its call graph for any UI mutation.
- Multi-prompt / multi-model / repeat / bulk dispatch functions currently mutate `self` and schedule work. Treat them
  the same way: move pure-I/O prep to the worker, marshal UI-touching ops back to the main thread.
- Preserve the existing "daemon thread spawns the subprocess" behavior as-is — it's already off-thread; we just want to
  make sure the _prep_ before that spawn is also off-thread.

### 2. Yield between `_apply_loaded_agents` phases (lighter touch)

`_apply_loaded_agents` currently runs its full pipeline synchronously. The expensive parts — dismiss filtering, dedup,
fold/order/filter/status pipeline inside `_finalize_agent_list`, and the final
`_refresh_agents_display(list_changed=True)` — all block the loop. Convert the heavy pre-display computation into a
worker-thread step, then perform only the widget updates on the main thread.

Minimum viable improvement: push the filter/dedup stages before `_finalize_agent_list` into the same worker that just
finished the disk load (they use only plain Python data). This removes them from the main thread without touching the
trickier finalize-and-render phase. That alone should be enough to eliminate the post-launch lag once combined with
step 1.

### 3. Regression guard

Add a test in `tests/ace/tui/actions/agent_workflow/` that invokes `_finish_agent_launch` on a stub `AceApp` with a
prompt context configured and asserts:

- After `_finish_agent_launch` returns, the event loop is free (no long-running blocking call still on it).
- Simulated `action_next_changespec` / `action_prev_changespec` calls executed immediately after launch change
  `current_idx` as expected (i.e., they aren't dropped/deferred).

Keep the test narrow — we're guarding the "launch body does not block the loop for longer than X ms" property, not
end-to-end launch correctness.

## Implementation Plan

1. Audit `_run_agent_launch_body` and its callees to separate "UI-touching" ops from "pure I/O / computation" ops.
   Document which calls must stay on the main thread.
2. Refactor `_run_agent_launch_body` to run I/O in a worker thread and marshal UI ops back via `call_later`. Ensure the
   existing daemon-thread agent-spawn remains intact.
3. Apply the same off-loading pattern to `_launch_multi_prompt_agents`, `_launch_multi_model_agents`,
   `_launch_repeat_agents`, and `_launch_bulk_agents` — they share the same blocking pattern.
4. Move the filter/dedup computation in `_apply_loaded_agents` into a worker step (may need refactor of
   `_load_agents_async` to do more work in the `to_thread` call, returning already-filtered lists).
5. Add tests under `tests/ace/tui/actions/agent_workflow/` for the non-blocking property, plus any existing launch
   correctness tests that should continue to pass unchanged.
6. Run `just check` per repo policy. Manually verify in a live `sase ace` session with several queued launches that
   `j`/`k` works immediately.

## Risks and Mitigations

1. **Risk:** race between concurrent launches and the async refresh now that more work is off-thread.
   - Mitigation: existing `_agents_loading` / `_agents_refresh_pending` guard already coalesces stacked refresh requests
     (last-request-wins). Verify new launch path marshals any state-mutating ops back to main thread.

2. **Risk:** exceptions previously raised synchronously in `_run_agent_launch_body` will now surface in a worker. User
   may not see the error.
   - Mitigation: the body already catches top-level exceptions and calls `self.notify(..., severity="error")` via
     `call_later`. Extend this pattern to cover the new worker wrapper.

3. **Risk:** UI widgets mutated from the worker thread cause Textual to misbehave.
   - Mitigation: audit every `self.query_one(...)`, `.notify(...)`, `.call_later(...)` site and ensure widget mutations
     run on the main thread only. Textual provides `app.call_from_thread` for this.

4. **Risk:** test flakiness around thread timing.
   - Mitigation: keep tests deterministic by using `asyncio.to_thread` stubs or by inspecting the synchronous path
     (e.g., assert a specific helper is called rather than timing the loop).

## Expected Outcome

After the fix, pressing `j`/`k` immediately after submitting a launch prompt produces responsive navigation with no
perceptible dropped keystrokes, regardless of how many agents are currently running or how large the on-disk artifact
tree has grown. Launch correctness (history record, subprocess spawn, refreshed list with the new agent selected) is
unchanged.
