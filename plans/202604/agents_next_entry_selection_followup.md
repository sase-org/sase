---
create_time: 2026-04-27 14:15:01
status: done
---
# Agents Next-Entry Selection Follow-Up Cleanup

## Context

PR `d07da873` (`fix: align agent action focus with rendered order`) implemented the approved plan at
`~/.sase/plans/202604/agents_next_entry_selection.md`. I re-reviewed the diff in the context of the kill / dismiss /
mark call sites and verified the focused test suites still pass.

Findings:

1. **No bugs introduced.** The capture/restore pair correctly walks `_panel_navigation_stops()` against the old stops at
   capture time and the new stops at restore time. The stops cache (`_nav_stops_cache`) is keyed by `is self._agents`,
   so `_apply_killed_agents_in_memory` rebinding `_agents` to a freshly filtered list invalidates the cache between the
   two calls. Marking auto-advance via `_agents_visible_order()` correctly skips collapsed banner rows.

2. **One clear-win improvement.** In `src/sase/ace/tui/actions/agents/_core.py` `_restore_focus_after_removal` currently
   calls `_panel_navigation_stops()` inside two separate `try/except Exception` blocks — once when
   `prior_visible_pos is not None` and again when falling through to clean up a stale `_current_group_key`. The second
   branch is reached when `prior_visible_pos is None` _or_ when stops came back empty above. Compute `stops` once and
   reuse it. Pure refactor, no behavior change.

## Considered but rejected (NOT clear wins)

- `_advance_mark_selection` raw-list fallback can land on an invisible row when `prev_idx` isn't in
  `_agents_visible_order()` or `visible` is empty. Pre-existing edge case, only reachable with focus inside a collapsed
  group (which the UI generally prevents). "Fixing" it expands scope.
- Dismiss path (`_apply_dismissal_in_memory` -> `_refilter_agents` -> `_finalize_agent_list`) skips
  `_restore_focus_after_removal` when `identity_restored is True`, so a stale `_current_group_key` isn't cleaned up if a
  banner's group was emptied by an off-focus dismissal. Pre-existing, not introduced by the PR.
- Replacing the `assert isinstance(payload, tuple/int)` guards with `cast()` is subjective style.

## Plan

1. Refactor `_restore_focus_after_removal` in `src/sase/ace/tui/actions/agents/_core.py` to compute `stops` once at the
   top of the post-clamp section, then branch on `prior_visible_pos` and `_current_group_key` against the cached value.
   Behavior must remain identical (same returns, same fall-through to the stale-banner cleanup).

2. Re-run the focused regression suites:
   - `.venv/bin/pytest tests/ace/tui/test_agent_marking.py tests/ace/tui/test_agent_kill_focus_visible_order.py tests/ace/tui/test_agent_jk_navigation.py tests/ace/tui/test_jk_reliability.py`

3. Run `just check` per repo instructions.

## Out of scope

- Behavior changes (semantics of capture/restore, marking advance, banner cleanup in the dismiss path).
- New tests — there is no new behavior to cover; the existing suites already exercise the code paths touched here.
- Touching `_marking.py`, `_killing.py`, `_dismissing.py`, or any call site.
