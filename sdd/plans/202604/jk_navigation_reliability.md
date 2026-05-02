---
create_time: 2026-04-27 10:40:56
status: done
prompt: sdd/prompts/202604/jk_navigation_reliability.md
---
# Plan — Make `j`/`k` Navigation on the Agents Tab Reliable

## Symptom (user report)

> "`j`/`k` navigation is still super buggy. Dive deep into this, figure out why navigation using these keys is not
> reliable, and fix the issue."

This is the user's third or fourth complaint about j/k navigation. Prior plans (`instant_jk_navigation`,
`post_launch_jk_lag`, `jk_banner_highlight`, `jk_banner_highlight_refresh`, `agents_jk_random_jumps_at_fold_3`,
`fix_jk_nav_race`, `agents_navigation_delay`, …) each tackled one symptom and shipped — but the user still reports the
keys feel unreliable in normal use. We need to find what's left, not just patch the next visible glitch.

## Investigation summary

The j/k pipeline today (Agents tab, focused on an `AgentList` panel):

1. App-level binding (`bindings.py:8-9`) routes `j` / `k` to `action_next_changespec` / `action_prev_changespec`
   (`navigation/_basic.py:83-123`).
2. Each handler calls `_record_jk_navigation()` (`event_handlers.py:76-83` — sets `_nav_gate`'s monotonic timestamp) and
   `_navigate_agents_panel(±1)` (`navigation/_basic.py:15-63`).
3. `_navigate_agents_panel` calls `_panel_navigation_stops()` (`agents/_core.py:144-187`), which calls
   `build_agent_tree(panel_agents, …)` and `panel_key_per_agent(self._agents)` and `agents_for_panel(…)` — **rebuilt
   from scratch every keypress**.
4. It then linearly scans `stops` for the current banner key; falls through to a linear scan for `current_idx`; and **if
   neither matches, jumps to `stops[0]` (j) or `stops[-1]` (k)**.
5. The chosen stop is committed (`current_idx = payload` for an agent stop, or `_current_group_key = payload` for a
   banner stop).
6. `current_idx`'s setter fires `watch_current_idx` → `_refresh_agents_display_debounced()`
   (`agents/_display.py:234-243`), which synchronously runs `_refresh_panel_highlights()` (`agents/_display.py:492-532`)
   — another `panel_key_per_agent` + `query_one` + `query` + `widget.update_highlight`.
7. `update_highlight` (`agent_list.py:422-457`) sets `_programmatic_update=True`, sets `self.highlighted=row`, and
   schedules `call_later(self._clear_programmatic_flag)`.
8. Background reconcilers (`_on_artifact_change`, `_on_auto_refresh`, `_run_agents_async_refresh`) each consult
   `NavigationGate.is_navigating()` (250 ms window) and re-arm via `set_timer` while the user is mid-burst — so a
   refresh shouldn't land during a j/k burst.

The gating works. The debouncer works. The expensive detail-panel refresh waits the burst out. But three things still go
wrong in normal use, and together they explain the "buggy" feel:

### Bug 1: silent jumps to row 0 / last when stops don't contain the current cursor

In `_navigate_agents_panel`:

```python
if pos is None:
    new_pos = 0 if direction > 0 else len(stops) - 1
```

`pos` is `None` whenever:

- `_current_group_key` points at a banner that is no longer collapsed (e.g. `_folding.py` expanded the group while the
  cursor was anchored on its banner — see the many `_current_group_key` writes around `_folding.py:142,152,…`), AND
- `current_idx` happens to land on an agent that is currently inside a _different_ collapsed group, or in a panel that
  is no longer the focused panel, or got dropped from `_agents` by the most recent reload.

The user's cursor visibly teleports to the first/last visible row. Because `_panel_navigation_stops` is rebuilt fresh
every keypress, the very next press starts from that random anchor — so a couple of taps after a fold/unfold or a
panel-focus-change feel like the cursor "jumped sideways". Symptoms reported in `agents_jk_random_jumps_at_fold_3.md`
and `agents_jk_banner_navigation.md` were specific instances; the underlying fall-through is general.

### Bug 2: stale `_current_group_key` after the banner row is gone

`_current_group_key` is a plain attribute (no watcher). Many code paths mutate it (`_folding.py` ~9 sites,
`_grouping.py:90`, `_panels.py:54`, `event_handlers.py:373`, `_navigate_agents_panel` itself). When a
fold/expand/refocus changes the panel's tree such that the banner is no longer present (or no longer collapsed),
`_current_group_key` is left dangling. The next j/k press hits Bug 1's fall-through — the cursor jumps.

The symmetric case: a banner is created (a group becomes collapsed) but the cursor anchor stays on `current_idx`. The
user's mental model says "I'm on agent X"; the renderer hides X inside a collapsed banner; the next j/k press has
`current_idx` pointing at a _hidden_ agent that isn't in `stops` → fall-through → jump.

### Bug 3: per-keystroke tree rebuild + duplicated panel_key walks

Every j/k keypress runs:

- `_panel_navigation_stops()`: 1× `panel_key_per_agent(self._agents)` + 1× `agents_for_panel(...)` + 1×
  `build_agent_tree(panel_agents, …)`. Walking ~5N ops where N is `len(self._agents)`.
- `_refresh_panel_highlights()`: 1× `panel_key_per_agent(self._agents)` _again_ + a list comprehension over the result +
  `query_one` for the focused panel widget + `query("#agent-list-container AgentList")` to set the focus class.
- `_update_agents_info_panel()`: 2× `query_one` + a `bisect_right`.

For ~50 agents this stays under 1 ms. For 200+ agents (or when many agents have many `attempt_history` records, which
`build_agent_tree`'s walk consults indirectly through name-root dedup) it climbs to several ms. When the terminal
autorepeats j/k at ~30 Hz the event loop spends most of its time rebuilding state it just had — and a launched agent
(with worker-thread reload landing in the same moment) competes for the few free milliseconds.

The user's "super buggy" complaint is the accumulation of these costs into perceptible queueing **plus** the random
teleports of Bug 1 — a bad combo that reads as "keys are broken" even though each individual keystroke ultimately
produces a correct end state.

### Non-bugs (already fixed; preserve their behavior)

- **NavigationGate gating** (`nav_gate.py`, Phase 5 of `instant_jk_navigation`): all three async refresh paths consult
  it. Don't touch.
- **Detail-panel debouncer** (`util/debounce.py`, `agents/_display.py:234-243`): 150 ms quiesce is right. Don't touch.
- **Per-row render cache** (`agent_list.py:_agent_render_cache`): correct. Don't touch.
- **`update_highlight` programmatic-update flag** (`agent_list.py:422-461`): the `call_later` clear _does_ race against
  `OptionHighlighted` dispatch in principle, but in practice `event.index` resolves to the same `target_global` we just
  set — `on_agent_list_selection_changed` is idempotent on identical values (`event_handlers.py:366-370`). No observable
  bug; leave it alone for this plan.

## Root cause (one sentence)

`_navigate_agents_panel` recomputes the navigation stops from scratch on every keystroke and silently snaps to position
0/last when its current anchor (`current_idx` or `_current_group_key`) isn't in the freshly-rebuilt stops list — so any
state drift between the cursor's anchor and the tree (folding, panel focus, refresh) reads as a random teleport, on top
of the per-keystroke tree-rebuild cost.

## Goal

`j`/`k` on the Agents tab feels rock-solid:

- The cursor moves exactly one stop per press, in tree order, with no silent teleports — even after fold / unfold,
  panel-focus change, refresh, or launch.
- Holding j/k under terminal autorepeat does not visibly stutter on workspaces of up to a few hundred agents.
- When the cursor's anchor genuinely vanishes (e.g. the agent it was on was killed and dropped from the list), the
  cursor lands on the _visually-nearest_ surviving stop, not the panel's first/last row.

## Non-goals

- Promoting `_current_group_key` into a `reactive` (rejected in `jk_banner_highlight_refresh.md` for ordering reasons;
  respect that decision).
- Changing the OptionList rebuild path or the per-row render cache.
- Cross-tab navigation (changespecs / axe). Same shape would apply but the user's complaint is the Agents tab.
- Replacing `NavigationGate`, the detail debouncer, or the artifact-watcher coalescing.
- Optimistic UI insertion of launched agents (out-of-scope; same call-out as `post_launch_jk_lag.md`).

## Design

Three phases. Each is independently mergeable; the user feels phase 1 and phase 2 immediately, phase 3 is the guard
rail.

### Phase 1 — kill the silent teleport: anchor-aware fall-through

The fix is local to `_navigate_agents_panel` (`navigation/_basic.py:15-63`). Replace the
`new_pos = 0 if direction > 0 else len(stops) - 1` fall-through with a _visually-nearest_ recovery.

**Algorithm**:

1. Snapshot `(old_idx, old_key)` as today.
2. Build `stops` once.
3. Try the existing matches: banner-key first if `old_key is not None`, then agent-idx.
4. If `pos is None`, compute a **fallback anchor**:
   - If `old_key is not None`: walk the panel's tree (already in `stops`) and find the _first_ stop whose group key is a
     prefix of `old_key`, or whose group key shares the deepest common ancestor with `old_key`. Fall back to `old_idx`'s
     lexically-nearest agent stop if no banner ancestor exists.
   - Otherwise (`old_idx`-anchored): find the agent stop whose `agent_idx` is closest to `old_idx` (`min` over
     `abs(stop_idx - old_idx)` for `kind == "agent"` stops). Tie-break by lower index — keeps the cursor going "up"
     rather than "down" when equidistant, which feels less jarring than the current jump.
   - If no agent stops exist at all, fall back to the first banner stop.
5. The chosen fallback is `pos`, then `new_pos = (pos + direction) % len(stops)` — i.e. **the user's keystroke still
   moves them by one stop in the requested direction**, but from a sensible anchor rather than from the start/end of the
   panel.

**Why it's right**: The current behavior's only justification is "we have no idea where the user is, so put them
somewhere defined." That's wrong — we _do_ know the last anchor; we just need to find the nearest live stop. The new
behavior matches what every vim-style navigator does (after a redraw your cursor lands near where it was, not at line
1).

**Why it doesn't regress**: when `pos` is found through banner-or-agent match, the path is unchanged. This phase only
changes the silent-teleport branch.

**Touch**: `src/sase/ace/tui/actions/navigation/_basic.py`. Add a small `_nearest_stop_anchor(stops, old_idx, old_key)`
helper to keep `_navigate_agents_panel` readable.

**Definition of done**: a unit test that constructs a `_StubApp` with stops where neither `old_idx` nor `old_key` match,
verifies the new cursor lands on the closest available stop and then steps by one, and confirms the fall-through to `0`
/ `len(stops)-1` no longer happens.

### Phase 2 — cache `_panel_navigation_stops()` per refresh cycle

Replace per-keystroke tree rebuilds with a memoized stops list, invalidated whenever the inputs change.

**Inputs that change the stops list**:

- `self._agents` (identity of the list — replaced wholesale by `_apply_loaded_agents_prepared` and `_refilter_agents`).
- `self._panel_group.focused_idx` / `.panel_keys`.
- `self._group_fold_registry` revision (the registry already exposes a notion of state; bump a version counter on every
  `set_collapsed` / `toggle`).
- `self._grouping_mode`.

**Mechanism**: introduce a small `_NavStopsCache` on the agents-loading mixin (or on `_panel_group`) that stores a tuple
`(agents_id, focused_idx, fold_version, mode)` and the cached `stops`. `_panel_navigation_stops()` returns the cached
list when the tuple matches, otherwise rebuilds and updates.

The `fold_version` counter lives on `AgentGroupFoldRegistry` (already present in the codebase as a per-mode registry)
and is bumped from a single chokepoint method (`set_collapsed`). Other callers already go through that method.

**Auxiliary cache**: `panel_key_per_agent(self._agents)` is also called twice per keystroke (once inside
`_panel_navigation_stops` via `agents_for_panel`, once inside `_refresh_panel_highlights`). Memoize it on the same cache
key — it shares the agents-id invalidation criterion. Avoid premature global memoization; just hang it off
`self._panel_group`.

**Why it's safe**: every cache invalidator already runs through a controlled method (panel focus change, fold/unfold,
grouping-mode change, agents reload). Plumb a `_bump_nav_stops_cache()` call into each of those paths once and forget
it. The cache can be invalidated _aggressively_ (cheap) — false invalidations cost a rebuild, never correctness.

**Touch**:

- `src/sase/ace/tui/actions/agents/_core.py` — `_panel_navigation_stops` becomes the cache reader.
- `src/sase/ace/tui/actions/agents/_display.py` — `_refresh_panel_highlights` reads from the same memoized panel-keys
  map.
- `src/sase/ace/tui/actions/agents/_panels.py` (panel focus change), `_folding.py` (fold/unfold), `_grouping.py`
  (grouping-mode cycle), `_loading.py` (agents reload), `startup.py` (init) — call the bump.
- `src/sase/ace/tui/models/agent_group_fold.py` — add a monotonic `version` on `AgentGroupFoldRegistry`, incremented by
  every `set_collapsed`.

**Definition of done**:

- A perf test asserts `build_agent_tree` is called **at most once** during a 20-keystroke j/k burst (vs. 20× today).
- Same assertion on `panel_key_per_agent`.
- Existing j/k tests in `tests/ace/tui/test_agent_jk_navigation.py` continue to pass.

### Phase 3 — regression test + perf gate

A targeted `tests/ace/tui/actions/agents/test_jk_reliability.py` (or extend the existing `test_agent_jk_navigation.py`)
that:

1. Builds a `_StubApp` with a mixed tree: two projects, one fully expanded, one with a collapsed group, and a tag panel
   that pushes some agents off the focused panel.
2. **Bug 1 guard**: pre-set `_current_group_key` to a banner that is _not_ in `stops` (simulate a stale anchor). Press j
   5 times. Assert each press moves exactly one stop and never lands on `stops[0]` from a non-adjacent anchor.
3. **Bug 1 guard**: pre-set `current_idx` to an agent that's been hidden by collapsing its group. Press j 5 times. Same
   assertion.
4. **Bug 3 guard**: instrument `build_agent_tree` and `panel_key_per_agent` with a counter, run a 20-keystroke burst
   with the agent list unchanged, and assert each helper ran ≤ 1 time across the whole burst.
5. **Acceptance**: existing `test_agent_jk_navigation.py` cases still pass; existing
   `test_jump_hints_for_folded_banners.py` and `test_agents_jk_random_jumps_at_fold_3.py` regression cases pass
   unchanged.

This is the tripwire that catches the next "still super buggy" report before the user has to file it.

## Sequencing

Phase 1 alone removes the random-teleport feel — the most visible "buggy" symptom. Phase 2 makes the per-keystroke cost
flat regardless of agent count, so under autorepeat the loop has no excuse to drop into queueing. Phase 3 locks both in.
Each phase is independently mergeable; phase 1 is a few lines and ships first.

## Risks

1. **Phase 1's "nearest stop" heuristic could surprise users** when they had `_current_group_key` set on a banner in a
   different panel after panel-focus change. Mitigation: when the chosen fallback is in a different panel than the
   cursor's _new_ anchor, prefer the focused-panel nearest stop. The `stops` list is already focused-panel-only
   (`_panel_navigation_stops` only enumerates the focused panel), so this case can't arise — just call it out so
   reviewers don't go looking.
2. **Phase 2's cache invalidation is correctness-critical**. If a code path mutates fold state without bumping the
   version (e.g. someone reaches into `AgentGroupFoldRegistry._collapsed_keys` directly), j/k will navigate stale stops.
   Mitigation: search the codebase for direct mutation, force every writer through `set_collapsed(...)`. Add a
   `_AgentGroupFoldRegistry__no_direct_mutation` test that introspects the public surface to make the contract explicit.
3. **Tests under `_StubApp` don't run a real Textual loop**, so Phase 3's "no random teleport" assertion is purely a
   state-machine check. That's fine for the regression guard — the e2e tests (`tests/ace/tui/page_objects/`) already
   cover the rendered side.

## Acceptance criteria

- Pressing `j` or `k` on the Agents tab moves the cursor to the _next_ tree-order stop, every time, with zero silent
  teleports — verified manually in a workspace with several folded groups, several tag panels, and at least one ongoing
  reload (e.g. an agent was just launched).
- A 20-keystroke j/k burst on a 200-agent workspace runs `build_agent_tree` and `panel_key_per_agent` at most once each
  (regression-tested).
- `just check` passes.
- The user can hold `j` for several seconds without perceptible lag or jumps.
