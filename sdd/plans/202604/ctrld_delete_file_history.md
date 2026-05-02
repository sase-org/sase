---
create_time: 2026-04-23 14:44:16
status: done
prompt: sdd/prompts/202604/ctrld_delete_file_history.md
---

# Plan: Ctrl+D to Delete Entries from File-History Completion Menu

## Problem / Goal

The `<ctrl+t>` keymap in the prompt input widget now opens a **file-history completion** panel listing paths the user
has previously referenced in prompts (see the prior plan at `plans/202604/ctrlt_file_history_completion.md` and the
shipped code in `src/sase/history/file_references.py` and `src/sase/ace/tui/widgets/_file_completion.py`).

The history grows monotonically: once a path lands in the list, the only way to get rid of it is to hand-edit
`~/.sase/file_reference_history.json`. Users will inevitably want to prune stale or noisy entries (e.g. a path they
referenced once by mistake, or a file that has since been deleted/renamed). We want a keyboard-native way to delete the
currently highlighted entry.

**Proposal:** when the file-history panel is open, `<ctrl+d>` removes the highlighted path from both the panel and the
on-disk history, then keeps the panel open on the remaining entries (or closes it if the list becomes empty).

## Scope

### In scope

1. **New store API** `remove_file_reference(path: str) -> None` in `src/sase/history/file_references.py` — removes the
   first exact-match occurrence from the on-disk history and writes atomically. Silent no-op if the file is
   missing/corrupt or the path is not present.
2. **New mixin method** `_delete_selected_file_completion()` on `FileCompletionMixin` in
   `src/sase/ace/tui/widgets/_file_completion.py`:
   - Only acts when `_completion_kind == "file_history"`.
   - Identifies the currently highlighted candidate via `_file_completion_index`.
   - Calls `remove_file_reference(path)` for that candidate.
   - Removes the entry from `_file_completion_candidates` in-place and adjusts `_file_completion_index` to stay in
     bounds.
   - If the list becomes empty, calls `_clear_file_completion()` (closes panel).
   - Otherwise, calls `_update_file_completion_panel("")` to re-render with the same kind and (clamped) selection.
3. **Key binding** in `PromptTextArea._on_key` (`src/sase/ace/tui/widgets/prompt_text_area.py`), next to the existing
   `ctrl+l` accept handler inside the `if self._file_completion_active:` block:
   - Intercept `event.key == "ctrl+d"` **only** when `self._completion_kind == "file_history"`.
   - Call `_delete_selected_file_completion()`, stop + prevent_default the event.
   - For any other completion kind (`"file"`, `"xprompt"`) and when no completion panel is active, do not intercept —
     let Textual's default behavior apply so we don't regress unrelated terminal/text-area semantics.
4. **Panel affordance:** when `completion_kind == "file_history"`, append a `[Ctrl+D] delete` hint next to the existing
   `[Ctrl+L] accept` text in the completion panel's subtitle / hint line (visual inventory TBD — see Design §4). This
   keeps the new keymap discoverable without a separate help popup dive.
5. **Help popup:** update the `?` help modal to document the new keymap (per the repo mandate in
   `src/sase/ace/AGENTS.md` that any `sase ace` option change must stay in sync with the help popup).
6. **Tests:**
   - Unit: `remove_file_reference` in `tests/history/test_file_references.py` covering: present-path removal,
     missing-path no-op, missing-file no-op, corrupt-file no-op, dedup interaction (confirm there is at most one
     occurrence; exact-match removal suffices).
   - Integration: extend `TestFileHistoryCompletion` in `tests/ace/tui/widgets/test_prompt_file_completion.py` with:
     - Ctrl+D on a middle entry: removes that entry, panel stays open with next entry selected.
     - Ctrl+D on the last entry in the list: panel closes, on-disk history empty.
     - Ctrl+D does nothing when the panel is in `"file"` or `"xprompt"` kind (i.e. the key is not swallowed, so
       Textual's default handling applies).
     - Deletion persists: reloading via `load_file_references()` reflects the removal.

### Out of scope

- **Bulk delete / clear-all.** Deferred until a user asks.
- **Undo.** A single Ctrl+D is destructive to history; we mirror the rest of the history modules (no undo stack anywhere
  else in the codebase).
- **Confirmation prompt.** The entries are user-typed file paths, not prompts or code; the cost of an errant delete is
  low (user just re-references the file and it re-enters history).
- **Deleting from other completion kinds.** `"file"` completion enumerates the filesystem and `"xprompt"` enumerates
  registered xprompts — neither has a user-owned persistence layer to delete from. Ctrl+D there is meaningless.
- **Persisting the selection across a delete-and-reopen cycle.** After delete, the panel shows the clamped next entry;
  we don't try to "remember" the deleted position between Ctrl+T invocations.

## High-Level Design

### 1. Store deletion API

**Edit:** `src/sase/history/file_references.py`, after `record_file_references`.

```python
def remove_file_reference(path: str) -> None:
    """Remove *path* from the on-disk history, atomically.

    Silent no-op if the history file is missing or corrupt, or if *path*
    is not present.  Exact-match comparison: the caller must pass the
    stored form (``@`` already stripped, ``~`` not expanded) — which is
    exactly what ``load_file_references`` returns.
    """
```

Implementation:

- Call `load_file_references()`.
- Build `remaining = [p for p in existing if p != path]`.
- If `len(remaining) == len(existing)`: return (no write, nothing changed).
- Otherwise, reuse the atomic tmp-file + `os.replace` pattern from `record_file_references` (extract into a private
  `_write_history(paths)` helper at the same time — both call sites benefit and the duplication is already awkward).

`seen` dedup semantics in `record_file_references` already guarantee at most one entry per path, so an exact-match
filter is sufficient.

### 2. Mixin method

**Edit:** `src/sase/ace/tui/widgets/_file_completion.py`.

```python
def _delete_selected_file_completion(self) -> bool:
    """Delete the highlighted entry from file-history completion."""
    if not self._file_completion_active:
        return False
    if self._completion_kind != "file_history":
        return False
    if not self._file_completion_candidates:
        return False

    from sase.history.file_references import remove_file_reference

    idx = self._file_completion_index
    victim = self._file_completion_candidates[idx].insertion
    remove_file_reference(victim)

    del self._file_completion_candidates[idx]
    if not self._file_completion_candidates:
        self._clear_file_completion()
        return True

    self._file_completion_index = min(idx, len(self._file_completion_candidates) - 1)
    self._update_file_completion_panel("")
    return True
```

Notes:

- Returns `bool` so the keymap handler can `event.stop()` only on a successful intercept — matches the shape of
  `_accept_file_completion` / `_move_file_completion`.
- Uses `CompletionCandidate.insertion` (not `display`) for the removal key, because that is the raw stored path; for
  `file_history` they are identical today (see `build_file_history_completion_candidates`), but keying on `insertion`
  keeps us robust if `display` ever gains decoration.
- No need to re-read the store after removal — the in-memory candidate list is already the source of truth for the
  panel.

### 3. Key wiring

**Edit:** `src/sase/ace/tui/widgets/prompt_text_area.py`, inside the existing `if self._file_completion_active:` block
around line 214–229, after the `ctrl+l` branch:

```python
if event.key == "ctrl+d" and self._completion_kind == "file_history":
    event.stop()
    event.prevent_default()
    self._delete_selected_file_completion()
    return
```

The `_completion_kind == "file_history"` guard is load-bearing: Textual's TextArea may have its own Ctrl+D semantics
(forward-delete in some configurations) and we only want to shadow it while the history panel is up.

### 4. Panel affordance

**Edit:** `src/sase/ace/tui/widgets/prompt_input_bar.py`, in `show_file_completions` near the
`is_history = completion_kind == "file_history"` branch (around lines 196–234).

Inspect the panel's subtitle/hint composition (the rendering already sets `panel.border_title = "recent files"` for this
kind). Add a `[Ctrl+D] delete` hint alongside whatever navigation/accept hint is shown today. If the current
file-history panel doesn't render a subtitle, add one with the minimal set: `"[Ctrl+L] accept  [Ctrl+D] delete"`.

Exact placement to be finalized during implementation — the decision point is small and does not change the shape of the
plan.

### 5. Help popup

**Edit:** the `?` help modal content (likely `src/sase/ace/tui/widgets/help_modal.py`, per `src/sase/ace/AGENTS.md`).
Add a single-line entry under the prompt-input-bar / completion section describing `<ctrl+d>` in file-history mode.

Respect the 57-character box width / 32-character description-cap constraints called out in the ace AGENTS.md.

### 6. Tests

**Edit:** `tests/history/test_file_references.py` — add a `TestRemoveFileReference` class (or top-level functions
matching existing style) with:

- `test_removes_existing_path` — file with `["a", "b", "c"]`, remove `"b"`, load → `["a", "c"]`.
- `test_missing_path_is_noop` — remove a path not in the list; file contents unchanged (check mtime or exact bytes).
- `test_missing_file_is_noop` — no history file on disk; call succeeds; still no file.
- `test_corrupt_file_is_noop` — write invalid JSON; call succeeds; file not overwritten to empty (important: we
  shouldn't wipe a user's corrupt-but-recoverable history on a Ctrl+D miss).

**Edit:** `tests/ace/tui/widgets/test_prompt_file_completion.py`, in `TestFileHistoryCompletion`:

- `test_ctrl_d_removes_highlighted_entry_and_keeps_panel_open` — seed history with three entries, Ctrl+T to open, Ctrl+N
  once, Ctrl+D, assert: middle entry gone from panel rows, first entry now highlighted if we deleted the
  last-then-wrapped? (Be explicit about expected post-delete selection — plan says `min(idx, len-1)`.) Reload store →
  middle entry gone.
- `test_ctrl_d_on_last_remaining_entry_closes_panel` — seed with one entry, Ctrl+T, Ctrl+D, assert
  `_file_completion_active` is False and store is empty.
- `test_ctrl_d_is_passthrough_for_file_kind` — trigger file completion with a real path token, send Ctrl+D, assert panel
  state unchanged and (ideally) that the default TextArea Ctrl+D behavior fired (or at minimum, our handler didn't
  swallow it).

## Files Touched (summary)

| Kind  | Path                                                   | Reason                                                       |
| ----- | ------------------------------------------------------ | ------------------------------------------------------------ |
| Edit  | `src/sase/history/file_references.py`                  | Add `remove_file_reference`; extract `_write_history` helper |
| Edit  | `src/sase/ace/tui/widgets/_file_completion.py`         | Add `_delete_selected_file_completion`                       |
| Edit  | `src/sase/ace/tui/widgets/prompt_text_area.py`         | Wire `<ctrl+d>` when `_completion_kind == "file_history"`    |
| Edit  | `src/sase/ace/tui/widgets/prompt_input_bar.py`         | Panel hint includes `[Ctrl+D] delete` in history mode        |
| Edit  | `src/sase/ace/tui/widgets/help_modal.py` (path TBD)    | Document `<ctrl+d>` in help popup                            |
| Tests | `tests/history/test_file_references.py`                | `remove_file_reference` unit tests                           |
| Tests | `tests/ace/tui/widgets/test_prompt_file_completion.py` | Ctrl+D panel integration tests                               |

## Risks / Non-Risks

- **Low risk — additive.** No existing completion behavior changes when the panel is not in `file_history` mode. The
  store gains one function; deletion never runs except on explicit Ctrl+D in the history panel.
- **Ctrl+D collision with TextArea default.** Mitigated by the `_completion_kind` guard — we only intercept when the
  history panel is up, leaving normal INSERT-mode Ctrl+D (if any) untouched. Worth a quick manual smoke test: hit Ctrl+D
  in an ordinary prompt, in xprompt completion, and in path completion, and confirm nothing regresses.
- **Concurrency.** Two sase TUIs open simultaneously could race on the history file (one deletes, the other records).
  The existing modules don't lock and neither will this one; last-writer-wins is acceptable and matches
  `record_file_references`.
- **No undo.** Intentional — matches every other history store in the repo. If users ask for confirmation later, we can
  add an opt-in config flag without changing the core design.

## Open Questions

1. **Subtitle/hint vs. help-popup-only.** Should we inline the `[Ctrl+D] delete` affordance in the panel subtitle, or
   keep the history panel visually minimal and rely on the `?` popup? Proposal: inline it — discoverability is the whole
   reason Ctrl+L is inline today.
2. **Fallback when `_file_completion_index` is out of range.** Shouldn't happen given the navigation code clamps it, but
   worth an assertion/log? Proposal: defensive `if idx >= len(candidates): return False` rather than an assert, matching
   the mixin's general "fail-closed, clear state" posture.
3. **Should Ctrl+D also work on `"file"` / `"xprompt"` panels to mean something else** (e.g. close the panel)? Proposal:
   no — Escape already dismisses, and overloading Ctrl+D with different semantics per kind makes it less teachable.
