---
create_time: 2026-05-16 16:25:19
status: done
prompt: sdd/prompts/202605/tui_agent_refresh_gating.md
---
# Plan: Tab-gate and debounce the TUI agent loader

## Problem

The ACE TUI auto-refresh path still runs `agents.load_from_disk` (p50 ≈ 1.4 s, p95 ≈ 2.9 s) on essentially every refresh
tick. Empirical evidence from `~/.sase/perf/tui_trace.jsonl` after commit `7f507ac871c4`:

- 120 calls to `agents.load_from_disk` in a short driving session.
- Total CPU spent: 219 s.
- 30/120 (25%) of those calls fired while the user was on the **CLs** tab — i.e. work the user can't see.
- Every other span is in single- or low-double-digit ms. The loader is the only thing that matters.

### Why the previous fix did not cover this

Commit `7f507ac871c4` ("avoid unnecessary TUI agent refreshes") only narrowed the **inotify-driven** immediate-refresh
path (`_on_artifact_change` in `src/sase/ace/tui/actions/_event_refresh.py:21-75`) so notification/changespec writes no
longer kick an immediate `_load_agents_async`.

It did **not** touch the **timer-driven** path (`_on_auto_refresh`, lines 125-205). That handler still calls
`_load_agents_async` whenever `_dirty_agents` is True, and `_dirty_agents` is set by _any_ write under
`~/.sase/projects/*/artifacts/` (via `_dirty_surfaces_for_paths`, lines 77-106). With many agents running, the flag is
essentially always True.

Tab is not consulted at all on the agent-load branch (compare line 197 for changespecs, which _is_ tab-gated).

## Goals

1. **Cut load count by ~80%** in the driving scenario (mixed tab usage, many agents running). Verified by inspecting
   `tui_trace.jsonl` post-fix.
2. **Zero impact on correctness** — the agent list must still appear fresh when the user is looking at it, and missed
   inotify events must still recover via the 60-second sanity refresh.
3. **No deeper changes** — out of scope: `_record_from_dict` cost, Tier-2 search escalation, Rust-side index work,
   sibling-repo `sase ace --tmux` deployment issue.

## Non-goals

- Speeding up an _individual_ `load_from_disk` call. The 1.4 s cost is real and would require touching the Rust index /
  Python record-decoding loop; that work was reverted on master and is its own initiative.
- Changing inotify path filtering. The 7f507ac fix already does the right thing on that side.
- Adding a new perf-tracing flag or runbook. Existing trace records will show the improvement directly.

## Design

### Change 1 — Tab-gate the agent load in `_on_auto_refresh`

In `src/sase/ace/tui/actions/_event_refresh.py:125-205`:

- Wrap the `if agents_due:` block so it only runs when one of:
  - `self.current_tab == "agents"`, or
  - `sanity_due` is True (the 60-second floor must remain tab-blind so we recover from missed inotify events even if the
    user lives on the CLs tab forever).
- **Do not clear `_dirty_agents` when we skip.** That way the next eligible refresh (tab switch or sanity tick) still
  picks up the work.

This is symmetric with the existing changespec branch on line 197, which already gates on
`self.current_tab == "changespecs"`.

### Change 2 — Trigger a refresh on tab-switch _to_ agents

Hook `watch_current_tab` in `src/sase/ace/tui/app.py:305`. When the new tab is `"agents"` and `_dirty_agents` is True
(and a load isn't already in flight), schedule an async agent refresh via the existing `_schedule_agents_async_refresh`
helper. Symmetric handling for `new_tab == "changespecs"` and a dirty `_dirty_changespecs` flag falls naturally out of
the same pattern; include it if and only if the diff stays small — otherwise leave changespecs alone since it's already
cheap.

Risk: if `watch_current_tab` fires very early during startup before mixins are wired, guard the call with
`hasattr(self, "_schedule_agents_async_refresh")`.

### Change 3 — Debounce repeated agent loads

Add `_last_agents_load_mono: float` to `_state_init.py` (initial value `0.0`, near line 103 next to
`_last_full_sanity_refresh`).

In `_on_auto_refresh`, after computing `agents_due` and before invoking `_load_agents_async`:

```python
DEBOUNCE = AGENTS_LOAD_MIN_INTERVAL_SECONDS  # 5.0 default
since_last = now_mono - self._last_agents_load_mono
debounce_active = since_last < DEBOUNCE and not sanity_due
if agents_due and debounce_active:
    agents_due = False  # leave _dirty_agents set; next tick will retry
```

Set `self._last_agents_load_mono = time.monotonic()` after the `_load_agents_async` call returns (success or exception).

Constant: define `AGENTS_LOAD_MIN_INTERVAL_SECONDS = 5.0` next to `FULL_SANITY_REFRESH_SECONDS` at the top of
`_event_refresh.py`. No env-var override needed for the first cut — keep the surface small. (If a user genuinely needs
it tighter for development, they can set `--refresh-interval` lower; the debounce is the floor, not the ceiling.)

Rationale for 5 s:

- The user's refresh-interval default is ~2 s. A 5 s floor turns the worst case (loader fires every tick) into "loader
  fires once every 5 s" — that alone is a 2.5× reduction on the agents tab.
- Combined with Change 1, off-tab loads drop to zero between sanity ticks, so the typical CLs-tab session sees one load
  per minute instead of one every two seconds (~30× reduction off-tab).
- 5 s is short enough that a freshly-spawned agent appears in the list with no perceptible lag.

### Why not also make `_dirty_agents` more selective?

The original diagnosis suggested filtering "log-only" artifact writes from the dirty-flag promotion path. Skipping that
here because:

- It requires teaching `_dirty_surfaces_for_paths` what counts as a "structural" change (new agent directory vs. log
  append), which means parsing artifact-path semantics. That's fragile.
- The debounce + tab gate gets us the same outcome with a fraction of the surface area. If post-fix traces still show a
  problem, that's the next lever; not now.

## Implementation order

1. Add the debounce constant and state field; update `_on_auto_refresh`. Implement Change 1 and Change 3 in the same
   edit since they share the `agents_due` decision.
2. Add the `watch_current_tab` hook (Change 2).
3. Update / extend tests in `tests/ace/tui/test_event_handlers_dirty_flags.py` and (if needed)
   `tests/ace/tui/test_artifact_pane_tab_navigation.py`:
   - Off-tab auto-refresh leaves `_dirty_agents` set and does **not** call the loader.
   - Off-tab sanity tick (60 s elapsed) _does_ call the loader even with the user on CLs.
   - Two back-to-back auto-refresh ticks within `<5 s` only call the loader once.
   - Tab-switch to `"agents"` while `_dirty_agents=True` schedules a load.
4. Run `just check` per `memory/short/build_and_run.md`. Then drive `sase ace --tmux` again to capture a fresh trace and
   confirm the load count drops as projected.

## Verification

Before/after comparison against `~/.sase/perf/tui_trace.jsonl`. Acceptance:

- `count(span="agents.load_from_disk", tab="changespecs") == 0` outside 60 s sanity windows.
- `count(span="agents.load_from_disk") per minute on agents tab ≤ 12` (i.e. ≤ once per 5 s).
- All existing tests still pass; new tests cover the three branches above.

## Files touched

- `src/sase/ace/tui/actions/_event_refresh.py` — new constant, gating, debounce.
- `src/sase/ace/tui/actions/_state_init.py` — new state field.
- `src/sase/ace/tui/app.py` — `watch_current_tab` hook.
- `tests/ace/tui/test_event_handlers_dirty_flags.py` — new coverage.
- Possibly `tests/ace/tui/test_artifact_pane_tab_navigation.py` for the tab-switch trigger; only if a focused test fits
  more naturally there.

## Risks and mitigations

- **User switches to agents tab and sees a 5 s lag before the list updates.** The `watch_current_tab` hook eliminates
  this — the load fires the moment the user switches in.
- **The debounce hides a needed refresh.** Sanity tick (60 s) is unaffected, and the dirty flag remains set so the very
  next eligible tick reloads. Worst case the user sees an up-to-60-s-old list off-tab, which they cannot see by
  definition.
- **`watch_current_tab` fires during early startup.** Guard with `hasattr` for the scheduler method.
