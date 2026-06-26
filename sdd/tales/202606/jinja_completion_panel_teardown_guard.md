---
create_time: 2026-06-26 08:18:23
status: done
prompt: sdd/prompts/202606/jinja_completion_panel_teardown_guard.md
---
# Fix flaky `#prompt-completion` teardown race in live Jinja diagnostics

## Problem

CI intermittently fails with:

```
FAILED tests/ace/tui/widgets/test_prompt_jinja_pair_editing.py::test_forward_delete_padding_strips_both_boundary_spaces
  - textual.css.query.NoMatches: No nodes match '#prompt-completion' on PromptInputBar(classes='feedback-mode')
```

The named test never queries `#prompt-completion` itself — the query happens deep inside widget code that the `delete`
keypress triggers. This is a **flaky teardown race**, not a logic bug in the test's assertions.

## Root cause

1. The `delete` / `backspace` handlers in `_prompt_text_area_key_handling.py` apply a Jinja-pair edit and call
   `_on_prompt_completion_context_changed()`.
2. That schedules a **debounced timer** (`_jinja_diagnostics_timer`, default ~90 ms) in
   `_jinja_diagnostics.py::_schedule_jinja_diagnostics_refresh`.
3. When the timer fires (`_fire_jinja_diagnostics_timer` → `_apply_jinja_diagnostics` → `_publish_jinja_diagnostics`),
   it calls the parent bar's `show_jinja_diagnostics()` / `hide_jinja_diagnostics()` (the latter delegates to
   `hide_file_completions()`).
4. Those methods in `_prompt_input_bar_completion.py` call `self.query_one("#prompt-completion", Static)`.
5. During app/widget teardown (e.g. the `async with app.run_test()` block exiting, or a prompt-stack rebuild), the bar's
   direct `#prompt-completion` child can already be pruned while the text area is still attached to the bar.
   `_find_prompt_bar()` still resolves the bar, but the panel query on it raises `NoMatches`.

The flake surfaces on the test ending with `"{{}}"` because invalid Jinja drives the `show_jinja_diagnostics()` path
(which performs the query); whether the 90 ms timer fires before or after teardown depends on machine timing, so it is
intermittent.

This is the **newly-added** Jinja diagnostics path (commit `540bbe3fd feat(ace): support Jinja prompt input`). The
functionally identical query in the older search path (`_prompt_input_bar_search.py::_hide_completion_panel_for_search`)
**already guards** the same `query_one("#prompt-completion")` with a `try/except` that bails when the panel is absent —
confirming this is a known, expected runtime condition that the new path simply failed to handle.

## Why a guard is the correct fix (not just symptom suppression)

The `#prompt-completion` panel is composed unconditionally, so it is _only ever_ missing during teardown. When it is
missing there is genuinely nothing to render or hide, so making the panel-touching methods safe no-ops in that window is
the semantically correct behavior — it does not mask any real-usage bug. Merely cancelling the timer on unmount is
insufficient on its own, because a timer callback can already be queued/in-flight before cancellation runs; the guard at
the query site is the robust fix and matches the existing convention in the search mixin.

## Scope of the fix

All four panel-touching entry points in `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` share the same
unguarded `query_one("#prompt-completion", Static)` and must all tolerate the panel being absent:

- `show_file_completions`
- `hide_file_completions`
- `show_xprompt_arg_hint`
- `show_jinja_diagnostics`

## Plan

### 1. Add a safe panel accessor on the completion mixin

In `_prompt_input_bar_completion.py`, add a small private helper that returns the panel or `None` when it is detached
(mirroring the search mixin's tolerance for a missing panel), e.g. a `_completion_panel(self) -> Static | None` that
catches `textual.css.query.NoMatches`.

### 2. Guard every panel entry point

Replace each `panel = self.query_one("#prompt-completion", Static)` in the four methods above with the safe accessor
plus an early return when the panel is `None`. Bailing early correctly skips the follow-on state mutation
(`_completion_visible`, `_completion_line_count`, `_update_height()`), which is the right behavior for a widget that is
tearing down.

### 3. (Optional hardening) Skip debounced work after unmount

Optionally short-circuit `_fire_jinja_diagnostics_timer` when the text area is no longer mounted, to avoid running
`inspect_template` during teardown. This is a minor efficiency improvement layered on top of the guard; the guard above
is what actually fixes the flake. (The soft-completion timer does not query `#prompt-completion`, so it needs no
change.)

### 4. Consider de-duplicating the existing search guard (optional cleanup)

`_hide_completion_panel_for_search` already hand-rolls a `try/except` around the same query. If it reads cleanly, route
it through the new `_completion_panel()` helper so there is a single canonical panel-lookup path. Skip if it complicates
the diff.

## Regression test (deterministic — no timing dependence)

Add an async Textual test (natural home: `tests/ace/tui/widgets/test_prompt_jinja.py`, which already exercises
`#prompt-completion` and has a synchronous `_compute_jinja_now(ta)` helper that fires the diagnostics path directly)
that reproduces the race deterministically:

1. Mount the prompt-bar test app and load invalid Jinja text (e.g. `"{{}}"`) so the diagnostics path would call
   `show_jinja_diagnostics`.
2. `await` removal of the bar's `#prompt-completion` child to model the teardown window (panel pruned while the text
   area is still attached).
3. Drive the diagnostics path (`_compute_jinja_now(ta)` / direct `bar.show_jinja_diagnostics(...)`) and assert it does
   **not** raise.
4. Also assert `hide_file_completions()` / `show_file_completions(...)` / `show_xprompt_arg_hint(...)` are safe no-ops
   when the panel is absent, covering all four guarded entry points.

Without the fix this test raises `NoMatches`; with the fix it passes.

## Validation

- `just install` (ephemeral workspaces may have stale deps) then `just check` (ruff + mypy + tests).
- Run the previously-flaky test and the new regression test specifically:
  `tests/ace/tui/widgets/test_prompt_jinja_pair_editing.py` and `tests/ace/tui/widgets/test_prompt_jinja.py`.

## Boundary / non-goals

- Pure Textual presentation/teardown lifecycle in this repo — no shared backend semantics — so this stays on the
  Python/TUI side and does **not** touch the Rust core (`sase-core`).
- No behavioral change to live Jinja diagnostics during normal operation: the panel is always present then, so the
  guards are inert outside teardown.
- Not changing the debounce interval or the diagnostics computation itself.
