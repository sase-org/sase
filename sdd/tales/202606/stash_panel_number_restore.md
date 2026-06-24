---
create_time: 2026-06-24 15:14:02
status: done
---
# Plan: `@<N>` — restore the Nth prompt stash entry with numbered keycaps in the panel

## Goal

When the prompt-stash panel (`StashedPromptsModal`) is open, let the user press a single digit to restore a specific row
by position:

- `1`-`9` restore the **1st through 9th** rows (top to bottom, newest-first).
- `0` restores the **10th** row.
- Rows **11+ have no number keymap** (and show no keycap).

Each numbered row visibly shows its keycap so the digit↔row mapping is obvious at a glance. Combined with the global `@`
key (which opens this panel when 2+ entries are stashed), this delivers the requested `@<N>` flow: press `@` to open the
panel, then the digit to restore that row — a one-keystroke express lane that complements the existing
navigate-then-`enter` flow.

**"Restore" here is pin-aware**, mirroring the `@`-on-a-lone-entry behavior that just landed:

- Digit on an **unpinned** row → restore into the bar **and pop** it (remove from the stash).
- Digit on a **pinned** row → restore into the bar but **keep** it stashed.

This makes the digit keys the indexed generalization of `@`: `@N` behaves exactly like `@` would if that row were the
sole entry. A digit on a **bundle** row restores all of the bundle's panes and pops it (bundles can't be pinned), the
same as `enter` on a highlighted bundle today.

## Background / Context

The prompt stash is a single per-user pile of stashed prompt drafts (JSONL at `~/.sase/prompt_stash.jsonl`). All
persistence lives in the Rust core, fronted by a thin Python facade; each entry carries a persistent `pinned: bool`.

The panel `StashedPromptsModal` (`src/sase/ace/tui/modals/stashed_prompts_modal.py`) is a `ModalScreen` over an
`OptionList`. It is reached two ways, both of which still apply unchanged:

- Global **`@`** → `action_restore_prompt_stash` → `_open_prompt_stash_panel(auto_restore_single=True)`. With **1**
  entry it auto-restores directly (no panel); with **2+** it opens this panel.
- Prompt-local **`Ctrl+G p`** → `RestoreRequested` → `_open_prompt_stash_panel(...)` → always opens this panel (even for
  a single entry).

The panel renders one `OptionList` row per entry via the pure helper `_stash_row_label(entry, ...)`:

```
[✓/✗ marker (2)] [📌 pin (2)] [age (9)]  [project (14)]  [bundle (10)]  [preview (≤40)]
```

Entries are sorted **newest-first** in `__init__` (`created_at`, then `pane_index`, reversed). Pin/delete marking
re-styles rows in place but never reorders them, so the position→entry mapping is stable for the panel's lifetime.

The panel returns its decision as a `StashRestoreResult` via `dismiss(...)`:

- `pop_ids` — loaded into the bar **and** removed from the store.
- `keep_ids` — loaded **and** kept stashed.
- `delete_ids` — removed without loading.

The app callback `_on_prompt_stash_restore_confirmed` → `_apply_stash_restore` already handles every combination of
these (loads `pop+keep` oldest-first, expands bundles to panes, removes `pop+delete` in one store call, refreshes the
badge only when the store changed, toasts a count-aware summary). **A digit-key restore simply dismisses with a
`StashRestoreResult`, so it flows through this exact, already-tested machinery — the app side needs no changes.**

### Key facts established during exploration

1. **No `sase-core` change, and no app-glue change.** This is contained entirely in the modal: new key bindings, a new
   restore action, and a number-gutter in row rendering. The restore transport (`StashRestoreResult`) and its app-side
   handler (`_apply_stash_restore`, which already supports `pop_ids` and `keep_ids`) ship today. Per
   `memory/rust_core_backend_boundary.md`, "open panel vs. restore which row" is a TUI interaction choice (presentation
   glue), not shared domain behavior — it stays in this repo.

2. **Modal bindings win over the app-global digit bindings.** The app binds `0`-`9` globally to `load_saved_query_N`
   (`src/sase/ace/tui/bindings.py`). But the modal is the active `ModalScreen`, and its bindings are resolved before the
   app's. This is already proven in production: the app also binds `a` (accept), `d` (diff), `space` (run-agent), and
   `tab` (next-tab); the panel re-binds all four (`toggle_all`, `mark_delete`, `toggle_pin`, `toggle_pop`) and its tests
   pass. Digits are the same case — while the panel is open, a digit triggers `restore_index`, not a saved-query load.
   No `priority=True` is needed on the digit bindings (the app's digit bindings are non-priority).

3. **`OptionList` does not consume digits.** It has no digit bindings and no type-ahead, so digits bubble to the screen
   exactly like the panel's existing `a`/`d` letter keys do.

4. **`keep_ids` is honored on restore but `enter`/`tab` currently always pop.** The panel's `space`/`📌` tracks the
   persisted pin flag and its glyph, but `action_confirm`'s "no marks → restore highlighted" branch hard-codes
   `pop_ids`, so `enter` on a pinned highlighted row pops it. To make the panel internally coherent with the new
   pin-aware digit restore (and with `@`-single), this plan also makes the **no-marks `enter`/click** path pin-aware
   (pinned → keep, unpinned → pop). The explicit bulk path (`tab`-mark then `enter`) is unchanged and still force-pops —
   `tab` literally means "restore + pop". No existing test pins-then-presses-enter, so this is a safe, coherent
   tightening rather than a churny behavior break.

## Design

### Behavior matrix (panel open)

| Key             | Behavior                                                                                             |
| --------------- | ---------------------------------------------------------------------------------------------------- |
| `1`-`9`         | Restore row 1-9 (pin-aware: pinned ⇒ keep, else pop), then dismiss. No-op if that row doesn't exist. |
| `0`             | Restore row 10 (pin-aware), then dismiss. No-op if there is no 10th row.                             |
| `enter` / click | No marks: restore the highlighted row **pin-aware** (was: always pop). With marks: unchanged.        |
| `tab`           | Mark restore **+ pop** (unchanged, force-pop regardless of pin).                                     |
| `space` `a` `d` | Pin toggle / toggle-all-pop / delete-mark (all unchanged).                                           |
| `esc` `q`       | Cancel (unchanged).                                                                                  |

The digit keys are an **express lane**: they act on the row at that position immediately, ignoring any pending
pop/delete marks, and close the panel. This matches the user's framing ("press `@<N>` to restore the Nth entry").

### Numbered keycap gutter (the visual)

Prepend a fixed **4-column gutter** to every row, ahead of the existing marker column:

- Rows 1-10: a **keycap chip** — the literal key (`1`…`9`, then `0`) rendered as `N` on a violet background
  (`bold black on #AF87FF`), then a one-space separator. Violet is the stash's restore accent (the `✓` pop marker and
  the top-bar badge already use `#AF87FF`), so the keycap reads as "press this to restore." The chip keeps its own
  background even when the row is the highlighted cursor row, so the number stays legible.
- Rows 11+: four blank spaces (no chip), preserving column alignment.

Crucially the chip shows the **key you actually press**, not the ordinal — so the 10th row shows `0` (the key), never
`10`. This is the honest, least-surprising mapping for single-key shortcuts.

To keep the row within the panel's fixed width budget (option area ≈ 86 cols), reduce the preview column from **40 →
36** so the 4-col gutter is absorbed with no change to total row width (still ≈ 83 cols, same comfortable slack). The
age, project, bundle, and marker columns are untouched.

Rendering stays a pure, unit-testable helper: a small `_shortcut_gutter`/`_append_shortcut` helper builds the gutter
`Text`, and `_build_options` assembles `gutter + _stash_row_label(...)`. `_stash_row_label` itself is unchanged except
for the narrower preview default, so its existing helper tests keep passing.

### Hint line

The panel's bottom hint currently lists the marking keys on one (already-wrapping) line. Restructure it into two tidy,
non-wrapping lines and surface the new shortcut prominently:

```
1-9 0  restore row    j/k ↑/↓ navigate    enter confirm    esc/q cancel
space 📌 pin    tab ✓ restore+pop    d ✗ delete    a all
```

Line 1 groups quick-restore + navigation + confirm/cancel; line 2 keeps the marking ops. Every existing documented token
(`restore+pop`, `pin`, `📌`, `delete`) is preserved, so the panel's hint test only needs an added assertion for the new
`1-9 0 … restore row` token. The title stays `Stashed prompts (N)`.

### Implementation approach (all in `stashed_prompts_modal.py`)

1. **Keycap key map + gutter constants.** Add `_INDEX_KEYS = "1234567890"` (position `i` is the key for row `i`),
   `_SHORTCUT_WIDTH = 4`, and the keycap style. Update the module's width-budget comment and reduce `_PREVIEW_WIDTH`
   to 36.

2. **Digit bindings.** Append to `BINDINGS` one `Binding(key, f"restore_index({i})", f"Restore #{i+1}", show=False)` per
   `(i, key)` in `enumerate(_INDEX_KEYS)`. (`enter`/`tab`/`space`/`a`/`d`/nav unchanged.)

3. **`action_restore_index(self, index)`** — guard `0 <= index < len(self._entries)`; otherwise dismiss with
   `self._single_restore_result(self._entries[index])`.

4. **`_single_restore_result(self, entry)`** — `keep_ids=[id]` when `entry.id in self._pinned`, else `pop_ids=[id]`.
   Using `self._pinned` (not `entry.pinned`) ties the keep/pop decision to the exact pin glyph shown. Shared by the
   digit path and the `enter`-no-marks path.

5. **`action_confirm`** — replace the no-marks "restore highlighted" branch to dismiss via `_single_restore_result(...)`
   (pin-aware) instead of hard-coding `pop_ids`; the marked-set branch is unchanged. Update the stale "no key produces
   keep marks" comment.

6. **Number gutter in rendering** — add `_append_shortcut(text, shortcut)` (chip when a key, else 4 spaces) and have
   `_build_options` compute `shortcut = _INDEX_KEYS[idx] if idx < len(_INDEX_KEYS) else None`, then assemble the gutter
   ahead of the `_stash_row_label` content into one `no_wrap`/ellipsis `Text` per option.

7. **`_hint_text`** — the two-line layout above.

No changes to `bindings.py`, `default_config.yml`, the keymap registry, the footer, the `?` help modal, the wire, the
facade, the Rust core, or the app-side `_prompt_bar_stash.py`. The panel's in-modal keys (like the existing
`tab`/`space`/`a`/`d`) are documented by the panel's own hint line, not the help modal or footer — so the help/footer
sync conventions don't require an entry here. (Flagged per the AGENTS help-sync convention so the reviewer can confirm.)

## Scope of changes

### A. `src/sase/ace/tui/modals/stashed_prompts_modal.py`

- Add keycap constants; narrow `_PREVIEW_WIDTH` 40 → 36; refresh the column-budget comment.
- Add the 10 digit `Binding`s; add `action_restore_index` and `_single_restore_result`.
- Make `action_confirm`'s no-marks branch pin-aware (reuse `_single_restore_result`); update its comment.
- Add `_append_shortcut`; assemble the gutter in `_build_options`.
- Two-line `_hint_text`.
- Update the module docstring to describe the digit restore + numbered keycaps.

### B. Tests

`tests/ace/tui/modals/test_stashed_prompts_modal.py` (the existing `_ModalHost` pilot harness + pure-helper tests):

1. **`_append_shortcut` keycap vs. blank** — `" 3 "`-chip+separator for a key; 4 spaces for `None`; equal widths.
2. **Gutter assignment order** — build a modal with 11 entries; assert option labels' gutters show `1`…`9`,`0` for the
   first ten and a blank gutter for the eleventh.
3. **Digit restores unpinned → pop** — 3 rows, press `2` → dismiss `pop_ids == [2nd id]`, `keep`/`delete` empty.
4. **Digit restores pinned → keep** — pin a row (`space`) then press its digit → `keep_ids == [id]`, `pop` empty.
5. **`0` restores the 10th row** — 10 rows, press `0` → restores row index 9.
6. **Out-of-range digit is a no-op** — 2 rows, press `5` → modal stays open (result still `UNSET`).
7. **Digit on a bundle row pops the bundle** — bundle at row 1, press `1` → `pop_ids == [bundle id]`.
8. **`enter` on a pinned highlighted row now keeps** — pin the highlighted row, `enter` → `keep_ids == [id]` (guards the
   `action_confirm` change). Existing `enter`-unpinned and `tab`/`a`/`d` tests stay green unchanged.
9. **Hint** — extend `test_title_and_hints_describe_unified_panel` to also assert the `restore row` / `1-9` token.

`_stash_row_label`'s existing marker/preview helper tests are unaffected (gutter lives outside that helper; the narrower
preview doesn't change their short-text inputs).

### C. Visual snapshot

`tests/ace/tui/visual/test_ace_png_snapshots_prompt_stash.py` already renders the panel with 5 entries; the new gutter
(keycaps `1`-`5`), narrower preview, and two-line hint change the frame. Regenerate
`stashed_prompts_restore_modal_120x40.png` with `--sase-update-visual-snapshots`, inspect the diff in
`.pytest_cache/sase-visual/`, and update the test's docstring to mention the numbered keycap gutter. The badge snapshot
is unaffected.

## Out of scope / explicitly deferred

- **`@`-single auto-restore, `Ctrl+G p`, the empty/mode-guard paths** — unchanged.
- **`tab`/`a`/`d`/`space` marking semantics** — unchanged (digit + `enter`-no-marks are the only restore paths made
  pin-aware).
- **Multi-digit indices / paging beyond 10 rows** — out of scope; rows 11+ are reachable via `j/k` + `enter` only.
- **A distinct "kept" toast for pinned restores** — deferred (keeps `_notify_restore_outcome` untouched; "Restored
  prompt" is shown for both, consistent with `@`-single).
- **`bindings.py`, `default_config.yml`, keymap registry, footer, `?` help** — unchanged.

## Verification

1. `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + fast tests).
2. Targeted: `tests/ace/tui/modals/test_stashed_prompts_modal.py` and the visual suite (`just test-visual`) after
   regenerating the golden.
3. **Manual sanity** in `sase ace` (stash 3+ prompts): press `@` → panel opens with `1 2 3 …` keycaps; press `2` → the
   2nd draft loads into the bar and is popped; pin a row, reopen, press its digit → it loads and stays stashed; with 11+
   stashed, the 11th row shows no keycap and its position has no digit shortcut.

## Risks / Notes

- **Binding precedence** is the main risk and is resolved: the active modal's bindings beat the app-global `0`-`9`
  saved-query bindings, proven by the panel already overriding app-global `a`/`d`/`space`/`tab`.
- **Pin-aware `enter`** is a deliberate, small behavior tightening so the panel is internally consistent with `@`-single
  and the digit keys; `tab` remains the explicit force-pop. No test regresses.
- **Width budget** is preserved by trading 4 preview columns for the gutter (total row width unchanged), so nothing
  clips.
- **Boundary**: pure presentation/orchestration in the modal reusing the shipped `StashRestoreResult` transport — no
  `sase-core`, wire, facade, or app-glue change.
- **Plan-file portability**: all paths are repo-relative; no workspace-specific directories referenced.
