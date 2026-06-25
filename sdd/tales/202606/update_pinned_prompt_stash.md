---
create_time: 2026-06-25 07:26:56
status: done
prompt: sdd/prompts/202606/update_pinned_prompt_stash.md
---
# Plan: `gS` / `<Ctrl+G>S` — update a pinned prompt stash with the current prompt

## Summary

Add two prompt-input-bar keymaps that let the user **save the prompt they are currently drafting back over an existing
pinned prompt stash**, in place:

- `gS` in NORMAL mode
- `<Ctrl+G>S` in INSERT mode

This is the natural companion to yesterday's pinned-prompt-stash work. Pinned stashes act as reusable prompt templates:
you restore one, edit it, and now you want to push your edits back to that same pinned entry without spawning a
brand-new stash row. `gS` = "**S**ave to a pinned stash" (capital `S` mnemonic, distinct from lowercase `gs` = "stash
all and clear").

Behavior:

- **0 pinned stashes** → friendly warning toast, no store write.
- **1 pinned stash** → update it automatically (no prompt), then a success toast.
- **2+ pinned stashes** → a small, beautiful single-keypress picker listing only the pinned entries; one key press picks
  the target, then a success toast.

A key UX distinction from `gs`: `gS` **does not clear or dismiss the prompt bar** — it is a "save a copy back to the
pin" gesture, so the user keeps editing afterward.

## Product / UX design

### Trigger surface

`gS` joins the existing prompt `g`-prefix family (`g<enter>`, `gj/gk`, `gJ/gK`, `g-`, `g=`, `gs`, `<Ctrl+G>p`). Both the
bare-`g` NORMAL path and the `<Ctrl+G>` INSERT path already route through one declarative binding table, so a single new
table row gives us both keymaps _and_ the in-context hint-panel entry for free (no separate help-doc surface to
maintain).

### What gets captured

`gS` captures the **entire current prompt** the same way `gs` does: every non-empty pane, joined into one bundle
(`\n---\n`), plus the bar's shared YAML frontmatter. This is the round-trip-faithful choice — a pinned entry may itself
be a multi-pane bundle, so capturing only the active pane would silently drop the rest of the bundle on save. Capturing
all panes mirrors the existing stash-all / restore round-trip exactly.

If the current prompt is empty (no non-empty pane), there is nothing to save → a `"Nothing to save"` warning toast and
no store write (mirrors the existing `"Nothing to stash"` no-op).

### Choosing the target pin

- Read the stash snapshot off-thread, filter to `pinned == True`.
- **None pinned** → warning toast, e.g.
  `"No pinned prompt stash to update — pin one with space in the stash picker (Ctrl+G p)"`. No write.
- **Exactly one** → update it directly. No modal: the whole point of "if there's only one, update it automatically".
- **Multiple** → open `UpdatePinnedStashModal`, a single-keypress picker.

### The picker (multiple pinned)

Visually consistent with the existing `StashedPromptsModal` so it feels like the same family: each row shows the
numbered keycap (`1`–`9`, `0`), the 📌 pin glyph, relative age, originating-project chip, bundle chip, and a one-line
preview. Interaction:

- `1`–`9` / `0` → immediately pick that row and update it (single key press).
- `j`/`k` and `↑`/`↓` navigate; `enter` confirms the highlighted row (covers >10 pins).
- `esc` / `q` cancel (no write).

It is a _pick-one_ dialog only — no pin/pop/delete toggles (those belong to the full picker). Title:
`"Update pinned prompt"`.

### The update itself

The chosen entry is rewritten **in place**: its `text` and `frontmatter` are replaced with the captured prompt; its
`id`, `created_at`, `project`, `source`, `pane_index`, and `pinned` flag are preserved. Keeping `created_at` (rather
than bumping it) means the pin stays put in the picker ordering — it is the _same_ logical pin with refreshed content,
not a new one. Updating `frontmatter` to the captured value even when empty keeps "save current prompt as-is" honest.

### Success toast

Specific and a little delightful, e.g.:

> `Updated pinned prompt 📌 "<first-line preview>"`

The preview is the first non-blank line of the saved prompt (reusing the existing preview/truncation helper), so the
user knows exactly which pin they overwrote.

## Key design decisions & rationale

1. **No Rust core changes are required.** The Rust core already has `rewrite_prompt_stash(path, entries)` — a _merge_
   primitive: caller rows win on id collision, on-disk rows absent from the input are preserved, and it is atomic under
   the store's file lock. Passing a single entry whose `id` matches the target pin overwrites exactly that row in place
   and leaves every other row untouched — precisely an in-place update. It is **already exposed** through the
   `sase_core_rs` binding (`rewrite_prompt_stash(path: str, entries: list[dict]) -> dict`) but has had no Python
   consumer yet. So this feature adds the Python facade wrapper + callers only, honoring the Rust-core-boundary rule
   (the persisted-store mutation lives in core) without touching Rust. (Boundary verified against
   `crates/sase_core/src/prompt_stash/store.rs` and `crates/sase_core_py/src/lib.rs` in the `sase-core` linked repo.)

2. **Presentation/app split (boundary rule D6) is preserved.** The bar stays presentation-only: it captures pane
   text(s) + frontmatter and posts a new `PromptInputBar.UpdatePinnedRequested` message. The app glue performs the
   snapshot read, pin filtering, modal orchestration, store write, badge refresh, and toasts — mirroring how `Stashed` /
   `RestoreRequested` are already handled.

3. **Hint availability stays O(1) (TUI perf rules 1 & 7).** The `gS` hint must not do disk I/O on every `g` press. We
   cache a **pinned count** alongside the existing stashed-prompt badge count: the snapshot reads that already feed the
   badge (startup, app-focus reconcile, post-capture/restore refreshes) also count pinned rows, stored on
   `StashedPromptsIndicator`. The bar's availability check reads that cached integer via a new
   `App._has_pinned_stashed_prompts()` (sibling to the existing `_has_stashed_prompts()`). The only disk read happens on
   the actual `gS` action, off-thread via `asyncio.to_thread`.

4. **`gS` does not clear the bar** (unlike `gs`). It is a save-back gesture; the draft stays so the user keeps working.
   This is the core mnemonic distinction (`s` stash-away vs. `S` save-to-pin).

5. **Visual reuse for beauty + DRY.** The picker reuses the existing pinned-stash row renderer. To avoid a cross-module
   private import (which `pyvision` forbids), the row-label helpers are promoted into a small shared module that both
   `StashedPromptsModal` and the new modal import. The function bodies move verbatim so existing rendering (incl. PNG
   snapshots) is unchanged.

## Implementation plan (by layer; repo-relative paths)

### A. Backend — Rust core

**No changes.** `rewrite_prompt_stash` already exists and is bound. (Confirmed in the `sase-core` linked repo.)

### B. Python facade + binding guard

- `src/sase/core/prompt_stash_facade.py`: add a thin `rewrite_prompt_stash(path, entries)` wrapper mirroring the
  existing facade functions (require binding, project wires to dicts via `prompt_stash_wire_to_json_dict`, rehydrate the
  returned snapshot); export in `__all__`.
- `tools/validate_sase_core_rs`: add `"rewrite_prompt_stash"` to `REQUIRED_BINDINGS` so a stale wheel without it is
  caught by the existing version-skew guard.

### C. Shared pinned-stash row renderer (refactor, behavior-preserving)

- New `src/sase/ace/tui/modals/prompt_stash_row.py`: move the row-rendering helpers out of `stashed_prompts_modal.py`
  under public names (index keycaps, shortcut gutter, project / bundle chips, first-line preview, and the
  `stash_row_label(...)` builder + the width/glyph constants). Bodies copied verbatim.
- `src/sase/ace/tui/modals/stashed_prompts_modal.py`: import the shared helpers instead of the local privates; no
  rendering change.

### D. Bar (presentation-only)

- `src/sase/ace/tui/widgets/_prompt_input_bar_messages.py`: add `UpdatePinnedRequested(Message)` carrying
  `panes: list[StashedPromptPane]`.
- `src/sase/ace/tui/widgets/prompt_input_bar.py`: import + alias `UpdatePinnedRequested = _UpdatePinnedRequested`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`:
  - Add one row to `_PROMPT_G_PREFIX_BINDINGS`: key `"S"` → action `request_update_pinned_stash`, label
    `_g_prefix_label_update_pin`, availability `_g_prefix_available_update_pin`.
  - `request_update_pinned_stash()`: prompt-mode only; sync state; capture every non-empty pane as a `StashedPromptPane`
    (same shape as `stash_all_panes`); post `UpdatePinnedRequested(panes)` (empty list when nothing stashable). **Does
    not** remove panes or dismiss the bar.
  - `_g_prefix_available_update_pin()`: prompt mode AND `self.app._has_pinned_stashed_prompts()` AND at least one pane
    has text (mirror `stash_all`'s sync+any-text check, but with no multi-pane requirement). Defensive
    `getattr`/try-except around the app call, like `_g_prefix_available_stash_restore`.
  - `_g_prefix_label_update_pin()` → `"update pinned stash"` (final wording tunable; see open questions).
  - Add `UpdatePinnedRequested` to the mixin's `TYPE_CHECKING` attribute block.

### E. App glue — `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`

- `async on_prompt_input_bar_update_pinned_requested(event)`: type-guard; empty panes → `"Nothing to save"` warning;
  otherwise `await self._update_pinned_stash(event.panes)`.
- `async _update_pinned_stash(panes)`: build the bundle `text` (`\n---\n`-joined) and `frontmatter` (first non-empty)
  exactly like `_persist_stashed_panes`; read the snapshot off-thread; filter pinned. None → warning toast; one →
  `_write_pinned_update(...)`; multiple → `push_screen(UpdatePinnedStashModal(pinned), callback)` whose callback
  resolves the chosen id to its entry and spawns `_write_pinned_update(...)`.
- `async _write_pinned_update(base_entry, text, frontmatter)`:
  `replace(base_entry, text=text, frontmatter=frontmatter)`; off-thread `rewrite_prompt_stash(path, [updated])`
  serialized under a store lock (reuse the existing pin-write lock pattern); on success refresh the badge and toast the
  success message; on error toast an error (no crash). Reuse `_spawn_prompt_stash_task` for task tracking.
- Pinned-count plumbing: have the existing snapshot-count read also return a pinned count; funnel both through the
  badge-apply path; add `_has_pinned_stashed_prompts()`. Touch the small set of existing refresh call sites
  (`_refresh_prompt_stash_indicator`, `_refresh_prompt_stash_badge_async`, `on_app_focus`) to carry the pinned count.

### F. Indicator widget — `src/sase/ace/tui/widgets/stashed_prompts_indicator.py`

- Track a `pinned_count` alongside `count` (extend the setter or add a sibling setter) and expose a `pinned_count`
  property. The visible badge/tooltip stay total-based (no visual change); the pinned count is purely the cheap source
  for the `gS` hint gate.

### G. New modal — `src/sase/ace/tui/modals/update_pinned_stash_modal.py`

- `UpdatePinnedStashModal(OptionListNavigationMixin, ModalScreen[str | None])`: takes the pinned entries (newest-first),
  renders rows via the shared renderer with numbered keycaps, `1`–`9`/`0` to pick (dismiss with the entry id),
  `j/k`+`enter` on the highlighted row, `esc`/`q` cancel. Register it in `src/sase/ace/tui/modals/__init__.py`.

### H. Docs / config (verify, mostly no-ops)

- `src/sase/default_config.yml`: **no change** — prompt `g`-prefix keymaps live in the code binding table, not YAML
  config (confirmed).
- `src/sase/ace/tui/modals/help_modal.py`: **no change** — the prompt `g`-prefix keymaps are not documented in the help
  modal; discoverability is the in-context hint panel, which auto-updates from the binding table.
- Keybinding footer: not applicable — these are prompt-bar hint-panel keymaps, not entry-conditional footer keymaps.

## Edge cases

- Empty prompt → `"Nothing to save"`, no write.
- No pinned stash → warning toast, no write.
- Single pane current prompt overwriting a former bundle pin → collapses to one segment (correct: the user edited it
  down).
- Concurrent multi-instance: the target pin removed by another instance between snapshot read and write would be
  re-added by the merge primitive (it always writes input rows). This is a negligible, non-destructive corner for a
  single-user TUI; the success toast still reflects the row that now exists. (Noted, not guarded, to avoid
  over-engineering.)
- Non-prompt bars (feedback / approve-prompt): `gS` is a no-op and the hint never shows.

## Testing

- **Facade** (`tests/test_core_facade/test_prompt_stash.py`): fake-module test that `rewrite_prompt_stash` projects
  entries to dicts and rehydrates the snapshot; a real-extension integration test (guarded by a `hasattr` skip) that
  updating one entry's text in place preserves `id`/`created_at`/`pinned` and leaves other rows intact.
- **New modal** (`tests/ace/tui/modals/test_update_pinned_stash_modal.py`): `1`/`2` pick the expected entry id;
  `esc`/`q` → `None`; `enter` confirms the highlighted row; rows render the 📌 glyph + preview; `j/k` navigation.
- **App glue** (`tests/ace/tui/actions/` — new `test_prompt_stash_update.py` or extend the existing handler test,
  reusing the `_StashHarness` style): empty → "Nothing to save"; zero pinned → warning, no write; one pinned →
  `rewrite_prompt_stash` called with the correctly updated entry, success toast, bar **not** dismissed, badge refreshed;
  multiple → modal pushed and the chosen id updated; store/IO error → error toast.
- **Bar** (`tests/ace/tui/widgets/test_prompt_stash_capture.py` or sibling): `request_update_pinned_stash` captures all
  non-empty panes and posts `UpdatePinnedRequested`; empty posts an empty list; panes are not removed and the bar is not
  dismissed.
- **Hints** (`tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`): `gS` and `<Ctrl+G>S` dispatch to
  `request_update_pinned_stash`; the hint appears only when a pin exists and the prompt has text; label text is correct.
- **Visual**: run `just test-visual` to confirm the row-renderer extraction did not change `StashedPromptsModal`
  rendering; add a PNG golden for `UpdatePinnedStashModal` if/only if it matches the existing modal-snapshot convention.

## Verification

- `just install` then `just check` (ephemeral-workspace rule).
- `just test-visual` for the PNG snapshot suite.

## Out of scope / open questions for the user

1. **Hint/label wording.** Proposed `"update pinned stash"` for the hint and `Updated pinned prompt 📌 "<preview>"` for
   the toast. Open to `"save to pinned stash"` etc.
2. **Capture granularity.** Plan captures _all_ panes as a bundle (round-trip faithful). If you'd prefer `gS` to save
   only the **active** pane, that's a one-line change — flag it.
3. **`created_at` on update.** Plan preserves it (pin keeps its place). Alternative: bump it so a freshly-updated pin
   floats to the top of the picker. Say the word if you'd prefer the float-to-top behavior.
