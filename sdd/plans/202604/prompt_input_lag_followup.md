---
create_time: 2026-04-27 16:36:55
status: done
prompt: sdd/prompts/202604/prompt_input_lag_followup.md
---
# Plan: Follow-up Fixes for Prompt Input Lag Implementation

## Context

Commit `5ca84936 fix(ace/tui): defer refresh work during prompt input` added a guard so background auto-refresh and
watcher-driven refresh do not run UI-thread work while a prompt input surface is mounted. While reviewing the
implementation in `src/sase/ace/tui/actions/event_handlers.py`, one real bug and a few clear-win cleanups surfaced.

## Bug: artifact-change defer timers do not deduplicate

`_on_artifact_change()` schedules `self.set_timer(PROMPT_INPUT_DEFER_SECONDS, self._on_artifact_change)` every time it
runs while a prompt is mounted. There is no dedup, so each inotify wake-up creates an independent self-perpetuating
timer chain.

Trace (prompt bar open the whole time):

1. Artifact event 1 → marks dirty, prompt active, schedules T1.
2. Artifact event 2 → marks dirty (no-op), prompt active, schedules T2.
3. Artifact event N → schedules TN.
4. 0.25 s later, T1..TN all fire → each marks dirty, sees prompt still active, each schedules T1'..TN'.

Result: N parallel chains running at 4 Hz on the UI thread, every cycle calling `_prompt_input_active()`, which iterates
the DOM via `self.query(PromptInputBar)`. This is exactly the UI-thread spam the original fix was meant to eliminate.

When the prompt finally closes, all pending timers fire in rapid succession; each calls `_schedule_agents_async_refresh`
and `_schedule_changespecs_async_refresh`. The internal `_*_loading` machinery prevents duplicated refresh work, but the
redundant Python-level calls and DOM queries still hit the UI thread.

### Fix

Track whether a defer timer is already pending and only schedule one. Use a separate timer callback so the flag is
cleared exactly when the timer fires (not when an external watcher event arrives), so back-to-back watcher events
collapse into the single pending timer instead of resetting the flag and re-scheduling.

## Clear-win cleanups (non-subjective)

These were noticed while diagnosing the bug and improve the implementation without changing behavior on a mounted
Textual `App`.

1. **Lift the `PromptInputBar` import to module scope.** `_prompt_input_active()` currently does
   `from ..widgets import PromptInputBar` inside a `try/except` on every call. The widgets package is already imported
   at the top of the file (`from ..widgets import (AgentList, ...)`); adding `PromptInputBar` there introduces no new
   dependency and removes the per-call lookup.

2. **Use `bool(query(PromptInputBar))` instead of `any(True for _ in query(...))`.** Verified that
   `textual.css.query.DOMQuery` defines both `__bool__` and `__len__`. The bool form is idiomatic and avoids
   constructing a generator each call.

3. **Drop the broad `try/except Exception`.** On a mounted Textual `App`, `query(WidgetClass)` returns an empty
   `DOMQuery` rather than raising. `_on_artifact_change` and `_on_auto_refresh` only run after mount (they are wired up
   via `set_interval` and the artifact watcher). The except clause masks real bugs without protecting from any realistic
   failure mode.

The `getattr(self, "query", None)` defense at the start of the DOM-query branch should stay —
`tests/ace/tui/test_event_handlers_nav_gate.py::_FakeApp` does not implement `query`, and removing the defense would
force unrelated test-fake edits. The three `getattr(self, "_prompt_context", None)` style checks should also stay, since
they match the pre-existing pattern in this file (`getattr(self, "_hint_mode_active", False)`, etc.).

## Implementation

### `src/sase/ace/tui/actions/event_handlers.py`

- Add `PromptInputBar` to the existing top-level `from ..widgets import (...)` block.
- Declare a new mixin class attribute `_artifact_change_defer_pending: bool` near the dirty-flag attrs, with a default
  of `False` set in the existing init path (state lives on the same object that already owns `_dirty_changespecs` etc.).
- In `_prompt_input_active()`: drop the function-local import and the `try/except`. Keep the
  `getattr(self, "query", None)` defense. Use `bool(query(PromptInputBar))`.
- In `_on_artifact_change()`: when prompt input is active, schedule a defer timer **only if**
  `_artifact_change_defer_pending` is `False`. Set the flag when scheduling, and pass
  `self._on_artifact_change_deferred` (new method) as the callback.
- Add `_on_artifact_change_deferred()`: clears `_artifact_change_defer_pending`, then calls `_on_artifact_change()`.
  This ordering ensures the dedup flag is cleared exactly when the timer fires; subsequent watcher-driven entries while
  the prompt is still active will set it again and schedule a single fresh timer.

### `src/sase/ace/tui/actions/_state_init.py`

- Initialize `self._artifact_change_defer_pending = False` alongside the other dirty/scheduling flags (this is the file
  `StateInitMixin` lives in after the recent split). One-line addition.

### `tests/ace/tui/test_event_handlers_dirty_flags.py`

- Add `self._artifact_change_defer_pending = False` to `_FakeApp.__init__`.
- Update the existing `test_artifact_change_defers_refresh_work_during_prompt_input` to assert the scheduled callback is
  `_on_artifact_change_deferred` (not `_on_artifact_change`).
- New `test_artifact_change_dedupes_defer_timers_during_prompt_input`: simulate three back-to-back artifact events while
  a prompt context is set; assert exactly one entry in `deferred_calls` and that `_artifact_change_defer_pending` is
  `True`.
- New `test_artifact_change_deferred_reschedules_while_prompt_still_active`: prime
  `_artifact_change_defer_pending = True`, invoke `_on_artifact_change_deferred()` while a prompt context is still set;
  assert a single new defer timer was scheduled and the flag is `True` again (cleared on entry by the deferred wrapper,
  re-set when the inner call re-schedules).
- New `test_artifact_change_deferred_resumes_refresh_after_prompt_closes`: prime
  `_artifact_change_defer_pending = True`, leave all prompt contexts unset, invoke `_on_artifact_change_deferred()`;
  assert `_schedule_agents_async_refresh` and `_schedule_changespecs_async_refresh` were called and
  `_artifact_change_defer_pending` ends `False`.

## Verification

1. `uv run pytest tests/ace/tui/test_event_handlers_dirty_flags.py tests/ace/tui/test_event_handlers_nav_gate.py`
2. `just check` (matches the project memory's post-change requirement)

## Acceptance Criteria

- Multiple inotify events during prompt input result in at most one pending defer timer at any time.
- A pending defer timer that fires while the prompt is still active reschedules itself exactly once.
- After the prompt closes, dirty flags still drive a single round of `_schedule_*` calls (no regression on the existing
  dispatch path).
- `_prompt_input_active()` has no hidden imports and no broad exception suppression.
- All existing tests in `test_event_handlers_dirty_flags.py` and `test_event_handlers_nav_gate.py` continue to pass.
