---
create_time: 2026-07-06 12:53:53
status: done
prompt: sdd/prompts/202607/fix_flaky_preview_scroll_test.md
---
# Fix flaky `test_preview_scroll_keys_move_preview_region` CI failure

## Problem

CI (GitHub Actions) intermittently fails with:

```
FAILED tests/ace/tui/test_config_edit_modal_editors_widget.py::test_preview_scroll_keys_move_preview_region
  - AssertionError: wait_for() timed out after 5.0s — predicate never returned True
```

Evidence that this is a flake, not a regression:

- The failing run (28804185231) was on commit `ba445aaf9`, which only added two markdown files under `sdd/` (no code
  changes).
- On that same commit, only the Python 3.13 matrix job failed; 3.12 and 3.14 passed.
- CI runs on the surrounding code commits (`9a784e2ca`, `a0f33b6ef`) passed.
- The test passes locally, including 30 consecutive instrumented iterations.

The CI traceback pins the timeout to `tests/ace/tui/test_config_edit_modal_editors_widget.py:84`:

```python
await page.press("j")
await page.wait_for(lambda _s: scroll.scroll_y > 0)   # <- times out
```

i.e. the single `j` keypress never moved `#config-edit-preview-scroll`.

## Root cause

The preview-stage scroll actions in `ConfigEditModal` (`src/sase/ace/tui/modals/config_edit_modal.py`) use Textual's
default deferred scrolling:

- `_scroll_preview()` → `scroll.scroll_relative(y=delta, animate=False)`
- `action_preview_top()` → `scroll_home(animate=False)`
- `action_preview_bottom()` → `scroll_end(animate=False)`

In Textual (pinned 8.2.7), `scroll_to`/`scroll_relative`/`scroll_home`/`scroll_end` with the default `immediate=False`
do **not** scroll synchronously — they schedule the real `_scroll_to` via `call_after_refresh`. When `_scroll_to`
finally runs it evaluates:

```python
maybe_scroll_y = y is not None and (self.allow_vertical_scroll or force)
```

and if `allow_vertical_scroll` is False at that moment, the scroll is **silently dropped** (not queued, not clamped —
nothing happens). `allow_vertical_scroll` depends on the `show_vertical_scrollbar` reactive, which is refreshed by
`_refresh_scrollbars()` — and that method early-returns while the container reports a zero size, so the reactive can lag
the layout during a relayout. Independently, the deferred `_scroll_to` clamps against `max_scroll_y` _at apply time_,
which is also transient-layout-sensitive.

The test flow makes this window reachable: the preview scroll container flips from `display: false` to visible when the
stage changes to preview, its content is then replaced with an 80-line diff, and the test presses `j` exactly once as
soon as `max_scroll_y > 0` is observed. Instrumentation shows the keypress lands while layout is still mid-flight. On a
loaded CI runner (pytest-xdist on a busy machine), the deferred scroll can execute inside the stale window and get
dropped; since the test never re-presses, `scroll_y` stays 0 and `wait_for` times out after 5s. The same hazard applies
to the subsequent `g` / `G` / `ctrl+u` presses in the test.

This is also a (minor) real-UX bug: a user pressing a scroll key in the preview stage right as the modal relayouts can
have the keypress silently swallowed.

## Fix

Presentation-only Textual behavior — belongs in this repo (no Rust core changes).

### 1. Make preview scrolls immediate and forced (`src/sase/ace/tui/modals/config_edit_modal.py`)

Pass `immediate=True, force=True` at the three preview scroll call sites:

- `_scroll_preview()`: `scroll.scroll_relative(y=delta, animate=False, immediate=True, force=True)`
- `action_preview_top()`: `scroll_home(animate=False, immediate=True, force=True)`
- `action_preview_bottom()`: `scroll_end(animate=False, immediate=True, force=True)`

Rationale:

- `immediate=True` applies the scroll synchronously inside the key action, when the widget is laid out and the state the
  user (and test) just observed is current — no deferral window for a relayout to invalidate.
- `force=True` bypasses the `allow_vertical_scroll` gate, whose `show_vertical_scrollbar` input can be stale
  mid-relayout. The preview container is always meant to scroll when its content overflows; when content fits, targets
  clamp into `[0, 0]` so `force` has no visible effect.
- Add a short comment at `_scroll_preview` explaining why (keypresses must not be dropped by Textual's deferred, gated
  scroll path).

### 2. Harden the test precondition (`tests/ace/tui/test_config_edit_modal_editors_widget.py`)

Strengthen the pre-press wait in `test_preview_scroll_keys_move_preview_region` so it expresses what the keypress
actually requires:

```python
await page.wait_for(lambda _s: scroll.allow_vertical_scroll and scroll.max_scroll_y > 0)
```

With fix 1 this is belt-and-braces, but it documents the real precondition and protects against any future revert of the
`force=True` behavior.

Deliberately out of scope: other modals use the same deferred-scroll pattern, but none of their tests are flaking;
sweeping them is a separate hardening exercise if flakes appear.

## Validation

- Run the affected test file: `pytest tests/ace/tui/test_config_edit_modal_editors_widget.py`.
- Run the broader config-edit-modal widget test set (`pytest tests/ace/tui/ -k config_edit_modal`) to confirm no
  behavior change in the other preview-flow tests.
- Loop the fixed test (~30 iterations) to check for regressions in the timing behavior.
- `just check` per repo policy (known caveats: the full-suite test phase can be killed by the sandbox with exit 144, and
  there are known pre-existing `llm_provider` failures caused by the dev environment's `default_effort` setting —
  neither indicates a regression from this change; fall back to the targeted pytest runs above for the test signal).
