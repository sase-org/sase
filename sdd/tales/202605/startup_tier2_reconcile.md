---
create_time: 2026-05-16 19:07:50
status: done
prompt: sdd/prompts/202605/startup_tier2_reconcile.md
---
# One-shot Startup Tier 2 Full-History Reconcile

## Motivation

The 2026-05-16 perf push deferred the Tier 2 full-history reconcile in `sase ace` because firing it unconditionally at
startup was the dominant wall-time span (~2.7 s scanning ~12 k artifacts on an established home dir). After commit
`366a3cb47` the reconcile is sticky-pending and triggered only by:

- the 1 s countdown tick once input has been quiet for `TIER2_RECONCILE_IDLE_THRESHOLD_S = 30 s`, or
- a manual `y` refresh while the flag is still pending.

In practice this means users who launch `sase ace` and immediately interact never see the full agent set until they idle
for 30 s or press `y`. The research doc claims the default Agents view shows the same 32 visible rows in either case,
but that is conditional on the user not changing query, expanding a fold, or operating on a home dir whose visible Tier
1 ≠ visible Tier 2. On affected setups (the user reports this is the common case for them), agents that should show up
are missing on startup until idle/refresh.

The user wants the full set available "right after `sase ace` starts" again, but **without** reintroducing the prior
behavior of firing Tier 2 as the immediate next action after the Tier 1 apply — which is what caused the dominant span
and the GIL contention with early j/k bursts.

## Goal

Add a one-shot "startup tier 2" trigger that fires the deferred reconcile shortly after `sase ace` starts. Keep the idle
(30 s) and manual (`y`) triggers as fallbacks. The startup trigger should:

1. Fire exactly once per session.
2. Fire close enough to startup that the user sees the full agent set within the first few seconds.
3. Fire after the initial paint has rendered the Tier 1 result, so the user is not staring at a blank list for the
   entire Tier 2 wall time.
4. Not fire if Tier 1 already returned complete history (no reconcile needed).
5. Coexist with the idle / manual paths so we do not double-schedule.

## Non-goals

- We are not reverting to the "schedule Tier 2 the moment Tier 1 arrives" pattern. The small startup delay is the point.
- We are not changing how Tier 2 itself is loaded (still `asyncio.to_thread`, still routes through
  `_schedule_agents_async_refresh(full_history=True)` and `_run_agents_async_refresh`).
- We are not adding scroll-past-Tier1 / query-entered / fold-expansion triggers from the research doc's "full
  lazy-trigger set". The user already chose Q1 = "Idle + manual refresh (y)"; this plan only adds a startup trigger on
  top of those.

## Design

### Trigger timing

After the first `_apply_loaded_agents_prepared_inner` call that lands a load with `complete_history == False`, schedule
a one-shot timer:

```
self.set_timer(STARTUP_TIER2_RECONCILE_DELAY_S, self._fire_startup_tier2_reconcile)
```

`STARTUP_TIER2_RECONCILE_DELAY_S` defaults to **2.0 s**. Rationale:

- The first Tier 1 apply lands ~0.6 s after process start in the captured traces, so a 2.0 s delay puts the reconcile
  worker start ~2.6 s after launch — still inside the "right after startup" window the user wants.
- The captured key-to-paint worst-case Agents-tab paints in the first j/k burst were 77 ms / 71 ms during the Tier 2
  contention window; a 2 s delay shifts most of the Tier 2 Rust scan to _after_ a typical first burst, reducing GIL
  contention with the most jank-sensitive navigation.
- Short enough that users who type immediately still get the full set within ~5 s of launch.

This constant lives next to `TIER2_RECONCILE_IDLE_THRESHOLD_S` in `_loading_refresh.py` so both knobs are tunable in one
place.

### State

Add one new state field:

- `_agents_startup_tier2_scheduled: bool` — set True once we've armed the one-shot startup timer for this session.
  Prevents double-arming if subsequent Tier 1 applies also report incomplete history (e.g. the auto-refresh tick
  re-loads Tier 1 before the startup timer fires).

Declared in `_loading_state.py` (typing surface), initialized to False in `_state_init.py`, and never cleared during a
normal session. A complete-history apply does not need to clear it because once Tier 2 has merged the pending flag is
False and the timer callback no-ops.

### Apply hook (`_loading_apply.py`)

In the existing branch that sets the pending flag:

```python
if (
    load_state is not None
    and load_state.needs_full_history_reconcile
    and not getattr(self, "_agents_history_reconcile_pending", False)
):
    self._agents_history_reconcile_pending = True
    self._agents_history_reconcile_armed_mono = time.monotonic()
    # NEW: arm one-shot startup trigger if we haven't already.
    if not getattr(self, "_agents_startup_tier2_scheduled", False):
        self._agents_startup_tier2_scheduled = True
        self.set_timer(
            STARTUP_TIER2_RECONCILE_DELAY_S,
            self._fire_startup_tier2_reconcile,
        )
```

Import `STARTUP_TIER2_RECONCILE_DELAY_S` from `_loading_refresh` (same module already imports time).

### Trigger method (`_loading_refresh.py`)

Add a sibling to `_maybe_trigger_idle_tier2_reconcile`:

```python
def _fire_startup_tier2_reconcile(self) -> None:
    """One-shot startup Tier 2 reconcile trigger.

    Fires ~STARTUP_TIER2_RECONCILE_DELAY_S after the first incomplete-
    history apply so the user sees the full agent set within a few
    seconds of launching `sase ace`, while still giving the initial
    Tier 1 paint a head start on the UI thread.
    """
    if not getattr(self, "_agents_history_reconcile_pending", False):
        return
    if self._agents_loading or self._agents_refresh_scheduled:
        # Another path already arranged a reload; either the next
        # apply will land complete-history or the pending flag will
        # still be set, in which case the idle / manual paths cover us.
        return
    self._agents_history_reconcile_pending = False
    self._schedule_agents_async_refresh(full_history=True)
```

We deliberately do _not_ re-arm the timer if `_agents_loading` is True at firing time — the in-flight refresh is almost
certainly a Tier 1 load whose apply will set the pending flag again, and the existing idle / manual paths will then
convert it. Keeping the startup trigger strictly one-shot avoids retry storms.

### Coexistence with idle / manual paths

The three triggers all toggle the same `_agents_history_reconcile_pending` sticky flag. Whichever fires first clears it;
the others no-op. So:

- Typical case: startup timer fires at t ≈ 2 s → pending flag cleared, Tier 2 refresh scheduled. Idle tick at t ≥ 32 s
  sees flag clear → no double-fire. Manual `y` after t ≈ 2 s issues a normal (non-`full_history`) refresh because the
  flag is clear.
- Edge case: a refresh was already in flight when the startup timer fires. Timer no-ops. The next Tier 1 apply re-arms
  the flag, the idle tick (or manual `y`) converts it later.
- Edge case: user closes the app before the timer fires. No effect.
- Edge case: Tier 1 returns complete history (small home dir). The pending flag is never set, the timer is never armed.

### Acceptance criteria

A fresh tmux capture (same drive script as the 2026-05-16 follow-up) should show:

- Exactly one `agents.load_from_disk` Tier 1 span ~0.3 s at startup.
- Exactly one `agents.load_from_disk` Tier 2 span ~2.7 s starting at ~2.6 s after launch (i.e. ~2 s after the Tier 1
  apply).
- Plus the periodic Tier 1 auto-refresh after `y` if pressed.
- No additional Tier 2 span unless the user idles ≥30 s or presses `y` before the startup timer fires.

Agents-tab `paint_ms` p95 should remain ≤35 ms outside the Tier 2 contention window; we expect 1–2 outliers (~60–80 ms)
right around the Tier 2 apply step, which is the cost the user has accepted.

## Files to change

- `src/sase/ace/tui/actions/agents/_loading_refresh.py`
  - Add `STARTUP_TIER2_RECONCILE_DELAY_S = 2.0` constant.
  - Add `_fire_startup_tier2_reconcile` method to `AgentLoadingRefreshMixin`.
- `src/sase/ace/tui/actions/agents/_loading_apply.py`
  - In the incomplete-history branch, arm the one-shot timer when `_agents_startup_tier2_scheduled` is False.
- `src/sase/ace/tui/actions/agents/_loading_state.py`
  - Add typing declaration for `_agents_startup_tier2_scheduled: bool`.
- `src/sase/ace/tui/actions/_state_init.py`
  - Initialize `_agents_startup_tier2_scheduled = False`.
- `tests/ace/tui/test_lazy_tier2_reconcile.py`
  - Add tests:
    - `test_apply_arms_startup_tier2_timer` — first incomplete-history apply records a
      `set_timer(STARTUP_TIER2_RECONCILE_DELAY_S, …)` call and sets `_agents_startup_tier2_scheduled = True`.
    - `test_apply_does_not_double_arm_startup_tier2_timer` — a second incomplete-history apply does not record another
      `set_timer`.
    - `test_startup_trigger_fires_full_history_refresh` — calling `_fire_startup_tier2_reconcile` with the pending flag
      set schedules `_schedule_agents_async_refresh(full_history=True)` and clears the pending flag.
    - `test_startup_trigger_noop_when_flag_clear` — already cleared (e.g. idle path beat us to it) → no schedule, no
      state changes.
    - `test_startup_trigger_noop_when_loading` — in-flight refresh → no schedule, pending flag preserved for idle/manual
      fallback.
    - `test_apply_complete_history_skips_startup_arm` — first apply lands complete history → no timer armed, no pending
      flag.

## Verification

- `just check` — fmt, ruff, mypy, full test suite.
- Fresh tmux capture matching the acceptance criteria above; preserve the traces under `~/.sase/perf/research_<date>/`.
- Manual smoke: launch `sase ace`, observe that after ~3 s the agent count grows from the Tier 1 partial set to the Tier
  2 complete set without any keypress.

## Risk / rollback

- Risk: the 2.0 s delay collides with a particularly long initial j/k burst, producing the same 70 ms paint outliers we
  saw before. Tunable via `STARTUP_TIER2_RECONCILE_DELAY_S`; raising to 4–5 s pushes the Tier 2 cost past nearly all
  real bursts.
- Rollback: revert this commit. The deferred-only behavior from `366a3cb47` is the immediate fallback and remains
  correct.
