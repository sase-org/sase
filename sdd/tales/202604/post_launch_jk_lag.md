---
create_time: 2026-04-27 09:02:02
status: done
prompt: sdd/prompts/202604/post_launch_jk_lag.md
---
# Plan — Eliminate the Post-Launch `j`/`k` Lag

## Symptom (user report)

> "There is still a lag after launching an agent before the `j`/`k` keys work to navigate to different agent/workflow
> entries."

After submitting a prompt to launch a new agent in the `sase ace` Agents tab, `j`/`k` keystrokes feel laggy or "queued"
for ~0.5–2s. Once the dust settles, navigation is instant again. Previous fixes (`fix_agents_jk_after_launch.md`,
`instant_jk_navigation.md` Phases 1–5) reduced but did not fully eliminate this lag.

## Diagnosis — why prior fixes don't close the loop

The previous work moved the right things off the UI thread:

- **`_run_agent_launch_body`** is now wrapped in `asyncio.to_thread` (good — disk I/O for VCS resolution, history
  writes, xprompt expansion, subprocess spawn no longer blocks the loop).
- **`_load_agents_async`** runs `load_agents_from_disk` and `_compute_loader_cleanup` via `asyncio.to_thread`.
- **`NavigationGate`** (Phase 5) defers `_on_artifact_change` and `_on_auto_refresh` when the user is mid j/k burst —
  they re-arm via `set_timer` until the user pauses.

But **the launch-driven refresh path bypasses every one of these guards on its post-disk leg**. Concretely, the worker
thread finishes the launch and calls:

```python
self.call_later(self._schedule_agents_async_refresh)   # _agent_launch.py:286, :377
```

That schedules `_run_agents_async_refresh`, which awaits `_load_agents_async()`. The disk I/O leg is off-thread, but the
**post-await leg runs synchronously on the UI thread** and does substantial work:

1. `_apply_loaded_agents` — dismissed-set filtering, **synchronous `save_dismissed_agents()` disk I/O for each
   auto-dismissed agent**, hideable categorization (`_loading.py:199-335`).
2. `_finalize_agent_list` — fold-state filtering, agent-query parse + evaluation, status overrides, collapse-key GC,
   tab-bar count update (`_loading.py:449-`).
3. `_refresh_agents_display(list_changed=True, defer_detail=True)` — full panel rebuild via `_refresh_panel_widgets`,
   which calls `widget.update_list(...)` for **every panel**: each call does `clear_options()` + `add_option()` per row
   (`agent_list.py:118-341`). For 30–80 agents this alone is tens to hundreds of milliseconds.

While that leg runs, the event loop is blocked. j/k keystrokes queue. When the leg completes, queued events fire in a
burst (some coalesced/dropped by the terminal) — exactly the "doesn't work well right after launching" feel.

Three additional aggravators stack on top:

- **`_run_agents_async_refresh` does not consult `NavigationGate`.** Phase 5 only gated the auto-refresh timer and the
  inotify callback. The refresh fired by launch (and by kill / dismiss / approve / hitl) walks straight onto the UI
  thread regardless of whether the user is currently navigating.
- **The newly-launched agent's spawn writes a flurry of artifact files** (`agent_meta.json`, prompt files, workspace
  setup). Those writes trigger inotify in `ArtifactWatcher`. Even with the 50 ms coalesce window, the _first_ event
  after launch — when the user hasn't pressed j/k yet — slips past the gate and fires another full apply/render pass. So
  the user sees back-to-back blocking refreshes.
- **Multi-prompt / repeat / multi-model launchers schedule the refresh several times** (per agent spawned, plus a final
  wrap-up — `_launch_multi_prompt.py:44-64`). The `_agents_loading` / `_agents_refresh_pending` flag coalesces
  concurrent triggers down to "one in flight + one follow-up", so the user still gets exactly two heavy apply/render
  passes regardless — and both still block.

### Why j/k itself is not the culprit

The j/k action path (`action_next_changespec` → `_navigate_agents_panel` → `current_idx` setter → `watch_current_idx` →
`_refresh_agents_display_debounced` → `_refresh_panel_highlights` + `_update_agents_info_panel` + 150 ms detail
debounce) is genuinely cheap. The instrumentation harness from Phase 1 confirms this on idle timelines. The lag is
collateral damage from the refresh **landing during** or **immediately before** the user's j/k burst.

## Root cause (one sentence)

**The refresh fired by `_finish_agent_launch` (and by every other state-mutating action) runs its apply/finalize/render
pipeline synchronously on the UI thread, and it bypasses `NavigationGate`, so the event loop is blocked through the
user's first j/k burst after launch.**

## Goal

Pressing `j`/`k` immediately after submitting a launch prompt feels indistinguishable from idle navigation — no
perceptible queueing, no dropped keystrokes — regardless of agent count or how many launches were chained (single,
multi-prompt, multi-model, repeat, bulk). The new agent appears in the list within a few hundred milliseconds of the
user pausing j/k.

## Non-goals

- Optimistic UI insertion of the launching agent before the disk reload returns. (Compelling, but a larger surface
  change. Out of scope for this plan; revisit only if the gating + offload approach below proves insufficient.)
- Rewriting the OptionList rebuild path. We rely on Phase 3's per-row render cache and the existing `update_list` API.
- Changes to the launch semantics (history saved, subprocess spawned, list refreshed, correct selection).
- inotify / fs-watcher refactors. Phase 5's `ArtifactWatcher` already gates correctly.
- Cross-tab work (ChangeSpecs, Axe). The user's report is the Agents tab; the same fix shape applies if needed but is a
  follow-up.

## Design

The fix has three stacked changes. Each is mergeable on its own and each later one only sharpens the behavior set up by
the earlier ones.

### Phase 1 — Gate `_schedule_agents_async_refresh` on `NavigationGate`

**Single source of truth for "should we land a refresh right now?"**

Move the same gate check that `_on_artifact_change` and `_on_auto_refresh` already use into `_run_agents_async_refresh`
(the ultimate consumer; gating there catches every caller). When the gate reports `is_navigating()`, defer via
`set_timer(time_until_idle + 0.05, self._run_agents_async_refresh)` exactly like the inotify path. Preserve the existing
`_agents_loading` / `_agents_refresh_pending` coalescing — the deferred re-arm should set
`_agents_refresh_pending = True` rather than re-scheduling unconditionally, so a launch that fires three refreshes
during a long j/k hold still produces one final apply/render pass once the user pauses.

**Why it works**: The expensive UI-thread leg (apply + finalize + full panel rebuild) only fires when the user is _not_
in a navigation burst. The first j/k after launch grabs the loop, the gate trips, and the refresh waits ~250 ms past the
user's last keystroke before claiming the thread.

**Why it doesn't break correctness**: The deferred refresh re-arms; the user always sees the new agent within ~250 ms of
their last keystroke. `_agents_loading` ensures we never run two passes concurrently. The `_agents_refresh_pending` flag
(already in place) is the merge point for "one more full pass needed once we finish".

**Touch**: `src/sase/ace/tui/actions/agents/_loading.py` (`_schedule_agents_async_refresh`,
`_run_agents_async_refresh`); `src/sase/ace/tui/util/nav_gate.py` if a small `defer()` helper helps deduplicate the
re-arm pattern between this and `_on_artifact_change`.

**Definition of done**: A scripted Pilot test launches a fake agent (stubbed out at the worker boundary so no subprocess
actually spawns), records the post-launch refresh path's `t_apply_started` against the user's synthetic j/k bursts, and
asserts: while a j/k burst is active, no `_apply_loaded_agents` call lands; after the user pauses for
`>= window_s + epsilon`, exactly one apply/render pass runs and the new agent appears.

### Phase 2 — Offload the apply/finalize data pipeline to the worker thread

Phase 1 hides the lag behind the gate, but a careful user pressing j/k for >250 ms straight will still feel the
apply/render pass when it finally lands. Phase 2 makes the landed pass cheap.

The on-UI-thread work in `_apply_loaded_agents` and `_finalize_agent_list` is **mostly pure data transformation**:
dismissed-set filtering, hideable categorization, fold-state filtering, query evaluation, status-override application.
These are operations on plain Python lists/sets/dataclasses — no Textual widget access, no async machinery. Move them
into the same `asyncio.to_thread` call that `_load_agents_async` already uses for disk I/O.

The output of the worker leg becomes a **fully prepped, ready-to-render** list of agents plus the small set of side
effects that _do_ need the UI thread: tab-bar count update, `_refresh_panel_widgets`, panel-height re-application,
info-panel update, file-panel refresh.

Two side-effects need re-routing:

1. `_persist_dismissed_agent` calls `save_dismissed_agents(...)` (disk write). Today it's invoked from
   `_apply_loaded_agents` on the UI thread. Move it into the worker leg and just merge the resulting dismissed-set
   update into `self._dismissed_agents` after the worker returns.
2. `_compute_loader_cleanup` already runs in `asyncio.to_thread` from the async path; the _sync_ re-call inside
   `_apply_loaded_agents` (lines 254-265) is now dead code on the async path and can be removed from the post-disk leg.

After Phase 2, the on-UI-thread post-await footprint shrinks to essentially:

- write the new agent list onto `self._agents` / `self._agents_with_children`
- call `_refresh_panel_widgets` (the unavoidable widget-touching work)
- update tab-bar counts and info panel

The render cost remains, but is bounded by the OptionList rebuild itself — already cushioned by Phase 3's per-row render
cache.

**Touch**: `src/sase/ace/tui/actions/agents/_loading.py` (split `_apply_loaded_agents` into a pure-data worker step and
a UI-thread render step; `_finalize_agent_list` likewise — its query/filter/sort body moves to the worker, only the
widget calls stay on the UI thread).

**Definition of done**: With Phase 1's gate disabled (test-only), bench harness from Phase 1 of the prior plan shows
post-launch p95 key-to-paint drops to within 5 ms of the idle baseline on a 50-agent workspace. With the gate
re-enabled, p95 matches the idle baseline exactly.

### Phase 3 — Regression test

Add a focused test under `tests/ace/tui/actions/agent_workflow/` that:

1. Boots a stub `AceApp` with a populated `_agents` list and a configured `PromptContext`.
2. Calls `_finish_agent_launch("hello")`.
3. Synthesizes 20 j/k actions immediately after, recording each `action_next_changespec` entry time.
4. Asserts every action's `_apply_agent_detail_update` does not block for more than `_FRAME_BUDGET` ms (e.g. 16 ms), and
   that no `_apply_loaded_agents` invocation overlaps a j/k action.

The test should not depend on real subprocesses or real disk I/O — stub `_launch_background_agent`,
`load_agents_from_disk`, and `save_dismissed_agents`.

This is the regression guard the user explicitly asked for ("finally fix it") — without a test, the next post-launch lag
complaint will be playing whack-a-mole against the next code path that bypasses the gate.

**Touch**: new test file under `tests/ace/tui/actions/agent_workflow/`.

## Sequencing

Phase 1 ships first and is the user-visible fix. Phase 2 is hardening for the long-press case. Phase 3 is the guard.
Each is independently mergeable. Phase 1 alone should already feel right to the user; Phase 2 makes the land _itself_
fast; Phase 3 prevents regression.

## Risks

1. **Gate-induced staleness window.** A user holding j/k for several seconds after launch won't see the new agent until
   they pause. Mitigation: the 250 ms window is short by human standards; the existing "Agent started for X" toast
   already confirms the launch happened.
2. **Coalescing edge case.** If a refresh is deferred by the gate and then a _second_ refresh trigger arrives (e.g.
   inotify fires) before the first lands, both should fold into one final pass. The `_agents_refresh_pending` flag
   already handles this; verify the deferred re-arm path sets it correctly.
3. **Worker-thread access to `self._dismissed_agents`.** Phase 2 moves `_persist_dismissed_agent` into the worker leg.
   The set is read on the UI thread elsewhere; Python's GIL makes `set.add` / `set.discard` atomic, but mutating it from
   a worker while UI code iterates is risky. Mitigation: the worker leg computes a _delta_ (set of identities to add);
   the UI thread applies the delta after the worker returns.
4. **Tests that depend on synchronous post-launch state.** Existing tests may assume `_finish_agent_launch` leaves the
   agent list updated synchronously. Audit `tests/ace/tui/test_agent_launch_*` and adjust to await / drive the worker
   via the test harness.

## Acceptance criteria

- Launching one or several agents (single / multi-prompt / multi-model / repeat / bulk) produces no perceptible j/k lag.
  Phase-1 perf bench p95 key-to-paint stays at the idle baseline through the launch window.
- The newly-launched agent appears in the list within ~300 ms of the user's last navigation keystroke.
- `just check` passes; no regressions in launch correctness (history record, subprocess spawn, refreshed list, correct
  selection).
- Regression test asserts the no-overlap property: no `_apply_loaded_agents` call overlaps an active j/k burst.
