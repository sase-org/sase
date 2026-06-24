---
create_time: 2026-06-24 12:18:16
status: done
prompt: sdd/prompts/202606/cancel_toast.md
---
# Plan: Make the prompt-cancel toast meaningful

## Problem & product context

In the `sase ace` TUI, cancelling an agent prompt from the prompt input bar always shows a toast —
`Prompt input cancelled` (whole-bar cancel) or `Prompt pane cancelled` (per-pane cancel in a multi-pane stack). Today
that toast fires **unconditionally**, even when nothing useful happened:

- An **empty / whitespace-only** prompt is cancelled → toast, but nothing is stored.
- A prompt that is **only a VCS xprompt workflow** (e.g. a bare `#gh:sase`) is cancelled → toast, but nothing is stored.

These cases are noise: the toast claims something was cancelled, yet there is nothing in prompt history to recover, so
the notification is hollow.

We want two changes:

1. **Suppress the toast when the cancelled prompt is not stored to prompt history.** The toast should appear only when
   the cancel actually preserved something the user can re-run later.
2. **Show the cancelled prompt in the toast.** When a toast _is_ shown, it should display the (truncated, if necessary)
   prompt text that was stored — turning a vague confirmation into a useful, recoverable receipt.

### Design goals

- **Intuitive** — the toast becomes a receipt: "this exact prompt is now in your history." No toast means nothing was
  kept, which matches user intuition (empty / single-token prompts are not worth keeping).
- **Reliable** — the toast fires _exactly_ when storage happens, with no second predicate that can drift from the real
  storage rule. The text shown is exactly the text stored.
- **Beautiful** — a clean two-part toast (a concise title + the quoted prompt preview), reusing the existing single-line
  truncation helper with its Unicode ellipsis.

## Current behavior (where things live)

- **Cancel handler:** `PromptBarSubmitMixin.on_prompt_input_bar_cancelled` in
  `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py`.
  - Per-pane cancel (`event.keep_bar` true): calls `self._save_text_as_cancelled(event.cancelled_text)` then
    `self.notify("Prompt pane cancelled")`.
  - Whole-bar cancel: calls `self.notify("Prompt input cancelled")` then `self._unmount_prompt_bar()` (which saves the
    text) then clears `_prompt_context`.
- **Save helpers:** in `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py`:
  - `_save_text_as_cancelled(text)` — strips text, returns early if empty, otherwise calls
    `add_or_update_prompt(text, cancelled=True)` and records file references.
  - `_save_bar_text_as_cancelled(bar)` — reads `bar.current_prompt_text()` and delegates.
  - `_unmount_prompt_bar()` — the catch-all dismissal path; calls `_save_bar_text_as_cancelled` (safety net) then
    detaches the bar. Called from ~14 sites (mounting a new bar, request flows, submit-empty, etc.), all of which ignore
    its result.
- **The real storage rule:** `add_or_update_prompt` in `src/sase/history/prompt_store.py` drops anything below a word
  threshold:
  ```python
  _MIN_PROMPT_WORDS = 2
  ...
  if not allow_short and len(text.split()) < _MIN_PROMPT_WORDS:
      return
  ```
  Cancellation always uses the default `allow_short=False`, so a cancelled prompt is stored **iff it has ≥ 2
  whitespace-separated tokens**. A bare `#gh:sase` is one token → dropped; empty → dropped. This single gate is the
  authoritative definition of "stored to history," and it already produces exactly the two example cases the user cited.

### Key insight

"Stored to prompt history" is **not** a new concept we need to re-detect (we do _not_ need to separately sniff for
VCS-only prompts). It is precisely the existing `add_or_update_prompt` word-count gate. The robust design makes the
toast a downstream consequence of that one gate, so the toast can never disagree with what actually got stored — even if
the threshold changes later.

## Proposed design

Thread a "what did we actually store?" signal up from the save helpers to the cancel handler, and drive the toast off
that signal. One predicate, one source of truth.

### 1. Expose the storage predicate (single source of truth)

In `src/sase/history/prompt_store.py`, extract the threshold gate into a named, pure predicate and use it inside
`add_or_update_prompt` (no behavior change):

```python
def is_recordable_prompt(text: str, *, allow_short: bool = False) -> bool:
    """Return True if *text* meets the prompt-history recording threshold."""
    return allow_short or len(text.split()) >= _MIN_PROMPT_WORDS
```

`add_or_update_prompt`'s early-return becomes `if not is_recordable_prompt(text, allow_short=allow_short): return`.
Re-export `is_recordable_prompt` from the `sase.history.prompt` facade (add to its imports and `__all__`).

_Boundary note:_ prompt-history storage already lives entirely in Python (`sase.history`), not in the Rust core, and the
toast itself is pure TUI presentation. This is a local refactor plus presentation logic, so it stays in this repo and
does not cross the Rust-core backend boundary.

### 2. Have the save helpers report the stored text

In `_prompt_bar_mount.py`, make the save chain return the text that was actually stored (empty string when nothing was).
This is purely additive — every existing caller ignores the return value.

- `_save_text_as_cancelled(text) -> str`:
  - Strip; if empty, return `""`.
  - Compute `recorded = is_recordable_prompt(text)`.
  - Call `add_or_update_prompt(text, cancelled=True)` (still a no-op below threshold).
  - **Keep file-reference recording unchanged** (still runs regardless of `recorded`, so we don't alter that behavior).
  - Return `text if recorded else ""`.
- `_save_bar_text_as_cancelled(bar) -> str`: return `""` on the read exception, otherwise return
  `self._save_text_as_cancelled(text)`.
- `_unmount_prompt_bar() -> str`: return `""` when no bar is present, otherwise return the result of
  `_save_bar_text_as_cancelled(bar)` (before/while detaching). The ~14 other callers continue to ignore the return.

This guarantees the toast shows **exactly** the text that landed in history (no reliance on `event.cancelled_text`
matching the bar's live text).

### 3. Drive the toast off the stored text

Rework `on_prompt_input_bar_cancelled` so each cancel branch only notifies when something was stored, and shows it:

- Per-pane branch:
  ```python
  stored = self._save_text_as_cancelled(event.cancelled_text)
  if stored:
      self._notify_prompt_cancelled(stored, pane=True)
  return
  ```
- Whole-bar branch (note: notify now happens _after_ the save so we know the result):
  ```python
  stored = self._unmount_prompt_bar()
  self._prompt_context = None
  if stored:
      self._notify_prompt_cancelled(stored, pane=False)
  ```

### 4. The toast itself (beautiful + intuitive)

Add a small presentation helper on `PromptBarSubmitMixin`:

```python
def _notify_prompt_cancelled(self, stored_text: str, *, pane: bool) -> None:
    from sase.history.prompt_stats import short_preview
    title = "Prompt pane cancelled" if pane else "Prompt input cancelled"
    self.notify(f'"{short_preview(stored_text)}"', title=f"{title} — saved to history")
```

- Reuse the existing `short_preview` helper (`src/sase/history/prompt_stats.py`): it collapses whitespace to a single
  line and truncates with a Unicode ellipsis `…` (default 60 chars). No new ad-hoc truncation.
- The **title** keeps the familiar "Prompt input/pane cancelled" wording and adds "— saved to history" so the user
  understands the prompt is recoverable; the **message** is the quoted, truncated prompt. Default (information)
  severity, matching the current cancel toasts. Using `title=` is a deliberate, scoped enhancement over the current
  message-only toast to give the prompt its own visual line.

### What stays the same / out of scope

- The `_unmount_prompt_bar` **safety net is preserved**: cancel still always saves before detaching; only the explicit
  cancel handler decides whether to toast.
- File-reference recording on cancel is unchanged.
- Other toasts are left as-is: the empty-**submit** warning (`Empty prompt - cancelled`), `Plan feedback cancelled`, and
  the approve-prompt cancel flow are different UX (submit rejection / modal flows), not prompt-history cancels, so they
  are intentionally untouched.

## Behavior matrix (after change)

| Cancelled input                              | Stored to history? | Toast                                                              |
| -------------------------------------------- | ------------------ | ------------------------------------------------------------------ |
| Empty / whitespace only                      | No                 | none                                                               |
| Bare VCS workflow, e.g. `#gh:sase` (1 token) | No                 | none                                                               |
| `fix the auth bug` (≥ 2 tokens)              | Yes                | `Prompt input cancelled — saved to history` / `"fix the auth bug"` |
| Long prompt                                  | Yes                | title + quoted preview truncated with `…`                          |
| Per-pane cancel of a ≥ 2-token pane          | Yes (that pane)    | `Prompt pane cancelled — saved to history` / `"…"`                 |
| Per-pane cancel of a bare-VCS pane           | No                 | none                                                               |

## Testing

Extend existing suites (patterns already established in the repo):

- **Predicate unit tests** (`tests/history/`): `is_recordable_prompt` is True for ≥ 2-token text, False for empty /
  single-token (`#gh:sase`), and True for any text when `allow_short=True`. Confirm `add_or_update_prompt` behavior is
  unchanged.
- **Save-helper return values** (extend `tests/ace/tui/test_prompt_bar_submit_no_cancel_save.py` style harness):
  cancelling a ≥ 2-token prompt returns/propagates the stored text up through `_save_text_as_cancelled` →
  `_save_bar_text_as_cancelled` → `_unmount_prompt_bar`; empty and single-token inputs propagate `""`. The existing
  "cancel unmount still saves" and "submit path skips cancel-save" guarantees still hold.
- **Toast gating** (harness capturing `notify(message, title=...)` calls, per
  `tests/ace/tui/test_prompt_bar_xprompt_selector_requests.py`):
  - Whole-bar cancel of a real prompt → one toast whose title starts with "Prompt input cancelled" and whose message
    contains the prompt preview.
  - Whole-bar cancel of empty / bare `#gh:sase` → **no** toast.
  - Per-pane cancel: real pane → "Prompt pane cancelled …" toast with preview; bare-VCS pane → no toast (extend
    `tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py` coverage at the handler level).
  - Long prompt → toast message is truncated with `…`.

## Files touched

- `src/sase/history/prompt_store.py` — add `is_recordable_prompt`; use it in `add_or_update_prompt`.
- `src/sase/history/prompt.py` — re-export `is_recordable_prompt`.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py` — return stored text from the three save/unmount
  helpers.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py` — gate the toast on the stored text and add
  `_notify_prompt_cancelled`.
- Tests as above.

## Risks / mitigations

- **Toast now fires after the save (whole-bar path).** Toasts are non-blocking, so the one-tick reordering is invisible;
  in exchange the toast can report exactly what was stored. Low risk.
- **Return-type changes.** All existing callers discard the return value, so widening `None → str` is safe and additive.
- **Predicate drift.** Avoided by construction — the toast and the storage gate both call the single
  `is_recordable_prompt`.
