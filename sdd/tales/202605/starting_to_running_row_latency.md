---
create_time: 2026-05-21 13:52:48
status: done
prompt: sdd/prompts/202605/starting_to_running_row_latency.md
---
# Promote STARTING agents to row entries soon after run_started_at lands

## Product context

When a user launches an agent in the ACE TUI, two visible effects fire on different schedules:

- The Agents-tab info panel's **"starting" count** ticks up almost immediately (within ~150-500 ms). It's computed from
  `AgentPanelIndex.hidden_starting_indices` (`_display_detail.py:208-220`) and refreshes on every 1-second countdown
  tick.
- The matching **agent row** does **not** appear in any panel until the agent's status transitions out of `STARTING`.
  Row rendering filters through `agent_is_rendered_in_agents_panel()` in `agent_panels.py:44-46`, which excludes any
  agent whose `status == "STARTING"`.

The transition `STARTING → RUNNING` (or `WAITING`) happens in `_meta_enrichment.py:294-302`: when the agent writes
`run_started_at` into its `agent_meta.json`, the next refresh picks it up and the row becomes eligible to render.

Today the only reliable triggers that drive a fresh tier-1 reload after the agent writes `run_started_at` are:

1. The inotify `ArtifactWatcher` (`fs_watcher.py`) → `_on_artifact_change` → `_schedule_agents_async_refresh()`. This is
   the intended fast path but is fragile in two ways: (a) the new `artifacts/<workflow>/<timestamp>/` subtree must
   already be under a watch by the time the agent writes its meta — there is an unavoidable race between the
   `<timestamp>/` dir being created and `_add_watch_tree()` installing watches on its children
   (`fs_watcher.py:337-342`); (b) the watcher can be unavailable altogether (non-Linux platforms, watch-table exhaustion
   at 4096 entries).
2. The one-shot startup Tier-2 reconcile, ~2 seconds after the first Tier-1 paint (`_loading_refresh.py:25,145-165`).
   This only fires once per app session.
3. The idle Tier-2 reconcile after 30 seconds of input quiescence (`_loading_refresh.py:18,113-143`).
4. The periodic auto-refresh tick (default interval 10 s; gated by a 5 s floor `AGENTS_LOAD_MIN_INTERVAL_SECONDS` in
   `_event_refresh.py`).

When the inotify race or coverage gap hits, the visible time-to-row is bounded by case (3) or (4) — 5–30 seconds — even
though the data needed to flip the status is on disk within ~1 second of the agent actually starting. That's the symptom
the user is reporting: counts tick up immediately; the row catches up "a while" later.

## Goal

When an agent transitions from `STARTING` to `RUNNING`/`WAITING`, its row should appear in the Agents-tab panel within
~1 second of the on-disk transition (modulo the existing 150 ms launch debounce), without regressing TUI responsiveness
or refresh cost during normal steady-state operation.

## Non-goals

- Remove the inotify watcher or the existing Tier-1/Tier-2 split. The two-tier model is load-bearing for startup latency
  on large artifact trees — we want to keep both paths and only add a targeted nudge for the narrow `STARTING` window.
- Surface STARTING rows directly (e.g. render them greyed out). That's a UX change the user hasn't asked for, and it
  would change selection/navigation semantics in ways that touch many call sites (`agent_panels.py`,
  `agent_panel_index.py`, selection snap, etc.).
- Change how `run_started_at` is recorded by the agent runner. The axe-side artifact-index upsert already happens
  (`run_agent_markers.py:153`); this plan stays purely in the TUI.

## Design

### Strategy: targeted STARTING-aware nudge on the existing 1 s tick

The Agents-tab already wakes every second via `_on_countdown_tick` (`_event_activity.py:15`). It calls
`_update_agents_info_panel()` and `_patch_agent_runtime_rows()` cheaply. We piggyback on this same tick to detect
STARTING transitions and request a coalesced refresh — but only while there is at least one STARTING agent in
`self._agents`, so the steady-state cost stays at the current baseline.

Mechanism:

1. **Counted gate.** Track whether the current `self._agents` list contains any STARTING agents. This is already
   computed implicitly by `AgentPanelIndex.hidden_starting_indices` (`agent_panel_index.py:75-101`); re-use it via a
   `bool` `has_starting` derived from the panel index, so we avoid an extra scan.

2. **Per-tick poll, only when gated open.** When `has_starting` is true, the countdown tick stats each STARTING agent's
   `agent_meta.json` (path is `agent.get_artifacts_dir() / "agent_meta.json"`). Cache the previous `(mtime_ns, size)`
   per agent identity on the TUI app instance (a small `dict` keyed by the agent's `identity` tuple). When any STARTING
   agent's meta mtime advances, fire `self.request_agents_refresh("starting_poll")` — exactly one call per tick
   regardless of how many agents transitioned. The existing 150 ms debounce and last-request-wins guard in
   `request_agents_refresh` collapse this into one Tier-1 reload, even when several STARTING agents flip in the same
   tick.

3. **Fallback nudge.** As a safety net for the case where `agent_meta.json` does **not** exist yet (e.g. the agent is
   still in its very early startup phase before the first meta write): if `has_starting` is true **and** at least one
   STARTING agent's `agent_meta.json` did not exist on the previous tick but exists now (i.e. file appearance, not just
   modification), also nudge a refresh. This catches the case where the watcher missed the `CREATE` event on the new
   timestamp directory.

4. **Eviction.** When an agent leaves STARTING (either we observed the transition or the agent disappeared from
   `self._agents`), drop it from the mtime cache. Cache size is bounded by the number of concurrent STARTING agents,
   typically 0–5.

### Why this stays cheap

- When no agent is STARTING (the steady-state for an established session), the tick adds **one boolean check** and
  short-circuits. Zero stat calls.
- When the user launches a fan-out of N agents, the tick stats N files per second for the ~few seconds between launch
  and `run_started_at`. A `stat` of a small JSON file is sub-100 µs; even at N=20 this is well under 2 ms per tick.
- The debounced `request_agents_refresh` already coalesces bursts, so a fan-out of 20 simultaneous transitions still
  produces exactly one Tier-1 reload.
- The Tier-1 reload itself already handles `run_started_at` enrichment via `enrich_agent_from_meta`
  (`_running_loaders.py:144`) and the meta_enrichment promotion logic — no changes needed there.

### Why not other approaches

- **Render STARTING rows immediately.** Cleanest visually but a UX change and a wide blast radius (selection, panel-key
  membership, counts split between visible vs. starting buckets). Defer.
- **Tighten the auto-refresh interval globally.** Regresses steady-state cost across all sessions, not just the launch
  window. Rejected.
- **Lower `AGENTS_LOAD_MIN_INTERVAL_SECONDS`.** Same problem — global change with no STARTING-awareness.
- **Schedule a one-shot `request_agents_refresh` 2 s after every launch.** Already partly covered by the startup Tier-2
  reconcile. Doesn't help when `run_started_at` arrives later than 2 s, which is common for cold-start agents (workspace
  clone, venv install).
- **Trust the watcher harder (e.g. recursive pre-watch).** Practical to attempt but doesn't help on platforms without
  inotify or under watch-table exhaustion; the 1 s tick poll is a cheap safety net regardless.

### Anti-regression bound

The fix only activates when `len(hidden_starting_indices) > 0`. A session with no recently-launched agents (the
overwhelming common case) pays a single `len(...) == 0` check per second per tab — well below measurement noise. The new
code path has no allocations in the steady state.

## Implementation outline

- **New helper** in `src/sase/ace/tui/actions/agents/_loading_refresh.py` (or a sibling module in `actions/agents/`):
  `_poll_starting_agent_transitions(self) -> None`. Walks the STARTING agents in `self._agents`, stats their
  `agent_meta.json`, compares to the cached `(mtime_ns, size)`, and either calls
  `self.request_agents_refresh("starting_poll")` or returns. Uses a per-app `dict[Identity, tuple[int, int] | None]`
  (None = file absent last tick) — initialised in `_state_init.py` next to `_last_agents_load_mono`.
- **Wire into the tick** in `src/sase/ace/tui/actions/_event_activity.py:_on_countdown_tick`, immediately after
  `_patch_agent_runtime_rows()` in the `current_tab == "agents"` branch. (We can also run the poll when the agents tab
  is not focused — STARTING transitions matter for the count even if the user is on another tab — but the row rendering
  only matters when the user comes back. Starting on the agents tab keeps the change minimal; we can revisit if needed.)
- **Eviction** lives inside the same helper: rebuild the cache from the live `hidden_starting_indices`, dropping
  identities that are no longer STARTING.
- **Tests** (mirroring the existing fixtures in `tests/ace/tui/test_launch_fan_out_unified.py` and
  `tests/ace/tui/test_event_handlers_dirty_flags.py`):
  - Steady state (no STARTING agents) → poll is a no-op; assert zero `request_agents_refresh` calls across N ticks.
  - Single STARTING agent → simulated `agent_meta.json` write with advanced mtime → exactly one debounced refresh
    request fires.
  - Fan-out of 5 STARTING agents → all transition in the same tick → still exactly one refresh request (coalesced by the
    existing debounce).
  - STARTING agent whose meta file appears (didn't exist last tick) → triggers a refresh.
  - STARTING agent that never transitions (dead PID etc.) → does not fire refreshes once eviction has dropped it;
    verifies the cache doesn't grow unbounded.
- **Telemetry.** Optionally tag the `tui_trace` span on the triggered refresh with `source="starting_poll"` (mirroring
  the existing `"idle_tier2_reconcile"` / `"startup_tier2_reconcile"` reasons) so we can confirm in profile traces that
  the poll is doing real work and not firing in the steady state.

## Risks and follow-ups

- **Cost during big launch bursts.** Stats stay O(STARTING-count). Worst plausible session: a user firing a 50-way
  `#xprompt` fan-out. 50 stats/second for ~10 seconds = 500 stats total, well under 50 ms aggregate. Mitigated further
  if needed by capping the poll set (e.g. newest 20).
- **Inotify watcher fix is still worthwhile.** This plan does _not_ fix the underlying race in `_add_watch_tree` for
  newly created agent directories. A follow-up could pre-walk the per-project `artifacts/<workflow>/` tree more
  aggressively on startup, or convert the watcher to a recursive subscription on the artifacts root. Out of scope here.
- **STARTING-state UX change** (rendering STARTING rows directly, perhaps muted) remains a viable future simplification;
  this plan doesn't preclude it.

## Open questions

- Should the poll run on every tab or only on the Agents tab? Minimal answer (Agents tab only) keeps blast radius small
  and is symmetric with how `_patch_agent_runtime_rows()` is tab-gated. Counter-argument: the info-panel "starting"
  count is visible on the Agents tab regardless, but the row that "appears" is also only visible on the Agents tab.
  Sticking with tab-gated is fine.
- Should we widen the trigger to also stat `waiting.json` and `done.json`? Out of scope for the STARTING→RUNNING bug;
  the WAITING/DONE transitions are already handled adequately by the watcher and existing refresh cadence.
